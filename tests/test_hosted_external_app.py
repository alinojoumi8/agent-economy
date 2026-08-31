from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import time
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from agents.external import ExternalAgentService
from hosted.app import create_hosted_app
from tests.test_hosted_app import (
    ADMIN_ID,
    EXTERNAL_AGENT_ID,
    FakeAuth,
    FakeCatalog,
    FakeExternalService,
    FakeSupervisor,
    NOW,
    OBSERVER_ID,
    RUN_A,
    RUN_CONNECTION_ID,
    TENANT_A,
    csrf_headers,
    login,
)


NEW_EXTERNAL_AGENT_ID = UUID("90000000-0000-4000-8000-000000000009")


class ExternalCatalog(FakeCatalog):
    def __init__(self) -> None:
        super().__init__()
        self.external_create_calls: list[dict[str, Any]] = []
        self.external_replace_calls: list[dict[str, Any]] = []

    def create_external_agent_with_credential(self, tenant_id: UUID, **kwargs: Any):
        self.external_create_calls.append({"tenant_id": tenant_id, **kwargs})
        record = SimpleNamespace(
            id=kwargs["external_agent_id"],
            tenant_id=tenant_id,
            owner_user_id=kwargs["owner_user_id"],
            run_id=kwargs["run_id"],
            run_connection_id=kwargs["run_connection_id"],
            external_agent_id=kwargs["external_agent_id"],
            display_name=kwargs["display_name"],
            biography=kwargs["biography"],
            preferred_occupation=kwargs["preferred_occupation"],
            tier=kwargs["tier"],
            scopes=tuple(kwargs["scopes"]),
            status="active" if kwargs["tier"] == "observer" else "pending_actor",
            actor_id=None,
            last_seen_at=None,
            lease_expires_at=None,
            created_at=NOW,
        )
        self.external_agents[record.id] = record
        return record, SimpleNamespace(token_hash=kwargs["token_hash"])

    def replace_external_personal_credential(
        self, tenant_id: UUID, connection_id: UUID, **kwargs: Any,
    ):
        self.external_replace_calls.append(
            {"tenant_id": tenant_id, "connection_id": connection_id, **kwargs}
        )
        return SimpleNamespace(token_hash=kwargs["token_hash"])


class ExternalService(FakeExternalService):
    def __init__(self) -> None:
        super().__init__()
        self.audience = "agent-economy"
        self.created_token = (
            f"ae_pat_{NEW_EXTERNAL_AGENT_ID}.test-generated-personal-token-material"
        )
        self._rotation_lock = threading.Lock()
        self._rotation_count = 0
        self.active_rotations = 0
        self.max_active_rotations = 0
        self.rotation_delay_seconds = 0.0

    def create_connection(self, **kwargs: Any):
        scopes = kwargs.get("scopes") or ["world.read", "commons.read"]
        return {
            "connection": {"id": str(NEW_EXTERNAL_AGENT_ID), "scopes": list(scopes)},
            "credential": {
                "token": self.created_token,
                "expires_at": "2026-09-29T12:00:00+00:00",
            },
        }

    def rotate_personal_credential(self, _connection_id: str, **_kwargs: Any):
        with self._rotation_lock:
            self._rotation_count += 1
            sequence = self._rotation_count
            self.active_rotations += 1
            self.max_active_rotations = max(
                self.max_active_rotations, self.active_rotations
            )
        try:
            if self.rotation_delay_seconds:
                time.sleep(self.rotation_delay_seconds)
            token = (
                f"ae_pat_{RUN_CONNECTION_ID}.test-rotated-personal-token-{sequence}"
            )
            return {"token": token, "expires_at": "2026-09-29T12:00:00+00:00"}
        finally:
            with self._rotation_lock:
                self.active_rotations -= 1

    def revoke_credentials(self, _connection_id: str, **_kwargs: Any):
        return {"revoked": 1}


@pytest.fixture()
def external_services():
    catalog = ExternalCatalog()
    auth = FakeAuth(catalog)
    supervisor = FakeSupervisor(catalog)
    service = ExternalService()
    handle = supervisor.handles[(TENANT_A, RUN_A)]
    handle.external = service
    handle.world.runtime.external = service
    clock = {"now": NOW}
    return catalog, auth, supervisor, service, clock


@pytest.fixture()
def external_client(external_services):
    catalog, auth, supervisor, _service, clock = external_services
    app = create_hosted_app(
        catalog=catalog,
        auth=auth,
        supervisor=supervisor,
        clock=lambda: clock["now"],
    )
    with TestClient(app, base_url="https://testserver") as active:
        yield active


