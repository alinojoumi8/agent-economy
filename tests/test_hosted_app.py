from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hosted.app import CSRF_HEADER_NAME, create_hosted_app
from hosted.auth import AuthFailure
from hosted.catalog_auth import CatalogAuthService
from hosted.security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    hash_opaque_token,
    hash_password,
)


NOW = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
TENANT_A = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = UUID("20000000-0000-4000-8000-000000000002")
ADMIN_ID = UUID("30000000-0000-4000-8000-000000000003")
OBSERVER_ID = UUID("40000000-0000-4000-8000-000000000004")
RUN_A = UUID("50000000-0000-4000-8000-000000000005")
RUN_B = UUID("60000000-0000-4000-8000-000000000006")
EXTERNAL_AGENT_ID = UUID("70000000-0000-4000-8000-000000000007")
RUN_CONNECTION_ID = UUID("80000000-0000-4000-8000-000000000008")

def opaque_token(byte: bytes) -> str:
    return base64.urlsafe_b64encode(byte * 32).decode("ascii").rstrip("=")


ADMIN_SESSION = opaque_token(b"S")
ADMIN_CSRF = opaque_token(b"C")
OBSERVER_SESSION = opaque_token(b"O")
OBSERVER_CSRF = opaque_token(b"X")
INVITE_TOKEN = opaque_token(b"I")
REGISTRATION_TOKEN = opaque_token(b"R")


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    display_name: str


@dataclass(frozen=True)
class Authenticated:
    user: User
    session: Any


@dataclass
class Session:
    user: User
    tenant_id: UUID
    csrf_token: str
    expires_at: datetime
    revoked: bool = False


@dataclass(frozen=True)
class Credentials:
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class Membership:
    tenant_id: UUID
    user_id: UUID
    role: str
    status: str = "active"


@dataclass(frozen=True)
class Invitation:
    id: UUID
    tenant_id: UUID
    email_normalized: str
    role: str
    token_hash: str
    invited_by_user_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class Run:
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    run_key: str
    display_name: str
    status: str = "paused"
    schema_version: int = 11
    engine_semantics_version: int = 7
    snapshot_object_key: str | None = "tenants/private/snapshot.sqlite3"
    snapshot_sha256: str | None = "a" * 64
    snapshot_size_bytes: int | None = 4096
    writer_lease_owner: str | None = "worker-with-private-hostname"
    writer_lease_token: UUID | None = UUID("70000000-0000-4000-8000-000000000007")


class FakeAuth:
    invite_ttl = timedelta(days=7)

    def __init__(self, catalog: "FakeCatalog") -> None:
        self.catalog = catalog
        self.users = {
            "admin@example.test": (User(str(ADMIN_ID), "admin@example.test", "Admin"), "admin-password"),
            "observer@example.test": (
                User(str(OBSERVER_ID), "observer@example.test", "Observer"),
                "observer-password",
            ),
        }
        self.sessions: dict[str, Session] = {}
        self.invites = {REGISTRATION_TOKEN: "new@example.test"}
        self.revoked_invites: set[str] = set()

    def issue_invite(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: str,
        now: datetime,
        display_name_hint: str | None = None,
        created_by_user_id: str | None = None,
    ) -> str:
        assert now.tzinfo is not None
        assert created_by_user_id == str(ADMIN_ID)
        self.invites[INVITE_TOKEN] = email.lower()
        self.catalog.create_invitation(
            tenant_id,
            email=email,
            role=role,
            token_hash=hash_opaque_token(INVITE_TOKEN),
            invited_by_user_id=UUID(str(created_by_user_id)),
            expires_at=now + self.invite_ttl,
        )
        return INVITE_TOKEN

    def revoke_invite(self, invite_token: str, *, now: datetime) -> bool:
        self.revoked_invites.add(invite_token)
        return self.catalog.revoke_invitation_by_hash(hash_opaque_token(invite_token))

    def register_with_invite(
        self,
        *,
        invite_token: str,
        email: str,
        display_name: str,
        password: str,
        now: datetime,
    ) -> User:
        expected = self.invites.get(invite_token)
        if expected is None or expected != email.lower() or invite_token in self.revoked_invites:
            raise AuthFailure("invalid_invite")
        user = User(str(uuid4()), email.lower(), display_name)
        self.users[email.lower()] = (user, password)
        membership = self.catalog.consume_invitation(
            hash_opaque_token(invite_token), user_id=UUID(user.user_id)
        )
        if membership is None:
            raise AuthFailure("invite_unavailable")
        del self.invites[invite_token]
        return user

    def login(
        self,
        *,
        tenant_id: UUID,
        email: str,
        password: str,
        client_key: str,
        now: datetime,
    ) -> Credentials:
        item = self.users.get(email.lower())
        if item is None or item[1] != password:
            raise AuthFailure("invalid_credentials")
        user = item[0]
        membership = self.catalog.get_membership(tenant_id, UUID(user.user_id))
        if membership is None or membership.status != "active":
            raise AuthFailure("invalid_credentials")
        if user.user_id == str(ADMIN_ID):
            token, csrf = ADMIN_SESSION, ADMIN_CSRF
        else:
            token, csrf = OBSERVER_SESSION, OBSERVER_CSRF
        expires = now + timedelta(hours=1)
        self.sessions[token] = Session(user, tenant_id, csrf, expires)
        return Credentials(token, csrf, expires)

    def authenticate_session(self, session_token: str, *, now: datetime) -> Authenticated:
        session = self.sessions.get(session_token)
        if session is None or session.revoked:
            raise AuthFailure("revoked_session")
        if now >= session.expires_at:
            raise AuthFailure("expired_session")
        return Authenticated(session.user, session)

    def authenticate_csrf(
        self,
        *,
        session_token: str,
        submitted_csrf_token: str,
        csrf_cookie_token: str,
        now: datetime,
    ) -> Authenticated:
        authenticated = self.authenticate_session(session_token, now=now)
        session = self.sessions[session_token]
        if not (
            submitted_csrf_token == csrf_cookie_token == session.csrf_token
        ):
            raise AuthFailure("invalid_csrf")
        return authenticated

    def revoke_session(self, session_token: str, *, now: datetime) -> bool:
        session = self.sessions.get(session_token)
        if session is None:
            return False
        session.revoked = True
        return True


