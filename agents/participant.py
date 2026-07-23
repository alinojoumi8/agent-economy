"""Server-authoritative participant control for local sandbox runs.

Participant commands are durable inputs, but they still travel through the
normal ActionExecutor during EXECUTION.  This module never mutates economic
state directly.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from engine.store import Store, load_json
from .citizen_actions import action_spec, citizen_world_action_types


PARTICIPANT_TYPES = citizen_world_action_types()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_value(source: dict, path: list[str], default: Any = None) -> Any:
    value: Any = source
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _path_assign(target: dict, path: list[str], value: Any) -> None:
    cursor = target
    for part in path[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[path[-1]] = value


class ParticipantError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ParticipantService:
    """Persist one local participant lease and one command per future tick."""

    def __init__(self, store: Store, context_builder, config: dict):
        self.store = store
        self.ctx = context_builder
        self.config = config
        self.local_currency_action_surfaces = bool(
            config.get("llm", {}).get("local_currency_action_surfaces", False))
        self.engine_semantics_version = int(config.get("engine_semantics_version", 2))
        self.enabled = bool(config.get("participant_mode", {}).get("enabled", False))
        if self.enabled and config.get("acceptance"):
            raise ValueError("participant mode cannot be enabled for an acceptance run")

    def _control(self):
        return self.store.query_one("SELECT * FROM participant_control WHERE id=1")

    def active_agent_id(self) -> Optional[int]:
        row = self._control()
        if not row or not row["active"] or row["agent_id"] is None:
            return None
        agent = self.store.query_one(
            "SELECT id, alive, kind FROM agents WHERE id=?", (int(row["agent_id"]),))
        if not agent or not agent["alive"] or agent["kind"] != "citizen":
            return None
        return int(agent["id"])

    def release_if_unavailable(self, tick: int, *, commit: bool) -> bool:
        """Close a stale lease after the citizen dies or otherwise disappears."""
        row = self._control()
        if not row or not row["active"] or row["agent_id"] is None:
            return False
        agent_id = int(row["agent_id"])
        agent = self.store.query_one(
            "SELECT alive,kind FROM agents WHERE id=?", (agent_id,))
        if agent and agent["alive"] and agent["kind"] == "citizen":
            return False
        self.store.execute(
            "UPDATE participant_control SET active=0,updated_at=? WHERE id=1", (_utcnow(),))
        self.store.execute(
            "UPDATE participant_actions SET status='cancelled' "
            "WHERE agent_id=? AND target_tick>=? AND status='queued'",
            (agent_id, int(tick)),
        )
        self.store.log_event(
            int(tick), "participant_control_released",
            {"agent_id": agent_id, "reason": "citizen_unavailable"}, phase="CONTROL",
            subject_type="agent", subject_id=agent_id, importance=1.5)
        if commit:
            self.store.commit()
        return True

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ParticipantError(403, "participant mode is disabled for this run")

    def _require_boundary(self, expected_tick: int, running: bool) -> None:
        self._require_enabled()
        if running:
            raise ParticipantError(409, "pause the world before changing participant control")
        meta = self.store.get_meta()
        if meta["active_tick"] is not None:
            raise ParticipantError(409, "participant changes require a completed-day boundary")
        if int(expected_tick) != self.store.tick:
            raise ParticipantError(
                409, f"stale participant state: expected day {expected_tick}, current day {self.store.tick}")

    def acquire(self, agent_id: int, expected_tick: int, *, running: bool) -> dict:
        self._require_boundary(expected_tick, running)
        agent = self.store.query_one(
            "SELECT id, name, kind, alive FROM agents WHERE id=?", (int(agent_id),))
        if not agent:
            raise ParticipantError(404, "citizen not found")
        if agent["kind"] != "citizen" or not agent["alive"]:
            raise ParticipantError(409, "only a living citizen can be controlled")
        current = self.active_agent_id()
        if current is not None and current != int(agent_id):
            raise ParticipantError(409, f"citizen {current} is already under participant control")
        self.store.execute(
            "INSERT INTO participant_control(id,agent_id,active,acquired_tick,updated_at) "
            "VALUES(1,?,1,?,?) ON CONFLICT(id) DO UPDATE SET "
            "agent_id=excluded.agent_id,active=1,acquired_tick=excluded.acquired_tick,"
            "updated_at=excluded.updated_at",
            (int(agent_id), self.store.tick, _utcnow()),
        )
        self.store.set_meta(participant_influenced=1)
        self.store.log_event(
            self.store.tick, "participant_control_acquired",
            {"agent_id": int(agent_id), "name": agent["name"]}, phase="CONTROL",
            subject_type="agent", subject_id=int(agent_id), importance=1.5)
        self.store.commit()
        return self.status(running=False)

    def release(self, expected_tick: int, *, running: bool, reason: str = "released") -> dict:
        self._require_boundary(expected_tick, running)
        agent_id = self.active_agent_id()
        if agent_id is None:
            raise ParticipantError(409, "no citizen is under participant control")
        self.store.execute(
            "UPDATE participant_control SET active=0,updated_at=? WHERE id=1", (_utcnow(),))
        self.store.execute(
            "UPDATE participant_actions SET status='cancelled' "
            "WHERE agent_id=? AND target_tick>? AND status='queued'",
            (agent_id, self.store.tick),
        )
        self.store.log_event(
            self.store.tick, "participant_control_released",
            {"agent_id": agent_id, "reason": reason}, phase="CONTROL",
            subject_type="agent", subject_id=agent_id, importance=1.2)
        self.store.commit()
        return self.status(running=False)

    def has_queued_action(self) -> bool:
        agent_id = self.active_agent_id()
        if agent_id is None:
            return False
        return bool(self.store.scalar(
            "SELECT COUNT(*) FROM participant_actions "
            "WHERE agent_id=? AND target_tick=? AND status='queued'",
            (agent_id, self.store.tick + 1), default=0))

    def queue_action(
        self, expected_tick: int, action: dict, reasoning: str = "", *, running: bool,
    ) -> dict:
        self._require_boundary(expected_tick, running)
        agent_id = self.active_agent_id()
        if agent_id is None:
            raise ParticipantError(409, "take control of a citizen before choosing an action")
        normalized = self._normalize_action(agent_id, action)
        target_tick = self.store.tick + 1
        prior = self.store.query_one(
            "SELECT id FROM participant_actions WHERE agent_id=? AND target_tick=?",
            (agent_id, target_tick))
        self.store.execute(
            "INSERT INTO participant_actions(agent_id,target_tick,action_json,reasoning,status,"
            "result_json,created_at,executed_at) VALUES(?,?,?,?,'queued',NULL,?,NULL) "
            "ON CONFLICT(agent_id,target_tick) DO UPDATE SET action_json=excluded.action_json,"
            "reasoning=excluded.reasoning,status='queued',result_json=NULL,executed_at=NULL",
            (agent_id, target_tick, json.dumps(normalized), str(reasoning).strip()[:500], _utcnow()),
        )
        event = "participant_action_replaced" if prior else "participant_action_queued"
        self.store.set_meta(participant_influenced=1)
        self.store.log_event(
            self.store.tick, event,
            {"agent_id": agent_id, "target_tick": target_tick, "action": normalized},
            phase="CONTROL", subject_type="agent", subject_id=agent_id, importance=1.2)
        self.store.commit()
        return self.status(running=False)

    def status(self, *, running: bool) -> dict:
        if not self.enabled:
            reason = "disabled for acceptance runs" if self.config.get("acceptance") else "disabled by config"
            return {"enabled": False, "reason": reason, "active": False}
        meta = self.store.get_meta()
        if not running and meta["active_tick"] is None:
            self.release_if_unavailable(self.store.tick, commit=True)
        agent_id = self.active_agent_id()
        control = None
        catalog: list[dict] = []
        queued = None
        if agent_id is not None:
            agent = self.store.query_one(
                "SELECT id,name,occupation,age,health,retired FROM agents WHERE id=?", (agent_id,))
            control = dict(agent) if agent else {"id": agent_id}
            catalog = self.action_catalog(agent_id)
            row = self.store.query_one(
                "SELECT * FROM participant_actions WHERE agent_id=? AND target_tick=? "
                "ORDER BY id DESC LIMIT 1", (agent_id, self.store.tick + 1))
            if row:
                queued = {
                    "id": int(row["id"]), "target_tick": int(row["target_tick"]),
                    "action": load_json(row["action_json"], {}), "reasoning": row["reasoning"],
                    "status": row["status"],
                }
        last = self.store.query_one(
            "SELECT * FROM participant_actions WHERE status IN ('executed','rejected') "
            "ORDER BY executed_at DESC,id DESC LIMIT 1")
        return {
            "enabled": True, "active": agent_id is not None, "running": bool(running),
            "controlled_agent": control, "completed_tick": self.store.tick,
            "next_tick": self.store.tick + 1, "queued_action": queued,
            "action_catalog": catalog,
            "last_result": ({
                "agent_id": int(last["agent_id"]), "target_tick": int(last["target_tick"]),
                "action": load_json(last["action_json"], {}), "status": last["status"],
                "result": load_json(last["result_json"], []),
            } if last else None),
        }

    def history(
        self, agent_id: int, *, limit: int = 50, before_id: Optional[int] = None,
    ) -> dict:
        """Return a bounded, newest-first audit history for one citizen."""
        self._require_enabled()
        agent = self.store.query_one(
            "SELECT id,name,kind FROM agents WHERE id=?", (int(agent_id),))
        if not agent:
            raise ParticipantError(404, "citizen not found")
        if agent["kind"] != "citizen":
            raise ParticipantError(409, "participant history is available only for citizens")
        bounded_limit = max(1, min(100, int(limit)))
        params: list[Any] = [int(agent_id)]
        before = ""
        if before_id is not None:
            before = " AND id<?"
            params.append(int(before_id))
        params.append(bounded_limit + 1)
        rows = list(self.store.query(
            "SELECT id,agent_id,target_tick,action_json,reasoning,status,result_json,"
            "source_action_id,created_at,executed_at FROM participant_actions "
            f"WHERE agent_id=?{before} ORDER BY id DESC LIMIT ?", tuple(params)))
        has_more = len(rows) > bounded_limit
        rows = rows[:bounded_limit]
        items = [{
            "id": int(row["id"]),
            "agent_id": int(row["agent_id"]),
            "target_tick": int(row["target_tick"]),
            "action": load_json(row["action_json"], {}),
            "reasoning": row["reasoning"] or "",
            "status": row["status"],
            "result": load_json(row["result_json"], None),
            "source_action_id": (
                int(row["source_action_id"])
                if row["source_action_id"] is not None else None),
            "created_at": row["created_at"],
            "executed_at": row["executed_at"],
        } for row in rows]
        return {
            "agent": {"id": int(agent["id"]), "name": agent["name"]},
            "items": items,
            "next_before_id": int(rows[-1]["id"]) if has_more and rows else None,
        }

    def action_catalog(self, agent_id: int) -> list[dict]:
        agent = self.store.query_one("SELECT * FROM agents WHERE id=?", (int(agent_id),))
        if not agent or not agent["alive"] or agent["kind"] != "citizen":
            return []
        ctx = self.ctx.build(agent, self.store.tick + 1)
        prices = ctx.get("prices", [])
        jobs = ctx.get("jobs", [])
        listed = ctx.get("listed_firms", [])
        banks = [bank for bank in ctx.get("banks", []) if bank.get("status") == "open"]
        current_bank = ctx.get("state", {}).get("bank_id")
        destinations = [bank for bank in banks if bank.get("id") != current_bank]
        if self.local_currency_action_surfaces:
            primary_currency = str(self.store.scalar(
                "SELECT ac.currency_code FROM agents a JOIN accounts ac "
                "ON ac.id=a.checking_account_id WHERE a.id=?", (int(agent_id),),
                default="USD") or "USD")
            account_rows = self.store.query(
                "SELECT ac.id,ac.owner_type,ac.owner_id,ac.label,ac.currency_code,"
                "COALESCE(a.name,f.name,ac.label) AS name "
                "FROM accounts ac LEFT JOIN agents a ON ac.owner_type='agent' AND a.id=ac.owner_id "
                "LEFT JOIN firms f ON ac.owner_type='firm' AND f.id=ac.owner_id "
                "WHERE ac.id<>? AND ac.currency_code=? "
                "AND (ac.owner_type<>'agent' OR a.alive=1) ORDER BY ac.id LIMIT 250",
                (int(agent["checking_account_id"] or 0), primary_currency))
        else:
            account_rows = self.store.query(
                "SELECT ac.id,ac.owner_type,ac.owner_id,ac.label,"
                "COALESCE(a.name,f.name,ac.label) AS name "
                "FROM accounts ac LEFT JOIN agents a ON ac.owner_type='agent' AND a.id=ac.owner_id "
                "LEFT JOIN firms f ON ac.owner_type='firm' AND f.id=ac.owner_id "
                "WHERE ac.id<>? AND (ac.owner_type<>'agent' OR a.alive=1) "
                "ORDER BY ac.id LIMIT 250", (int(agent["checking_account_id"] or 0),))
        accounts = [dict(row) for row in account_rows]
        firm = ctx.get("my_firm")
        applications = ctx.get("firm_applications", [])
        incoming_job_offers = ctx.get("incoming_job_offers", [])
        firm_job_offers = ctx.get("firm_job_offers", [])
        ipo_offerings = ctx.get("ipo_offerings", [])
        lawyers = [dict(row) for row in self.store.query(
            "SELECT id,name FROM agents WHERE alive=1 AND lower(COALESCE(occupation,''))='lawyer' ORDER BY id")]

        def select(name: str, label: str, options: list[dict], *, required: bool = True) -> dict:
            return {"name": name, "label": label, "kind": "select", "required": required,
                    "options": options}

        def number(name: str, label: str, default: int, minimum: int = 0) -> dict:
            return {"name": name, "label": label, "kind": "number", "required": True,
                    "default": default, "min": minimum}

        def text(name: str, label: str, default: str = "", maximum: int = 120,
                 required: bool = True) -> dict:
            return {"name": name, "label": label, "kind": "text", "required": required,
                    "default": default, "max_length": maximum}

        def exact_action(action: dict, label: str, variant: str) -> dict:
            """Expose a context-authorized action without letting clients retarget it."""
            canonical = json.loads(json.dumps(action, sort_keys=True))
            fields = [
                {"name": key, "label": key.replace("_", " ").title(),
                 "kind": "hidden", "default": value}
                for key, value in canonical.items()
                if key not in {"type", "variant"}
            ]
            template = {**canonical, "variant": variant}
            return {
                "type": str(canonical["type"]),
                "variant": variant,
                "label": label,
                "fields": fields,
                "action": template,
            }

        founding_action = ((ctx.get("entrepreneurship_opportunity") or {}).get("action") or {})
        founding_idea = (founding_action.get("business_idea")
                         if isinstance(founding_action.get("business_idea"), dict) else {})
        founding_fields = [
            text("name", "Company name", str(founding_action.get("name", "")), 60),
            text("sector", "Sector", str(founding_action.get("sector", "services")), 40),
            select("lawyer_agent_id", "Lawyer", [
                {"value": l["id"], "label": l["name"]} for l in lawyers]),
            number("opening_capital", "Opening capital (cents)",
                   int(founding_action.get("opening_capital", 0)), 0),
        ]
        if founding_action.get("lawyer_agent_id") is not None:
            founding_fields[2]["default"] = int(founding_action["lawyer_agent_id"])
        if bool(self.config.get("entrepreneurship", {}).get("enabled", False)):
            idea_fields = [
                text("mission", "Mission", str(founding_idea.get("mission", "")), 240),
                text("customer_problem", "Customer / problem",
                     str(founding_idea.get("customer_problem", "")), 240),
                text("offering", "Offering", str(founding_idea.get("offering", "")), 160),
            ]
            for field in idea_fields:
                field["action_path"] = ["business_idea", field["name"]]
            founding_fields.extend(idea_fields)

        items = [
            {"type": "do_nothing", "label": "Do nothing", "fields": []},
            {"type": "buy_goods", "label": "Buy goods", "fields": [
                select("firm_id", "Seller", [{"value": p["firm_id"],
                        "label": f"{p['product']} - {p['price']}c - {p['inventory']} available"}
                        for p in prices]), number("qty", "Quantity", 1, 1)]},
            {"type": "apply_job", "label": "Apply for a job", "fields": [
                select("job_id", "Job", [{"value": j["job_id"],
                        "label": f"{j['title']} - {j['wage']}c"} for j in jobs])]},
            {"type": "apply_loan", "label": "Apply for a personal loan", "fields": [
                select("bank_id", "Bank", [{"value": b["id"], "label": b["name"]} for b in banks]),
                number("amount", "Amount (cents)", 100_000, 1),
                text("purpose", "Purpose", "personal expenses", 120)]},
            {"type": "move_deposits", "label": "Move bank deposits", "fields": [
                select("to_bank_id", "Destination bank", [{"value": b["id"], "label": b["name"]}
                       for b in destinations]),
                number("amount", "Amount (cents, 0 = all)", 0, 0)]},
            {"type": "place_order", "label": "Place a stock order", "fields": [
                select("firm_id", "Company", [{"value": f["firm_id"], "label": f["name"]}
                       for f in listed]),
                select("side", "Side", [{"value": "buy", "label": "Buy"},
                       {"value": "sell", "label": "Sell"}]),
                number("qty", "Shares", 1, 1), number("limit_price", "Limit price (cents, 0 = market)", 0, 0)]},
            {"type": "cancel_orders", "label": "Cancel my open stock orders", "fields": []},
            {"type": "transfer", "label": "Transfer money", "fields": [
                select("to_account", "Recipient", [{"value": a["id"],
                        "label": f"{a.get('name') or a.get('label') or a['owner_type']} - account {a['id']}"}
                        for a in accounts]), number("amount", "Amount (cents)", 1_000, 1),
                text("memo", "Memo", "", 120, required=False)]},
            {"type": "say_public", "label": "Make a public statement", "fields": [
                text("text", "Statement", "", 500)]},
            {"type": "buy_insurance", "label": "Buy health insurance", "fields": []},
            {"type": "cancel_insurance", "label": "Cancel health insurance", "fields": []},
            {"type": "found_company", "label": "Found a company", "fields": founding_fields},
        ]
        if self.engine_semantics_version >= 7 and bool(agent["retired"]):
            # Retirees do not search for work. Their only liquidity action is a
            # bounded transfer between the two accounts declared on their row.
            items = [item for item in items if item["type"] != "apply_job"]
            savings_balance = int(self.store.scalar(
                "SELECT ac.balance_cents FROM agents a JOIN accounts ac "
                "ON ac.id=a.savings_account_id WHERE a.id=? "
                "AND ac.owner_type='agent' AND ac.owner_id=a.id AND ac.kind='savings'",
                (int(agent_id),), default=0) or 0)
            items.append({
                "type": "withdraw_savings",
                "label": "Draw retirement savings",
                "fields": [number(
                    "amount", "Amount (cents)", max(1, min(savings_balance, 100_000)), 1)],
                "enabled": savings_balance > 0,
                "disabled_reason": "No savings balance is available",
            })
        if self.engine_semantics_version >= 6:
            candidate_offer_options = [{
                "value": offer["offer_id"],
                "label": f"{offer['firm_name']} - {offer['offered_wage']}c",
            } for offer in incoming_job_offers]
            ipo_options = [{
                "value": offering["offering_id"],
                "label": f"{offering['firm_name']} - reserve {offering['reserve_price']}c",
            } for offering in ipo_offerings]
            items.extend([
                {"type": "accept_job_offer", "variant": "candidate",
                 "label": "Accept a wage offer", "fields": [
                    select("offer_id", "Offer", candidate_offer_options)]},
                {"type": "counter_job_offer", "variant": "candidate",
                 "label": "Counter a wage offer", "fields": [
                    select("offer_id", "Offer", candidate_offer_options),
                    number("wage", "Requested wage (cents)", 200_00, 0)]},
                {"type": "reject_job_offer", "variant": "candidate",
                 "label": "Reject a wage offer", "fields": [
                    select("offer_id", "Offer", candidate_offer_options)]},
                {"type": "place_ipo_bid", "label": "Bid in an IPO", "fields": [
                    select("offering_id", "Offering", ipo_options),
                    number("qty", "Shares", 1, 1),
                    number("max_price", "Maximum price per share (cents)", 100, 1)]},
            ])
        if self.engine_semantics_version >= 7:
            for index, quote in enumerate(ctx.get("fx_quotes", [])):
                for side in ("buy", "sell"):
                    action = quote.get(f"{side}_action")
                    if isinstance(action, dict):
                        items.append(exact_action(
                            action,
                            f"{side.title()} FX {quote.get('pair', '')}".strip(),
                            f"fx-{index}-{side}",
                        ))
            for index, order in enumerate(ctx.get("open_fx_orders", [])):
                action = order.get("cancel_action")
                if isinstance(action, dict):
                    items.append(exact_action(
                        action, "Cancel an open FX order", f"fx-cancel-{index}"))
            for index, option in enumerate(ctx.get("migration_options", [])):
                action = option.get("action")
                if isinstance(action, dict):
                    items.append(exact_action(
                        action, "Request an authorized migration",
                        f"migration-{index}"))
            for index, opportunity in enumerate(ctx.get("trade_opportunities", [])):
                action = opportunity.get("action")
                if isinstance(action, dict):
                    items.append(exact_action(
                        action, "Create an authorized trade shipment",
                        f"trade-{index}"))
            startup = ctx.get("startup_work") or {}
            for index, action in enumerate(startup.get("eligible_actions", [])):
                if isinstance(action, dict) and action.get("type") in PARTICIPANT_TYPES:
                    items.append(exact_action(
                        action,
                        f"Perform authorized {str(action['type']).replace('_', ' ')}",
                        f"startup-{index}",
                    ))
        if self.engine_semantics_version >= 8:
            directory = ctx.get("communication_directory", [])[:20]
            for contact in directory:
                recipient_id = int(contact["agent_id"])
                variant = f"direct-{recipient_id}"
                items.append({
                    "type": "send_message",
                    "variant": variant,
                    "label": f"Message {contact.get('name') or f'agent {recipient_id}'}",
                    "fields": [
                        {"name": "audience", "kind": "hidden",
                         "default": {"kind": "direct", "agent_ids": [recipient_id]}},
                        text("subject", "Subject", "", 120),
                        text("body", "Message", "", 2_000),
                    ],
                    "action": {
                        "type": "send_message", "variant": variant,
                        "audience": {"kind": "direct", "agent_ids": [recipient_id]},
                        "subject": "", "body": "",
                    },
                })
            items.append({
                "type": "send_message",
                "variant": "public",
                "label": "Send a public message",
                "fields": [
                    {"name": "audience", "kind": "hidden",
                     "default": {"kind": "public"}},
                    text("subject", "Subject", "", 120),
                    text("body", "Message", "", 2_000),
                ],
                "action": {
                    "type": "send_message", "variant": "public",
                    "audience": {"kind": "public"}, "subject": "", "body": "",
                },
            })
            for item in ctx.get("authorized_inbox", [])[:20]:
                message_id = int(item["message_id"])
                if bool(item.get("can_reply")):
                    items.append({
                        "type": "reply_message",
                        "variant": f"reply-{message_id}",
                        "label": f"Reply to {item.get('sender_name') or message_id}",
                        "fields": [
                            {"name": "parent_message_id", "kind": "hidden",
                             "default": message_id},
                            text("body", "Reply", "", 2_000),
                        ],
                        "action": {
                            "type": "reply_message",
                            "variant": f"reply-{message_id}",
                            "parent_message_id": message_id,
                            "body": "",
                        },
                    })
                items.append({
                    "type": "forward_message",
                    "variant": f"forward-public-{message_id}",
                    "label": f"Forward message {message_id} publicly",
                    "fields": [
                        {"name": "source_message_id", "kind": "hidden",
                         "default": message_id},
                        {"name": "audience", "kind": "hidden",
                         "default": {"kind": "public"}},
                        text("note", "Forwarding note", "", 500, required=False),
                    ],
                    "action": {
                        "type": "forward_message",
                        "variant": f"forward-public-{message_id}",
                        "source_message_id": message_id,
                        "audience": {"kind": "public"},
                        "note": "",
                    },
                })
        if self.engine_semantics_version >= 11:
            for offer in ctx.get("compute_plan_offers", []):
                action = offer.get("action")
                if isinstance(action, dict) and bool(offer.get("eligible")):
                    items.append(exact_action(
                        action,
                        f"Buy {offer.get('tier')} compute plan "
                        f"({offer.get('price_cents')}c)",
                        f"compute-{offer.get('tier')}",
                    ))
            cancel = ctx.get("compute_plan_cancel_action")
            if isinstance(cancel, dict):
                items.append(exact_action(
                    cancel, "Cancel compute plan", "compute-cancel"))
            sponsorship = ctx.get("compute_sponsorship") or {}
            for index, action in enumerate(sponsorship.get("actions", [])):
                if isinstance(action, dict):
                    items.append(exact_action(
                        action, "Sponsor employee compute", f"sponsor-{index}"))
            for option in ctx.get("study_skill_options", []):
                action = option.get("action")
                if isinstance(action, dict):
                    items.append(exact_action(
                        action,
                        f"Study {option.get('skill_key')} "
                        f"({option.get('price_cents')}c)",
                        f"study-{option.get('skill_key')}",
                    ))
        if firm:
            firm_id = int(firm["firm_id"])
            firm_items = [
                {"type": "set_price", "label": "Set my company price", "fields": [
                    {"name": "firm_id", "kind": "hidden", "default": firm_id},
                    number("price", "Unit price (cents)", int(firm["price"]), 1)]},
                {"type": "post_job", "label": "Post a company job", "fields": [
                    {"name": "firm_id", "kind": "hidden", "default": firm_id},
                    text("title", "Job title", "worker", 60), number("wage", "Wage (cents)", 200_00, 0)]},
                {"type": "fire", "label": "Fire an employee", "fields": [
                    select("employment_id", "Employee", [{"value": e["employment_id"],
                           "label": f"Agent {e['agent_id']} - {e['occupation'] or 'employee'}"}
                           for e in firm.get("employee_roster", [])])]},
                {"type": "pitch_vc", "label": "Pitch my company to VC", "fields": [
                    {"name": "firm_id", "kind": "hidden", "default": firm_id},
                    number("ask", "Funding request (cents)", 500_00, 1),
                    text("summary", "Pitch", "growth capital", 300)]},
                {"type": "apply_loan", "label": "Apply for a company loan", "variant": "firm", "fields": [
                    {"name": "as_firm", "kind": "hidden", "default": True},
                    {"name": "firm_id", "kind": "hidden", "default": firm_id},
                    select("bank_id", "Bank", [{"value": b["id"], "label": b["name"]} for b in banks]),
                    number("amount", "Amount (cents)", 300_00, 1),
                    text("purpose", "Purpose", "working capital", 120)]},
            ]
            if self.engine_semantics_version < 6:
                firm_items.insert(2, {
                    "type": "hire", "label": "Hire an applicant", "fields": [
                        select("application_id", "Applicant", [{"value": a["application_id"],
                               "label": f"Agent {a['agent_id']} - {a['occupation'] or 'candidate'}"}
                               for a in applications])],
                })
            else:
                available_applications = [a for a in applications if a.get("current_offer_id") is None]
                incoming_options = [{
                    "value": offer["offer_id"],
                    "label": f"Agent {offer['candidate_agent_id']} - {offer['requested_wage']}c",
                } for offer in firm_job_offers]
                qualification = firm.get("ipo_qualification", {})
                active_ipo = firm.get("active_ipo")
                firm_items.extend([
                    {"type": "make_job_offer", "label": "Make a wage offer", "fields": [
                        select("application_id", "Applicant", [{
                            "value": a["application_id"],
                            "label": f"Agent {a['agent_id']} - posted {a['posted_wage']}c",
                        } for a in available_applications]),
                        number("wage", "Offered wage (cents)", 200_00, 0)]},
                    {"type": "accept_job_offer", "variant": "firm",
                     "label": "Accept a candidate counteroffer", "fields": [
                        select("offer_id", "Counteroffer", incoming_options)]},
                    {"type": "counter_job_offer", "variant": "firm",
                     "label": "Counter a candidate wage request", "fields": [
                        select("offer_id", "Counteroffer", incoming_options),
                        number("wage", "Offered wage (cents)", 200_00, 0)]},
                    {"type": "reject_job_offer", "variant": "firm",
                     "label": "Reject a candidate counteroffer", "fields": [
                        select("offer_id", "Counteroffer", incoming_options)]},
                    {"type": "open_ipo", "label": "Open an IPO book", "fields": [
                        {"name": "firm_id", "kind": "hidden", "default": firm_id},
                        number("shares_offered", "New shares offered", 100, 1),
                        number("reserve_price", "Reserve price (cents)", 100, 1),
                        number("minimum_subscription_bps", "Minimum subscription (bps)", 5000, 1)],
                     "enabled": bool(qualification.get("qualified")),
                     "disabled_reason": "; ".join(qualification.get("reasons", []))
                         or "Firm does not qualify"},
                    {"type": "close_ipo", "label": "Close my IPO book", "fields": [
                        {"name": "offering_id", "kind": "hidden",
                         "default": int(active_ipo["offering_id"]) if active_ipo else 0}],
                     "enabled": active_ipo is not None,
                     "disabled_reason": "No active IPO book"},
                ])
            items.extend(firm_items)
        for item in items:
            item.setdefault("variant", "default")
            spec = action_spec(str(item["type"]))
            if spec is not None:
                item["category"] = spec["category"]
                item["channel"] = spec["channel"]
            empty_required_select = any(
                field.get("kind") == "select" and field.get("required", True)
                and not field.get("options") for field in item.get("fields", []))
            item["enabled"] = bool(item.get("enabled", True)) and not empty_required_select
            if empty_required_select:
                item["disabled_reason"] = "No valid options are currently available"
        return items

    def _normalize_action(self, agent_id: int, action: Any) -> dict:
        if not isinstance(action, dict):
            raise ParticipantError(400, "action must be a JSON object")
        action_type = str(action.get("type", ""))
        if action_type not in PARTICIPANT_TYPES:
            raise ParticipantError(400, f"action type {action_type or '<missing>'} is not available")
        variant = str(action.get("variant", "default"))
        descriptors = [item for item in self.action_catalog(agent_id)
                       if item["type"] == action_type and item.get("variant", "default") == variant]
        if not descriptors:
            raise ParticipantError(400, "action is not available to the controlled citizen")
        descriptor = descriptors[0]
        if not descriptor.get("enabled", True):
            raise ParticipantError(409, descriptor.get("disabled_reason", "action is currently unavailable"))
        normalized: dict[str, Any] = {"type": action_type}
        allowed = {"type", "variant"}
        nested_allowed: dict[str, set[str]] = {}
        for field in descriptor.get("fields", []):
            name = field["name"]
            path = list(field.get("action_path") or [name])
            allowed.add(path[0])
            if len(path) > 1:
                nested_allowed.setdefault(path[0], set()).add(path[1])
            kind = field.get("kind")
            # Hidden fields are server-owned capability data. A client may echo
            # them, but it cannot redirect an action to another firm or role.
            value = (field.get("default") if kind == "hidden" else
                     _path_value(action, path, field.get("default")))
            if value is None or value == "":
                if field.get("required", True):
                    raise ParticipantError(400, f"{name} is required")
                continue
            if kind in {"number", "hidden"} and isinstance(field.get("default"), bool):
                value = bool(value)
            elif kind == "number":
                if isinstance(value, bool):
                    raise ParticipantError(400, f"{name} must be an integer")
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ParticipantError(400, f"{name} must be an integer") from None
                if value < int(field.get("min", value)):
                    raise ParticipantError(400, f"{name} must be at least {field['min']}")
            elif kind == "select":
                values = [option["value"] for option in field.get("options", [])]
                if value not in values:
                    raise ParticipantError(409, f"{name} is stale or unavailable")
            elif kind == "text":
                value = str(value).strip()
                if field.get("required", True) and not value:
                    raise ParticipantError(400, f"{name} is required")
                value = value[:int(field.get("max_length", 500))]
            _path_assign(normalized, path, value)
        for root, names in nested_allowed.items():
            supplied = action.get(root)
            if supplied is not None and not isinstance(supplied, dict):
                raise ParticipantError(400, f"{root} must be a JSON object")
            if isinstance(supplied, dict):
                nested_extras = set(supplied).difference(names)
                if nested_extras:
                    raise ParticipantError(
                        400, f"unexpected {root} fields: {sorted(nested_extras)}")
        extras = set(action).difference(allowed)
        if extras:
            raise ParticipantError(400, f"unexpected action fields: {sorted(extras)}")
        return normalized

    def normalize_action(self, agent_id: int, action: Any) -> dict:
        """Validate an action against the shared, state-filtered participant catalog."""
        return self._normalize_action(agent_id, action)

    def decision_for_tick(self, tick: int) -> Optional[dict]:
        row = self._replay_action(tick)
        if row is None:
            self.release_if_unavailable(tick, commit=False)
            agent_id = self.active_agent_id()
            if agent_id is None:
                return None
            row = self.store.query_one(
                "SELECT * FROM participant_actions WHERE agent_id=? AND target_tick=? "
                "AND status='queued' ORDER BY id DESC LIMIT 1", (agent_id, tick))
            if row is None:
                self.store.log_event(
                    tick, "participant_idle", {"agent_id": agent_id}, phase="MORNING",
                    subject_type="agent", subject_id=agent_id, importance=0.8)
                return {"agent_id": agent_id, "purpose": "participant_idle",
                        "envelope": {"actions": [{"type": "do_nothing"}], "belief_updates": []},
                        "reasoning": "Participant explicitly supplied no command.",
                        "llm_call_id": None, "participant_action_id": None}
        action = load_json(row["action_json"], {})
        return {
            "agent_id": int(row["agent_id"]), "purpose": "participant",
            "envelope": {"actions": [action], "belief_updates": []},
            "reasoning": str(row["reasoning"] or "Participant-selected action."),
            "llm_call_id": None, "participant_action_id": int(row["id"]),
        }

    def _replay_action(self, tick: int):
        source_path = self.config.get("replay_source_path")
        if not source_path:
            return None
        path = Path(str(source_path))
        if not path.exists():
            return None
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='participant_actions'").fetchone()
            if not exists:
                return None
            source = conn.execute(
                "SELECT * FROM participant_actions WHERE target_tick=? "
                "AND status IN ('executed','rejected') ORDER BY id LIMIT 1", (tick,)).fetchone()
            if not source:
                return None
            self.store.execute(
                "INSERT OR IGNORE INTO participant_actions(agent_id,target_tick,action_json,reasoning,"
                "status,source_action_id,created_at) VALUES(?,?,?,?,'queued',?,?)",
                (int(source["agent_id"]), tick, source["action_json"], source["reasoning"],
                 int(source["id"]), _utcnow()),
            )
            self.store.set_meta(participant_influenced=1)
            return self.store.query_one(
                "SELECT * FROM participant_actions WHERE agent_id=? AND target_tick=?",
                (int(source["agent_id"]), tick))
        finally:
            conn.close()

    def complete(self, action_id: Optional[int], results: list[dict], tick: int) -> None:
        if action_id is None:
            return
        row = self.store.query_one("SELECT * FROM participant_actions WHERE id=?", (int(action_id),))
        if not row or row["status"] != "queued":
            return
        ok = bool(results) and all(bool(result.get("ok")) for result in results)
        status = "executed" if ok else "rejected"
        self.store.execute(
            "UPDATE participant_actions SET status=?,result_json=?,executed_at=? WHERE id=?",
            (status, json.dumps(results), _utcnow(), int(action_id)))
        self.store.log_event(
            tick, f"participant_action_{status}",
            {"participant_action_id": int(action_id), "agent_id": int(row["agent_id"]),
             "action": load_json(row["action_json"], {}), "results": results},
            phase="EXECUTION", subject_type="agent", subject_id=int(row["agent_id"]),
            importance=1.5 if ok else 1.0)