def test_external_connection_uses_real_gateway_compatibility_checks(
    external_client: TestClient, external_services,
):
    catalog, _auth, supervisor, _service, _clock = external_services
    login(external_client)
    handle = supervisor.handles[(TENANT_A, RUN_A)]
    body = {
        "run_id": str(RUN_A),
        "display_name": "Outside agent",
        "tier": "observer",
    }

    for config, expected_code in (
        ({"engine_semantics_version": 7, "external_gateway": {"enabled": True}},
         "semantics_not_enabled"),
        ({"engine_semantics_version": 10, "external_gateway": {"enabled": False}},
         "gateway_disabled"),
    ):
        service = ExternalAgentService(
            SimpleNamespace(store=object()), object(), config
        )
        handle.external = service
        handle.world.runtime.external = service
        response = external_client.post(
            f"/api/v2/tenants/{TENANT_A}/agent-connections",
            headers=csrf_headers(external_client),
            json=body,
        )
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": expected_code}}

    assert catalog.external_create_calls == []


def test_external_connection_hashes_gateway_structured_credential(
    external_client: TestClient, external_services,
):
    catalog, _auth, _supervisor, service, _clock = external_services
    login(external_client)

    response = external_client.post(
        f"/api/v2/tenants/{TENANT_A}/agent-connections",
        headers=csrf_headers(external_client),
        json={
            "run_id": str(RUN_A),
            "display_name": "Outside observer",
            "tier": "observer",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["credential"]["token"] == service.created_token
    assert catalog.external_create_calls[-1]["token_hash"] == hashlib.sha256(
        service.created_token.encode("utf-8")
    ).hexdigest()
    assert service.created_token not in repr(catalog.external_create_calls)
    assert service.created_token not in repr(catalog.external_agents)


def test_external_credential_rotation_hashes_structured_credential(
    external_client: TestClient, external_services,
):
    catalog, _auth, _supervisor, _service, _clock = external_services
    login(external_client)

    response = external_client.post(
        f"/api/v2/tenants/{TENANT_A}/agent-connections/"
        f"{EXTERNAL_AGENT_ID}/credentials",
        headers=csrf_headers(external_client),
        json={"action": "rotate"},
    )

    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert catalog.external_replace_calls[-1]["token_hash"] == hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()
    assert token not in repr(catalog.external_replace_calls)


def test_admin_can_rotate_another_owners_external_connection(
    external_client: TestClient, external_services,
):
    catalog, _auth, _supervisor, _service, _clock = external_services
    catalog.external_agents[EXTERNAL_AGENT_ID].owner_user_id = OBSERVER_ID
    login(external_client)

    response = external_client.post(
        f"/api/v2/tenants/{TENANT_A}/agent-connections/"
        f"{EXTERNAL_AGENT_ID}/credentials",
        headers=csrf_headers(external_client),
        json={"action": "rotate"},
    )

    assert response.status_code == 200, response.text
    replacement = catalog.external_replace_calls[-1]
    assert replacement["owner_user_id"] == ADMIN_ID
    assert replacement["admin"] is True


def test_concurrent_rotations_are_serialized_through_catalog_commit(
    external_client: TestClient, external_services,
):
    catalog, _auth, _supervisor, service, _clock = external_services
    service.rotation_delay_seconds = 0.05
    login(external_client)
    headers = csrf_headers(external_client)
    url = (
        f"/api/v2/tenants/{TENANT_A}/agent-connections/"
        f"{EXTERNAL_AGENT_ID}/credentials"
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda _index: external_client.post(
                url, headers=headers, json={"action": "rotate"}
            ),
            range(2),
        ))

    assert [response.status_code for response in responses] == [200, 200]
    assert service.max_active_rotations == 1
    assert len(catalog.external_replace_calls) == 2
    expected_hashes = {
        hashlib.sha256(response.json()["token"].encode("utf-8")).hexdigest()
        for response in responses
    }
    assert {call["token_hash"] for call in catalog.external_replace_calls} == expected_hashes


def test_encoded_parent_segments_cannot_escape_external_agent_proxy(
    external_client: TestClient, external_services,
):
    _catalog, _auth, supervisor, _service, _clock = external_services
    invoked = {"value": False}
    handle = supervisor.handles[(TENANT_A, RUN_A)]

    @handle.app.post("/api/run/stop")
    async def internal_stop():
        invoked["value"] = True
        return {"status": "stopped"}

    token = f"ae_pat_{EXTERNAL_AGENT_ID}.known-active-connection-routing-token"
    response = external_client.post(
        "/api/v2/agent/%2e%2e/%2e%2e/%2e%2e/api/run/stop",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "not_found"}}
    assert invoked["value"] is False