class FakeCatalog:
    def __init__(self) -> None:
        self.create_invitation_calls = 0
        self.consume_invitation_calls = 0
        self.memberships: dict[tuple[UUID, UUID], Membership] = {
            (TENANT_A, ADMIN_ID): Membership(TENANT_A, ADMIN_ID, "admin"),
            (TENANT_A, OBSERVER_ID): Membership(TENANT_A, OBSERVER_ID, "observer"),
            (TENANT_B, ADMIN_ID): Membership(TENANT_B, ADMIN_ID, "admin"),
        }
        self.runs: dict[tuple[UUID, UUID], Run] = {
            (TENANT_A, RUN_A): Run(RUN_A, TENANT_A, ADMIN_ID, "hosted", "Tenant A"),
            (TENANT_B, RUN_B): Run(RUN_B, TENANT_B, ADMIN_ID, "hosted", "Tenant B"),
        }
        self.invitations: dict[str, Invitation] = {
            hash_opaque_token(REGISTRATION_TOKEN): Invitation(
                uuid4(),
                TENANT_A,
                "new@example.test",
                "observer",
                hash_opaque_token(REGISTRATION_TOKEN),
                ADMIN_ID,
                NOW + timedelta(days=1),
            )
        }
        self.revoked_users: list[tuple[UUID, UUID]] = []
        self.oauth_clients: dict[str, dict[str, Any]] = {}
        self.external_agents = {
            EXTERNAL_AGENT_ID: SimpleNamespace(
                id=EXTERNAL_AGENT_ID,
                tenant_id=TENANT_A,
                owner_user_id=ADMIN_ID,
                run_id=RUN_A,
                run_connection_id=RUN_CONNECTION_ID,
                external_agent_id=EXTERNAL_AGENT_ID,
                display_name="Hosted Founder",
                biography="",
                preferred_occupation="builder",
                tier="actor",
                scopes=("world.read", "world.act", "commons.read", "commons.write"),
                status="active",
            )
        }

    def ready(self) -> bool:
        return True

    def register_external_oauth_client(
        self, *, client_name: str, redirect_uris, grant_types, response_types,
        token_endpoint_auth_method: str = "none",
    ) -> dict[str, Any]:
        client_id = "ae_client_hosted_test_123456"
        value = {
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": list(redirect_uris),
            "grant_types": list(grant_types),
            "response_types": list(response_types),
            "token_endpoint_auth_method": token_endpoint_auth_method,
        }
        self.oauth_clients[client_id] = value
        return value

    def get_external_oauth_client(self, client_id: str):
        return self.oauth_clients.get(client_id)

    def list_external_agents(
        self, tenant_id: UUID, *, owner_user_id: UUID | None = None,
        limit: int = 200,
    ):
        records = [
            record for record in self.external_agents.values()
            if record.tenant_id == UUID(str(tenant_id))
            and (owner_user_id is None or record.owner_user_id == owner_user_id)
        ]
        return tuple(records[:limit])

    def get_external_agent(
        self, tenant_id: UUID, external_agent_id: UUID, *,
        owner_user_id: UUID | None = None,
    ):
        record = self.external_agents.get(UUID(str(external_agent_id)))
        if record is None or record.tenant_id != UUID(str(tenant_id)):
            return None
        if owner_user_id is not None and record.owner_user_id != owner_user_id:
            return None
        return record

    def get_membership(self, tenant_id: UUID, user_id: UUID) -> Membership | None:
        return self.memberships.get((UUID(str(tenant_id)), UUID(str(user_id))))

    def list_members(self, tenant_id: UUID) -> tuple[Membership, ...]:
        return tuple(
            value for (scope, _), value in self.memberships.items() if scope == tenant_id
        )

    def update_membership(
        self, tenant_id: UUID, user_id: UUID, *, role: str, enabled: bool
    ) -> Membership | None:
        key = (tenant_id, user_id)
        if key not in self.memberships:
            return None
        updated = Membership(tenant_id, user_id, role, "active" if enabled else "revoked")
        self.memberships[key] = updated
        return updated

    def revoke_user_sessions(self, tenant_id: UUID, user_id: UUID) -> int:
        self.revoked_users.append((tenant_id, user_id))
        return 1

    def lookup_invitation_by_hash(self, token_hash: str) -> Invitation | None:
        return self.invitations.get(token_hash)

    def create_invitation(
        self,
        tenant_id: UUID,
        *,
        email: str,
        role: str,
        token_hash: str,
        invited_by_user_id: UUID,
        expires_at: datetime,
    ) -> Invitation:
        self.create_invitation_calls += 1
        invitation = Invitation(
            uuid4(), tenant_id, email.lower(), role, token_hash, invited_by_user_id, expires_at
        )
        self.invitations[token_hash] = invitation
        return invitation

    def consume_invitation(self, token_hash: str, *, user_id: UUID) -> Membership | None:
        self.consume_invitation_calls += 1
        invitation = self.invitations.pop(token_hash, None)
        if invitation is None:
            return None
        membership = Membership(invitation.tenant_id, user_id, invitation.role)
        self.memberships[(invitation.tenant_id, user_id)] = membership
        return membership

    def revoke_invitation_by_hash(self, token_hash: str) -> bool:
        return self.invitations.pop(token_hash, None) is not None

    def get_run(self, tenant_id: UUID, run_id: UUID) -> Run | None:
        return self.runs.get((UUID(str(tenant_id)), UUID(str(run_id))))

    def list_runs(self, tenant_id: UUID, *, limit: int = 100) -> tuple[Run, ...]:
        return tuple(
            value for (scope, _), value in self.runs.items() if scope == tenant_id
        )[:limit]

    def update_run_status(self, tenant_id: UUID, run_id: UUID, status: str) -> Run | None:
        key = (tenant_id, run_id)
        record = self.runs.get(key)
        if record is None:
            return None
        updated = replace(record, status=status)
        self.runs[key] = updated
        return updated

    def transfer_run_owner(
        self, tenant_id: UUID, run_id: UUID, owner_user_id: UUID
    ) -> Run | None:
        if self.get_membership(tenant_id, owner_user_id) is None:
            return None
        key = (tenant_id, run_id)
        record = self.runs.get(key)
        if record is None:
            return None
        updated = replace(record, owner_user_id=owner_user_id)
        self.runs[key] = updated
        return updated


