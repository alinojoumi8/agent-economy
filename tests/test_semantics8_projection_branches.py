"""Branch-complete tests for the shared live/replay projection layer."""
from __future__ import annotations

import json

import pytest

from communications.delivery import CommunicationDelivery
from communications.policy import AccessBasis, Principal
from engine.actions import ActionExecutor
from server.projections import causal as causal_projection
from server.projections.causal import (
    _message_for_memory,
    _node_allowed,
    _semantic_row,
    build_causal_projection,
)
from server.projections.communications import _audience_view, build_message, build_threads
from server.projections.envelope import (
    ProjectionRequestError,
    build_envelope,
    current_cursor,
    lineage,
    resolve_tick,
    semantics_version,
    validate_fork,
)
from server.projections.events import build_backfill, build_events
from server.projections.snapshot import build_snapshot
from server.projections.transport import recovery_messages
from tests.conftest import make_agent, make_bank


def _world(economy):
    economy.config["engine_semantics_version"] = 8
    economy.config.setdefault("communications", {})
    economy.store.set_meta(
        tick=6, status="paused", phase="FINALIZE",
        config_json=json.dumps(economy.config, sort_keys=True))
    bank_id = make_bank(economy)
    sender, _ = make_agent(
        economy, bank_id, name="Sender", role="founder", population_tier="core")
    recipient, _ = make_agent(economy, bank_id, name="Recipient")
    outsider, _ = make_agent(economy, bank_id, name="Outsider")
    return bank_id, sender, recipient, outsider


def _send(economy, sender, audience, *, tick=1, subject="Subject", body="Body"):
    result = ActionExecutor(economy).execute_action(
        tick, sender,
        {"type": "send_message", "audience": audience, "subject": subject, "body": body})
    assert result["ok"], result
    return result


def _direct(economy, sender, recipient, **kwargs):
    return _send(
        economy, sender, {"kind": "direct", "agent_ids": [recipient]}, **kwargs)


def test_envelope_tick_lineage_fork_and_cursor_validation(economy):
    economy.store.set_meta(tick=5, config_json="{}")
    assert resolve_tick(economy.store, None) == 5
    assert resolve_tick(economy.store, "live") == 5
    assert resolve_tick(economy.store, "3") == 3
    for requested, match in (("bad", "non-negative"), (-1, "outside"), (6, "outside")):
        with pytest.raises(ProjectionRequestError, match=match):
            resolve_tick(economy.store, requested)
    assert semantics_version(economy.store) == 1
    assert current_cursor(economy.store) == 0
    assert current_cursor(economy.store, 3) == 0

    meta = lineage(economy.store)
    assert meta["fork_id"] is None
    validate_fork(economy.store, None)
    with pytest.raises(ProjectionRequestError, match="fork"):
        validate_fork(economy.store, "wrong")

    economy.store.set_meta(parent_run_id="parent", fork_tick=2)
    fork = lineage(economy.store)
    assert fork["fork_id"] == fork["run_id"]
    validate_fork(economy.store, fork["fork_id"])
    validate_fork(economy.store, None)
    economy.store.execute(
        "INSERT INTO projection_commits (tick,phase,domains_json) VALUES (3,'FINALIZE','[]')")
    envelope = build_envelope(
        economy.store, Principal("ordinary"), "probe", {"value": 1},
        as_of_tick=3, event_cursor=99)
    assert envelope["event_cursor"] == 99


def test_event_and_backfill_filters_limits_and_empty_pages(economy):
    _world(economy)
    economy.store.log_event(1, "low", {}, phase=None, importance=0.5)
    important = economy.store.log_event(
        2, "important", {"value": 1}, phase="MARKET",
        subject_type="agent", subject_id=1, importance=2.0)
    economy.store.log_event(3, "important", {}, phase="MARKET", importance=2.0)
    filtered = build_events(
        economy.store, as_of_tick=3, after_id=0, limit=1, kinds=("important",))
    assert filtered["items"][0]["id"] == important
    assert filtered["truncated"] is True
    assert filtered["next_after_id"] == important
    assert build_events(economy.store, as_of_tick=3, limit=0)["items"]
    assert len(build_events(economy.store, as_of_tick=3, limit=999)["items"]) == 3
    empty = build_events(economy.store, as_of_tick=0, after_id=999, limit=1)
    assert empty == {"items": [], "next_after_id": None, "truncated": False}

    for tick in range(1, 4):
        economy.store.execute(
            "INSERT INTO projection_commits (tick,phase,domains_json) VALUES (?,?,?)",
            (tick, "FINALIZE", json.dumps(["events"])))
    page = build_backfill(economy.store, after_cursor=0, limit=1)
    assert page["truncated"] is True
    assert page["next_cursor"] == page["commits"][0]["event_cursor"]
    assert build_backfill(economy.store, after_cursor=999, limit=999) == {
        "commits": [], "next_cursor": None, "truncated": False}
    assert recovery_messages(economy.store, after_cursor=0, limit=1)[0][
        "type"] == "projection_invalidated"


