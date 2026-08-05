"""Generated temporal sequences for Semantics 8 communication invariants."""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from communications.delivery import CommunicationDelivery
from communications.handlers import CommunicationService
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.store import load_json
from research.supplier_warning_experiment import create_common_checkpoint


class CommunicationModel(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self._temp = tempfile.TemporaryDirectory(prefix="world-os-stateful-")
        self.store, self.identity = create_common_checkpoint(
            Path(self._temp.name) / "world.db")
        self.config = load_json(self.store.get_meta()["config_json"], {}) or {}
        self.economy = Economy(
            self.store, self.config, random.Random(20_260_718), random.Random(20_260_719))
        self.economy.ensure_system_accounts()
        self.executor = ActionExecutor(self.economy)
        self.delivery = CommunicationDelivery(self.store, self.config)
        self.service = CommunicationService(self.store, self.config)
        self.tick = 5
        self.sent_message_ids: list[int] = []
        self.firm_id = self.identity.supplier_firm_id
        for agent_id in (self.identity.retailer_agent_id, self.identity.outside_agent_id):
            self.store.insert(
                "employments", firm_id=self.firm_id, agent_id=agent_id,
                title="staff", wage_cents=100, start_tick=4, end_tick=None,
                status="active", pay_interval_ticks=30, next_pay_tick=34)
            self.store.update("agents", agent_id, employer_id=self.firm_id)

    def teardown(self):
        self.store.close()
        self._temp.cleanup()

    def _advance(self) -> int:
        self.tick += 1
        return self.tick

    def _recipient(self, index: int) -> int:
        return (
            self.identity.retailer_agent_id
            if index == 0 else self.identity.outside_agent_id)

    @rule(recipient_index=st.integers(min_value=0, max_value=1), marker=st.integers(0, 20))
    def send_direct(self, recipient_index: int, marker: int):
        tick = self._advance()
        result = self.executor.execute_action(tick, self.identity.sender_agent_id, {
            "type": "send_message",
            "audience": {"kind": "direct", "agent_ids": [
                self._recipient(recipient_index)]},
            "subject": f"Direct {marker}",
            "body": f"Stateful body {marker}",
        })
        if result.get("ok"):
            self.sent_message_ids.append(int(result["message_id"]))

    @rule(marker=st.integers(0, 20))
    def send_organization(self, marker: int):
        tick = self._advance()
        result = self.executor.execute_action(tick, self.identity.sender_agent_id, {
            "type": "send_message",
            "audience": {
                "kind": "organization", "organization_kind": "firm",
                "organization_id": self.firm_id,
            },
            "subject": f"Organization {marker}",
            "body": f"Organization body {marker}",
        })
        if result.get("ok"):
            self.sent_message_ids.append(int(result["message_id"]))

    @rule(marker=st.integers(0, 20))
    def send_public(self, marker: int):
        tick = self._advance()
        result = self.executor.execute_action(tick, self.identity.sender_agent_id, {
            "type": "send_message", "audience": {"kind": "public"},
            "subject": f"Public {marker}", "body": f"Public body {marker}",
        })
        if result.get("ok"):
            self.sent_message_ids.append(int(result["message_id"]))

    @rule()
    def deliver_due(self):
        self._advance()
        self.delivery.deliver_due(self.tick)

    @rule(recipient_index=st.integers(min_value=0, max_value=1))
    def mark_dead(self, recipient_index: int):
        agent_id = self._recipient(recipient_index)
        self.store.update("agents", agent_id, alive=0, died_tick=self.tick)

    @rule(recipient_index=st.integers(min_value=0, max_value=1))
    def end_membership(self, recipient_index: int):
        agent_id = self._recipient(recipient_index)
        self.store.execute(
            "UPDATE employments SET status='ended',end_tick=? "
            "WHERE firm_id=? AND agent_id=? AND status='active'",
            (self.tick, self.firm_id, agent_id),
        )
        self.store.update("agents", agent_id, employer_id=None)

    @rule()
    def reply_to_latest_delivery(self):
        parent = self.store.query_one(
            "SELECT d.message_id,d.recipient_agent_id FROM comm_deliveries d "
            "JOIN agents a ON a.id=d.recipient_agent_id "
            "WHERE d.delivery_status='delivered' AND a.alive=1 "
            "ORDER BY d.id DESC LIMIT 1")
        if parent is None:
            return
        tick = self._advance()
        result = self.executor.execute_action(tick, int(parent["recipient_agent_id"]), {
            "type": "reply_message", "parent_message_id": int(parent["message_id"]),
            "body": "Stateful acknowledgment",
        })
        if result.get("ok"):
            self.sent_message_ids.append(int(result["message_id"]))

    @rule()
    def forward_latest_delivery(self):
        source = self.store.query_one(
            "SELECT d.message_id,d.recipient_agent_id FROM comm_deliveries d "
            "JOIN agents a ON a.id=d.recipient_agent_id "
            "WHERE d.delivery_status='delivered' AND a.alive=1 "
            "ORDER BY d.id DESC LIMIT 1")
        if source is None:
            return
        sender_id = int(source["recipient_agent_id"])
        target_id = (
            self.identity.outside_agent_id
            if sender_id != self.identity.outside_agent_id
            else self.identity.sender_agent_id)
        tick = self._advance()
        result = self.executor.execute_action(tick, sender_id, {
            "type": "forward_message", "source_message_id": int(source["message_id"]),
            "audience": {"kind": "direct", "agent_ids": [target_id]},
            "note": "Stateful forward",
        })
        if result.get("ok"):
            self.sent_message_ids.append(int(result["message_id"]))

    @rule()
    def disclose_latest_message(self):
        message_id = self.store.scalar(
            "SELECT MAX(id) FROM comm_messages", default=None)
        if message_id is None:
            return
        authority_event_id = self.store.log_event(
            self.tick, "court_order", {"case_id": 77})
        try:
            self.service.grant_disclosure(
                tick=self.tick, message_id=int(message_id), case_id=77,
                grantee_agent_id=self.identity.outside_agent_id,
                authority_kind="court_order", authority_record_id=f"order-{message_id}",
                authority_event_id=authority_event_id,
                authority_ref={"case_id": 77}, verified_case_id=77,
            )
        except Exception:
            # Repeated generated commands can encounter an already-granted key;
            # the database invariants below remain the oracle.
            pass

    @invariant()
    def temporal_and_exactly_once_invariants_hold(self):
        assert self.store.scalar(
            "SELECT COUNT(*) FROM comm_messages "
            "WHERE deliver_at_tick<created_tick+1") == 0
        assert self.store.scalar(
            "SELECT COUNT(*)-COUNT(DISTINCT dedupe_key) FROM comm_deliveries") == 0
        assert self.store.scalar(
            "SELECT COUNT(*) FROM comm_deliveries WHERE delivery_status='delivered' "
            "AND memory_id IS NULL") == 0
        assert self.store.scalar(
            "SELECT COUNT(*) FROM comm_deliveries WHERE delivery_status='undeliverable' "
            "AND memory_id IS NOT NULL") == 0
        assert self.store.scalar(
            "SELECT COUNT(*) FROM comm_deliveries d LEFT JOIN memories m ON m.id=d.memory_id "
            "WHERE d.delivery_status='delivered' AND (m.id IS NULL OR m.kind<>'communication')") == 0
        delivered = int(self.store.scalar(
            "SELECT COUNT(*) FROM comm_deliveries WHERE delivery_status='delivered'"))
        observed = int(self.store.scalar(
            "SELECT COUNT(*) FROM causal_links WHERE source_kind='message' "
            "AND target_kind='memory' AND relation='observed' AND authority='engine'"))
        assert observed == delivered
        assert self.store.scalar(
            "SELECT COUNT(*) FROM comm_audiences a JOIN comm_messages m ON m.id=a.message_id "
            "WHERE a.audience_kind='public' AND EXISTS("
            "SELECT 1 FROM comm_deliveries d WHERE d.message_id=m.id)") == 0
        private_rows = self.store.query(
            "SELECT t.subject,m.body_text FROM comm_messages m "
            "JOIN comm_threads t ON t.id=m.thread_id WHERE m.visibility<>'public'")
        event_payloads = "\n".join(
            str(row["payload_json"] or "") for row in self.store.query("SELECT payload_json FROM events"))
        for row in private_rows:
            assert str(row["subject"]) not in event_payloads
            assert str(row["body_text"]) not in event_payloads
        for row in self.store.query(
                "SELECT membership_ref_json FROM comm_deliveries "
                "WHERE membership_ref_json IS NOT NULL"):
            snapshot = json.loads(row["membership_ref_json"])
            assert snapshot["tick"] <= self.tick


TestCommunicationModel = CommunicationModel.TestCase
TestCommunicationModel.settings = settings(
    max_examples=10,
    stateful_step_count=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