class FakeHub:
    def __init__(self) -> None:
        self.clients: set[Any] = set()

    async def connect(self, websocket: Any) -> None:
        await websocket.accept()
        self.clients.add(websocket)

    def disconnect(self, websocket: Any) -> None:
        self.clients.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        import json

        for client in tuple(self.clients):
            await client.send_text(json.dumps(payload))


class FakeController:
    def __init__(self) -> None:
        self.hub = FakeHub()
        self.actions: list[tuple[str, Any]] = []

    async def start(self, max_ticks: int | None = None) -> dict[str, Any]:
        self.actions.append(("start", max_ticks))
        return {"status": "running", "database_path": "C:/private/run.sqlite"}

    def pause(self) -> dict[str, str]:
        self.actions.append(("pause", None))
        return {"status": "paused"}

    async def stop(self) -> dict[str, str]:
        self.actions.append(("stop", None))
        return {"status": "stopped"}

    async def step(self) -> dict[str, int]:
        self.actions.append(("step", None))
        return {"tick": 1}

    def set_speed(self, delay_s: float) -> dict[str, float]:
        self.actions.append(("speed", delay_s))
        return {"delay_s": delay_s}


class FakeExternalService:
    def __init__(self) -> None:
        self.authorization_calls: list[dict[str, Any]] = []

    def create_authorization_code(self, connection_id: str, **kwargs: Any):
        self.authorization_calls.append({"connection_id": connection_id, **kwargs})
        return {"code": "hosted-oauth-code"}