def test_recovery_can_return_an_empty_delta_set(economy):
    economy.store.set_meta(tick=0)
    assert recovery_messages(economy.store, after_cursor=-1) == []


def test_snapshot_domain_selection_and_alert_filter(economy):
    _world(economy)
    economy.store.set_meta(active_tick=None)
    economy.store.log_event(1, "low", {}, importance=0.5)
    economy.store.log_event(1, "high", {}, importance=2.0)
    summary_only = build_snapshot(
        economy.store, Principal("ordinary"), as_of_tick=1, domains=("summary",))
    assert set(summary_only) == {"summary"}
    assert summary_only["summary"]["active_tick"] is None
    economy.store.set_meta(active_tick=1)
    defaults = build_snapshot(
        economy.store, Principal("ordinary"), as_of_tick=1, domains=())
    assert set(defaults) == {"summary", "alerts", "communications", "events"}
    assert [item["kind"] for item in defaults["alerts"]] == ["high"]
    assert defaults["summary"]["active_tick"] == 1


def test_message_projection_organization_sender_absence_and_delivery_cutoff(
        economy, monkeypatch):
    _, sender, recipient, _ = _world(economy)
    direct = _direct(economy, sender, recipient)
    firm_id = economy.store.insert(
        "firms", name="Firm", sector="goods", founder_agent_id=sender,
        status="private", product_json="{}", founded_tick=0)
    economy.store.insert(
        "employments", firm_id=firm_id, agent_id=recipient, title="staff", wage_cents=1,
        start_tick=0, end_tick=None, status="active", pay_interval_ticks=30,
        next_pay_tick=30)
    organization = _send(
        economy, sender,
        {"kind": "organization", "organization_kind": "firm", "organization_id": firm_id})

    before = build_message(
        economy.store, Principal("sender", agent_id=sender), direct["message_id"],
        as_of_tick=1)
    assert before["status"] == "queued"
    assert before["deliveries"] == []
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    economy.store.execute(
        "UPDATE comm_deliveries SET read_tick=2,read_context_key='read' "
        "WHERE message_id=? AND recipient_agent_id=?",
        (direct["message_id"], recipient))
    recipient_view = build_message(
        economy.store, Principal("recipient", agent_id=recipient), direct["message_id"],
        as_of_tick=2)
    assert recipient_view["deliveries"][0]["read_tick"] == 2
    organization_view = build_message(
        economy.store, Principal("recipient", agent_id=recipient), organization["message_id"],
        as_of_tick=2)
    assert organization_view["audience"] == [{
        "kind": "organization", "organization_kind": "firm", "organization_id": firm_id}]
    assert _audience_view(
        economy.store, direct["message_id"], AccessBasis.ORGANIZATION_AT_DELIVERY) == []

    original = economy.store.query_one

    def no_sender(sql, params=()):
        if sql.startswith("SELECT id,name,role FROM agents"):
            return None
        return original(sql, params)

    monkeypatch.setattr(economy.store, "query_one", no_sender)
    assert "sender" not in build_message(
        economy.store, Principal("sender", agent_id=sender), direct["message_id"],
        as_of_tick=2)


def test_thread_projection_skips_hidden_rows_and_paginates(economy, monkeypatch):
    _, sender, recipient, outsider = _world(economy)
    _direct(economy, sender, recipient, subject="Private")
    first = _send(economy, sender, {"kind": "public"}, subject="Public 1")
    second = _send(economy, sender, {"kind": "public"}, subject="Public 2")
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    ordinary = Principal("ordinary")
    page = build_threads(economy.store, ordinary, as_of_tick=2, limit=1)
    assert [item["subject"] for item in page["items"]] == ["Public 1"]
    assert page["truncated"] is True
    assert page["next_after_thread_id"] == first["thread_id"]
    second_page = build_threads(
        economy.store, ordinary, as_of_tick=2,
        after_thread_id=page["next_after_thread_id"], limit=999)
    assert [item["thread_id"] for item in second_page["items"]] == [second["thread_id"]]
    assert build_message(
        economy.store, Principal("outside", agent_id=outsider),
        first["message_id"], as_of_tick=0) is None

    reply = ActionExecutor(economy).execute_action(
        2, sender,
        {"type": "reply_message", "parent_message_id": first["message_id"], "body": "reply"})
    assert reply["ok"]
    import server.projections.communications as module
    real_build_message = module.build_message

    def sometimes_missing(store, principal, message_id, **kwargs):
        if int(message_id) == int(reply["message_id"]):
            return None
        return real_build_message(store, principal, message_id, **kwargs)

    monkeypatch.setattr(module, "build_message", sometimes_missing)
    sender_threads = build_threads(
        economy.store, Principal("sender", agent_id=sender), as_of_tick=2)
    public_one = next(item for item in sender_threads["items"] if item["thread_id"] == first["thread_id"])
    assert len(public_one["messages"]) == 1
    monkeypatch.setattr(module, "build_message", real_build_message)


