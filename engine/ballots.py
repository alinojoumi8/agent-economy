"""Opt-in recorded voting over the existing immutable event ledger.

The legacy formulas remain unchanged when the recorded-v1 contract is absent.
Opening fixes the electorate, alternatives, bill version and closing tick.
Only explicit actor commands count as votes; missing decisions are nonvotes.
"""
from __future__ import annotations

import json
from collections import Counter


class RecordedBallots:
    def __init__(self, economy):
        self.e, self.store = economy, economy.store
        settings = economy.config.get("recorded_voting")
        self.enabled = settings is not None
        self.activation_tick = 1
        if self.enabled:
            if (not isinstance(settings, dict) or set(settings) - {"version", "activation_tick"}
                    or type(settings.get("version")) is not int or settings["version"] != 1
                    or economy.engine_semantics_version < 20):
                raise ValueError("recorded_voting requires version 1 and prospective Semantics 20+")
            self.activation_tick = settings.get("activation_tick", 1)
            if type(self.activation_tick) is not int or self.activation_tick < 1:
                raise ValueError("recorded_voting.activation_tick must be a positive integer")
            if economy.config.get("political_model", {}).get("enabled", False):
                from llm.decision_config import decision_policy, POLICY_VERSION_V4
                policy = decision_policy(economy.config)
                if (policy is None or policy["version"] != POLICY_VERSION_V4
                        or "politics" not in policy["domains"]):
                    raise ValueError("recorded_voting with politics requires the V4 politics domain")

    def active(self, tick):
        return self.enabled and tick >= self.activation_tick

    def _events(self, kind, tick):
        return [json.loads(r["payload_json"]) for r in self.store.query(
            "SELECT payload_json FROM events WHERE kind=? AND tick=? ORDER BY id", (kind, tick))]

    def contests(self, tick):
        return self._events("ballot_opened", tick) if self.active(tick) else []

    def _local(self, actor, tick):
        return self.e.engine_semantics_version < 21 or self.e.population.is_local(actor, tick)

    def _open(self, tick, key, electorate, choices, **details):
        if any(c["key"] == key for c in self.contests(tick)):
            return
        self.store.log_event(tick, "ballot_opened", {
            "contract": "recorded-voting-v1", "key": key, "opened_tick": tick,
            "closes_tick": tick, "electorate": sorted(set(electorate)),
            "choices": choices, **details}, phase="NIGHT_CLOSE", importance=2)

    def open_day(self, tick):
        if not self.active(tick):
            return
        people = [dict(r) for r in self.store.query(
            "SELECT id,kind FROM agents WHERE alive=1 AND age>=18 ORDER BY id")
            if self._local(int(r["id"]), tick)]
        fiscal = int(self.e.gov.p["election_interval_ticks"])
        if fiscal > 0 and tick % fiscal == 0:
            p, gov = self.e.gov.p, self.e.gov
            choices = {}
            for label, sign in (("expand", 1), ("austerity", -1)):
                choices[label] = {
                    "tax_rate_bps": max(int(p["min_tax_bps"]), min(int(p["max_tax_bps"]),
                        gov.tax_rate_bps() + sign * int(p["tax_step_bps"]))),
                    "unemployment_benefit_cents": max(int(p["min_benefit_cents"]),
                        min(int(p["max_benefit_cents"]), gov.benefit_cents() + sign * int(p["benefit_step_cents"])))}
            choices["abstain"] = {"meaning": "No policy preference"}
            self._open(tick, "fiscal", [r["id"] for r in people], choices,
                old_tax_bps=gov.tax_rate_bps(), old_benefit_cents=gov.benefit_cents())
        politics = self.e.politics
        if not politics.enabled:
            return
        for kind, interval in (("legislative", politics.house_interval), ("executive", politics.executive_interval)):
            if interval > 0 and tick % interval == 0:
                parties = [dict(r) for r in self.store.query("SELECT * FROM political_parties ORDER BY id")]
                choices = {f"party_{p['id']}": p for p in parties}
                choices["abstain"] = {"meaning": "No party preference"}
                self._open(tick, kind, [r["id"] for r in people if r["kind"] == "citizen"], choices)
        for bill in self.store.query("SELECT * FROM bills WHERE status IN ('committee','floor_house','floor_senate') ORDER BY id"):
            stage = bill["status"].removeprefix("floor_")
            if stage == "committee":
                members = self.store.query("SELECT l.id,l.agent_id FROM committee_members cm JOIN legislators l "
                    "ON l.id=cm.legislator_id WHERE cm.committee_id=? AND l.active=1 ORDER BY l.id", (bill["committee_id"],))
            else:
                members = self.store.query("SELECT id,agent_id FROM legislators WHERE chamber=? AND active=1 ORDER BY id", (stage,))
            live = {p["id"] for p in people}
            electorate = [r["agent_id"] for r in members if r["agent_id"] in live]
            version = self.store.query_one("SELECT * FROM bill_versions WHERE bill_id=? AND version=?", (bill["id"], bill["current_version"]))
            self._open(tick, f"bill_{bill['id']}_{bill['current_version']}_{stage}", electorate,
                {v: {"meaning": v} for v in ("yes", "no", "abstain")},
                bill_id=bill["id"], version=bill["current_version"], stage=stage,
                bill=dict(bill), terms=dict(version) if version else {})

    def pending_actors(self, tick):
        return sorted({aid for c in self.contests(tick) for aid in c["electorate"]})

    def upcoming_choices(self, actor_id, tick):
        """A preview for external wakes collected before NIGHT_CLOSE.

        Eligibility is rechecked against the actual opening snapshot at
        execution; the preview does not create votes or future event rows.
        """
        if not self.active(tick):
            return []
        actor = self.store.query_one("SELECT kind,alive,age FROM agents WHERE id=?", (actor_id,))
        if not actor or not actor["alive"] or actor["age"] < 18 or not self._local(actor_id, tick):
            return []
        choices = []
        interval = int(self.e.gov.p["election_interval_ticks"])
        if interval > 0 and tick % interval == 0:
            choices.append({"key": "fiscal", "choices": ["expand", "austerity", "abstain"]})
        if actor["kind"] == "citizen" and self.e.politics.enabled:
            parties = ["party_" + str(r["id"]) for r in self.store.query("SELECT id FROM political_parties ORDER BY id")]
            for key, interval in (("legislative", self.e.politics.house_interval), ("executive", self.e.politics.executive_interval)):
                if interval > 0 and tick % interval == 0:
                    choices.append({"key": key, "choices": parties + ["abstain"]})
        return choices

    def context(self, actor_id, tick):
        voted = {r["key"] for r in self._events("ballot_cast", tick) if r["actor_id"] == actor_id}
        return [{k: v for k, v in c.items() if k != "electorate"}
            for c in self.contests(tick) if actor_id in c["electorate"] and c["key"] not in voted]

    def cast(self, tick, actor_id, key, choice):
        if not self.active(tick):
            return {"ok": False, "reason": "recorded voting is not active"}
        contest = next((c for c in self.contests(tick) if c["key"] == key), None)
        if contest is None or any(c["key"] == key for c in self._events("ballot_closed", tick)):
            return {"ok": False, "reason": "ballot is not open for this tick"}
        actor = self.store.query_one("SELECT alive,age FROM agents WHERE id=?", (actor_id,))
        if (actor_id not in contest["electorate"] or not actor or not actor["alive"]
                or actor["age"] < 18 or not self._local(actor_id, tick)):
            return {"ok": False, "reason": "actor is not an eligible voter"}
        if choice not in contest["choices"]:
            return {"ok": False, "reason": "choice is not on this ballot"}
        existing = next((c for c in self._events("ballot_cast", tick) if c["key"] == key and c["actor_id"] == actor_id), None)
        if existing:
            return {"ok": choice == existing["choice"], "idempotent": choice == existing["choice"],
                    "reason": "ballot already recorded", "ballot_key": key}
        if "bill_id" in contest:
            bill = self.store.query_one("SELECT * FROM bills WHERE id=?", (contest["bill_id"],))
            stage = bill["status"].removeprefix("floor_") if bill else None
            legislator = self.e.politics._legislator_for_agent(actor_id)
            if not bill or not legislator or bill["current_version"] != contest["version"] or stage != contest["stage"]:
                return {"ok": False, "reason": "bill version, stage or authority changed"}
            self.e.politics._record_vote(bill, legislator, stage, choice, tick)
        self.store.log_event(tick, "ballot_cast", {"contract": "recorded-voting-v1",
            "key": key, "actor_id": actor_id, "choice": choice}, phase="EXECUTION",
            subject_type="agent", subject_id=actor_id, importance=1)
        return {"ok": True, "ballot_key": key, "choice": choice}

    def cast_legislative(self, tick, actor, bill_id, stage, choice):
        contest = next((c for c in self.contests(tick)
            if c.get("bill_id") == bill_id and (c.get("stage") == stage or stage == "floor" and c.get("stage") in {"house", "senate"})), None)
        return self.cast(tick, actor, contest["key"], choice) if contest else {"ok": False, "reason": "no open legislative ballot"}

    def close_day(self, tick):
        if not self.active(tick):
            return
        closed = {c["key"] for c in self._events("ballot_closed", tick)}
        casts = self._events("ballot_cast", tick)
        for contest in self.contests(tick):
            key = contest["key"]
            if key in closed:
                continue
            counts = Counter(c["choice"] for c in casts if c["key"] == key)
            result = {"contract": "recorded-voting-v1", "key": key, "counts": dict(sorted(counts.items())),
                "eligible": len(contest["electorate"]), "submitted": sum(counts.values()),
                "nonvotes": len(contest["electorate"]) - sum(counts.values())}
            if "bill_id" in contest:
                self._close_bill(tick, contest, counts, result)
            elif key == "fiscal":
                winner = "expand" if counts["expand"] > counts["austerity"] else "austerity"
                if counts["expand"] == counts["austerity"]:
                    winner = None
                values = contest["choices"][winner] if winner else {
                    "tax_rate_bps": contest["old_tax_bps"], "unemployment_benefit_cents": contest["old_benefit_cents"]}
                for metric, value in values.items():
                    self.store.record_metric(tick, metric, value)
                result.update(winner=winner, **values)
                self.store.log_event(tick, "election_held", result, phase="FINALIZE", subject_type="gov", importance=4)
            else:
                self._close_federal(tick, contest, counts, result)
            self.store.log_event(tick, "ballot_closed", result, phase="FINALIZE", importance=3)

    def _close_bill(self, tick, c, counts, result):
        bill = self.store.query_one("SELECT * FROM bills WHERE id=?", (c["bill_id"],))
        if not bill or bill["current_version"] != c["version"] or bill["status"].removeprefix("floor_") != c["stage"]:
            result["status"] = "superseded"
            return
        passed = counts["yes"] > len(c["electorate"]) / 2
        status = "rejected"
        if passed:
            stage = c["stage"]
            if stage == "committee":
                status = f"floor_{bill['origin_chamber']}"
                label = "committee_reported"
            else:
                other = "senate" if stage == "house" else "house"
                other_passed = self.store.query_one(
                    "SELECT 1 FROM bill_actions WHERE bill_id=? AND action_type=? "
                    "AND json_extract(detail_json,'$.version')=?", (bill["id"], other + "_passed", c["version"]))
                status = "executive" if other_passed else "floor_" + other
                label = stage + "_passed"
            self.e.politics._bill_action(bill["id"], tick, label, None, {"version": c["version"], "yes": counts["yes"], "electorate": len(c["electorate"])})
        self.store.update("bills", bill["id"], status=status)
        result.update(status=status, bill_id=bill["id"], version=c["version"])

    def _close_federal(self, tick, c, counts, result):
        options = [k for k in c["choices"] if k != "abstain"]
        total = sum(counts[k] for k in options)
        maximum = max((counts[k] for k in options), default=0)
        winners = [k for k in options if counts[k] == maximum]
        winner = winners[0] if total and len(winners) == 1 else None
        result.update(winner_party_id=c["choices"][winner]["id"] if winner else None, turnout=total)
        if total and c["key"] == "legislative":
            # Largest remainders; stable party IDs break seat allocation ties.
            for chamber in ("house", "senate"):
                legislators = self.store.query("SELECT id FROM legislators WHERE chamber=? AND active=1 ORDER BY seat_number", (chamber,))
                seats = {key: len(legislators) * counts[key] // total for key in options}
                residual = len(legislators) - sum(seats.values())
                for key in sorted(options, key=lambda k: (-(len(legislators) * counts[k] % total), c["choices"][k]["id"]))[:residual]:
                    seats[key] += 1
                allocation = [c["choices"][key]["id"] for key in options for _ in range(seats[key])]
                for legislator, party_id in zip(legislators, allocation):
                    self.store.update("legislators", legislator["id"], party_id=party_id, term_start_tick=tick,
                        term_end_tick=tick + self.e.politics.house_interval * (3 if chamber == "senate" else 1))
        elif winner and c["key"] == "executive":
            self.store.record_metric(tick, "executive_party_id", result["winner_party_id"])
        eid = self.store.insert("elections", tick=tick, election_type=c["key"],
            results_json=json.dumps(result, sort_keys=True), turnout=total)
        self.store.log_event(tick, "federal_election_held", {"election_id": eid, **result},
            phase="FINALIZE", subject_type="government", subject_id=1, importance=4)
