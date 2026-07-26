from __future__ import annotations

import base64
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from agents.external import ExternalAgentError
from engine.store import Store
from run_config import load_config
from server.app import create_app
from world.loop import World
from world.replay_verify import verify_replay


def _world(tmp_path: Path, **gateway_overrides) -> World:
    config = load_config("runs/world-os-external.yaml")
    config["population"]["size"] = 4
    config["firms"]["count"] = 2
    config["firms"]["listed"] = 1
    config["banks"]["count"] = 1
    config["checkpoint_every"] = 0
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["external_gateway"].update(gateway_overrides)
    store = Store(str(tmp_path / "world.db"))
    store.init_run_meta("external-test", 42, config)
    world = World(store, config)
    world.initialize()
    return world


@pytest.fixture
def world10(tmp_path):
    world = _world(tmp_path)
    yield world
    world.close()


def _connection(world: World, *, owner: str = "owner-a", tier: str = "actor"):
    created = world.runtime.external.create_connection(
        tenant_id="tenant-a", owner_id=owner, display_name="Outside Founder",
        biography="A public test identity.", preferred_occupation="builder", tier=tier)
    if tier != "observer":
        world._spawn_due_arrivals(1)
    return created


def test_dedicated_actor_and_hash_only_personal_credential(world10: World):
    before = {int(row["id"]) for row in world10.store.query("SELECT id FROM agents")}
    created = _connection(world10)
    connection = created["connection"]
    token = created["credential"]["token"]
    bound = world10.runtime.external.connection(
        connection["id"], owner_id="owner-a", tenant_id="tenant-a")

    assert bound["actor_id"] not in before
    assert bound["actor_name"] == "Outside Founder"
    assert bound["actor_alive"] is True
    assert world10.store.query_one(
        "SELECT checking_account_id,age,region_id FROM agents WHERE id=?",
        (bound["actor_id"],))["checking_account_id"] is not None
    credential = world10.store.query_one(
        "SELECT token_hash FROM external_agent_credentials WHERE connection_id=?",
        (connection["id"],))
    assert credential["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in "\n".join(
        str(tuple(row)) for row in world10.store.query(
            "SELECT id,token_hash,scopes_json,audience FROM external_agent_credentials"))
    assert world10.store.get_meta()["external_agent_influenced"] == 1
    with pytest.raises(ExternalAgentError, match="not found"):
        world10.runtime.external.connection(
            connection["id"], owner_id="owner-b", tenant_id="tenant-a")


