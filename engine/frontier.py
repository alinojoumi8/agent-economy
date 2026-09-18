"""Seeded geography, paid expeditions and civic settlement formation.

Opt-in version 1 is prospective and supported in semantics 11. It deliberately
does not enable RegionalEconomy's currency issuance or rewrite old events.
All task effects execute in the world's normal transaction/savepoint boundary.
"""
from __future__ import annotations

import hashlib
import json
import random
import unicodedata

from .ledger import SYS_COMMODITY


def snapshot_at(store, tick):
    if not store.query_one("SELECT 1 FROM sqlite_master WHERE name='frontier_history'"):
        return None
    row = store.query_one(
        "SELECT data_json FROM frontier_history WHERE tick<=? ORDER BY tick DESC,id DESC LIMIT 1", (tick,))
    return json.loads(row["data_json"]) if row else None


def residence_regions_at(store, agents, tick):
    """Return only frontier-managed identities, including their pre-upgrade null."""
    if not store.query_one("SELECT 1 FROM sqlite_master WHERE name='frontier_residences'"):
        return {}
    result = {}
    for agent in agents:
        aid = int(agent["id"])
        if store.query_one("SELECT 1 FROM frontier_residences WHERE agent_id=?", (aid,)):
            row = store.query_one(
                "SELECT region_id FROM frontier_residences WHERE agent_id=? AND tick<=? ORDER BY tick DESC LIMIT 1",
                (aid, tick))
            result[aid] = row["region_id"] if row else None
    return result


