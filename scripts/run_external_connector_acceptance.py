#!/usr/bin/env python3
"""Explicit hosted connector runner that persists only sanitized public hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.external_connector_acceptance import (
    CONNECTORS,
    _public_https_origin,
    validate_external_connector_receipt,
    write_external_connector_receipt,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def load_credential_file(path: str | Path) -> dict[str, Any]:
    """Read a process-only credential file after strict ownership-mode checks."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("credential path must be a regular file, not a symlink")
    info = source.stat()
    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o600:
        raise PermissionError("credential file must have mode 600")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError("credential file must be owned by the current user")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("credential file must contain a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("credential file must contain a JSON object")
    token = value.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("credential file requires access_token")
    probe = value.get("isolation_probe_path")
    if (
        not isinstance(probe, str)
        or not probe.startswith("/")
        or probe.startswith("//")
        or urlsplit(probe).scheme
        or urlsplit(probe).netloc
    ):
        raise ValueError(
            "credential file requires isolation_probe_path to be a root-relative "
            "path that starts with a single '/'"
        )
    return value


class _RejectRedirects(HTTPRedirectHandler):
    """Return redirects to the caller instead of replaying credentialed requests."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirects())


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: Any | None = None,
    form_body: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, bytes]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "agent-economy-external-acceptance/1",
    }
    data = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = _canonical_bytes(json_body)
        headers["Content-Type"] = "application/json"
    elif form_body is not None:
        data = urlencode(form_body).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
            return int(response.status), response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        try:
            body = exc.read(2 * 1024 * 1024)
        except OSError:
            body = b""
        return int(exc.code), body
    except (OSError, URLError) as exc:
        raise RuntimeError(
            f"hosted request failed before an HTTP response ({type(exc).__name__})"
        ) from None


def _json_response(status: int, body: bytes, *, expected: set[int], label: str) -> dict:
    if status not in expected:
        raise RuntimeError(f"{label} returned HTTP {status}")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise RuntimeError(f"{label} returned invalid JSON") from None
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} returned a non-object JSON response")
    return value


def _url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _safe_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_id": str(receipt.get("submission_id") or ""),
        "target_tick": int(receipt.get("target_tick", 0)),
        "status": str(receipt.get("status") or ""),
        "resulting_state_hash": receipt.get("resulting_state_hash"),
        "event_ids": receipt.get("event_ids") or [],
    }


def _execute_wake(
    base_url: str,
    token: str,
    *,
    after_tick: int | None,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    query = "?wait_seconds=30"
    if after_tick is not None:
        query += f"&after_tick={int(after_tick)}"
    status, body = _request(
        "GET",
        _url(base_url, "/api/v2/agent/turn") + query,
        token=token,
        timeout=max(31.0, timeout),
    )
    turn = _json_response(status, body, expected={200}, label="turn read")
    raw_tick = turn.get("target_tick")
    target_tick = raw_tick if type(raw_tick) is int else -1
    projection_hash = str(turn.get("projection_hash") or "")
    if target_tick < 0 or len(projection_hash) != 64:
        raise RuntimeError("turn response lacks target tick or projection hash")
    action = {
        "target_tick": target_tick,
        "action": {"type": "do_nothing"},
        "observed_projection_hash": projection_hash,
        "idempotency_key": f"external-acceptance-{target_tick}-{os.urandom(8).hex()}",
        "rationale_summary": "Independent connector acceptance no-op.",
    }
    status, body = _request(
        "POST",
        _url(base_url, "/api/v2/agent/actions"),
        token=token,
        json_body=action,
        timeout=timeout,
    )
    submitted = _json_response(status, body, expected={202}, label="action submit")
    submission_id = str(submitted.get("submission_id") or "")
    if not submission_id:
        raise RuntimeError("action submission omitted its receipt ID")
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = submitted
    while time.monotonic() < deadline:
        status, body = _request(
            "GET",
            _url(base_url, f"/api/v2/agent/actions/{submission_id}"),
            token=token,
            timeout=min(30.0, timeout),
        )
        last = _json_response(status, body, expected={200}, label="receipt read")
        if last.get("status") in {"executed", "rejected", "stale"}:
            break
        time.sleep(1.0)
    if last.get("status") != "executed":
        raise RuntimeError(
            f"action receipt did not execute (status={last.get('status', 'unknown')})"
        )
    return action, submitted, _safe_receipt(last)


class _CredentialRevoker:
    """Make the single revocation attempt observable and idempotent."""

    def __init__(self, base_url: str, credential: dict[str, Any]) -> None:
        self.base_url = base_url
        self.token = str(
            credential.get("revocation_token") or credential["access_token"]
        )
        self.attempted = False

    def revoke(self) -> None:
        if self.attempted:
            return
        self.attempted = True
        status, _body = _request(
            "POST",
            _url(self.base_url, "/oauth/revoke"),
            form_body={"token": self.token},
        )
        if status not in {200, 204}:
            raise RuntimeError(f"credential revocation returned HTTP {status}")


def _run_authenticated_acceptance(
    args: argparse.Namespace,
    credential: dict[str, Any],
    revoker: _CredentialRevoker,
) -> dict[str, Any]:
    token = credential["access_token"]
    started_at = _now()
    public_requests: list[dict[str, Any]] = []
    public_responses: list[dict[str, Any]] = []

    auth_status, auth_body = _request(
        "GET", _url(args.base_url, "/.well-known/oauth-authorization-server")
    )
    authorization_metadata = _json_response(
        auth_status, auth_body, expected={200}, label="authorization metadata"
    )
    resource_status, resource_body = _request(
        "GET", _url(args.base_url, "/.well-known/oauth-protected-resource/mcp")
    )
    protected_metadata = _json_response(
        resource_status, resource_body, expected={200}, label="protected resource metadata"
    )
    identity_status, identity_body = _request(
        "GET", _url(args.base_url, "/api/v2/agent/me"), token=token
    )
    identity = _json_response(
        identity_status, identity_body, expected={200}, label="agent identity"
    )
    actor = identity.get("actor")
    if not isinstance(actor, dict) or actor.get("id") is None:
        raise RuntimeError("hosted connector identity has no active actor")
    scopes = sorted(str(scope) for scope in identity.get("scopes", []))

    discovery = None
    if args.connector == "independent_mcp":
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": args.client_name, "version": args.client_version},
            },
        }
        mcp_status, mcp_body = _request(
            "POST", _url(args.base_url, "/mcp"), token=token, json_body=initialize
        )
        initialized = _json_response(
            mcp_status, mcp_body, expected={200}, label="MCP initialize"
        )
        discovery = {
            "passed": True,
            "authorization_server_sha256": _hash(authorization_metadata),
            "protected_resource_sha256": _hash(protected_metadata),
            "initialize_sha256": _hash(initialized),
        }

    wake_count = 3 if args.connector in {"hermes", "openclaw"} else 1
    wakes: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    after_tick = None
    for _ in range(wake_count):
        action, submitted, safe = _execute_wake(
            args.base_url,
            token,
            after_tick=after_tick,
            timeout=args.timeout,
        )
        public_requests.append(action)
        public_responses.append({
            "submission_id": submitted.get("submission_id"),
            "status": submitted.get("status"),
            "receipt": safe,
        })
        executed.append({
            "receipt_id": safe["receipt_id"],
            "sha256": _hash(safe),
            "status": safe["status"],
        })
        wakes.append({
            "target_tick": safe["target_tick"],
            "submission_id": safe["receipt_id"],
            "receipt_id": safe["receipt_id"],
            "status": safe["status"],
        })
        after_tick = safe["target_tick"]

    isolation_status, _isolation_body = _request(
        "GET",
        _url(args.base_url, credential["isolation_probe_path"]),
        token=token,
    )
    isolation_passed = isolation_status in {403, 404}
    revoker.revoke()
    post_status, _post_body = _request(
        "GET", _url(args.base_url, "/api/v2/agent/me"), token=token
    )

    result: dict[str, Any] = {
        "schema": "agent-economy-external-connector-v1",
        "connector": args.connector,
        "execution_scope": "independent_external",
        "status": "passed",
        "candidate": {"commit": args.commit, "tree": args.tree},
        "client": {"name": args.client_name, "version": args.client_version},
        "signer": {"label": args.signer_label, "independent": True},
        "server_operator": args.server_operator,
        "base_url": args.base_url.rstrip("/"),
        "hosted_origin_sha256": _hash({"origin": args.base_url.rstrip("/")}),
        "tenant_id": str(identity.get("tenant_id") or ""),
        "run_id": str(identity.get("run_id") or ""),
        "actor_id": str(actor["id"]),
        "scopes": scopes,
        "started_at": started_at,
        "ended_at": _now(),
        "public_exchange": {
            "request_sha256": _hash(public_requests),
            "response_sha256": _hash(public_responses),
        },
        "executed_receipts": executed,
        "revocation": {
            "passed": post_status == 401,
            "post_revoke_status": post_status,
        },
        "cross_tenant_isolation": {
            "passed": isolation_passed,
            "status": isolation_status,
        },
        "notes": "Sanitized public hashes only; credentials and private payloads were not retained.",
    }
    if discovery is not None:
        result["discovery"] = discovery
    elif args.connector in {"hermes", "openclaw"}:
        result["wakes"] = wakes
    else:
        result["flows"] = {
            "authorized_submit": True,
            "receipt_read": bool(executed),
        }
    return validate_external_connector_receipt(
        result,
        expected_candidate={"commit": args.commit, "tree": args.tree},
        expected_connector=args.connector,
    )


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    """Execute exactly one connector against an existing hosted test identity."""
    if args.connector not in CONNECTORS:
        raise ValueError("unsupported connector")
    if not _public_https_origin(args.base_url):
        raise ValueError("base URL must be a public HTTPS origin")
    if not is_lowercase_hex(args.commit, 40) or not is_lowercase_hex(args.tree, 40):
        raise ValueError("candidate commit and tree must be lowercase 40-character hex IDs")
    credential = load_credential_file(args.credential_file)
    revoker = _CredentialRevoker(args.base_url, credential)
    flow_failed = False
    try:
        return _run_authenticated_acceptance(args, credential, revoker)
    except BaseException:
        flow_failed = True
        raise
    finally:
        if not revoker.attempted:
            try:
                revoker.revoke()
            except BaseException:
                if not flow_failed:
                    raise


def is_lowercase_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one separately authorized hosted connector acceptance gate."
    )
    parser.add_argument("--connector", required=True, choices=sorted(CONNECTORS))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--signer-label", required=True)
    parser.add_argument("--server-operator", required=True)
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--client-version", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    if args.timeout < 10 or args.timeout > 900:
        parser.error("--timeout must be between 10 and 900 seconds")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_acceptance(args)
        output = write_external_connector_receipt(result, args.output)
    except Exception as exc:
        print(
            json.dumps({
                "status": "failed",
                "error": type(exc).__name__,
                "message": str(exc),
            }),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({
        "status": "passed",
        "connector": args.connector,
        "receipt": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
