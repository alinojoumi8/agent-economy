from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from hosted.load_test import (
    MAX_LOAD_USERS,
    LoadUser,
    _parse_user,
    _write_result,
    run_load_test,
)


TENANT_A = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = UUID("20000000-0000-4000-8000-000000000002")
RUN_A = UUID("30000000-0000-4000-8000-000000000003")
RUN_B = UUID("40000000-0000-4000-8000-000000000004")


def _transport() -> httpx.MockTransport:
    scopes = {
        "a@example.test": (TENANT_A, RUN_A, "session-a"),
        "b@example.test": (TENANT_B, RUN_B, "session-b"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            body = json.loads(request.content)
            tenant, _, session = scopes[body["email"]]
            if body["tenant_id"] != str(tenant) or body["password"] != "test-password":
                return httpx.Response(401, json={"detail": {"code": "invalid_credentials"}})
            return httpx.Response(
                200,
                json={"tenant_id": str(tenant), "role": "admin"},
                headers={"set-cookie": f"__Host-ae_session={session}; Path=/; Secure; HttpOnly"},
            )
        cookie = request.headers.get("cookie", "")
        own_tenant, own_run = (
            (TENANT_A, RUN_A) if "session-a" in cookie else (TENANT_B, RUN_B)
        )
        parts = request.url.path.split("/")
        requested_tenant = UUID(parts[4])
        if requested_tenant != own_tenant:
            return httpx.Response(404, json={"detail": {"code": "not_found"}})
        if parts[-1] == "session":
            return httpx.Response(200, json={"tenant_id": str(own_tenant)})
        if parts[-1] == "runs":
            return httpx.Response(
                200,
                json={"runs": [{"tenant_id": str(own_tenant), "run_id": str(own_run)}]},
            )
        requested_run = UUID(parts[-1])
        if requested_run != own_run:
            return httpx.Response(404, json={"detail": {"code": "not_found"}})
        return httpx.Response(
            200, json={"tenant_id": str(own_tenant), "run_id": str(own_run)}
        )

    return httpx.MockTransport(handler)


def test_load_probe_records_concurrency_and_cross_tenant_denials(monkeypatch):
    monkeypatch.setenv("PASSWORD_A", "test-password")
    monkeypatch.setenv("PASSWORD_B", "test-password")
    result = asyncio.run(
        run_load_test(
            base_url="https://hosted.test",
            users=[
                LoadUser(TENANT_A, "a@example.test", "PASSWORD_A", RUN_A),
                LoadUser(TENANT_B, "b@example.test", "PASSWORD_B", RUN_B),
            ],
            requests_per_user=25,
            concurrency=8,
            transport=_transport(),
            build_ref="a" * 40,
        )
    )
    assert result["status"] == "passed"
    assert result["requests"] == 50
    assert result["passed_requests"] == 50
    assert result["failed_requests"] == 0
    assert result["cross_tenant_denials"] == 20
    assert result["complete_isolation_probe"] is True
    assert result["build_ref"] == "a" * 40
    serialized = json.dumps(result)
    assert "test-password" not in serialized
    assert "session-a" not in serialized
    assert "@example.test" not in serialized


def test_load_probe_rejects_insecure_remote_and_duplicate_tenants(monkeypatch):
    monkeypatch.setenv("PASSWORD_A", "test-password")
    user = LoadUser(TENANT_A, "a@example.test", "PASSWORD_A")
    with pytest.raises(ValueError, match="HTTPS"):
        asyncio.run(
            run_load_test(
                base_url="http://localhost",
                users=[user, LoadUser(TENANT_B, "b@example.test", "PASSWORD_A")],
                transport=_transport(),
            )
        )
    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(
            run_load_test(
                base_url="https://hosted.example",
                users=[user, LoadUser(TENANT_B, "b@example.test", "PASSWORD_A")],
                allow_insecure_loopback=True,
                transport=_transport(),
            )
        )
    with pytest.raises(ValueError, match="distinct tenants"):
        asyncio.run(
            run_load_test(
                base_url="https://hosted.test", users=[user, user], transport=_transport()
            )
        )
    with pytest.raises(ValueError, match="cover every"):
        asyncio.run(
            run_load_test(
                base_url="https://hosted.test",
                users=[
                    user,
                    LoadUser(TENANT_B, "b@example.test", "PASSWORD_A"),
                ],
                requests_per_user=1,
                transport=_transport(),
            )
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        asyncio.run(
            run_load_test(
                base_url="https://hosted.test",
                users=[
                    LoadUser(
                        UUID(int=index + 1),
                        f"user-{index}@example.test",
                        "PASSWORD_A",
                    )
                    for index in range(MAX_LOAD_USERS + 1)
                ],
                transport=_transport(),
            )
        )
    with pytest.raises(ValueError, match="total scheduled"):
        asyncio.run(
            run_load_test(
                base_url="https://hosted.test",
                users=[user, LoadUser(TENANT_B, "b@example.test", "PASSWORD_A")],
                requests_per_user=5_001,
                transport=_transport(),
            )
        )


def test_user_parser_and_result_write_are_bounded(tmp_path: Path):
    user = _parse_user(f"{TENANT_A},a@example.test,PASSWORD_A,{RUN_A}")
    assert user == LoadUser(TENANT_A, "a@example.test", "PASSWORD_A", RUN_A)
    with pytest.raises(Exception):
        _parse_user(f"{TENANT_A},a@example.test,../../secret")
    with pytest.raises(ValueError, match="without credentials"):
        asyncio.run(
            run_load_test(
                base_url="https://user:secret@hosted.test/api",
                users=[
                    LoadUser(TENANT_A, "a@example.test", "PASSWORD_A"),
                    LoadUser(TENANT_B, "b@example.test", "PASSWORD_B"),
                ],
                transport=_transport(),
            )
        )

    destination = tmp_path / "evidence" / "load.json"
    _write_result(destination, {"status": "passed", "requests": 10})
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "requests": 10,
        "status": "passed",
    }


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0, -1, 121])
def test_load_probe_rejects_unbounded_timeouts(monkeypatch, timeout):
    monkeypatch.setenv("PASSWORD_A", "test-password")
    monkeypatch.setenv("PASSWORD_B", "test-password")
    with pytest.raises(ValueError, match="must be finite"):
        asyncio.run(
            run_load_test(
                base_url="https://hosted.test",
                users=[
                    LoadUser(TENANT_A, "a@example.test", "PASSWORD_A"),
                    LoadUser(TENANT_B, "b@example.test", "PASSWORD_B"),
                ],
                timeout_seconds=timeout,
                transport=_transport(),
            )
        )


@pytest.mark.parametrize(
    "build_ref",
    ["test-ref", "password@example.test", "a" * 39, "a" * 65, "a" * 40 + "\nsecret"],
)
def test_load_probe_rejects_non_object_build_references(monkeypatch, build_ref):
    monkeypatch.setenv("PASSWORD_A", "test-password")
    monkeypatch.setenv("PASSWORD_B", "test-password")
    with pytest.raises(ValueError, match="Git object ID"):
        asyncio.run(
            run_load_test(
                base_url="https://hosted.test",
                users=[
                    LoadUser(TENANT_A, "a@example.test", "PASSWORD_A"),
                    LoadUser(TENANT_B, "b@example.test", "PASSWORD_B"),
                ],
                build_ref=build_ref,
                transport=_transport(),
            )
        )
