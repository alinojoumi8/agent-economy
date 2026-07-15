"""Fail-closed HTTP composition for R22 hosted operation.

The simulation's existing FastAPI application is deliberately *not* exposed as
the public hosted application.  This module authenticates a tenant principal,
applies the hosted role policy, and then forwards only an explicit read-only
subset of a run's observatory API.  Run mutation is available through the small
admin control surface below.

The catalog, authentication service, and run supervisor are injected.  Keeping
those boundaries duck typed makes the policy layer easy to test without a
PostgreSQL server, object store, provider, or live simulation.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import re
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hosted.auth import AuthFailure
from hosted.security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SecurityValidationError,
    build_csrf_cookie,
    build_session_cookie,
    expire_csrf_cookie,
    expire_session_cookie,
    hash_opaque_token,
    parse_opaque_token,
)


ROLE_OBSERVER = "observer"
ROLE_ADMIN = "admin"
ACTIVE_MEMBERSHIP = "active"
CSRF_HEADER_NAME = "X-AE-CSRF"
MAX_PROXY_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_PROXY_QUERY_BYTES = 4096
MAX_PROXY_QUERY_FIELDS = 50
MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_CONCURRENT_WORLD_READS = 32
DEFAULT_READINESS_TIMEOUT_SECONDS = 2.0


class _RequestBodyLimitMiddleware:
    """Bound mutating request bodies before FastAPI/Pydantic allocates them."""

    def __init__(self, app: Any, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            chunk = bytes(message.get("body", b""))
            total += len(chunk)
            if total > self.max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": {"code": "request_too_large"}},
                    headers={
                        "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff",
                    },
                )
                await response(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


class TenantAuthService(Protocol):
    """Single durable, tenant-aware authentication boundary used by the app."""

    def issue_invite(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: str,
        now: datetime,
        created_by_user_id: str,
        display_name_hint: str | None = None,
    ) -> str: ...

    def register_with_invite(
        self,
        *,
        invite_token: str,
        email: str,
        display_name: str,
        password: str,
        now: datetime,
    ) -> Any: ...

    def login(
        self,
        *,
        tenant_id: UUID,
        email: str,
        password: str,
        client_key: str,
        now: datetime,
    ) -> Any: ...

    def authenticate_session(self, session_token: str, *, now: datetime) -> Any: ...

    def authenticate_csrf(
        self,
        *,
        session_token: str,
        submitted_csrf_token: str,
        csrf_cookie_token: str,
        now: datetime,
    ) -> Any: ...

    def revoke_session(self, session_token: str, *, now: datetime) -> bool: ...

    def revoke_invite(self, invite_token: str, *, now: datetime) -> bool: ...


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InviteRegistrationBody(_StrictBody):
    invite_token: str = Field(min_length=43, max_length=43)
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=1024)


class LoginBody(_StrictBody):
    tenant_id: UUID
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class InviteBody(_StrictBody):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["observer", "admin"] = "observer"
    display_name_hint: str | None = Field(default=None, max_length=120)


class RevokeInviteBody(_StrictBody):
    invite_token: str = Field(min_length=43, max_length=43)


class MemberUpdateBody(_StrictBody):
    role: Literal["observer", "admin"]
    enabled: bool


class RunCreateBody(_StrictBody):
    profile_slug: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$",
    )
    display_name: str = Field(min_length=1, max_length=160)


class RunUpdateBody(_StrictBody):
    status: Literal["created", "starting", "running", "paused", "stopped", "failed", "archived"] | None = None
    owner_user_id: UUID | None = None

    @model_validator(mode="after")
    def require_change(self) -> "RunUpdateBody":
        if self.status is None and self.owner_user_id is None:
            raise ValueError("a run update must include status or owner_user_id")
        return self


class RunControlBody(_StrictBody):
    action: Literal["start", "pause", "stop", "step", "speed", "snapshot"]
    max_ticks: int | None = Field(default=None, ge=1, le=1_000_000)
    delay_s: float | None = Field(default=None, ge=0, le=3600)

    @model_validator(mode="after")
    def validate_action_arguments(self) -> "RunControlBody":
        if self.action == "speed" and self.delay_s is None:
            raise ValueError("speed control requires delay_s")
        if self.action != "speed" and self.delay_s is not None:
            raise ValueError("delay_s is only valid for speed control")
        if self.action != "start" and self.max_ticks is not None:
            raise ValueError("max_ticks is only valid for start control")
        return self


class Principal:
    """A request-local authenticated tenant membership."""

    __slots__ = ("tenant_id", "user_id", "role", "authenticated", "membership")

    def __init__(self, tenant_id: UUID, user_id: UUID, role: str, authenticated: Any, membership: Any):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.role = role
        self.authenticated = authenticated
        self.membership = membership


class _HostedMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry
        self.requests = Counter(
            "agent_economy_hosted_http_requests_total",
            "Hosted HTTP requests by bounded route template and result.",
            ("method", "route", "status"),
            registry=registry,
        )
        self.latency = Histogram(
            "agent_economy_hosted_http_request_seconds",
            "Hosted HTTP request latency by bounded route template.",
            ("method", "route"),
            registry=registry,
        )
        self.auth_rejections = Counter(
            "agent_economy_hosted_auth_rejections_total",
            "Rejected hosted authentication/authorization checks.",
            ("reason",),
            registry=registry,
        )
        self.websocket_connections = Counter(
            "agent_economy_hosted_websocket_connections_total",
            "Authorized hosted WebSocket connections.",
            registry=registry,
        )


_SAFE_WORLD_PATHS = tuple(
    re.compile(pattern)
    for pattern in (
        r"/api/run/status\Z",
        r"/api/acceptance/status\Z",
        r"/api/participant(?:/history)?\Z",
        r"/api/metrics\Z",
        r"/api/agents(?:/[0-9]{1,18})?\Z",
        r"/api/banks\Z",
        r"/api/firms\Z",
        r"/api/news\Z",
        r"/api/conversations\Z",
        r"/api/events\Z",
        r"/api/trades\Z",
        r"/api/cost\Z",
        r"/api/oracle/predictions\Z",
        r"/api/institutions\Z",
        r"/api/shocks\Z",
        r"/api/v2/(?:map|legal|politics|information|startups|markets|datasets)\Z",
    )
)

_SECRET_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "csrf",
    "csrf_secret_hash",
    "csrf_token",
    "csrf_token_hash",
    "invite_token",
    "object_key",
    "password",
    "password_hash",
    "prompt",
    "provider_payload",
    "raw_request",
    "raw_response",
    "reasoning",
    "request",
    "request_json",
    "request_payload",
    "response_json",
    "response_payload",
    "response",
    "secret",
    "session_token",
    "token",
    "token_hash",
    "writer_lease_token",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _invoke(function: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Invoke sync persistence methods off-loop and accept async test/runtime APIs."""

    if inspect.iscoroutinefunction(function):
        return await function(*args, **kwargs)
    result = await asyncio.to_thread(function, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _attribute(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _uuid_attribute(value: Any, *names: str) -> UUID:
    raw = _attribute(value, *names)
    try:
        return raw if isinstance(raw, UUID) else UUID(str(raw))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError("identity service returned an invalid identifier") from exc


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and re.match(
            r"(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|tmp|var|opt|srv|mnt|data)/)",
            value,
        ):
            return "[REDACTED]"
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[BINARY REDACTED]"
    if isinstance(value, (UUID, datetime, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return str(value)


def sanitize_public_payload(value: Any, *, _depth: int = 0) -> Any:
    """Remove provider material, credentials, and local paths recursively."""

    if _depth > 12:
        return "[TRUNCATED]"
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            folded = key.casefold()
            if (
                folded in _SECRET_KEYS
                or folded == "path"
                or folded.endswith("_path")
                or folded.endswith("_directory")
                or folded.endswith("_object_key")
                or folded.startswith("raw_")
            ):
                continue
            clean[key] = sanitize_public_payload(child, _depth=_depth + 1)
        return clean
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_public_payload(child, _depth=_depth + 1) for child in value]
    return _json_scalar(value)


def _public_membership(record: Any) -> dict[str, Any]:
    return {
        "tenant_id": str(_uuid_attribute(record, "tenant_id")),
        "user_id": str(_uuid_attribute(record, "user_id")),
        "role": str(_attribute(record, "role", default="")),
        "status": str(_attribute(record, "status", default="")),
    }


def _public_run(record: Any) -> dict[str, Any]:
    """Serialize the hosted catalog row without artifact keys or lease secrets."""

    snapshot_sha = _attribute(record, "snapshot_sha256")
    snapshot_size = _attribute(record, "snapshot_size_bytes")
    return {
        "run_id": str(_uuid_attribute(record, "id", "run_id", "public_run_id")),
        "tenant_id": str(_uuid_attribute(record, "tenant_id")),
        "owner_user_id": str(_uuid_attribute(record, "owner_user_id", "user_id")),
        "run_key": str(_attribute(record, "run_key", "profile_slug", default="")),
        "display_name": str(_attribute(record, "display_name", default="")),
        "status": str(_attribute(record, "status", default="unknown")),
        "schema_version": int(_attribute(record, "schema_version", default=0)),
        "engine_semantics_version": int(
            _attribute(record, "engine_semantics_version", default=0)
        ),
        "snapshot": {
            "available": bool(snapshot_sha),
            "sha256": str(snapshot_sha) if snapshot_sha else None,
            "size_bytes": int(snapshot_size) if snapshot_size is not None else None,
        },
        "writer_active": bool(_attribute(record, "writer_lease_owner")),
    }


def _credentials(value: Any) -> tuple[str, str, datetime | None]:
    session_token = parse_opaque_token(_attribute(value, "session_token"))
    csrf_token = parse_opaque_token(_attribute(value, "csrf_token"))
    expires_at = _attribute(value, "expires_at")
    if expires_at is not None and not isinstance(expires_at, datetime):
        raise RuntimeError("authentication service returned an invalid expiry")
    return session_token, csrf_token, expires_at


def _authenticated_tenant(value: Any) -> UUID:
    """Read the tenant bound into the durable hosted session record."""

    session = _attribute(value, "session")
    return _uuid_attribute(session, "tenant_id")


def _session_cookie(request: Request | WebSocket) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def _csrf_cookie(request: Request) -> str | None:
    return request.cookies.get(CSRF_COOKIE_NAME)


def _generic_error(status: int, code: str, *, headers: Mapping[str, str] | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code}, headers=dict(headers or {}))


def _safe_world_path(path: str) -> str | None:
    if not path or ".." in path or "\\" in path or "%" in path:
        return None
    normalized = "/api/" + path.lstrip("/")
    return normalized if any(pattern.fullmatch(normalized) for pattern in _SAFE_WORLD_PATHS) else None


class _SanitizingSocket:
    """WebSocketHub-compatible wrapper that removes internal fields on every send."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket

    async def accept(self) -> None:
        await self.websocket.accept()

    async def send_text(self, text: str) -> None:
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            value = {"type": "invalid_upstream_message"}
        await self.websocket.send_json(sanitize_public_payload(value))


def create_hosted_app(
    *,
    catalog: Any,
    auth: TenantAuthService,
    supervisor: Any,
    clock: Callable[[], datetime] = _utc_now,
    readiness_checks: Mapping[str, Callable[[], Any]] | None = None,
    metrics_registry: CollectorRegistry | None = None,
    readiness_timeout_seconds: float = DEFAULT_READINESS_TIMEOUT_SECONDS,
    lifespan: Any = None,
) -> FastAPI:
    """Build the authenticated R22 hosted API from injected service boundaries."""

    if catalog is None or auth is None or supervisor is None:
        raise ValueError("catalog, auth, and supervisor are required")
    if not (0.01 <= float(readiness_timeout_seconds) <= 30.0):
        raise ValueError("readiness_timeout_seconds must be between 0.01 and 30")
    registry = metrics_registry or CollectorRegistry(auto_describe=True)
    metrics = _HostedMetrics(registry)
    checks = dict(readiness_checks or {})
    app = FastAPI(
        title="Agent Economy Hosted Control Plane",
        version="2",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.catalog = catalog
    app.state.auth = auth
    app.state.supervisor = supervisor
    app.state.metrics_registry = registry
    app.state.world_proxy_slots = asyncio.Semaphore(MAX_CONCURRENT_WORLD_READS)
    app.state.readiness_tasks = {}
    app.add_middleware(_RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        # Pydantic error input can contain a submitted credential.  Never reflect it.
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_request"}})

    @app.exception_handler(SecurityValidationError)
    async def security_validation_error(_request: Request, _exc: SecurityValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": {"code": "invalid_request"}})

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, _exc: Exception) -> JSONResponse:
        # Hosted errors are intentionally opaque; operational logging belongs at
        # the injected service boundaries where credential redaction is applied.
        return JSONResponse(status_code=503, content={"detail": {"code": "service_unavailable"}})

    @app.middleware("http")
    async def hosted_policy_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        route_label = getattr(route, "path", "unmatched")
        if not isinstance(route_label, str) or not route_label.startswith("/"):
            route_label = "unmatched"
        status = str(response.status_code)
        metrics.requests.labels(request.method, route_label, status).inc()
        metrics.latency.labels(request.method, route_label).observe(time.perf_counter() - started)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws: wss:; img-src 'self' data:; font-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def authenticate(request: Request | WebSocket) -> Any:
        token = _session_cookie(request)
        if token is None:
            metrics.auth_rejections.labels("missing_session").inc()
            raise _generic_error(401, "authentication_required")
        try:
            return await _invoke(auth.authenticate_session, token, now=clock())
        except (AuthFailure, SecurityValidationError, ValueError, TypeError):
            metrics.auth_rejections.labels("invalid_session").inc()
            raise _generic_error(401, "authentication_required") from None
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(503, "service_unavailable") from None

    async def authorize(
        request: Request | WebSocket,
        tenant_id: UUID,
        *,
        admin: bool = False,
        mutation: bool = False,
    ) -> Principal:
        authenticated = await authenticate(request)
        try:
            if _authenticated_tenant(authenticated) != tenant_id:
                metrics.auth_rejections.labels("tenant_scope").inc()
                raise _generic_error(404, "not_found")
        except HTTPException:
            raise
        except Exception:
            # A session without a durable tenant binding is invalid in hosted mode.
            metrics.auth_rejections.labels("invalid_session_scope").inc()
            raise _generic_error(401, "authentication_required") from None
        user = _attribute(authenticated, "user", default=authenticated)
        try:
            user_id = _uuid_attribute(user, "user_id", "id")
            membership = await _invoke(catalog.get_membership, tenant_id, user_id)
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        if membership is None or str(_attribute(membership, "status", default="")) != ACTIVE_MEMBERSHIP:
            metrics.auth_rejections.labels("tenant_scope").inc()
            # A valid credential gets no tenant-existence oracle.
            raise _generic_error(404, "not_found")
        role = str(_attribute(membership, "role", default=""))
        if role not in {ROLE_OBSERVER, ROLE_ADMIN}:
            metrics.auth_rejections.labels("invalid_role").inc()
            raise _generic_error(403, "forbidden")
        if (admin or mutation) and role != ROLE_ADMIN:
            metrics.auth_rejections.labels("role").inc()
            raise _generic_error(403, "forbidden")
        return Principal(tenant_id, user_id, role, authenticated, membership)

    async def authorize_mutation(request: Request, tenant_id: UUID, *, admin: bool = False) -> Principal:
        session_token = _session_cookie(request)
        submitted = request.headers.get(CSRF_HEADER_NAME)
        csrf_cookie = _csrf_cookie(request)
        if session_token is None or submitted is None or csrf_cookie is None:
            metrics.auth_rejections.labels("csrf").inc()
            raise _generic_error(403, "csrf_required")
        try:
            authenticated = await _invoke(
                auth.authenticate_csrf,
                session_token=session_token,
                submitted_csrf_token=submitted,
                csrf_cookie_token=csrf_cookie,
                now=clock(),
            )
        except (AuthFailure, SecurityValidationError, ValueError, TypeError):
            metrics.auth_rejections.labels("csrf").inc()
            raise _generic_error(403, "csrf_required") from None
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        try:
            if _authenticated_tenant(authenticated) != tenant_id:
                metrics.auth_rejections.labels("tenant_scope").inc()
                raise _generic_error(404, "not_found")
        except HTTPException:
            raise
        except Exception:
            metrics.auth_rejections.labels("invalid_session_scope").inc()
            raise _generic_error(401, "authentication_required") from None
        user = _attribute(authenticated, "user", default=authenticated)
        try:
            user_id = _uuid_attribute(user, "user_id", "id")
            membership = await _invoke(catalog.get_membership, tenant_id, user_id)
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        if membership is None or str(_attribute(membership, "status", default="")) != ACTIVE_MEMBERSHIP:
            metrics.auth_rejections.labels("tenant_scope").inc()
            raise _generic_error(404, "not_found")
        role = str(_attribute(membership, "role", default=""))
        if role not in {ROLE_OBSERVER, ROLE_ADMIN}:
            raise _generic_error(403, "forbidden")
        if admin and role != ROLE_ADMIN:
            metrics.auth_rejections.labels("role").inc()
            raise _generic_error(403, "forbidden")
        return Principal(tenant_id, user_id, role, authenticated, membership)

    async def tenant_run(tenant_id: UUID, run_id: UUID) -> Any:
        try:
            record = await _invoke(catalog.get_run, tenant_id, run_id)
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        if record is None:
            raise _generic_error(404, "not_found")
        return record

    async def run_handle(tenant_id: UUID, run_id: UUID, *, load: bool = True) -> Any:
        await tenant_run(tenant_id, run_id)
        try:
            handle = await _invoke(supervisor.get_handle, tenant_id, run_id, load=load)
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        if handle is None:
            raise _generic_error(404, "not_found")
        return handle

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    async def default_catalog_ready() -> bool:
        probe = getattr(catalog, "ready", None) or getattr(catalog, "ping", None)
        if probe is not None:
            return bool(await _invoke(probe))
        connection_factory = getattr(catalog, "_connection", None)
        if connection_factory is None:
            return False

        def probe_connection() -> bool:
            with connection_factory() as connection:
                row = connection.execute("SELECT 1").fetchone()
                return row is not None

        return bool(await asyncio.to_thread(probe_connection))

    async def default_supervisor_ready() -> bool:
        probe = getattr(supervisor, "ready", None) or getattr(supervisor, "check_readiness", None)
        if probe is not None:
            return bool(await _invoke(probe))
        # A constructed supervisor without an explicit probe is not sufficient
        # evidence for Kubernetes readiness.
        return False

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        active_checks: dict[str, Callable[[], Any]] = {
            "catalog": default_catalog_ready,
            "supervisor": default_supervisor_ready,
            **checks,
        }
        task_cache: dict[str, asyncio.Task[bool]] = app.state.readiness_tasks

        def task_for(name: str, check: Callable[[], Any]) -> asyncio.Task[bool]:
            existing = task_cache.get(name)
            if existing is not None and not existing.done():
                return existing

            async def execute() -> bool:
                try:
                    return bool(await _invoke(check))
                except Exception:
                    return False

            task = asyncio.create_task(execute())
            task_cache[name] = task

            def completed(done: asyncio.Task[bool]) -> None:
                if task_cache.get(name) is done:
                    task_cache.pop(name, None)

            task.add_done_callback(completed)
            return task

        named_tasks = {
            name: task_for(name, active_checks[name]) for name in sorted(active_checks)
        }
        done, _pending = await asyncio.wait(
            set(named_tasks.values()),
            timeout=float(readiness_timeout_seconds),
        )
        results: dict[str, str] = {}
        for name, task in named_tasks.items():
            if task not in done:
                results[name] = "timeout"
                continue
            try:
                healthy = task.result()
            except Exception:
                healthy = False
            results[name] = "ok" if healthy else "failed"
        ready = bool(results) and all(value == "ok" for value in results.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "checks": results},
        )

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(registry),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    @app.get("/api/v2/mode")
    async def hosted_mode() -> dict[str, Any]:
        profiles = getattr(supervisor, "profiles", {})
        profile_names = sorted(
            str(name) for name in profiles.keys()
        ) if isinstance(profiles, Mapping) else []
        return {
            "mode": "hosted",
            "hosted": True,
            "api_base": "/api/v2",
            "csrf_cookie_name": CSRF_COOKIE_NAME,
            "csrf_header_name": CSRF_HEADER_NAME,
            "registration": "invite_only",
            "profiles": profile_names,
            "capabilities": {
                "run_controls": ["start", "pause", "stop", "step", "speed", "snapshot"],
                "world_mutations": False,
            },
        }

    @app.post("/auth/register", status_code=201)
    async def register_with_invite(body: InviteRegistrationBody) -> dict[str, Any]:
        # Ensure the credential points to an active tenant invitation before the
        # identity service is allowed to consume it.
        try:
            token_hash = hash_opaque_token(body.invite_token)
            invitation = await _invoke(catalog.lookup_invitation_by_hash, token_hash)
        except (SecurityValidationError, ValueError, TypeError):
            raise _generic_error(400, "invalid_invite") from None
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        if invitation is None:
            raise _generic_error(400, "invalid_invite")
        try:
            user = await _invoke(
                auth.register_with_invite,
                invite_token=body.invite_token,
                email=body.email,
                display_name=body.display_name,
                password=body.password,
                now=clock(),
            )
            user_id = _uuid_attribute(user, "user_id", "id")
            tenant_id = _uuid_attribute(invitation, "tenant_id")
            membership = await _invoke(catalog.get_membership, tenant_id, user_id)
            if membership is None:
                raise RuntimeError("invitation redemption did not create a membership")
        except AuthFailure as exc:
            raise _generic_error(400, "invalid_invite") from exc
        except (SecurityValidationError, ValueError, TypeError):
            raise _generic_error(400, "invalid_request") from None
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        return {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "role": str(_attribute(membership, "role", default="observer")),
        }

    @app.post("/auth/login")
    async def login(body: LoginBody, request: Request) -> Response:
        client_host = request.client.host if request.client else "unknown"
        try:
            credentials = await _invoke(
                auth.login,
                tenant_id=body.tenant_id,
                email=body.email,
                password=body.password,
                client_key=client_host,
                now=clock(),
            )
            session_token, csrf_token, expires_at = _credentials(credentials)
            authenticated = await _invoke(auth.authenticate_session, session_token, now=clock())
            if _authenticated_tenant(authenticated) != body.tenant_id:
                await _invoke(auth.revoke_session, session_token, now=clock())
                raise AuthFailure("invalid_credentials")
            user = _attribute(authenticated, "user", default=authenticated)
            user_id = _uuid_attribute(user, "user_id", "id")
            membership = await _invoke(catalog.get_membership, body.tenant_id, user_id)
            if membership is None or str(_attribute(membership, "status", default="")) != ACTIVE_MEMBERSHIP:
                await _invoke(auth.revoke_session, session_token, now=clock())
                raise AuthFailure("invalid_credentials")
            role = str(_attribute(membership, "role", default=""))
            if role not in {ROLE_OBSERVER, ROLE_ADMIN}:
                await _invoke(auth.revoke_session, session_token, now=clock())
                raise AuthFailure("invalid_credentials")
        except AuthFailure as exc:
            headers = (
                {"Retry-After": str(exc.retry_after_seconds)}
                if exc.retry_after_seconds
                else None
            )
            status = 429 if exc.retry_after_seconds else 401
            metrics.auth_rejections.labels("login").inc()
            raise _generic_error(status, "invalid_credentials", headers=headers) from None
        except (SecurityValidationError, ValueError, TypeError):
            metrics.auth_rejections.labels("login").inc()
            raise _generic_error(401, "invalid_credentials") from None
        except Exception:
            # Login is a pre-authentication surface.  Persistence failures
            # (including a tenant UUID with no durable row) must not create a
            # tenant-existence oracle through a distinct 503 response.
            metrics.auth_rejections.labels("login").inc()
            raise _generic_error(401, "invalid_credentials") from None
        response = JSONResponse(
            {
                "tenant_id": str(body.tenant_id),
                "user_id": str(user_id),
                "role": role,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }
        )
        response.headers.append("Set-Cookie", build_session_cookie(session_token))
        response.headers.append("Set-Cookie", build_csrf_cookie(csrf_token))
        return response

    @app.post("/auth/logout", status_code=204)
    async def logout(request: Request) -> Response:
        session_token = _session_cookie(request)
        if session_token is None:
            raise _generic_error(401, "authentication_required")
        submitted = request.headers.get(CSRF_HEADER_NAME)
        csrf_cookie = _csrf_cookie(request)
        if submitted is None or csrf_cookie is None:
            raise _generic_error(403, "csrf_required")
        try:
            await _invoke(
                auth.authenticate_csrf,
                session_token=session_token,
                submitted_csrf_token=submitted,
                csrf_cookie_token=csrf_cookie,
                now=clock(),
            )
            await _invoke(auth.revoke_session, session_token, now=clock())
        except (AuthFailure, SecurityValidationError, ValueError, TypeError):
            raise _generic_error(403, "csrf_required") from None
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        response = Response(status_code=204)
        response.headers.append("Set-Cookie", expire_session_cookie())
        response.headers.append("Set-Cookie", expire_csrf_cookie())
        return response

    @app.get("/api/v2/tenants/{tenant_id}/session")
    async def session_detail(tenant_id: UUID, request: Request) -> dict[str, Any]:
        principal = await authorize(request, tenant_id)
        return {
            "tenant_id": str(principal.tenant_id),
            "user_id": str(principal.user_id),
            "role": principal.role,
        }

    @app.post("/api/v2/tenants/{tenant_id}/invitations", status_code=201)
    async def create_invitation(tenant_id: UUID, body: InviteBody, request: Request) -> dict[str, Any]:
        principal = await authorize_mutation(request, tenant_id, admin=True)
        token: str | None = None
        try:
            token = await _invoke(
                auth.issue_invite,
                tenant_id=tenant_id,
                email=body.email,
                role=body.role,
                now=clock(),
                display_name_hint=body.display_name_hint,
                created_by_user_id=str(principal.user_id),
            )
            token = parse_opaque_token(token)
            invitation = await _invoke(
                catalog.lookup_invitation_by_hash, hash_opaque_token(token)
            )
            if invitation is None or _uuid_attribute(invitation, "tenant_id") != tenant_id:
                raise RuntimeError("tenant invitation was not durably recorded")
        except Exception:
            if token is not None:
                revoke = getattr(auth, "revoke_invite", None)
                if revoke is not None:
                    try:
                        await _invoke(revoke, token, now=clock())
                    except Exception:
                        pass
            raise _generic_error(503, "service_unavailable") from None
        return {
            "invitation_id": str(_uuid_attribute(invitation, "id", "invitation_id")),
            "tenant_id": str(tenant_id),
            "role": body.role,
            "expires_at": str(_attribute(invitation, "expires_at")),
            # This is the only administrative response that discloses the
            # one-time invite credential.
            "invite_token": token,
        }

    @app.post("/api/v2/tenants/{tenant_id}/invitations/revoke")
    async def revoke_invitation(tenant_id: UUID, body: RevokeInviteBody, request: Request) -> dict[str, bool]:
        await authorize_mutation(request, tenant_id, admin=True)
        try:
            token_hash = hash_opaque_token(body.invite_token)
            invitation = await _invoke(catalog.lookup_invitation_by_hash, token_hash)
            if invitation is None or _uuid_attribute(invitation, "tenant_id") != tenant_id:
                raise _generic_error(404, "not_found")
            revoked = await _invoke(auth.revoke_invite, body.invite_token, now=clock())
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        return {"revoked": bool(revoked)}

    @app.get("/api/v2/tenants/{tenant_id}/members")
    async def list_members(tenant_id: UUID, request: Request) -> dict[str, Any]:
        await authorize(request, tenant_id, admin=True)
        try:
            members = await _invoke(catalog.list_members, tenant_id)
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        return {"members": [_public_membership(member) for member in members]}

    @app.patch("/api/v2/tenants/{tenant_id}/members/{user_id}")
    async def update_member(
        tenant_id: UUID, user_id: UUID, body: MemberUpdateBody, request: Request
    ) -> dict[str, Any]:
        principal = await authorize_mutation(request, tenant_id, admin=True)
        if user_id == principal.user_id and (not body.enabled or body.role != ROLE_ADMIN):
            raise _generic_error(409, "self_admin_change_denied")
        try:
            membership = await _invoke(
                catalog.update_membership,
                tenant_id,
                user_id,
                role=body.role,
                enabled=body.enabled,
            )
            if membership is None:
                raise _generic_error(404, "not_found")
            if not body.enabled:
                revoke_sessions = getattr(catalog, "revoke_user_sessions", None)
                if revoke_sessions is not None:
                    await _invoke(revoke_sessions, tenant_id, user_id)
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        return _public_membership(membership)

    @app.get("/api/v2/tenants/{tenant_id}/runs")
    async def list_runs(
        tenant_id: UUID, request: Request, limit: int = Query(default=100, ge=1, le=500)
    ) -> dict[str, Any]:
        await authorize(request, tenant_id)
        try:
            records = await _invoke(catalog.list_runs, tenant_id, limit=limit)
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        return {"runs": [_public_run(record) for record in records]}

    @app.post("/api/v2/tenants/{tenant_id}/runs", status_code=201)
    async def create_run(tenant_id: UUID, body: RunCreateBody, request: Request) -> dict[str, Any]:
        principal = await authorize_mutation(request, tenant_id, admin=True)
        try:
            handle = await _invoke(
                supervisor.create_run,
                tenant_id,
                principal.user_id,
                body.profile_slug,
                body.display_name,
            )
            status_method = getattr(handle, "status", None)
            payload = await _invoke(status_method) if status_method is not None else handle
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        return sanitize_public_payload(payload)

    @app.get("/api/v2/tenants/{tenant_id}/runs/{run_id}")
    async def get_run(tenant_id: UUID, run_id: UUID, request: Request) -> dict[str, Any]:
        await authorize(request, tenant_id)
        record = await tenant_run(tenant_id, run_id)
        payload = _public_run(record)
        try:
            handle = await _invoke(supervisor.get_handle, tenant_id, run_id, load=False)
            if handle is not None and getattr(handle, "status", None) is not None:
                payload["runtime"] = sanitize_public_payload(await _invoke(handle.status))
        except Exception:
            # Catalog detail remains useful if a stopped run has no live worker.
            payload["runtime"] = None
        return payload

    @app.patch("/api/v2/tenants/{tenant_id}/runs/{run_id}")
    async def update_run(
        tenant_id: UUID, run_id: UUID, body: RunUpdateBody, request: Request
    ) -> dict[str, Any]:
        await authorize_mutation(request, tenant_id, admin=True)
        if body.status is not None:
            # Catalog terminal transitions clear the writer lease.  Applying
            # one directly while a loaded world is still running permits a
            # second supervisor to acquire the run and creates split-brain
            # writers.  Lifecycle transitions must go through /control.
            raise _generic_error(409, "run_status_control_required")
        record = await tenant_run(tenant_id, run_id)
        try:
            if body.owner_user_id is not None:
                record = await _invoke(
                    catalog.transfer_run_owner, tenant_id, run_id, body.owner_user_id
                )
                if record is None:
                    raise _generic_error(409, "owner_not_active")
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(503, "service_unavailable") from None
        return _public_run(record)

    @app.post("/api/v2/tenants/{tenant_id}/runs/{run_id}/control")
    async def control_run(
        tenant_id: UUID, run_id: UUID, body: RunControlBody, request: Request
    ) -> Any:
        await authorize_mutation(request, tenant_id, admin=True)
        handle = await run_handle(tenant_id, run_id)
        if body.action == "snapshot":
            snapshot = getattr(supervisor, "snapshot_boundary", None)
            if snapshot is None:
                raise _generic_error(503, "service_unavailable")
            try:
                result = snapshot(handle, "pause", manual=True)
                if inspect.isawaitable(result):
                    result = await result
            except Exception:
                raise _generic_error(409, "run_control_rejected") from None
            return sanitize_public_payload(result)
        controller = getattr(handle, "controller", None)
        if controller is None:
            raise _generic_error(503, "service_unavailable")
        action = getattr(controller, body.action, None)
        if action is None:
            action = getattr(controller, "set_speed", None) if body.action == "speed" else None
        if action is None:
            raise _generic_error(503, "service_unavailable")
        try:
            if body.action == "start":
                result = action(body.max_ticks)
            elif body.action == "speed":
                result = action(body.delay_s)
            else:
                result = action()
            if inspect.isawaitable(result):
                result = await result
            observe_control = getattr(supervisor, "observe_control", None)
            if observe_control is not None:
                inner_path = {
                    "start": "/api/run/start",
                    "pause": "/api/run/pause",
                    "stop": "/api/run/stop",
                    "step": "/api/run/step",
                    "speed": "/api/run/speed",
                }[body.action]
                observed = observe_control(handle, inner_path, "POST")
                if inspect.isawaitable(observed):
                    await observed
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(409, "run_control_rejected") from None
        return sanitize_public_payload(result)

    @app.api_route(
        "/api/v2/tenants/{tenant_id}/runs/{run_id}/world/{world_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def proxy_world(
        tenant_id: UUID,
        run_id: UUID,
        world_path: str,
        request: Request,
    ) -> Response:
        principal = await authorize(request, tenant_id)
        if request.method not in {"GET", "HEAD"}:
            if principal.role == ROLE_OBSERVER:
                raise _generic_error(403, "read_only_role")
            raise _generic_error(405, "world_mutation_not_allowed")
        upstream_path = _safe_world_path(world_path)
        if upstream_path is None:
            raise _generic_error(404, "not_found")
        query_items = list(request.query_params.multi_items())
        if (
            len(request.url.query.encode("utf-8")) > MAX_PROXY_QUERY_BYTES
            or len(query_items) > MAX_PROXY_QUERY_FIELDS
        ):
            raise _generic_error(413, "query_too_large")
        handle = await run_handle(tenant_id, run_id)
        run_app = getattr(handle, "app", None)
        if run_app is None:
            raise _generic_error(503, "service_unavailable")
        slots: asyncio.Semaphore = app.state.world_proxy_slots
        try:
            try:
                await asyncio.wait_for(slots.acquire(), timeout=0.05)
            except asyncio.TimeoutError:
                raise _generic_error(429, "world_read_capacity") from None
            try:
                transport = httpx.ASGITransport(app=run_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://run.internal",
                    timeout=httpx.Timeout(10.0),
                ) as client:
                    upstream = await client.request(
                        "GET" if request.method == "HEAD" else request.method,
                        upstream_path,
                        params=query_items,
                        headers={"accept": "application/json"},
                    )
            finally:
                slots.release()
            if len(upstream.content) > MAX_PROXY_RESPONSE_BYTES:
                raise _generic_error(502, "upstream_response_too_large")
            try:
                data = upstream.json()
            except (ValueError, json.JSONDecodeError):
                raise _generic_error(502, "invalid_upstream_response") from None
        except HTTPException:
            raise
        except Exception:
            raise _generic_error(502, "upstream_unavailable") from None
        if request.method == "HEAD":
            return Response(status_code=upstream.status_code, media_type="application/json")
        return JSONResponse(
            status_code=upstream.status_code,
            content=sanitize_public_payload(data),
        )

    @app.websocket("/api/v2/tenants/{tenant_id}/runs/{run_id}/ws")
    async def hosted_websocket(websocket: WebSocket, tenant_id: UUID, run_id: UUID) -> None:
        # Every potentially revealing lookup occurs before accept.
        try:
            await authorize(websocket, tenant_id)
        except HTTPException as exc:
            await websocket.close(code=4401 if exc.status_code == 401 else 4403)
            return
        try:
            record = await _invoke(catalog.get_run, tenant_id, run_id)
            if record is None:
                await websocket.close(code=4404)
                return
            handle = await _invoke(supervisor.get_handle, tenant_id, run_id, load=True)
            if handle is None or getattr(handle, "controller", None) is None:
                await websocket.close(code=4404)
                return
        except Exception:
            await websocket.close(code=1013)
            return
        controller = handle.controller
        hub = getattr(controller, "hub", None)
        if hub is None:
            await websocket.close(code=1013)
            return
        wrapped = _SanitizingSocket(websocket)
        try:
            await hub.connect(wrapped)
            metrics.websocket_connections.inc()
            status = getattr(handle, "status", None)
            if status is not None:
                raw_status = await _invoke(status)
                status_payload = sanitize_public_payload(raw_status)
                if not isinstance(status_payload, Mapping):
                    status_payload = {"status": str(status_payload)}
                await websocket.send_json(
                    {"type": "run_status", **dict(status_payload)}
                )
            while True:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                await websocket.close(code=1008)
                break
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(wrapped)

    # Serve only the immutable observatory bundle.  Hosted mode intentionally
    # does not mount the local reports directory or accept a request-derived
    # filesystem root.
    static_root = Path(__file__).resolve().parents[1] / "server" / "static"
    index_path = static_root / "index.html"
    if index_path.is_file() and (static_root / "assets").is_dir():
        @app.get("/", include_in_schema=False)
        async def hosted_dashboard() -> FileResponse:
            return FileResponse(index_path)

        app.mount(
            "/static",
            StaticFiles(directory=static_root, check_dir=True),
            name="hosted-static",
        )

    return app


# Conventional alias for deployment entrypoints.
create_app = create_hosted_app


__all__ = [
    "CSRF_HEADER_NAME",
    "Principal",
    "TenantAuthService",
    "create_app",
    "create_hosted_app",
    "sanitize_public_payload",
]
