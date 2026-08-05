"""Small synchronous REST client with no framework-specific assumptions."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


class AgentEconomyError(RuntimeError):
    """Raised when the gateway returns a non-success response."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


class AgentEconomyClient:
    """REST client for one scoped external-agent credential."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 65.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("token is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> "AgentEconomyClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            body = response.json()
        except ValueError:
            body = {}
        detail = body.get("detail", body.get("error", {})) if isinstance(body, dict) else {}
        if isinstance(detail, dict):
            code = str(detail.get("code", body.get("error", "gateway_error")))
            message = str(detail.get("message", body.get(
                "error_description", response.reason_phrase)))
        else:
            code = "gateway_error"
            message = str(detail or response.reason_phrase)
        raise AgentEconomyError(response.status_code, code, message)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.request(method, path, **kwargs)
        self._raise(response)
        value = response.json()
        if not isinstance(value, dict):
            raise AgentEconomyError(
                response.status_code, "invalid_response", "expected a JSON object")
        return value

    def identity(self) -> dict[str, Any]:
        return self._request("GET", "/api/v2/agent/me")

    def turn(self, *, after_tick: int | None = None,
             wait_seconds: float = 0) -> dict[str, Any]:
        params: dict[str, Any] = {"wait_seconds": wait_seconds}
        if after_tick is not None:
            params["after_tick"] = after_tick
        return self._request("GET", "/api/v2/agent/turn", params=params)

    def submit_action(
        self,
        *,
        target_tick: int,
        action: Mapping[str, Any],
        observed_projection_hash: str,
        idempotency_key: str,
        rationale_summary: str = "",
    ) -> dict[str, Any]:
        return self._request("POST", "/api/v2/agent/actions", json={
            "target_tick": target_tick,
            "action": dict(action),
            "observed_projection_hash": observed_projection_hash,
            "idempotency_key": idempotency_key,
            "rationale_summary": rationale_summary,
        })

    def receipt(self, submission_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v2/agent/actions/{submission_id}")

    def events(self, *, cursor: int = 0, limit: int = 100) -> dict[str, Any]:
        return self._request("GET", "/api/v2/agent/events", params={
            "cursor": cursor, "limit": limit})

    def commons_read(
        self, *, kind: str = "chronological", community_id: int | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"kind": kind, "limit": limit}
        if community_id is not None:
            params["community_id"] = community_id
        return self._request("GET", "/api/v2/agent/commons", params=params)

    def commons_act(self, action: Mapping[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v2/agent/commons", json={"action": dict(action)})
