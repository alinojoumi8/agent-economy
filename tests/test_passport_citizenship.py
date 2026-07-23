from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from agents.citizen_actions import citizen_action_registry
from agents.participant import PARTICIPANT_TYPES
from engine.actions import VALID_TYPES
from engine.store import Store
from run_config import load_config
from server.app import create_app
from world.loop import World


def _world(tmp_path: Path, *, seats: int = 5) -> tuple[World, Path]:
    config = load_config("runs/world-os-external.yaml")
    config["population"]["size"] = 4
    config["firms"]["count"] = 2
    config["firms"]["listed"] = 1
    config["banks"]["count"] = 1
    config["checkpoint_every"] = 0
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    passport_path = tmp_path / "control-plane" / "agent-passports.db"
    config["external_gateway"]["public_join"] = {
        "enabled": True,
        "world_slug": "local-sandbox",
        "world_name": "Hermes Local Sandbox",
        "tenant_id": "local:local-sandbox",
        "seat_limit": seats,
        "max_passports_per_owner": 3,
        "local_claim_enabled": True,
        "passport_db_path": str(passport_path),
        "claim_hours": 24,
    }
    store = Store(str(tmp_path / "world.db"))
    store.init_run_meta("passport-test", 42, config)
    world = World(store, config)
    world.initialize()
    return world, passport_path


@pytest.fixture
def citizen_client(tmp_path):
    world, passport_path = _world(tmp_path)
    try:
        with TestClient(create_app(world)) as client:
            yield world, client, passport_path
    finally:
        world.close()


def _hidden(html: str, name: str) -> str:
    match = re.search(
        rf'name="{re.escape(name)}"\s+value="([^"]*)"', html)
    assert match is not None, f"missing hidden input {name}"
    return match.group(1)


def _registration(client: TestClient, handle: str = "hermes-citizen") -> dict:
    response = client.post("/api/v2/public/agent-registrations", json={
        "world_slug": "local-sandbox",
        "handle": handle,
        "display_name": handle.replace("-", " ").title(),
        "biography": "A local Hermes citizen.",
        "preferred_occupation": "entrepreneur",
        "runtime": "hermes",
    })
    assert response.status_code == 201
    return response.json()


def test_migration_join_documents_and_security_headers(citizen_client):
    world, client, _passport_path = citizen_client
    columns = {
        str(row["name"])
        for row in world.store.query("PRAGMA table_info(external_agent_connections)")
    }
    assert "passport_id" in columns
    assert int(world.store.get_meta()["schema_version"]) == 16

    join = client.get("/join/local-sandbox")
    assert join.status_code == 200
    assert "Hermes Local Sandbox" in join.text
    assert join.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in join.headers["content-security-policy"]
    assert join.headers["referrer-policy"] == "no-referrer"

    markdown = client.get("/join.md", params={"world": "local-sandbox"})
    assert markdown.status_code == 200
    assert "hermes -p agenteconomy mcp add" in markdown.text
    assert "exactly one" in markdown.text

    world_document = client.get(
        "/api/v2/public/worlds/local-sandbox").json()
    assert world_document["seat_limit"] == 5
    assert world_document["default_scopes"] == [
        "world.read", "world.act", "commons.read", "commons.write"]


def test_agent_registration_claim_exchange_hashing_and_replay(citizen_client):
    world, client, passport_path = citizen_client
    registration = _registration(client)
    claim_path = urlsplit(registration["claim_url"]).path

    denied = client.get(
        claim_path, headers={"host": "citizens.example"})
    assert denied.status_code == 404

    claim_page = client.get(claim_path)
    assert claim_page.status_code == 200
    csrf = _hidden(claim_page.text, "csrf_token")
    bad_csrf = client.post(
        claim_path, data={"csrf_token": "wrong"})
    assert bad_csrf.status_code == 403

    claimed = client.post(claim_path, data={"csrf_token": csrf})
    assert claimed.status_code == 200
    assert "Ownership is confirmed" in claimed.text
    replayed_claim = client.post(claim_path, data={"csrf_token": csrf})
    assert replayed_claim.status_code == 200

    headers = {"Authorization": f"Bearer {registration['bootstrap_token']}"}
    status = client.get(
        f"/api/v2/public/agent-registrations/{registration['registration_id']}",
        headers=headers)
    assert status.status_code == 200
    assert status.json()["citizenship"]["status"] == "offered"

    exchanged = client.post(
        f"/api/v2/public/agent-registrations/{registration['registration_id']}/exchange",
        headers=headers)
    assert exchanged.status_code == 200
    credential = exchanged.json()
    assert credential["access_token"].startswith("ae_pat_")
    assert credential["mcp_url"] == "http://testserver/mcp"
    assert client.post(
        f"/api/v2/public/agent-registrations/{registration['registration_id']}/exchange",
        headers=headers).status_code == 409

    with sqlite3.connect(passport_path) as control:
        dump = "\n".join(
            str(row)
            for table in (
                "passport_claims", "agent_passports", "passport_citizenships")
            for row in control.execute(f"SELECT * FROM {table}"))
    assert registration["bootstrap_token"] not in dump
    assert urlsplit(registration["claim_url"]).path.rsplit("/", 1)[-1] not in dump

    token_hash = hashlib.sha256(
        credential["access_token"].encode("utf-8")).hexdigest()
    stored = world.store.query_one(
        "SELECT token_hash FROM external_agent_credentials "
        "WHERE connection_id=?", (credential["connection"]["id"],))
    assert stored["token_hash"] == token_hash


