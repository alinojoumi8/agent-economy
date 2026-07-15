from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hosted.artifacts import FilesystemArtifactStore
from hosted.dispatcher import HostedPrincipal, MultiRunDispatcher
from hosted.supervisor import HostedRunSupervisor
from tests.test_hosted_supervisor import FakeCatalog, tiny_profile


class HeaderAuthenticator:
    def __init__(self, principals):
        self.principals = principals
        self.scopes = []

    def authenticate(self, scope):
        self.scopes.append((scope["type"], scope.get("path")))
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        token = headers.get(b"x-test-session", b"").decode("ascii")
        return self.principals.get(token)


def _contains_path_key(value) -> bool:
    if isinstance(value, dict):
        return any(
            key == "path" or key.endswith("_path") or key.endswith("_paths")
            or _contains_path_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_path_key(item) for item in value)
    return False


def test_dispatcher_binds_tenant_and_enforces_observer_read_only(tmp_path: Path):
    tenant_a, tenant_b = uuid4(), uuid4()
    admin_a, observer_a, admin_b = uuid4(), uuid4(), uuid4()
    catalog = FakeCatalog()
    supervisor = HostedRunSupervisor(
        catalog,
        FilesystemArtifactStore(tmp_path / "artifacts"),
        work_root=tmp_path / "work",
        profiles={"tiny": tiny_profile()},
        instance_id="dispatcher-test",
    )

    async def create_runs():
        return (
            await supervisor.create_run(tenant_a, admin_a, "tiny", "Tenant A"),
            await supervisor.create_run(tenant_b, admin_b, "tiny", "Tenant B"),
        )

    run_a, run_b = asyncio.run(create_runs())
    auth = HeaderAuthenticator({
        "admin-a": HostedPrincipal(str(tenant_a), str(admin_a), "admin"),
        "observer-a": HostedPrincipal(str(tenant_a), str(observer_a), "observer"),
        "admin-b": HostedPrincipal(str(tenant_b), str(admin_b), "admin"),
    })
    dispatcher = MultiRunDispatcher(supervisor, auth)

    with TestClient(dispatcher) as client:
        prefix_a = f"/api/runs/{run_a.public_run_id}"
        prefix_b = f"/api/runs/{run_b.public_run_id}"

        assert client.get(f"{prefix_a}/api/run/status").status_code == 401

        observed = client.get(
            f"{prefix_a}/api/run/status", headers={"x-test-session": "observer-a"})
        assert observed.status_code == 200
        assert observed.json()["tick"] == 0
        assert not _contains_path_key(observed.json())

        denied = client.post(
            f"{prefix_a}/api/run/step", headers={"x-test-session": "observer-a"})
        assert denied.status_code == 403
        assert run_a.world.store.tick == 0

        stepped = client.post(
            f"{prefix_a}/api/run/step", headers={"x-test-session": "admin-a"})
        assert stepped.status_code == 200
        assert stepped.json()["tick"] == 1
        assert run_a.world.store.tick == 1
        assert run_b.world.store.tick == 0

        # A valid UUID belonging to another tenant is indistinguishable from
        # an unknown UUID, even to that tenant's administrator.
        foreign = client.get(
            f"{prefix_b}/api/run/status", headers={"x-test-session": "admin-a"})
        assert foreign.status_code == 404
        unknown = client.get(
            f"/api/runs/{uuid4()}/api/run/status",
            headers={"x-test-session": "admin-a"},
        )
        assert unknown.status_code == 404
        malformed = client.get(
            "/api/runs/../../api/run/status",
            headers={"x-test-session": "admin-a"},
        )
        assert malformed.status_code == 404

        # Hosted-safe per-run apps have no global replay browser or raw file
        # mounts, regardless of administrator role.
        assert client.get(
            f"{prefix_a}/api/replay/runs",
            headers={"x-test-session": "admin-a"},
        ).status_code == 404
        assert client.get(
            f"{prefix_a}/reports/anything.html",
            headers={"x-test-session": "admin-a"},
        ).status_code == 404
        assert client.get(
            f"{prefix_a}/static/anything.js",
            headers={"x-test-session": "admin-a"},
        ).status_code == 404

    assert run_a.world.store._closed
    assert run_b.world.store._closed


def test_websocket_is_authenticated_and_tenant_checked_before_accept(tmp_path: Path):
    tenant_a, tenant_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()
    catalog = FakeCatalog()
    supervisor = HostedRunSupervisor(
        catalog,
        FilesystemArtifactStore(tmp_path / "artifacts"),
        work_root=tmp_path / "work",
        profiles={"tiny": tiny_profile()},
        instance_id="websocket-test",
    )

    async def create_runs():
        return (
            await supervisor.create_run(tenant_a, user_a, "tiny", "A"),
            await supervisor.create_run(tenant_b, user_b, "tiny", "B"),
        )

    run_a, run_b = asyncio.run(create_runs())
    auth = HeaderAuthenticator({
        "tenant-a": HostedPrincipal(str(tenant_a), str(user_a), "observer"),
        "tenant-b": HostedPrincipal(str(tenant_b), str(user_b), "observer"),
    })
    dispatcher = MultiRunDispatcher(supervisor, auth)
    ws_a = f"/api/runs/{run_a.public_run_id}/ws"

    with TestClient(dispatcher) as client:
        with pytest.raises(WebSocketDisconnect) as unauthenticated:
            with client.websocket_connect(ws_a):
                pass
        assert unauthenticated.value.code == 4401

        foreign_path = f"/api/runs/{run_b.public_run_id}/ws"
        with pytest.raises(WebSocketDisconnect) as foreign:
            with client.websocket_connect(
                foreign_path, headers={"x-test-session": "tenant-a"}
            ):
                pass
        assert foreign.value.code == 4404

        with client.websocket_connect(
            ws_a, headers={"x-test-session": "tenant-a"}
        ) as websocket:
            payload = websocket.receive_json()
            assert payload["type"] == "tick"
            assert payload["tick"] == 0
            assert "report_path" not in payload

    # Every WebSocket scope reached authentication before an inner hub could
    # issue an accept frame; only the final, tenant-matched socket connected.
    websocket_scopes = [item for item in auth.scopes if item[0] == "websocket"]
    assert len(websocket_scopes) == 3