def test_causal_semantic_rows_and_policy_filtering(economy, monkeypatch):
    _, sender, recipient, outsider = _world(economy)
    private = _direct(economy, sender, recipient)
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    communication_memory = economy.store.scalar(
        "SELECT memory_id FROM comm_deliveries WHERE message_id=?", (private["message_id"],))
    ordinary_memory = economy.store.insert(
        "memories", agent_id=sender, tick=1, kind="observation", text="ordinary",
        importance=1.0, entities_json="[]", last_accessed_tick=0, demoted=0)
    event_id = economy.store.log_event(
        1, "event", {"value": 1}, phase="MARKET", subject_type="agent",
        subject_id=sender, importance=1.5)
    proposal_id = economy.store.insert(
        "action_proposals", tick=2, actor_id=sender, action_type="buy",
        payload_json="{}", evidence_event_ids_json="[]", model_call_id=None,
        rationale_summary="", validation_status="accepted", result_json="{}")
    transaction_id = economy.store.insert(
        "transactions", tick=3, kind="purchase", memo="memo", created_at=None)

    event_node = {"kind": "event", "id": str(event_id), "tick": 1, "order_key": "1"}
    proposal_node = {
        "kind": "action_proposal", "id": str(proposal_id), "tick": 2, "order_key": "2"}
    ledger_node = {
        "kind": "ledger_transaction", "id": str(transaction_id), "tick": 3,
        "order_key": "3"}
    ordinary_memory_node = {
        "kind": "memory", "id": str(ordinary_memory), "tick": 1, "order_key": "m"}
    message_node = {
        "kind": "message", "id": str(private["message_id"]), "tick": 1,
        "order_key": "p"}
    communication_memory_node = {
        "kind": "memory", "id": str(communication_memory), "tick": 2,
        "order_key": "c"}
    future_node = {"kind": "event", "id": str(event_id), "tick": 9, "order_key": "f"}

    assert _message_for_memory(economy.store, ordinary_memory) is None
    assert _message_for_memory(economy.store, communication_memory) == private["message_id"]
    policy = causal_projection.CommunicationPolicy(economy.store)
    outside = Principal("outside", agent_id=outsider)
    assert not _node_allowed(economy.store, policy, outside, message_node, 3)
    assert not _node_allowed(
        economy.store, policy, outside, communication_memory_node, 3)
    assert _node_allowed(economy.store, policy, outside, ordinary_memory_node, 3)
    assert _node_allowed(economy.store, policy, outside, event_node, 3)

    assert _semantic_row(economy.store, event_node)["label"] == "event"
    assert _semantic_row(economy.store, proposal_node)["label"] == "buy"
    assert _semantic_row(economy.store, ledger_node)["label"] == "purchase"
    assert _semantic_row(economy.store, ordinary_memory_node)["label"] == "memory"
    for missing in (
        {"kind": "event", "id": "999999", "tick": 1, "order_key": "x"},
        {"kind": "action_proposal", "id": "999999", "tick": 1, "order_key": "x"},
        {"kind": "ledger_transaction", "id": "999999", "tick": 1, "order_key": "x"},
    ):
        assert "label" not in _semantic_row(economy.store, missing)

    def edge(source, target, relation, authority):
        return {
            "id": len(raw_edges) + 1,
            "source_kind": source["kind"], "source_id": source["id"],
            "target_kind": target["kind"], "target_id": target["id"],
            "relation": relation, "authority": authority, "confidence": 1.0,
            "method": None, "provenance_json": "{}", "evidence_json": "{}",
        }

    raw_edges = []
    raw_edges.append(edge(event_node, proposal_node, "triggered", "engine"))
    raw_edges.append(edge(message_node, event_node, "triggered", "engine"))
    raw_edges.append(edge(event_node, message_node, "triggered", "engine"))
    raw_edges.append(edge(proposal_node, ledger_node, "settled", "engine"))
    raw_edges.append(edge(event_node, ledger_node, "triggered", "actor_claim"))
    raw = {
        "root": message_node,
        "nodes": [event_node, proposal_node, ledger_node, ordinary_memory_node,
                  message_node, communication_memory_node, future_node],
        "edges": raw_edges,
        "cycles": [{"kind": "event", "id": str(event_id), "cycle": True}],
        "truncated": False,
    }

    class FakeCausal:
        def __init__(self, _store):
            pass

        def neighborhood(self, *_args, **_kwargs):
            return raw

    monkeypatch.setattr(causal_projection, "CausalLinkService", FakeCausal)
    projected = build_causal_projection(
        economy.store, outside, "message", private["message_id"], as_of_tick=3,
        relations=("triggered",), authorities=("engine",))
    assert projected["root"] is None
    assert [(item["relation"], item["authority"]) for item in projected["edges"]] == [
        ("triggered", "engine")]
    assert projected["cycles"] == raw["cycles"]