def test_standard_oauth_consent_pkce_tools_and_revocation(citizen_client):
    world, client, _passport_path = citizen_client
    redirect_uri = "http://127.0.0.1:43123/callback"
    registered = client.post("/oauth/register", json={
        "client_name": "Hermes profile agenteconomy",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "world.read world.act commons.read commons.write",
        "software_id": "hermes-agent",
    })
    assert registered.status_code == 201
    client_id = registered.json()["client_id"]
    assert registered.json()["scope"] == (
        "commons.read commons.write world.act world.read")

    verifier = "h" * 64
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    consent = client.get("/oauth/authorize", params={
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "hermes-state",
        "resource": "http://testserver/mcp",
    })
    assert consent.status_code == 200
    assert "tenant_id" not in consent.request.url.params
    request_id = _hidden(consent.text, "request_id")
    csrf = _hidden(consent.text, "csrf_token")

    invalid = client.post("/oauth/authorize/consent", data={
        "request_id": request_id,
        "csrf_token": "wrong",
        "decision": "approve",
        "handle": "oauth-hermes",
        "display_name": "OAuth Hermes",
    })
    assert invalid.status_code == 403

    approved = client.post(
        "/oauth/authorize/consent",
        data={
            "request_id": request_id,
            "csrf_token": csrf,
            "decision": "approve",
            "handle": "oauth-hermes",
            "display_name": "OAuth Hermes",
            "biography": "A Passport-backed agent.",
            "preferred_occupation": "builder",
            "runtime": "hermes",
        },
        follow_redirects=False,
    )
    assert approved.status_code == 302
    callback = urlsplit(approved.headers["location"])
    query = parse_qs(callback.query)
    assert callback.netloc == "127.0.0.1:43123"
    assert query["state"] == ["hermes-state"]
    assert query["iss"] == ["http://testserver"]

    pair = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": query["code"][0],
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "resource": "http://testserver/mcp",
    })
    assert pair.status_code == 200
    bearer = {"Authorization": f"Bearer {pair.json()['access_token']}"}
    tools = client.post("/mcp", headers=bearer, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    }).json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "ae_identity_get",
        "ae_world_observe",
        "ae_turn_wait",
        "ae_actions_list",
        "ae_action_submit",
        "ae_action_receipt_get",
        "ae_commons_read",
        "ae_commons_act",
    }
    initialized = client.post("/mcp", headers=bearer, json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25"},
    }).json()["result"]
    assert initialized["protocolVersion"] == "2025-11-25"
    assert "exactly one state-valid action" in initialized["instructions"]

    world._spawn_due_arrivals(1)
    identity = client.get("/api/v2/agent/me", headers=bearer).json()
    assert identity["status"] == "active"
    assert identity["actor"]["id"] is not None
    authenticated = world.runtime.external.authenticate(
        pair.json()["access_token"], rate_limit=False)
    external_turn = world.runtime.external.turn(authenticated)
    native_catalog = world.runtime.participant.action_catalog(
        int(identity["actor"]["id"]))
    assert external_turn["action_catalog"] == native_catalog
    assert "set_policy_rate" not in {
        item["type"] for item in external_turn["action_catalog"]}

    agents = client.get("/my-agents")
    revoke_csrf = _hidden(agents.text, "csrf_token")
    passport_id = world.store.query_one(
        "SELECT passport_id FROM external_agent_connections "
        "WHERE id=?", (identity["connection_id"],))["passport_id"]
    revoked = client.post(
        f"/my-agents/{passport_id}/revoke",
        data={"csrf_token": revoke_csrf},
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    assert client.get("/api/v2/agent/me", headers=bearer).status_code == 401


def test_capacity_claims_are_serialized_and_hosted_mode_has_no_local_routes(tmp_path):
    world, _passport_path = _world(tmp_path, seats=1)
    try:
        app = create_app(world)
        with TestClient(app) as client:
            first = _registration(client, "capacity-one")
            second = _registration(client, "capacity-two")
            service = app.state.citizenship_service
            claim_tokens = [
                urlsplit(item["claim_url"]).path.rsplit("/", 1)[-1]
                for item in (first, second)
            ]
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda item: service.claim(item[1], item[0]),
                    [("owner-one", claim_tokens[0]),
                     ("owner-two", claim_tokens[1])],
                ))
            states = sorted(item["citizenship"]["status"] for item in results)
            assert states == ["offered", "waitlisted"]
            assert service.seats_used() == 1

        with TestClient(create_app(world, hosted_safe=True)) as hosted:
            assert hosted.get("/join/local-sandbox").status_code == 404
            assert hosted.get(
                f"/claim/{claim_tokens[0]}").status_code == 404
            assert hosted.get(
                "/api/v2/public/worlds/local-sandbox").status_code == 404
    finally:
        world.close()


def test_canonical_registry_covers_citizen_families_without_institutional_roles():
    assert PARTICIPANT_TYPES <= VALID_TYPES
    assert {
        "buy_goods",
        "apply_job",
        "apply_loan",
        "found_company",
        "send_message",
        "buy_compute_plan",
        "study_skill",
        "say_public",
    } <= PARTICIPANT_TYPES
    assert {
        "approve_loan",
        "deny_loan",
        "set_policy_rate",
        "decide_liquidity_support",
        "committee_vote",
        "review_merger",
    }.isdisjoint(PARTICIPANT_TYPES)

    registry = citizen_action_registry(11)
    categories = {
        item["category"] for item in registry["activities"]}
    assert {
        "economic",
        "employment",
        "finance",
        "company",
        "private_message",
        "compute_plan",
        "skill_learning",
        "public",
        "commons",
    } <= categories
    assert "moderate" not in {
        item["type"] for item in registry["activities"]}
    moderated = citizen_action_registry(11, include_moderation=True)
    moderation = next(
        item for item in moderated["activities"] if item["type"] == "moderate")
    assert moderation["role_restricted"] is True