class Handle:
    def __init__(self, record: Run) -> None:
        self.public_run_id = record.id
        self.tenant_id = record.tenant_id
        self.profile_slug = record.run_key
        self.controller = FakeController()
        self.external = FakeExternalService()
        self.world = SimpleNamespace(
            runtime=SimpleNamespace(external=self.external))
        self.app = FastAPI()

        @self.app.get("/api/agents")
        async def agents() -> dict[str, Any]:
            return {
                "agents": [{"id": 1, "name": "Public", "raw_response": "provider secret"}],
                "database_path": "C:/private/run.sqlite",
                "nested": {"safe": True, "provider_payload": {"token": "secret"}},
                "recent_decisions": [
                    {
                        "model": "private-provider-model",
                        "request": {"messages": ["private prompt"]},
                        "response": {"reasoning": "private completion"},
                    }
                ],
            }

        @self.app.get("/api/run/status")
        async def run_status() -> dict[str, Any]:
            return {"tick": 4, "status": "paused", "report_path": "C:/private/report.html"}

        @self.app.get("/api/v2/map")
        async def map_view() -> dict[str, Any]:
            return {"regions": [{"id": "north"}], "database_path": "C:/private/run.sqlite"}

    def status(self) -> dict[str, Any]:
        return {
            "run_id": str(self.public_run_id),
            "tenant_id": str(self.tenant_id),
            "profile_slug": self.profile_slug,
            "status": "paused",
            "tick": 4,
            "database_path": "C:/private/run.sqlite",
            "provider_payload": {"api_key": "secret"},
            "snapshot": {
                "object_key": "tenants/private/run.sqlite3",
                "sha256": "b" * 64,
            },
        }


class FakeSupervisor:
    def __init__(self, catalog: FakeCatalog) -> None:
        self.catalog = catalog
        self.profiles = {"zeta": {}, "alpha": {}}
        self.handles = {(TENANT_A, RUN_A): Handle(catalog.runs[(TENANT_A, RUN_A)])}
        self.get_handle_calls: list[tuple[UUID, UUID, bool]] = []
        self.observed_controls: list[tuple[str, str]] = []

    def ready(self) -> bool:
        return True

    async def get_handle(
        self, tenant_id: UUID, run_id: UUID, *, load: bool = True
    ) -> Handle | None:
        self.get_handle_calls.append((tenant_id, run_id, load))
        return self.handles.get((tenant_id, run_id))

    async def create_run(
        self,
        tenant_id: UUID,
        owner_user_id: UUID,
        profile_slug: str,
        display_name: str,
    ) -> Handle:
        run_id = UUID("80000000-0000-4000-8000-000000000008")
        record = Run(run_id, tenant_id, owner_user_id, profile_slug, display_name, "created")
        self.catalog.runs[(tenant_id, run_id)] = record
        handle = Handle(record)
        self.handles[(tenant_id, run_id)] = handle
        return handle

    def observe_control(self, handle: Handle, inner_path: str, method: str) -> None:
        # The real observer creates an asyncio task and must run on this loop,
        # not in the persistence thread pool.
        asyncio.get_running_loop()
        self.observed_controls.append((inner_path, method))


class DurableAuthCatalog(FakeCatalog):
    """Small durable-catalog double used with the real CatalogAuthService."""

    def __init__(self) -> None:
        super().__init__()
        self.auth_user = SimpleNamespace(
            id=ADMIN_ID,
            email_normalized="admin@example.test",
            display_name="Admin",
            password_hash=hash_password(
                "admin-password", random_bytes=lambda size: b"p" * size
            ),
            disabled_at=None,
            created_at=NOW,
        )
        self.auth_sessions: dict[str, Any] = {}
        self.login_failures: dict[tuple[UUID, str], list[datetime]] = {}
        self.auth_audits: list[tuple[UUID, dict[str, Any]]] = []

    def get_user_by_email(self, email: str):
        return self.auth_user if email == self.auth_user.email_normalized else None

    def get_user_by_id(self, user_id: UUID):
        return self.auth_user if UUID(str(user_id)) == self.auth_user.id else None

    def get_tenant(self, tenant_id: UUID):
        tenant = UUID(str(tenant_id))
        if any(key[0] == tenant for key in self.memberships):
            return SimpleNamespace(id=tenant, status="active")
        return None

    def reserve_login_attempt(
        self,
        tenant_id: UUID,
        account_hash: str,
        client_account_hash: str,
        *,
        since: datetime,
        occurred_at: datetime,
        max_failures: int,
    ):
        key = (UUID(str(tenant_id)), account_hash)
        failures = tuple(
            item for item in self.login_failures.get(key, []) if item > since
        )
        if len(failures) >= max_failures:
            return SimpleNamespace(
                tenant_active=True,
                account_failures=failures,
                client_account_failures=failures,
                reserved=False,
            )
        self.login_failures.setdefault(key, []).append(occurred_at)
        failures = (*failures, occurred_at)
        return SimpleNamespace(
            tenant_active=True,
            account_failures=failures,
            client_account_failures=failures,
            reserved=True,
        )

    def record_login_attempt(
        self,
        tenant_id: UUID,
        account_hash: str,
        *,
        client_account_hash: str | None = None,
        succeeded: bool,
        occurred_at: datetime,
        user_id: UUID | None = None,
    ) -> int:
        if succeeded:
            self.login_failures.pop((UUID(str(tenant_id)), account_hash), None)
        return 1

    def create_session(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        token_hash: str,
        csrf_secret_hash: str,
        expires_at: datetime,
    ):
        record = SimpleNamespace(
            id=uuid4(),
            tenant_id=UUID(str(tenant_id)),
            user_id=UUID(str(user_id)),
            token_hash=token_hash,
            csrf_secret_hash=csrf_secret_hash,
            expires_at=expires_at,
            revoked_at=None,
            created_at=NOW,
        )
        self.auth_sessions[token_hash] = record
        return record

    def lookup_session_by_hash(self, token_hash: str):
        record = self.auth_sessions.get(token_hash)
        return record if record is not None and record.revoked_at is None else None

    def revoke_session_by_hash(self, token_hash: str) -> bool:
        record = self.auth_sessions.get(token_hash)
        if record is None:
            return False
        record.revoked_at = NOW
        return True

    def revoke_session(self, tenant_id: UUID, session_id: UUID) -> bool:
        for record in self.auth_sessions.values():
            if record.tenant_id == tenant_id and record.id == session_id:
                record.revoked_at = NOW
                return True
        return False

    def append_auth_audit(self, tenant_id: UUID, **kwargs: Any) -> int:
        self.auth_audits.append((tenant_id, kwargs))
        return len(self.auth_audits)


