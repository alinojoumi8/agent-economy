"""Regression proofs for the September 2026 hosted security review."""
from dataclasses import replace
import asyncio
import base64
from datetime import datetime, timezone
import hashlib

import pytest
from fastapi.testclient import TestClient

from engine.storage_policy import StoragePolicy
from hosted.app import MAX_REQUEST_BODY_BYTES, create_hosted_app
from server.app import create_app
from agents.external import ExternalAgentError
from tests.test_external_agent_gateway import _connection, _world
from tests.test_hosted_app import (
    EXTERNAL_AGENT_ID, FakeAuth, FakeCatalog, FakeSupervisor, NOW,
)


@pytest.fixture
def review_world(tmp_path):
    world = _world(tmp_path)
    yield world
    world.close()


def test_refresh_token_cannot_authorize_rest_or_mcp(review_world):
    service = review_world.runtime.external
    created = _connection(review_world, tier="observer")
    pair = service._oauth_token_pair(
        created["connection"]["id"], ["world.read"],
        now=datetime.now(timezone.utc))
    review_world.store.commit()
    with TestClient(create_app(review_world, hosted_safe=True)) as client:
        for token in (created["credential"]["token"], pair["access_token"]):
            assert client.get("/api/v2/agent/me", headers={
                "Authorization": f"Bearer {token}"}).status_code == 200
        before = review_world.store.conn.total_changes
        for method, path, kwargs in (
            ("GET", "/api/v2/agent/me", {}),
            ("POST", "/mcp", {"json": {"jsonrpc": "2.0", "id": 1, "method": "ping"}}),
        ):
            response = client.request(method, path, headers={
                "Authorization": f"Bearer {pair['refresh_token']}"}, **kwargs)
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "invalid_token"
        assert review_world.store.conn.total_changes == before
        # The same refresh token remains valid at its intended endpoint.
        response = client.post("/oauth/token", json={
            "grant_type": "refresh_token", "refresh_token": pair["refresh_token"]})
        assert response.status_code == 200
        assert response.json()["access_token"] != pair["access_token"]