def test_agent_api_projects_hermes_lease_and_privacy_safe_receipt(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    actor_id = int(service.connection(
        created["connection"]["id"], owner_id="owner-a",
        tenant_id="tenant-a")["actor_id"])
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    turn = service.turn(auth)
    queued = service.submit_action(auth, {
        "target_tick": turn["target_tick"],
        "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "dashboard-proof",
        "rationale_summary": "Private rationale must not enter the public projection.",
    })
    service.complete(
        queued["submission_id"], [{"ok": True, "private": "not public"}],
        turn["target_tick"], event_ids=[77], resulting_state_hash="a" * 64,
    )
    world10.store.commit()

    with TestClient(create_app(world10)) as client:
        listed = next(
            row for row in client.get("/api/agents").json()
            if int(row["id"]) == actor_id
        )
        detail = client.get(f"/api/agents/{actor_id}").json()

    assert listed["execution"]["state"] == "hermes_connected"
    assert listed["execution"]["latest_turn"]["target_tick"] == turn["target_tick"]
    assert listed["execution"]["latest_receipt"]["status"] == "executed"
    assert listed["execution"]["latest_receipt"]["action_type"] == "do_nothing"
    assert detail["external_activity"]["receipts"][0]["event_ids"] == [77]
    serialized = str(detail["external_activity"])
    assert "Private rationale" not in serialized
    assert "not public" not in serialized

    world10.store.execute(
        "UPDATE external_agent_connections SET lease_expires_at=? WHERE id=?",
        ("2000-01-01T00:00:00+00:00", created["connection"]["id"]),
    )
    world10.store.set_meta(tick=turn["target_tick"])
    world10.store.commit()
    with TestClient(create_app(world10)) as client:
        completed_tick = client.get(f"/api/agents/{actor_id}").json()
    assert completed_tick["execution"]["state"] == "hermes_connected"

    world10.store.set_meta(tick=turn["target_tick"] + 1)
    world10.store.commit()
    with TestClient(create_app(world10)) as client:
        missed_tick = client.get(f"/api/agents/{actor_id}").json()
    assert missed_tick["execution"]["state"] == "offline_fallback"


def test_oauth_pkce_rotation_scope_reduction_expiry_and_revocation(
    world10: World, monkeypatch,
):
    created = _connection(world10)
    connection_id = created["connection"]["id"]
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    fixed = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("agents.external._now", lambda: fixed)
    code = world10.runtime.external.create_authorization_code(
        connection_id, tenant_id="tenant-a", owner_id="owner-a",
        client_id="test-client", redirect_uri="https://agent.test/callback",
        code_challenge=challenge, scopes=["world.read", "world.act"])
    pair = world10.runtime.external.exchange_authorization_code(
        code=code["code"], client_id="test-client",
        redirect_uri="https://agent.test/callback", code_verifier=verifier)
    identity = world10.runtime.external.authenticate(pair["access_token"], rate_limit=False)
    assert identity["scopes"] == ["world.act", "world.read"]
    with pytest.raises(ExternalAgentError, match="invalid"):
        world10.runtime.external.exchange_authorization_code(
            code=code["code"], client_id="test-client",
            redirect_uri="https://agent.test/callback", code_verifier=verifier)

    reduced = world10.runtime.external.refresh_access_token(
        refresh_token=pair["refresh_token"], scopes=["world.read"])
    assert reduced["scope"] == "world.read"
    with pytest.raises(ExternalAgentError, match="invalid"):
        world10.runtime.external.refresh_access_token(refresh_token=pair["refresh_token"])
    with pytest.raises(ExternalAgentError, match="escalation"):
        world10.runtime.external.refresh_access_token(
            refresh_token=reduced["refresh_token"], scopes=["world.read", "world.act"])

    monkeypatch.setattr("agents.external._now", lambda: fixed + timedelta(minutes=16))
    with pytest.raises(ExternalAgentError, match="expired"):
        world10.runtime.external.authenticate(reduced["access_token"], rate_limit=False)
    monkeypatch.setattr("agents.external._now", lambda: fixed)
    world10.runtime.external.revoke_token(pair["access_token"])
    with pytest.raises(ExternalAgentError, match="invalid"):
        world10.runtime.external.authenticate(pair["access_token"], rate_limit=False)


def test_turn_idempotency_execution_stale_rejection_and_safe_fallback(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    turn = service.turn(auth)
    first = service.submit_action(auth, {
        "target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "wake-1", "rationale_summary": "Safe no-op."})
    repeated = service.submit_action(auth, {
        "target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "wake-1"})
    assert first["submission_id"] == repeated["submission_id"]
    assert first["status"] == "queued"

    controlled, decisions = service.decisions_for_tick(turn["target_tick"])
    assert controlled == {auth["actor_id"]}
    assert decisions[0]["purpose"] == "external_agent"
    world10.runtime.execute_decisions(turn["target_tick"], decisions)
    executed = service.receipt(auth, first["submission_id"])
    assert executed["status"] == "executed"
    assert len(executed["resulting_state_hash"]) == 64

    world10.store.set_meta(tick=turn["target_tick"])
    next_turn = service.turn(auth)
    stale = service.submit_action(auth, {
        "target_tick": next_turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": "0" * 64, "idempotency_key": "wake-2-stale"})
    assert stale["status"] == "stale"
    assert stale["validator_results"][0]["validator"] == "projection_hash"

    controlled, fallback = service.decisions_for_tick(next_turn["target_tick"])
    assert controlled == {auth["actor_id"]}
    assert fallback[0]["purpose"] == "external_safe_policy"
    assert fallback[0]["envelope"]["actions"] == [{"type": "do_nothing"}]


def test_turn_expires_superseded_open_turn_before_creating_next_turn(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    first = service.turn(auth)

    world10.store.set_meta(tick=first["target_tick"])
    second = service.turn(auth)

    assert second["target_tick"] == first["target_tick"] + 1
    assert world10.store.scalar(
        "SELECT status FROM external_agent_turns WHERE id=?",
        (first["turn_id"],),
    ) == "expired"


def test_decision_tick_stales_queued_submissions_from_past_ticks(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    turn = service.turn(auth)
    queued = service.submit_action(auth, {
        "target_tick": turn["target_tick"],
        "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "late-after-snapshot",
    })

    service.decisions_for_tick(turn["target_tick"] + 1)

    receipt = service.receipt(auth, queued["submission_id"])
    assert receipt["status"] == "stale"
    assert receipt["validator_results"] == [{
        "validator": "target_tick",
        "ok": False,
        "message": "the target tick passed before execution",
    }]
    assert world10.store.scalar(
        "SELECT status FROM external_agent_turns WHERE id=?",
        (turn["turn_id"],),
    ) == "fallback"


def test_revocation_mid_turn_cancels_queued_action(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    turn = service.turn(auth)
    queued = service.submit_action(auth, {
        "target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "cancel-me"})
    service.revoke_credentials(
        auth["id"], owner_id="owner-a", tenant_id="tenant-a")
    receipt = service.receipt(auth, queued["submission_id"])
    assert receipt["status"] == "rejected"
    assert receipt["validator_results"][0]["message"] == "credentials_revoked"
    _controlled, decisions = service.decisions_for_tick(turn["target_tick"])
    assert decisions[0]["purpose"] == "external_safe_policy"


def test_complete_is_atomic_exactly_once_and_late_calls_are_noop(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    turn = service.turn(auth)
    queued = service.submit_action(auth, {
        "target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "exactly-once",
        "rationale_summary": "Race-safe completion.",
    })
    observed = world10.store.query_one(
        "SELECT status FROM external_action_submissions WHERE id=?",
        (queued["submission_id"],))
    assert observed["status"] == "queued"

    before_events = world10.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind LIKE 'external_action_%'",
        default=0)

    # Deterministic interleave: both callers observed queued, then complete twice.
    service.complete(
        queued["submission_id"], [{"ok": True, "effect": "first"}],
        turn["target_tick"], event_ids=[101], resulting_state_hash="a" * 64)
    service.complete(
        queued["submission_id"], [{"ok": False, "effect": "second"}],
        turn["target_tick"], event_ids=[202], resulting_state_hash="b" * 64)

    receipt = service.receipt(auth, queued["submission_id"])
    assert receipt["status"] == "executed"
    assert receipt["resulting_state_hash"] == "a" * 64
    assert receipt["event_ids"] == [101]
    after_events = world10.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind LIKE 'external_action_%'",
        default=0)
    assert after_events == before_events + 1
    terminal = world10.store.query(
        "SELECT kind,payload_json FROM events WHERE kind LIKE 'external_action_%' "
        "ORDER BY id DESC LIMIT 1")[0]
    assert terminal["kind"] == "external_action_executed"
    payload = json.loads(str(terminal["payload_json"]))
    assert payload["event_ids"] == [101]
    assert payload["resulting_state_hash"] == "a" * 64

    # Late complete after terminal status is a no-op.
    service.complete(
        queued["submission_id"], [{"ok": False}],
        turn["target_tick"], event_ids=[303], resulting_state_hash="c" * 64)
    assert service.receipt(auth, queued["submission_id"])["event_ids"] == [101]
    assert world10.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind LIKE 'external_action_%'",
        default=0) == after_events

    # Complete after rejection is also a no-op (fresh turn/connection).
    other = _connection(world10, owner="owner-reject")
    other_auth = service.authenticate(other["credential"]["token"], rate_limit=False)
    other_turn = service.turn(other_auth)
    rejected = service.submit_action(other_auth, {
        "target_tick": other_turn["target_tick"],
        "action": {"type": "not_a_real_action"},
        "observed_projection_hash": other_turn["projection_hash"],
        "idempotency_key": "already-rejected"})
    assert rejected["status"] == "rejected"
    rejected_events = world10.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind LIKE 'external_action_%'",
        default=0)
    service.complete(
        rejected["submission_id"], [{"ok": True}],
        other_turn["target_tick"], event_ids=[404], resulting_state_hash="d" * 64)
    assert service.receipt(other_auth, rejected["submission_id"])["status"] == "rejected"
    assert world10.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind LIKE 'external_action_%'",
        default=0) == rejected_events


def test_rest_mcp_contract_and_scope_filtered_tools(world10: World):
    created = _connection(world10, tier="observer")
    token = created["credential"]["token"]
    connection_id = created["connection"]["id"]
    app = create_app(world10)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v2/agent/me", headers=headers).status_code == 200
    turn = client.get("/api/v2/agent/turn", headers=headers).json()
    assert turn["version"] == "ae.turn.v1"
    initialized = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialized.status_code == 200
    assert initialized.headers["mcp-session-id"]
    tools = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).json()
    names = {item["name"] for item in tools["result"]["tools"]}
    assert {"ae_identity_get", "ae_world_observe", "ae_turn_wait"} <= names
    assert "ae_action_submit" not in names
    metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert metadata["resource"].endswith("/mcp")
    assert "world.read" in metadata["scopes_supported"]
    assert client.get("/api/v2/openapi.json").status_code == 200

    missing = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
    assert missing.status_code == 401
    missing_challenge = missing.headers["www-authenticate"]
    assert 'resource_metadata="http://testserver/.well-known/' in missing_challenge
    assert "oauth-protected-resource/mcp" in missing_challenge

    world10.runtime.external.revoke_credentials(
        connection_id, owner_id="owner-a", tenant_id="tenant-a")
    revoked = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}})
    assert revoked.status_code == 401
    revoked_challenge = revoked.headers["www-authenticate"]
    assert 'error="invalid_token"' in revoked_challenge
    assert 'resource_metadata="http://testserver/.well-known/' in revoked_challenge
    assert "oauth-protected-resource/mcp" in revoked_challenge


def test_oauth_discovery_dynamic_registration_browser_redirect_and_resource_binding(
    world10: World,
):
    created = _connection(world10, tier="observer")
    connection_id = created["connection"]["id"]
    client = TestClient(create_app(world10))
    redirect_uri = "http://127.0.0.1:43123/callback"
    registration = client.post("/oauth/register", json={
        "client_name": "OpenClaw test client", "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none",
    })
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]
    assert client_id.startswith("ae_client_")
    assert world10.store.scalar(
        "SELECT COUNT(*) FROM external_oauth_clients WHERE client_id=?", (client_id,)) == 1

    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["registration_endpoint"].endswith("/oauth/register")
    assert metadata["authorization_response_iss_parameter_supported"] is True
    verifier = "p" * 64
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    authorization = client.get(
        "/oauth/authorize", follow_redirects=False,
        headers={"X-AE-Owner-Id": "owner-a", "X-AE-Role": "agent_owner"},
        params={"response_type": "code", "client_id": client_id,
                "redirect_uri": redirect_uri, "code_challenge": challenge,
                "code_challenge_method": "S256", "scope": "world.read commons.read",
                "state": "opaque-state", "resource": "http://testserver/mcp",
                "tenant_id": "tenant-a", "connection_id": connection_id})
    assert authorization.status_code == 302
    callback = urlsplit(authorization.headers["location"])
    query = parse_qs(callback.query)
    assert query["state"] == ["opaque-state"]
    assert query["iss"] == ["http://testserver"]

    wrong_resource = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": query["code"][0],
        "client_id": client_id, "redirect_uri": redirect_uri,
        "code_verifier": verifier, "resource": "https://wrong.test/mcp"})
    assert wrong_resource.status_code == 400
    assert wrong_resource.json()["error"] == "invalid_target"
    pair = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": query["code"][0],
        "client_id": client_id, "redirect_uri": redirect_uri,
        "code_verifier": verifier, "resource": "http://testserver/mcp"})
    assert pair.status_code == 200
    pair_body = pair.json()
    token = pair_body["access_token"]
    refreshed = client.post("/oauth/token", data={
        "grant_type": "refresh_token",
        "refresh_token": pair_body["refresh_token"],
        "client_id": client_id,
    })
    assert refreshed.status_code == 200
    explicit_mismatch = client.post("/oauth/token", data={
        "grant_type": "refresh_token",
        "refresh_token": refreshed.json()["refresh_token"],
        "client_id": client_id,
        "resource": "https://wrong.test/mcp",
    })
    assert explicit_mismatch.status_code == 400
    assert explicit_mismatch.json()["error"] == "invalid_target"
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/mcp", headers=bearer).status_code == 405
    resources = client.post("/mcp", headers=bearer, json={
        "jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}}).json()
    uris = {item["uri"] for item in resources["result"]["resources"]}
    assert {"ae://identity", "ae://world/public", "ae://commons/public"} <= uris


def test_dead_actor_and_expired_decision_window_close_pending_receipts(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    turn = service.turn(auth)
    queued = service.submit_action(auth, {
        "target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "actor-dies"})
    world10.store.update("agents", auth["actor_id"], alive=0, died_tick=1)
    _controlled, decisions = service.decisions_for_tick(turn["target_tick"])
    assert decisions[0]["purpose"] == "external_safe_policy"
    assert service.receipt(auth, queued["submission_id"])["status"] == "rejected"

    world10.store.update("agents", auth["actor_id"], alive=1, died_tick=None)
    world10.store.set_meta(tick=turn["target_tick"])
    next_turn = service.turn(auth)
    world10.store.execute(
        "UPDATE external_agent_turns SET deadline_at=? WHERE id=?",
        ("2000-01-01T00:00:00+00:00", next_turn["turn_id"]))
    late = service.submit_action(auth, {
        "target_tick": next_turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": next_turn["projection_hash"],
        "idempotency_key": "too-late"})
    assert late["status"] == "stale"
    assert late["validator_results"][0]["validator"] == "deadline"


def test_event_cursor_excludes_private_communication_events(world10: World):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)
    cursor = int(world10.store.scalar("SELECT COALESCE(MAX(id),0) FROM events", default=0))

    world10.store.log_event(
        1, "communication_queued",
        {"body": "private-message-secret", "recipient_agent_id": 999},
        subject_type="agent", subject_id=auth["actor_id"])
    world10.store.log_event(
        1, "comm_internal_note",
        {"body": "private-note-secret"},
        subject_type="agent", subject_id=auth["actor_id"])
    world10.store.log_event(
        1, "belief_updated", {"belief": "private-belief-secret"},
        subject_type="agent", subject_id=auth["actor_id"])
    public_id = world10.store.log_event(
        1, "production", {"firm_id": 1, "units": 4,
                           "private_note": "private-production-secret"},
        subject_type="firm", subject_id=1)

    result = service.events(auth, cursor=cursor)
    assert [event["id"] for event in result["events"]] == [public_id]
    assert result["events"][0]["payload"] == {"firm_id": 1, "units": 4}
    assert "private-message-secret" not in repr(result)
    assert "private-note-secret" not in repr(result)
    assert "private-belief-secret" not in repr(result)
    assert "private-production-secret" not in repr(result)

    observed_kinds = {
        event["kind"] for event in service.observe(auth)["recent_public_events"]}
    assert "production" in observed_kinds
    assert "communication_queued" not in observed_kinds
    assert "belief_updated" not in observed_kinds


def test_recorded_external_action_replays_without_client_network(world10: World, tmp_path):
    created = _connection(world10)
    service = world10.runtime.external
    auth = service.authenticate(created["credential"]["token"], rate_limit=False)

    replay_path = tmp_path / "replay.db"
    target_connection = sqlite3.connect(replay_path)
    try:
        world10.store.conn.backup(target_connection)
    finally:
        target_connection.close()

    turn = service.turn(auth)
    queued = service.submit_action(auth, {
        "target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "recorded-source"})
    _controlled, decisions = service.decisions_for_tick(turn["target_tick"])
    world10.runtime.execute_decisions(turn["target_tick"], decisions)
    source_receipt = service.receipt(auth, queued["submission_id"])
    stale = service.submit_action(auth, {
        "target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
        "observed_projection_hash": turn["projection_hash"],
        "idempotency_key": "recorded-stale-control-plane-receipt",
    })
    assert stale["status"] == "stale"
    world10.store.commit()

    replay_store = Store(str(replay_path), create=False)
    replay_config = load_config("runs/world-os-external.yaml")
    replay_config.update({
        "replay_source_path": str(Path(world10.store.path).resolve()),
        "checkpoint_every": 0,
    })
    replay_world = World(replay_store, replay_config, replay=True)
    try:
        controlled, replayed = replay_world.runtime.external.decisions_for_tick(
            turn["target_tick"])
        assert controlled == {auth["actor_id"]}
        assert replayed[0]["purpose"] == "external_agent"
        assert replayed[0]["replay_source_submission_id"] == queued["submission_id"]
        replay_world.runtime.execute_decisions(turn["target_tick"], replayed)
        replay_auth = {**auth, "credential_id": "recorded", "credential_kind": "replay"}
        replay_receipt = replay_world.runtime.external.receipt(
            replay_auth, queued["submission_id"])
        assert replay_receipt["status"] == "executed"
        assert replay_receipt["resulting_state_hash"] == source_receipt["resulting_state_hash"]
        proof = verify_replay(world10.store.path, replay_store.path)
        assert proof["exact"], proof["differences"]
    finally:
        replay_world.close()


def test_fresh_replay_restores_external_arrival_and_commons_boundary(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = _world(source_dir)
    replay = None
    try:
        source.store.log_event(
            1,
            "communication_read_context",
            {"agent_id": 1, "message_count": 0, "context_key": "boundary-proof"},
            phase="MORNING",
            subject_type="agent",
            subject_id=1,
            importance=0.2,
        )
        created = source.runtime.external.create_connection(
            tenant_id="tenant-a",
            owner_id="owner-a",
            display_name="Replay Citizen",
            biography="Recorded external citizen.",
            preferred_occupation="builder",
            tier="actor",
        )
        source._spawn_due_arrivals(2)
        actor_id = int(source.runtime.external.connection(
            created["connection"]["id"],
            owner_id="owner-a",
            tenant_id="tenant-a",
        )["actor_id"])
        source.store.set_meta(tick=2)
        entry = source.commons.publish(actor_id, body="Replay this Commons post.")
        source.commons.feed(actor_id)
        source.commons.publish(
            actor_id, body="Published after the recorded feed boundary.")
        source.commons.react(actor_id, int(entry["id"]), "like")
        source.store.commit()

        replay_dir = tmp_path / "replay"
        replay_dir.mkdir()
        replay_config = deepcopy(source.config)
        replay_config["replay_source_path"] = str(Path(source.store.path).resolve())
        replay_config["checkpoint_dir"] = str(replay_dir / "checkpoints")
        replay_store = Store(str(replay_dir / "world.db"))
        replay_store.init_run_meta("external-replay-test", 42, replay_config)
        replay = World(replay_store, replay_config, replay=True)
        replay.initialize()
        replay.store.log_event(
            1,
            "communication_read_context",
            {"agent_id": 1, "message_count": 0, "context_key": "boundary-proof"},
            phase="MORNING",
            subject_type="agent",
            subject_id=1,
            importance=0.2,
        )
        replay.runtime.external.restore_replay_after_morning(1)
        replay._spawn_due_arrivals(2)
        replay.store.set_meta(tick=2)
        asyncio.run(replay.runtime.external.collect_online_turns(3))

        replay_connection = replay.store.query_one(
            "SELECT actor_id,actor_schedule_event_id,status "
            "FROM external_agent_connections WHERE id=?",
            (created["connection"]["id"],),
        )
        assert replay_connection["status"] == "active"
        assert int(replay_connection["actor_id"]) == actor_id
        assert replay.store.scalar(
            "SELECT COUNT(*) FROM commons_entries", default=0
        ) == 2
        assert replay.store.scalar(
            "SELECT COUNT(*) FROM commons_feed_impressions", default=0
        ) == 1
        assert replay.store.scalar(
            "SELECT COUNT(*) FROM commons_reactions", default=0
        ) == 1
        proof = verify_replay(source.store.path, replay.store.path)
        assert proof["exact"], proof["differences"]
    finally:
        if replay is not None:
            replay.close()
        source.close()


def test_rate_limit_and_one_hundred_offline_actor_fallbacks_are_bounded(tmp_path):
    world = _world(tmp_path, requests_per_minute=10)
    try:
        service = world.runtime.external
        observer = service.create_connection(
            tenant_id="tenant-a", owner_id="owner-a", display_name="Observer",
            tier="observer")
        token = observer["credential"]["token"]
        for _ in range(10):
            service.authenticate(token)
        with pytest.raises(ExternalAgentError, match="rate limit"):
            service.authenticate(token)

        credentials = []
        for index in range(100):
            created = service.create_connection(
                tenant_id="tenant-a", owner_id="owner-a",
                display_name=f"Load actor {index:03d}", tier="actor")
            credentials.append(created["credential"]["token"])
        world._spawn_due_arrivals(1)
        for token in credentials:
            auth = service.authenticate(token, rate_limit=False)
            assert service.turn(auth)["target_tick"] == 1
        world.store.execute(
            "UPDATE external_agent_connections SET lease_expires_at=? WHERE tier='actor'",
            ("2000-01-01T00:00:00+00:00",))
        asyncio.run(service.collect_online_turns(1))
        controlled, fallbacks = service.decisions_for_tick(1)
        assert len(controlled) == 100
        assert len(fallbacks) == 100
        assert {item["purpose"] for item in fallbacks} == {"external_safe_policy"}
        assert world.store.scalar(
            "SELECT COUNT(*) FROM external_agent_turns WHERE target_tick=1 "
            "AND status='fallback'", default=0) == 100
    finally:
        world.close()