@pytest.fixture()
def services() -> tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]]:
    catalog = FakeCatalog()
    auth = FakeAuth(catalog)
    supervisor = FakeSupervisor(catalog)
    clock = {"now": NOW}
    return catalog, auth, supervisor, clock


@pytest.fixture()
def client(
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]]
) -> TestClient:
    catalog, auth, supervisor, clock = services
    app = create_hosted_app(
        catalog=catalog,
        auth=auth,
        supervisor=supervisor,
        clock=lambda: clock["now"],
    )
    with TestClient(app, base_url="https://testserver") as active:
        yield active


def login(client: TestClient, *, observer: bool = False, tenant_id: UUID = TENANT_A):
    email = "observer@example.test" if observer else "admin@example.test"
    password = "observer-password" if observer else "admin-password"
    response = client.post(
        "/auth/login",
        json={"tenant_id": str(tenant_id), "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response


def csrf_headers(client: TestClient) -> dict[str, str]:
    value = client.cookies.get(CSRF_COOKIE_NAME)
    assert value
    return {CSRF_HEADER_NAME: value}


def test_login_sets_exact_hardened_cookies_without_returning_credentials(client: TestClient):
    response = login(client)
    cookies = response.headers.get_list("set-cookie")
    assert any(
        value == f"{SESSION_COOKIE_NAME}={ADMIN_SESSION}; Path=/; Secure; HttpOnly; SameSite=Lax"
        for value in cookies
    )
    assert any(
        value == f"{CSRF_COOKIE_NAME}={ADMIN_CSRF}; Path=/; Secure; SameSite=Lax"
        for value in cookies
    )
    assert ADMIN_SESSION not in response.text
    assert ADMIN_CSRF not in response.text
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_hosted_oauth_dcr_consent_and_redirect_flow(
    client: TestClient,
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    login(client)
    redirect_uri = "https://client.example/callback"
    registration = client.post("/oauth/register", json={
        "client_name": "<OpenClaw>",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    assert registration.status_code == 201
    assert registration.headers["cache-control"] == "no-store"
    client_id = registration.json()["client_id"]

    authorization_fields = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": "A" * 43,
        "code_challenge_method": "S256",
        "scope": "world.read world.act",
        "state": "openclaw-state",
        "resource": "https://testserver/mcp",
    }
    consent = client.get("/oauth/authorize", params=authorization_fields)
    assert consent.status_code == 200
    assert consent.headers["cache-control"] == "no-store"
    assert "&lt;OpenClaw&gt;" in consent.text
    assert "<strong><OpenClaw></strong>" not in consent.text
    assert "Hosted Founder" in consent.text
    assert ADMIN_CSRF in consent.text

    complete = client.post(
        "/oauth/authorize/complete",
        data={
            **authorization_fields,
            "csrf_token": ADMIN_CSRF,
            "tenant_id": str(TENANT_A),
            "connection_id": str(EXTERNAL_AGENT_ID),
        },
        follow_redirects=False,
    )
    assert complete.status_code == 302
    location = urlsplit(complete.headers["location"])
    assert (location.scheme, location.netloc, location.path) == (
        "https", "client.example", "/callback")
    assert parse_qs(location.query) == {
        "code": ["hosted-oauth-code"],
        "iss": ["https://testserver"],
        "state": ["openclaw-state"],
    }
    supervisor = services[2]
    call = supervisor.handles[(TENANT_A, RUN_A)].external.authorization_calls[-1]
    assert call == {
        "connection_id": str(RUN_CONNECTION_ID),
        "tenant_id": str(TENANT_A),
        "owner_id": str(ADMIN_ID),
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": "A" * 43,
        "scopes": ["world.read", "world.act"],
        "admin": True,
    }


def test_mutating_request_body_is_bounded_before_validation(client: TestClient):
    response = client.post(
        "/auth/register",
        json={
            "invite_token": REGISTRATION_TOKEN,
            "email": "new@example.test",
            "display_name": "x" * (70 * 1024),
            "password": "a-long-password",
        },
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"


def test_tenant_scope_is_404_observer_is_read_only_and_proxy_is_sanitized(
    client: TestClient,
):
    login(client, observer=True)

    own = client.get(f"/api/v2/tenants/{TENANT_A}/runs")
    assert own.status_code == 200
    assert [item["run_id"] for item in own.json()["runs"]] == [str(RUN_A)]
    assert "snapshot_object_key" not in own.text
    assert "writer_lease_token" not in own.text
    assert "private" not in own.text

    cross_tenant = client.get(f"/api/v2/tenants/{TENANT_B}/runs")
    assert cross_tenant.status_code == 404
    assert RUN_B.hex not in cross_tenant.text

    members = client.get(f"/api/v2/tenants/{TENANT_A}/members")
    assert members.status_code == 403

    proxy = client.get(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}/world/agents"
    )
    assert proxy.status_code == 200
    assert proxy.json() == {
        "agents": [{"id": 1, "name": "Public"}],
        "nested": {"safe": True},
        "recent_decisions": [{"model": "private-provider-model"}],
    }
    assert "secret" not in proxy.text
    assert "C:/" not in proxy.text

    v2_proxy = client.get(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}/world/v2/map"
    )
    assert v2_proxy.status_code == 200
    assert v2_proxy.json() == {"regions": [{"id": "north"}]}

    oversized_query = client.get(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}/world/agents",
        params=[(f"field{i}", "x") for i in range(51)],
    )
    assert oversized_query.status_code == 413
    assert oversized_query.json()["detail"]["code"] == "query_too_large"

    mutation = client.post(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}/world/agents",
        json={"action": "mutate"},
    )
    assert mutation.status_code == 403
    assert mutation.json()["detail"]["code"] == "read_only_role"


def test_cross_tenant_run_id_never_reaches_supervisor(
    client: TestClient,
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    _, _, supervisor, _ = services
    login(client, observer=True)
    response = client.get(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_B}/world/agents"
    )
    assert response.status_code == 404
    assert supervisor.get_handle_calls == []


def test_session_is_bound_to_selected_tenant_even_for_multi_tenant_member(
    client: TestClient,
):
    # The admin is a member of both tenants, but this credential was issued for
    # tenant A and must not silently become a tenant B credential.
    login(client, tenant_id=TENANT_A)
    denied = client.get(f"/api/v2/tenants/{TENANT_B}/runs")
    assert denied.status_code == 404

    login(client, tenant_id=TENANT_B)
    allowed = client.get(f"/api/v2/tenants/{TENANT_B}/runs")
    assert allowed.status_code == 200
    assert [run["run_id"] for run in allowed.json()["runs"]] == [str(RUN_B)]


def test_real_catalog_auth_service_interface_preserves_tenant_session_binding():
    catalog = DurableAuthCatalog()
    token_values = iter((b"s" * 32, b"c" * 32, b"t" * 32, b"d" * 32))
    auth = CatalogAuthService(
        catalog,
        token_random_bytes=lambda size: next(token_values),
        password_random_bytes=lambda size: b"q" * size,
    )
    supervisor = FakeSupervisor(catalog)
    app = create_hosted_app(
        catalog=catalog,
        auth=auth,
        supervisor=supervisor,
        clock=lambda: NOW,
    )
    with TestClient(app, base_url="https://testserver") as active:
        first = login(active, tenant_id=TENANT_A)
        assert first.json()["tenant_id"] == str(TENANT_A)
        assert active.get(f"/api/v2/tenants/{TENANT_A}/session").status_code == 200
        # The same global user is an admin in B; the A-bound session remains
        # unusable there until a tenant-B login creates a different session row.
        assert active.get(f"/api/v2/tenants/{TENANT_B}/session").status_code == 404

        second = login(active, tenant_id=TENANT_B)
        assert second.json()["tenant_id"] == str(TENANT_B)
        assert active.get(f"/api/v2/tenants/{TENANT_B}/session").status_code == 200

    assert {record.tenant_id for record in catalog.auth_sessions.values()} == {
        TENANT_A,
        TENANT_B,
    }


def test_mutations_require_csrf_and_admin_role(
    client: TestClient,
):
    login(client)
    endpoint = f"/api/v2/tenants/{TENANT_A}/runs"
    body = {"profile_slug": "hosted-test", "display_name": "Hosted Test"}

    missing = client.post(endpoint, json=body)
    assert missing.status_code == 403
    wrong = client.post(endpoint, json=body, headers={CSRF_HEADER_NAME: "W" * 43})
    assert wrong.status_code == 403

    created = client.post(endpoint, json=body, headers=csrf_headers(client))
    assert created.status_code == 201
    assert created.json()["profile_slug"] == "hosted-test"
    assert "path" not in created.text.casefold()
    assert "provider" not in created.text.casefold()

    # Logging in as an observer replaces the browser's session cookies.
    login(client, observer=True)
    denied = client.post(endpoint, json=body, headers=csrf_headers(client))
    assert denied.status_code == 403


def test_admin_invite_member_run_controls_keep_tokens_and_paths_bounded(
    client: TestClient,
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    catalog, _, supervisor, _ = services
    login(client)
    headers = csrf_headers(client)

    invitation = client.post(
        f"/api/v2/tenants/{TENANT_A}/invitations",
        headers=headers,
        json={"email": "invitee@example.test", "role": "observer"},
    )
    assert invitation.status_code == 201, invitation.text
    assert invitation.json()["invite_token"] == INVITE_TOKEN
    assert invitation.json()["tenant_id"] == str(TENANT_A)
    assert catalog.create_invitation_calls == 1

    members = client.get(f"/api/v2/tenants/{TENANT_A}/members")
    assert members.status_code == 200
    assert INVITE_TOKEN not in members.text
    assert ADMIN_SESSION not in members.text

    self_change = client.patch(
        f"/api/v2/tenants/{TENANT_A}/members/{ADMIN_ID}",
        headers=headers,
        json={"role": "observer", "enabled": True},
    )
    assert self_change.status_code == 409

    transferred = client.patch(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}",
        headers=headers,
        json={"owner_user_id": str(OBSERVER_ID)},
    )
    assert transferred.status_code == 200
    assert transferred.json()["owner_user_id"] == str(OBSERVER_ID)
    restored = client.patch(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}",
        headers=headers,
        json={"owner_user_id": str(ADMIN_ID)},
    )
    assert restored.status_code == 200
    assert restored.json()["owner_user_id"] == str(ADMIN_ID)

    disabled = client.patch(
        f"/api/v2/tenants/{TENANT_A}/members/{OBSERVER_ID}",
        headers=headers,
        json={"role": "observer", "enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "revoked"
    assert catalog.revoked_users == [(TENANT_A, OBSERVER_ID)]

    detail = client.get(f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}")
    assert detail.status_code == 200
    assert detail.json()["snapshot"]["sha256"] == "a" * 64
    assert "object_key" not in detail.text
    assert "C:/" not in detail.text
    assert "provider_payload" not in detail.text

    changed = client.patch(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}",
        headers=headers,
        json={"status": "archived"},
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "run_status_control_required"
    assert catalog.runs[(TENANT_A, RUN_A)].status == "paused"

    control = client.post(
        f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}/control",
        headers=headers,
        json={"action": "start", "max_ticks": 5},
    )
    assert control.status_code == 200
    assert control.json() == {"status": "running"}
    assert supervisor.handles[(TENANT_A, RUN_A)].controller.actions == [("start", 5)]
    assert supervisor.observed_controls == [("/api/run/start", "POST")]


def test_invite_registration_is_tenant_bound_and_failures_do_not_echo_token(
    client: TestClient,
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    catalog, _, _, _ = services
    response = client.post(
        "/auth/register",
        json={
            "invite_token": REGISTRATION_TOKEN,
            "email": "new@example.test",
            "display_name": "New User",
            "password": "a-long-password",
        },
    )
    assert response.status_code == 201
    new_user_id = UUID(response.json()["user_id"])
    assert catalog.get_membership(TENANT_A, new_user_id).role == "observer"
    assert catalog.consume_invitation_calls == 1
    assert REGISTRATION_TOKEN not in response.text

    rejected = client.post(
        "/auth/register",
        json={
            "invite_token": opaque_token(b"Z"),
            "email": "attacker@example.test",
            "display_name": "Attacker",
            "password": "another-long-password",
        },
    )
    assert rejected.status_code == 400
    assert opaque_token(b"Z") not in rejected.text


def test_session_expiry_revocation_and_logout_fail_closed(
    client: TestClient,
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    _, auth, _, clock = services
    login(client)
    endpoint = f"/api/v2/tenants/{TENANT_A}/session"
    assert client.get(endpoint).status_code == 200

    clock["now"] = NOW + timedelta(hours=2)
    assert client.get(endpoint).status_code == 401

    clock["now"] = NOW
    login(client)
    auth.sessions[ADMIN_SESSION].revoked = True
    assert client.get(endpoint).status_code == 401

    login(client)
    logout = client.post("/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204
    cookies = logout.headers.get_list("set-cookie")
    assert any(value.startswith(f"{SESSION_COOKIE_NAME}=;") and "Max-Age=0" in value for value in cookies)
    assert any(value.startswith(f"{CSRF_COOKIE_NAME}=;") and "Max-Age=0" in value for value in cookies)
    assert client.get(endpoint).status_code == 401


def test_health_readiness_metrics_and_opaque_dependency_failure(
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    catalog, auth, supervisor, clock = services

    def broken_object_store() -> bool:
        raise RuntimeError("s3 secret_access_key=do-not-reflect")

    app = create_hosted_app(
        catalog=catalog,
        auth=auth,
        supervisor=supervisor,
        clock=lambda: clock["now"],
        readiness_checks={"object_store": broken_object_store},
    )
    with TestClient(app, base_url="https://testserver") as active:
        live = active.get("/health/live")
        assert live.status_code == 200
        ready = active.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json() == {
            "status": "not_ready",
            "checks": {"catalog": "ok", "object_store": "failed", "supervisor": "ok"},
        }
        assert "secret_access_key" not in ready.text
        metrics = active.get("/metrics")
        assert metrics.status_code == 200
        assert metrics.headers["content-type"].startswith("text/plain; version=")
        assert "agent_economy_hosted_http_requests_total" in metrics.text
        assert 'route="/health/live"' in metrics.text


def test_readiness_has_one_deadline_and_reuses_a_still_running_probe(
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    catalog, auth, supervisor, _clock = services
    calls = 0

    def slow_store() -> bool:
        nonlocal calls
        calls += 1
        time.sleep(0.2)
        return True

    app = create_hosted_app(
        catalog=catalog,
        auth=auth,
        supervisor=supervisor,
        readiness_checks={"object_store": slow_store},
        readiness_timeout_seconds=0.05,
    )
    with TestClient(app, base_url="https://testserver") as active:
        first = active.get("/health/ready")
        second = active.get("/health/ready")
        assert first.status_code == second.status_code == 503
        assert first.json()["checks"]["object_store"] == "timeout"
        assert second.json()["checks"]["object_store"] == "timeout"
        assert calls == 1
        time.sleep(0.2)
        third = active.get("/health/ready")
        assert third.status_code == 503
        assert calls == 2


def test_public_hosted_mode_and_dashboard_are_sanitized_and_reports_are_unmounted(
    client: TestClient,
):
    mode = client.get("/api/v2/mode")
    assert mode.status_code == 200
    assert mode.json() == {
        "mode": "hosted",
        "hosted": True,
        "api_base": "/api/v2",
        "csrf_cookie_name": CSRF_COOKIE_NAME,
        "csrf_header_name": CSRF_HEADER_NAME,
        "registration": "invite_only",
        "profiles": ["alpha", "zeta"],
        "capabilities": {
            "run_controls": ["start", "pause", "stop", "step", "speed", "snapshot"],
            "world_mutations": False,
        },
    }
    assert SESSION_COOKIE_NAME not in mode.text
    assert "path" not in mode.text.casefold()
    assert mode.headers["cache-control"] == "no-store"

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "<div id=\"root\"></div>" in dashboard.text
    assert "/static/assets/" in dashboard.text
    assert "default-src 'self'" in dashboard.headers["content-security-policy"]
    assert "connect-src 'self' ws: wss:" in dashboard.headers["content-security-policy"]

    reports = client.get("/reports/private.html")
    assert reports.status_code == 404


def test_dependency_exception_fails_closed_without_reflecting_internal_detail(
    client: TestClient,
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    catalog, _, _, _ = services
    login(client)

    def broken_membership(_tenant_id: UUID, _user_id: UUID):
        raise RuntimeError("postgres://operator:secret@internal-host/control")

    catalog.get_membership = broken_membership  # type: ignore[method-assign]
    response = client.get(f"/api/v2/tenants/{TENANT_A}/runs")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "service_unavailable"}}
    assert "operator" not in response.text
    assert "internal-host" not in response.text


def test_websocket_denies_before_accept_and_authorized_stream_is_sanitized(
    client: TestClient,
    services: tuple[FakeCatalog, FakeAuth, FakeSupervisor, dict[str, datetime]],
):
    _, _, supervisor, _ = services
    endpoint = f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}/ws"

    with pytest.raises(WebSocketDisconnect) as missing:
        with client.websocket_connect(endpoint):
            pass
    assert missing.value.code == 4401
    assert supervisor.get_handle_calls == []

    login(client, observer=True)
    websocket_cookie = {
        "cookie": (
            f"{SESSION_COOKIE_NAME}={OBSERVER_SESSION}; "
            f"{CSRF_COOKIE_NAME}={OBSERVER_CSRF}"
        )
    }
    with client.websocket_connect(endpoint, headers=websocket_cookie) as websocket:
        first = websocket.receive_json()
        assert first["type"] == "run_status"
        assert first["run_id"] == str(RUN_A)
        assert "database_path" not in first
        assert "provider_payload" not in first
        websocket.send_text("ping")
        assert websocket.receive_json() == {"type": "pong"}

    cross_tenant = f"/api/v2/tenants/{TENANT_B}/runs/{RUN_B}/ws"
    before = len(supervisor.get_handle_calls)
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(cross_tenant, headers=websocket_cookie):
            pass
    assert denied.value.code == 4403
    assert len(supervisor.get_handle_calls) == before