def test_invalid_agent_credentials_never_trigger_storage_scan(review_world):
    created = _connection(review_world, tier="observer")
    review_world.storage_policy = StoragePolicy(min_free_bytes=0, max_run_bytes=0)
    scanned = []
    review_world.storage_guard = lambda: scanned.append(True)
    with TestClient(create_app(review_world, hosted_safe=True)) as client:
        response = client.post("/mcp", headers={"Authorization": "Bearer invalid"},
                               json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert response.status_code == 401
        assert scanned == []
        review_world.storage_policy = replace(review_world.storage_policy, max_run_bytes=1)
        assert client.post("/mcp", headers={"Authorization": "Bearer invalid"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
        assert client.post("/mcp", headers={
            "Authorization": f"Bearer {created['credential']['token']}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 507
        assert client.post("/oauth/token", json={"grant_type": "refresh_token",
                           "refresh_token": "invalid"}).status_code == 400


def test_get_body_cannot_bypass_hosted_request_limit():
    catalog = FakeCatalog()
    app = create_hosted_app(catalog=catalog, auth=FakeAuth(catalog),
                            supervisor=FakeSupervisor(catalog), clock=lambda: NOW)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.request("GET", "/api/v2/agent/me", headers={
            "Authorization": f"Bearer ae_pat_{EXTERNAL_AGENT_ID}.untrusted-material",
        }, content=b"x" * (MAX_REQUEST_BODY_BYTES + 1))
        assert response.status_code == 413
        assert response.json() == {"detail": {"code": "request_too_large"}}


def test_invalid_pkce_skips_admission_and_full_disk_preserves_valid_code(review_world):
    service = review_world.runtime.external
    created = _connection(review_world, tier="observer")
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    code = service.create_authorization_code(
        created["connection"]["id"], tenant_id="tenant-a", owner_id="owner-a",
        client_id="review-client", redirect_uri="https://client.example/callback",
        code_challenge=challenge, scopes=["world.read"])
    fields = {"grant_type": "authorization_code", "code": code["code"],
              "client_id": "review-client", "redirect_uri": "https://client.example/callback"}
    review_world.storage_policy = StoragePolicy(min_free_bytes=0, max_run_bytes=1)
    with TestClient(create_app(review_world, hosted_safe=True)) as client:
        for bad in ("x" * 64, "\N{SNOWMAN}" * 64, "x" * 129):
            assert client.post("/oauth/token", json={**fields, "code_verifier": bad}).status_code == 400
        before = review_world.store.conn.total_changes
        assert client.post("/oauth/token", json={**fields, "code_verifier": verifier}).status_code == 507
        assert review_world.store.conn.total_changes == before
        review_world.storage_policy = replace(review_world.storage_policy, max_run_bytes=0)
        assert client.post("/oauth/token", json={**fields, "code_verifier": verifier}).status_code == 200
        assert client.post("/oauth/token", json={**fields, "code_verifier": verifier}).status_code == 400


def test_anonymous_registration_burst_does_not_reach_catalog(monkeypatch):
    catalog = FakeCatalog()
    writes = []
    original = catalog.register_external_oauth_client
    def register(**kwargs):
        writes.append(True)
        return original(**kwargs)
    monkeypatch.setattr(catalog, "register_external_oauth_client", register)
    app = create_hosted_app(catalog=catalog, auth=FakeAuth(catalog),
                            supervisor=FakeSupervisor(catalog), clock=lambda: NOW)
    with TestClient(app, base_url="https://testserver") as client:
        for _ in range(20):
            assert client.post("/oauth/register", json={
                "redirect_uris": ["https://client.example/callback"]}).status_code == 201
        response = client.post("/oauth/register", json={
            "redirect_uris": ["https://client.example/callback"]},
            headers={"X-Forwarded-For": "198.51.100.222"})
        assert response.status_code == 429 and "retry-after" in response.headers
        assert len(writes) == 20


def test_registration_limiter_bounds_distinct_peers_and_expires():
    from server.request_limits import OAuthRegistrationLimitMiddleware
    now = [0.0]
    accepted = []
    async def next_app(scope, receive, send):
        accepted.append(scope["client"][0])
    limiter = OAuthRegistrationLimitMiddleware(next_app, global_limit=3,
                                              client_limit=2, window_seconds=60,
                                              clock=lambda: now[0])
    async def request(peer):
        messages = []
        async def receive():
            return {"type": "http.request", "body": b""}
        async def send(message):
            messages.append(message)
        await limiter({"type": "http", "method": "POST", "path": "/oauth/register",
                       "client": (peer, 1234)}, receive, send)
        return messages
    for peer in ("peer-a", "peer-b", "peer-c"):
        assert asyncio.run(request(peer)) == []
    for index in range(100):
        assert asyncio.run(request(str(index)))[0]["status"] == 429
    assert len(limiter._clients) == len(limiter._requests) == 3
    now[0] = 61
    assert asyncio.run(request("new-peer")) == []
    assert len(limiter._clients) == len(limiter._requests) == 1


def test_persistent_registration_cap_preserves_existing_clients(review_world, monkeypatch):
    service = review_world.runtime.external
    monkeypatch.setattr("agents.external.MAX_OAUTH_CLIENTS", 1)
    first = service.register_oauth_client(redirect_uris=["https://client.example/callback"])
    with pytest.raises(ExternalAgentError, match="registration capacity"):
        service.register_oauth_client(redirect_uris=["https://other.example/callback"])
    rows = review_world.store.query("SELECT client_id FROM external_oauth_clients")
    assert [row["client_id"] for row in rows] == [first["client_id"]]


def test_read_only_sftp_identity_cannot_replace_or_delete_recovery(tmp_path):
    paramiko = pytest.importorskip("paramiko")
    from tests.storage_sftp_support import sftp_replica
    root = tmp_path / "remote"
    root.mkdir()
    protected = root / "checkpoint"
    protected.write_bytes(b"irreplaceable recovery fixture")
    with sftp_replica(root, tmp_path, read_only=True, username="reader") as replica:
        host, port = replica["host"].rsplit(":", 1)
        host_key = paramiko.RSAKey(data=base64.b64decode(replica["host-key"].split()[1]))
        with paramiko.Transport((host, int(port))) as transport:
            transport.connect(hostkey=host_key, username=replica["user"],
                              pkey=paramiko.RSAKey.from_private_key_file(replica["key-path"]))
            with paramiko.SFTPClient.from_transport(transport) as sftp:
                with sftp.open("/checkpoint", "rb") as stream:
                    assert stream.read() == b"irreplaceable recovery fixture"
                with pytest.raises(OSError):
                    sftp.open("/checkpoint", "wb")
                with pytest.raises(OSError):
                    sftp.remove("/checkpoint")
                with pytest.raises(OSError):
                    sftp.rename("/checkpoint", "/replacement")
    assert protected.read_bytes() == b"irreplaceable recovery fixture"


def test_rate_limited_credentials_skip_scans_and_cannot_flood_denial_audit(review_world, monkeypatch):
    monkeypatch.setattr("agents.external._now", lambda: NOW)
    service = review_world.runtime.external
    created = _connection(review_world, tier="observer")
    token = created["credential"]["token"]
    service.requests_per_minute = 10
    for _ in range(10):
        service.authenticate(token)
    with pytest.raises(ExternalAgentError) as first:
        service.authenticate(token)
    assert first.value.status_code == 429
    before = review_world.store.conn.total_changes
    for _ in range(50):
        with pytest.raises(ExternalAgentError):
            service.authenticate(token)
    assert review_world.store.conn.total_changes == before
    scanned = []
    review_world.storage_policy = StoragePolicy(min_free_bytes=0, max_run_bytes=0)
    review_world.storage_guard = lambda: scanned.append(True)
    with TestClient(create_app(review_world, hosted_safe=True)) as client:
        response = client.post("/mcp", headers={"Authorization": f"Bearer {token}"},
                               json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert response.status_code == 429
        assert scanned == []
        assert review_world.store.conn.total_changes == before


def test_credentials_are_revalidated_after_storage_admission(review_world):
    service = review_world.runtime.external
    token = _connection(review_world, tier="observer")["credential"]["token"]
    review_world.storage_policy = StoragePolicy(min_free_bytes=0, max_run_bytes=0)
    review_world.storage_guard = lambda: service.revoke_token(token)
    with TestClient(create_app(review_world, hosted_safe=True)) as client:
        response = client.post("/mcp", headers={"Authorization": f"Bearer {token}"},
                               json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "invalid_token"
