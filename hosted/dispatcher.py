"""Authenticated ASGI dispatch into tenant-scoped hosted run applications."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable
from uuid import UUID

from hosted.supervisor import (
    HostedRunSupervisor,
    InvalidRunIdentifier,
    RunCapacityExceeded,
    WriterLeaseUnavailable,
)


_RUN_ROUTE_RE = re.compile(
    r"^/api/runs/(?P<run_id>[0-9a-fA-F-]{36})(?P<inner>/.*)?$"
)
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class HostedPrincipal:
    """Tenant binding established by the outer hosted authentication layer."""

    tenant_id: str
    user_id: str
    role: str

    def __post_init__(self) -> None:
        try:
            tenant = str(UUID(str(self.tenant_id)))
            user = str(UUID(str(self.user_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("hosted principal tenant and user ids must be UUIDs") from exc
        if self.role not in {"observer", "agent_owner", "admin"}:
            raise ValueError("hosted principal role must be observer, agent_owner, or admin")
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "user_id", user)


@runtime_checkable
class ScopeAuthenticator(Protocol):
    """Authenticate an HTTP/WebSocket scope before a run app sees it."""

    def authenticate(
        self, scope: Mapping[str, Any]
    ) -> HostedPrincipal | Mapping[str, Any] | None | Awaitable[
        HostedPrincipal | Mapping[str, Any] | None
    ]: ...


def _principal(value: HostedPrincipal | Mapping[str, Any] | None) -> HostedPrincipal | None:
    if value is None:
        return None
    if isinstance(value, HostedPrincipal):
        return value
    if isinstance(value, Mapping):
        return HostedPrincipal(
            tenant_id=str(value.get("tenant_id", "")),
            user_id=str(value.get("user_id", "")),
            role=str(value.get("role", "")),
        )
    raise ValueError("authenticator returned an invalid principal")


class MultiRunDispatcher:
    """Route authenticated requests to one isolated per-run FastAPI app.

    The dispatcher owns no file-serving endpoints and never takes a database or
    filesystem path from a request.  A public route such as
    ``/api/runs/<uuid>/api/run/status`` is rewritten to
    ``/api/run/status`` only after tenant-scoped catalog resolution.
    """

    def __init__(
        self,
        supervisor: HostedRunSupervisor,
        authenticator: ScopeAuthenticator | Callable[[Mapping[str, Any]], Any],
    ) -> None:
        self.supervisor = supervisor
        self.authenticator = authenticator

    async def _authenticate(self, scope: Mapping[str, Any]) -> HostedPrincipal | None:
        authenticate = getattr(self.authenticator, "authenticate", None)
        value = authenticate(scope) if callable(authenticate) else self.authenticator(scope)
        if inspect.isawaitable(value):
            value = await value
        return _principal(value)

    @staticmethod
    async def _http_error(send: Callable[..., Awaitable[None]], status: int, code: str) -> None:
        body = json.dumps(
            {"error": code}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})

    @staticmethod
    async def _websocket_error(send: Callable[..., Awaitable[None]], code: int) -> None:
        # No accept frame is sent: authentication and tenant binding have not
        # completed, so the per-run hub must never observe this socket.
        await send({"type": "websocket.close", "code": code})

    async def _lifespan(self, receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await self.supervisor.recover_active_runs()
                except Exception as exc:
                    await send({
                        "type": "lifespan.startup.failed",
                        "message": f"hosted recovery failed: {type(exc).__name__}",
                    })
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    await self.supervisor.shutdown()
                except Exception as exc:
                    await send({
                        "type": "lifespan.shutdown.failed",
                        "message": f"hosted shutdown failed: {type(exc).__name__}",
                    })
                    return
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def __call__(self, scope, receive, send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope_type not in {"http", "websocket"}:
            return

        try:
            principal = await self._authenticate(scope)
        except Exception:
            principal = None
        if principal is None:
            if scope_type == "http":
                await self._http_error(send, 401, "authentication_required")
            else:
                await self._websocket_error(send, 4401)
            return

        path = str(scope.get("path", ""))
        match = _RUN_ROUTE_RE.fullmatch(path)
        if match is None:
            if scope_type == "http":
                await self._http_error(send, 404, "not_found")
            else:
                await self._websocket_error(send, 4404)
            return
        public_run_id = match.group("run_id")
        inner_path = match.group("inner") or "/"
        try:
            handle = await self.supervisor.get_handle(
                principal.tenant_id, public_run_id, load=True
            )
        except (InvalidRunIdentifier, ValueError):
            handle = None
        except WriterLeaseUnavailable:
            if scope_type == "http":
                await self._http_error(send, 409, "writer_lease_unavailable")
            else:
                await self._websocket_error(send, 4410)
            return
        except RunCapacityExceeded:
            if scope_type == "http":
                await self._http_error(send, 503, "run_capacity_exceeded")
            else:
                await self._websocket_error(send, 4503)
            return
        if handle is None:
            # Tenant-scoped absence deliberately does not reveal whether the
            # UUID belongs to another tenant.
            if scope_type == "http":
                await self._http_error(send, 404, "run_not_found")
            else:
                await self._websocket_error(send, 4404)
            return

        method = str(scope.get("method", "GET")).upper()
        if scope_type == "http" and method in _MUTATING_METHODS and principal.role != "admin":
            await self._http_error(send, 403, "observer_read_only")
            return

        self.supervisor.bind_event_loop(handle)
        delegated = dict(scope)
        delegated["path"] = inner_path
        delegated["raw_path"] = inner_path.encode("utf-8")
        prefix = f"/api/runs/{public_run_id}"
        delegated["root_path"] = str(scope.get("root_path", "")) + prefix
        state = dict(scope.get("state") or {})
        state.update({
            "hosted_principal": principal,
            "hosted_tenant_id": principal.tenant_id,
            "hosted_run_id": handle.public_run_id,
        })
        delegated["state"] = state

        response_status = 101 if scope_type == "websocket" else 500

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message.get("type") == "http.response.start":
                response_status = int(message.get("status", 500))
            elif message.get("type") == "websocket.accept":
                response_status = 101
            await send(message)

        await handle.app(delegated, receive, tracked_send)
        if scope_type == "http" and response_status < 400:
            self.supervisor.observe_control(handle, inner_path, method)


# Descriptive and concise names are both kept for integrations.
HostedRunDispatcher = MultiRunDispatcher