class Frontier:
    REQUIRED_WORK = 3
    FOUND_COST = 2000
    WORK_COST = 250

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.config = economy.config.get("frontier", {})
        # Later population/time semantics need a different movement contract.
        # Fail closed rather than bypass household consent or time accounting.
        self.enabled = self.config.get("version") == 1 and economy.engine_semantics_version == 11
        if self.config.get("version") == 1 and not self.enabled:
            raise ValueError("frontier version 1 requires engine_semantics_version 11")
        self.activation = int(self.config.get("activation_tick", 0))

    def active(self, tick):
        return self.enabled and tick >= self.activation

    def _event(self, tick, kind, payload, actor=None, phase="NIGHT_CLOSE"):
        event_kind = "frontier_" + kind
        return self.store.log_event(tick, event_kind, payload, phase=phase,
                                   subject_type="agent" if actor else "world",
                                   subject_id=actor or 1, importance=3.0)

    def initialize(self, tick):
        if not self.active(tick) or self.store.query_one("SELECT 1 FROM frontier_sites"):
            return
        if self.store.query_one("SELECT 1 FROM regions") or self.e.regions.enabled:
            raise ValueError("frontier v1 requires a world without an existing regional economy")
        if self.store.query_one("SELECT 1 FROM agents WHERE region_id IS NOT NULL"):
            raise ValueError("frontier v1 cannot replace existing region assignments")
        if self.store.query_one("SELECT 1 FROM accounts WHERE currency_code<>'USD'"):
            raise ValueError("frontier v1 requires the existing USD economy")
        region = self.store.insert("regions", region_key="northstar", name="Northstar",
            currency_code="USD", population_target=100, specialization_json="[]",
            x=0.5, y=0.5, legal_ruleset="frontier-civic-v1", created_tick=tick)
        # A private stream leaves every pre-existing economic PRNG untouched.
        digest = hashlib.sha256(f"frontier-v1:{self.e.config.get('seed', 42)}".encode()).digest()
        rng = random.Random(int.from_bytes(digest, "big"))
        locations = [(0, 0)] + [(x, y) for y in (-1, 0, 1) for x in (-1, 0, 1) if (x, y) != (0, 0)]
        for x, y in locations:
            terrain, resource = rng.choice([
                ("meadow", "fertile soil"), ("forest", "timber"),
                ("hills", "stone"), ("riverbank", "fresh water")])
            self.store.insert("frontier_sites", x=x, y=y,
                terrain="plain" if (x, y) == (0, 0) else terrain,
                resource="established infrastructure" if (x, y) == (0, 0) else resource,
                capacity=1000 if (x, y) == (0, 0) else rng.randint(8, 16),
                discovered_tick=tick if (x, y) == (0, 0) else None)
        self.store.insert("frontier_settlements", site_id=1, name="Northstar", name_key="northstar",
            founded_tick=tick, work_units=self.REQUIRED_WORK, completed_tick=tick,
            region_id=region, charter_tick=tick)
        self._event(tick, "initialized", {"region_id": region, "name": "Northstar", "sites": 9, "version": 1})

    def residence(self, aid):
        return self.store.query_one(
            "SELECT r.*,s.site_id FROM frontier_residences r JOIN frontier_settlements s ON s.id=r.settlement_id "
            "WHERE r.agent_id=? ORDER BY r.tick DESC LIMIT 1", (aid,))

    def _move(self, aid, settlement, tick, phase="NIGHT_CLOSE"):
        self.store.execute(
            "INSERT INTO frontier_residences(agent_id,tick,settlement_id,region_id) VALUES (?,?,?,?) "
            "ON CONFLICT(agent_id,tick) DO UPDATE SET settlement_id=excluded.settlement_id,region_id=excluded.region_id",
            (aid, tick, settlement["id"], settlement["region_id"]))
        self.store.update("agents", aid, region_id=settlement["region_id"])
        self._event(tick, "residence_recorded", {"agent_id": aid, "settlement_id": settlement["id"],
            "region_id": settlement["region_id"]}, aid, phase)

    def busy(self, aid):
        return self.store.query_one("SELECT * FROM frontier_tasks WHERE agent_id=? AND status='pending'", (aid,))

    def _residents(self, sid):
        return [row["id"] for row in self.store.query(
            "SELECT a.id FROM agents a JOIN frontier_residences r ON r.agent_id=a.id "
            "WHERE a.alive=1 AND r.settlement_id=? "
            "AND r.tick=(SELECT MAX(tick) FROM frontier_residences WHERE agent_id=a.id) ORDER BY a.id", (sid,))]

    def run_nightly(self, tick):
        if not self.active(tick):
            return
        self.initialize(tick)
        home = self.store.query_one("SELECT * FROM frontier_settlements WHERE site_id=1")
        for row in self.store.query("SELECT id FROM agents WHERE alive=1 ORDER BY id"):
            if self.residence(row["id"]) is None:
                self._move(row["id"], home, tick)
        for task in self.store.query("SELECT * FROM frontier_tasks WHERE status='pending' AND due_tick<=? ORDER BY id", (tick,)):
            aid = task["agent_id"]
            agent = self.store.query_one("SELECT alive,employer_id FROM agents WHERE id=?", (aid,))
            status = "completed" if agent and agent["alive"] and not agent["employer_id"] else "cancelled"
            site = self.store.query_one("SELECT * FROM frontier_sites WHERE id=?", (task["site_id"],))
            settlement = self.store.query_one("SELECT * FROM frontier_settlements WHERE site_id=?", (site["id"],))
            if status == "completed":
                if task["kind"] == "explore_site":
                    if site["discovered_tick"] is None:
                        self.store.update("frontier_sites", site["id"], discovered_tick=tick, discovered_by=aid)
                        self._event(tick, "discovered", {"site_id": site["id"], "terrain": site["terrain"],
                            "resource": site["resource"], "capacity": site["capacity"]}, aid)
                elif task["kind"] == "build_settlement":
                    work = min(self.REQUIRED_WORK, settlement["work_units"] + 1)
                    self.store.update("frontier_settlements", settlement["id"], work_units=work,
                        completed_tick=settlement["completed_tick"] or (tick if work == self.REQUIRED_WORK else None))
                    self._event(tick, "construction", {"settlement_id": settlement["id"], "work_units": work,
                        "required_work": self.REQUIRED_WORK}, aid)
                elif task["kind"] == "move_settlement":
                    if len(self._residents(settlement["id"])) >= site["capacity"]:
                        status = "cancelled"
                    else:
                        self._move(aid, settlement, tick)
            self.store.update("frontier_tasks", task["id"], status=status, completed_tick=tick)
            self._event(tick, "task_" + status, {"task_id": task["id"], "kind": task["kind"],
                "site_id": site["id"], "supplies_consumed": True}, aid)
        self.publish(tick)

    def _name(self, value):
        name = " ".join(unicodedata.normalize("NFKC", value).split())
        if not 2 <= len(name) <= 48 or not all(c.isalnum() or c in " -'" for c in name):
            raise ValueError("use 2–48 letters, numbers, spaces, hyphens or apostrophes")
        if self.store.query_one("SELECT 1 FROM frontier_settlements WHERE name_key=?", (name.casefold(),)):
            raise ValueError("settlement name already exists")
        return name

    def _charge(self, aid, tick, amount):
        wallet = self.store.scalar("SELECT checking_account_id FROM agents WHERE id=?", (aid,))
        if not wallet or self.e.ledger.balance(wallet) < amount:
            raise ValueError("insufficient funds for supplies")
        sink = self.e.ledger.ensure_system_account(SYS_COMMODITY, currency_code="USD")
        return self.e.ledger.transfer(tick, wallet, sink, amount, kind="frontier_supplies",
                                     memo="Expedition or settlement materials consumed")

    def execute(self, tick, aid, action, phase):
        error = self.check(tick, aid, action)
        if error:
            return {"ok": False, "reason": error}
        kind = action["type"]
        site, settlement, duration, cost = self.terms(aid, action)
        if kind == "found_settlement":
            name = self._name(action["name"])
            txn = self._charge(aid, tick, cost)
            sid = self.store.insert("frontier_settlements", site_id=site["id"], name=name,
                name_key=name.casefold(), founder_id=aid, founded_tick=tick,
                region_id=self.store.scalar("SELECT id FROM regions WHERE region_key='northstar'"))
            self._event(tick, "settlement_founded", {"settlement_id": sid, "site_id": site["id"],
                "name": name, "cost_cents": cost, "transaction_id": txn}, aid, phase)
            result = {"ok": True, "settlement_id": sid, "transaction_id": txn}
        elif kind == "charter_region":
            self.store.insert("frontier_votes", settlement_id=settlement["id"], agent_id=aid, tick=tick)
            residents = self._residents(settlement["id"])
            voters = {r["agent_id"] for r in self.store.query("SELECT agent_id FROM frontier_votes WHERE settlement_id=?", (settlement["id"],))}
            votes = len(voters.intersection(residents))
            required = len(residents) // 2 + 1
            self._event(tick, "charter_vote", {"settlement_id": settlement["id"], "votes": votes,
                "required": required}, aid, phase)
            result = {"ok": True, "votes": votes, "required": required}
            if len(residents) >= 3 and votes >= required:
                rid = self.store.insert("regions", region_key=f"settlement-{settlement['id']}",
                    name=settlement["name"], currency_code="USD", population_target=site["capacity"],
                    specialization_json=json.dumps([site["resource"]]), x=(site["x"]+1)/2,
                    y=(site["y"]+1)/2, legal_ruleset="frontier-civic-v1", created_tick=tick)
                self.store.update("frontier_settlements", settlement["id"], region_id=rid, charter_tick=tick)
                updated = dict(settlement, region_id=rid)
                for resident in residents:
                    self._move(resident, updated, tick, phase)
                self._event(tick, "region_chartered", {"region_id": rid, "settlement_id": settlement["id"],
                    "name": settlement["name"], "votes": votes, "residents": len(residents)}, aid, phase)
                result["region_id"] = rid
        else:
            txn = self._charge(aid, tick, cost)
            task = self.store.insert("frontier_tasks", agent_id=aid, kind=kind, site_id=site["id"],
                started_tick=tick, due_tick=tick+duration, transaction_id=txn)
            result = {"ok": True, "task_id": task, "due_tick": tick+duration, "cost_cents": cost}
            self._event(tick, "task_started", {**result, "kind": kind, "site_id": site["id"]}, aid, phase)
        self.publish(tick)
        return result

    def terms(self, aid, action):
        settlement = None
        if "settlement_id" in action:
            settlement = self.store.query_one("SELECT * FROM frontier_settlements WHERE id=?", (action["settlement_id"],))
        site_id = settlement["site_id"] if settlement else action.get("site_id", 0)
        site = self.store.query_one("SELECT * FROM frontier_sites WHERE id=?", (site_id,))
        residence = self.residence(aid)
        origin = self.store.query_one("SELECT * FROM frontier_sites WHERE id=?", (residence["site_id"],)) if residence else None
        distance = max(1, abs(site["x"]-origin["x"]) + abs(site["y"]-origin["y"])) if site and origin else 1
        kind = action["type"]
        duration = distance + 1 if kind == "explore_site" else distance if kind == "move_settlement" else 1
        cost = self.FOUND_COST if kind == "found_settlement" else self.WORK_COST if kind == "build_settlement" else 0 if kind == "charter_region" else distance * 100
        return site, settlement, duration, cost

    def check(self, tick, aid, action):
        if not self.active(tick) or not self.store.query_one("SELECT 1 FROM frontier_sites"):
            return "frontier is not active"
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (aid,))
        if not actor or not actor["alive"] or actor["age"] < 18 or actor["kind"] != "citizen":
            return "only living adult citizens can undertake frontier actions"
        if not self.residence(aid):
            return "residence has not been registered"
        if self.busy(aid):
            return "finish the current frontier task first"
        if self.store.query_one("SELECT 1 FROM action_proposals WHERE actor_id=? AND tick=? AND validation_status='accepted' AND action_type IN ('explore_site','found_settlement','build_settlement','move_settlement','charter_region')", (aid, tick)):
            return "one frontier action per citizen per tick"
        site, settlement, duration, cost = self.terms(aid, action)
        if not site:
            return "unknown site or settlement"
        kind = action["type"]
        if kind != "charter_region" and actor["employer_id"]:
            return "frontier work requires a citizen free of employment commitments"
        if kind == "explore_site" and site["discovered_tick"] is not None:
            return "site already explored"
        if kind == "found_settlement":
            if site["discovered_tick"] is None:
                return "explore the site before founding"
            if self.store.query_one("SELECT 1 FROM frontier_settlements WHERE site_id=?", (site["id"],)):
                return "site already has a settlement"
            try:
                self._name(action.get("name", ""))
            except ValueError as exc:
                return str(exc)
        if kind in {"build_settlement", "move_settlement", "charter_region"} and not settlement:
            return "unknown settlement"
        if kind == "build_settlement":
            pending = self.store.scalar("SELECT COUNT(*) FROM frontier_tasks WHERE site_id=? AND kind='build_settlement' AND status='pending'", (site["id"],), default=0)
            if settlement["work_units"] + pending >= self.REQUIRED_WORK:
                return "all construction work is completed or reserved"
        if kind == "move_settlement":
            if settlement["completed_tick"] is None:
                return "settlement construction is incomplete"
            if self.residence(aid)["settlement_id"] == settlement["id"]:
                return "already resident in this settlement"
            reserved = self.store.scalar("SELECT COUNT(*) FROM frontier_tasks WHERE kind='move_settlement' AND site_id=? AND status='pending'", (site["id"],), default=0)
            if len(self._residents(settlement["id"])) + reserved >= site["capacity"]:
                return "settlement has no available housing capacity"
        if kind == "charter_region":
            if settlement["charter_tick"] is not None or settlement["completed_tick"] is None:
                return "settlement is not eligible for a charter"
            if aid not in self._residents(settlement["id"]) or len(self._residents(settlement["id"])) < 3:
                return "chartering requires at least three residents and a resident vote"
            if self.store.query_one("SELECT 1 FROM frontier_votes WHERE settlement_id=? AND agent_id=?", (settlement["id"], aid)):
                return "citizen already voted"
        if cost and (not actor["checking_account_id"] or self.e.ledger.balance(actor["checking_account_id"]) < cost):
            return "insufficient funds for supplies"
        return None

    def context(self, aid, tick):
        if not self.active(tick) or not self.store.query_one("SELECT 1 FROM frontier_sites"):
            return None
        state = snapshot_at(self.store, tick) or {}
        actions = []
        for site in self.store.query("SELECT * FROM frontier_sites ORDER BY id"):
            for kind in ("explore_site", "found_settlement"):
                action = {"type": kind, "site_id": site["id"]}
                if kind == "found_settlement":
                    action["name"] = f"New Haven {site['id']}"
                if not self.check(tick, aid, action):
                    _, _, duration, cost = self.terms(aid, action)
                    actions.append({"action": action, "cost_cents": cost, "duration_ticks": duration,
                        "label": f"{kind.replace('_', ' ').title()} · site {site['id']} · {cost} cents"})
        for settlement in self.store.query("SELECT * FROM frontier_settlements ORDER BY id"):
            for kind in ("build_settlement", "move_settlement", "charter_region"):
                action = {"type": kind, "settlement_id": settlement["id"]}
                if not self.check(tick, aid, action):
                    _, _, duration, cost = self.terms(aid, action)
                    actions.append({"action": action, "cost_cents": cost, "duration_ticks": duration,
                        "label": f"{kind.replace('_', ' ').title()} · {settlement['name']} · {cost} cents"})
        task = self.busy(aid)
        return {"map": state, "task": dict(task) if task else None, "options": actions,
                "rules": "Paid supplies are consumed. Tasks occupy your turns until due. Founding requires three paid work units before moving. Three residents and a majority vote establish a region. Choose your own unique settlement name."}

    def publish(self, tick):
        sites = []
        for row in self.store.query("SELECT * FROM frontier_sites ORDER BY id"):
            public = {key: row[key] for key in ("id", "x", "y", "discovered_tick", "discovered_by")}
            if row["discovered_tick"] is not None:
                public.update({key: row[key] for key in ("terrain", "resource", "capacity")})
            sites.append(public)
        settlements = [dict(r, residents=self._residents(r["id"])) for r in self.store.query("SELECT * FROM frontier_settlements ORDER BY id")]
        tasks = [dict(r) for r in self.store.query("SELECT id,agent_id,kind,site_id,started_tick,due_tick,status,completed_tick FROM frontier_tasks ORDER BY id")]
        data = {"tick": tick, "sites": sites, "settlements": settlements, "tasks": tasks,
                "required_work": self.REQUIRED_WORK}
        self.store.insert("frontier_history", tick=tick, data_json=json.dumps(data, sort_keys=True))
