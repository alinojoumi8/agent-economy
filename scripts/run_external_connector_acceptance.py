#!/usr/bin/env python3
"""Explicit hosted connector runner that persists only sanitized public hashes."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import socket
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.external_connector_acceptance import (
    CONNECTORS,
    MCP_PROTOCOL_VERSION,
    SCHEMA,
    _public_https_origin,
    build_external_release_gate_receipt,
    hosted_origin_sha256,
    validate_native_connector_result,
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


def _validate_credential_metadata(
    info: os.stat_result | Any,
    *,
    platform_name: str,
) -> None:
    """Reject non-files and Windows reparse points before credentials are read."""
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(info, "st_file_attributes", 0)
    if not stat.S_ISREG(info.st_mode) or file_attributes & reparse_flag:
        raise ValueError("credential path must be a regular file, not a symlink")
    # Windows' st_mode contains only a lossy projection of ACL permissions, so
    # a Unix 0600 comparison rejects normal private Windows files. Reparse-point
    # rejection plus the lstat/fstat identity check below provides the relevant
    # path-swap boundary there; POSIX retains its exact private-mode contract.
    if platform_name != "nt" and stat.S_IMODE(info.st_mode) != 0o600:
        raise PermissionError("credential file must have mode 600")


def load_credential_file(path: str | Path) -> dict[str, Any]:
    """Read a process-only credential after platform-specific path checks."""
    source = Path(path)
    descriptor: int | None = None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            source_info = os.lstat(source)
        except OSError as exc:
            raise ValueError(
                "credential path must be an existing regular file, not a symlink "
                f"({type(exc).__name__})"
            ) from exc
        _validate_credential_metadata(source_info, platform_name=os.name)
        try:
            descriptor = os.open(source, flags)
        except OSError as exc:
            raise ValueError(
                "credential path must be an existing regular file, not a symlink "
                f"({type(exc).__name__})"
            ) from exc
        info = os.fstat(descriptor)
        _validate_credential_metadata(info, platform_name=os.name)
        if not os.path.samestat(source_info, info):
            raise ValueError("credential path must be a regular file, not a symlink")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise PermissionError("credential file must be owned by the current user")
        try:
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = None
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("credential file must contain a JSON object") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
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


def load_native_result_file(
    path: str | Path,
    *,
    expected_candidate: dict[str, str],
    expected_connector: str,
) -> tuple[dict[str, Any], str]:
    """Load and validate the immutable, sanitized output of one native client."""
    source = Path(path)
    descriptor: int | None = None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_info = os.lstat(source)
        _validate_credential_metadata(source_info, platform_name="nt")
        descriptor = os.open(source, flags)
        opened_info = os.fstat(descriptor)
        _validate_credential_metadata(opened_info, platform_name="nt")
        if not os.path.samestat(source_info, opened_info):
            raise ValueError("native result path changed while it was opened")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant is not allowed: {constant}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            "native result must be a readable, finite JSON object in a regular file"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    validated = validate_native_connector_result(
        value,
        expected_candidate=expected_candidate,
        expected_connector=expected_connector,
    )
    return validated, hashlib.sha256(raw).hexdigest()


class _RejectRedirects(HTTPRedirectHandler):
    """Return redirects to the caller instead of replaying credentialed requests."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_DIRECT_PROXY_HANDLER = ProxyHandler({})
_NO_REDIRECT_OPENER = build_opener(_DIRECT_PROXY_HANDLER, _RejectRedirects())


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
    parts = urlsplit(base_url)
    origin = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
    return urljoin(origin, path)


def _resolved_origin_is_public(base_url: str) -> bool:
    """Reject origins whose current DNS answers include non-public addresses."""
    parsed = urlsplit(base_url)
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        port = parsed.port or 443
        answers = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except (OSError, ValueError):
        return False
    addresses = []
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0].split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address):
            embedded = (
                address.ipv4_mapped
                or address.sixtofour
                or (address.teredo[1] if address.teredo else None)
            )
            if embedded is not None:
                address = embedded
        addresses.append(address)
    return bool(addresses) and all(address.is_global for address in addresses)


def _safe_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    target_tick = receipt.get("target_tick")
    if type(target_tick) is not int:
        raise RuntimeError("receipt read returned a non-integer target tick")
    if target_tick < 0:
        raise RuntimeError("receipt read returned a negative target tick")
    receipt_id = receipt.get("submission_id")
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise RuntimeError("receipt read omitted its submission ID")
    return {
        "receipt_id": receipt_id,
        "target_tick": target_tick,
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
    if last.get("submission_id") != submission_id:
        raise RuntimeError("receipt read returned a different submission ID")
    return action, submitted, _safe_receipt(last)


class _CredentialRevoker:
    """Make the single revocation attempt observable and idempotent."""

    def __init__(self, base_url: str, credential: dict[str, Any]) -> None:
        self.base_url = base_url
        self.token = str(
            credential.get("revocation_token") or credential["access_token"]
        )
        self.attempted = False
        self.revoked = False

    def revoke(self) -> None:
        if self.revoked:
            return
        self.attempted = True
        status, _body = _request(
            "POST",
            _url(self.base_url, "/oauth/revoke"),
            form_body={"token": self.token},
        )
        if status not in {200, 204}:
            raise RuntimeError(f"credential revocation returned HTTP {status}")
        self.revoked = True


def _run_native_acceptance(
    args: argparse.Namespace,
    credential: dict[str, Any],
    revoker: _CredentialRevoker,
    native: dict[str, Any],
    native_sha256: str,
) -> dict[str, Any]:
    """Verify server state/security around an already completed native-client run."""
    token = credential["access_token"]
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
    raw_scopes = identity.get("scopes")
    if not isinstance(actor, dict) or actor.get("id") is None:
        raise RuntimeError("hosted connector identity has no active actor")
    if not isinstance(raw_scopes, list) or not raw_scopes:
        raise RuntimeError("hosted connector identity returned no scope list")
    scopes = sorted({str(scope) for scope in raw_scopes})
    observed_identity = {
        "tenant_id": str(identity.get("tenant_id") or ""),
        "run_id": str(identity.get("run_id") or ""),
        "actor_id": str(actor["id"]),
        "scopes": scopes,
    }
    expected_identity = {
        field: native[field] for field in ("tenant_id", "run_id", "actor_id", "scopes")
    }
    if observed_identity != expected_identity:
        raise RuntimeError("hosted identity differs from the native connector result")

    if native["connector"] == "independent_mcp":
        discovery = native["discovery"]
        if (
            discovery["authorization_server_sha256"] != _hash(authorization_metadata)
            or discovery["protected_resource_sha256"] != _hash(protected_metadata)
        ):
            raise RuntimeError("MCP discovery differs from the native connector result")

    wake_ticks = {
        wake["receipt_id"]: wake["target_tick"]
        for wake in native.get("wakes", [])
    }
    for expected_receipt in native["executed_receipts"]:
        receipt_id = expected_receipt["receipt_id"]
        status, body = _request(
            "GET",
            _url(args.base_url, f"/api/v2/agent/actions/{receipt_id}"),
            token=token,
            timeout=min(30.0, args.timeout),
        )
        observed = _safe_receipt(
            _json_response(status, body, expected={200}, label="native receipt read")
        )
        if (
            observed["receipt_id"] != receipt_id
            or observed["status"] != "executed"
            or _hash(observed) != expected_receipt["sha256"]
            or (
                receipt_id in wake_ticks
                and observed["target_tick"] != wake_ticks[receipt_id]
            )
        ):
            raise RuntimeError("server receipt differs from the native connector result")

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
    revocation_passed = post_status == 401
    if not isolation_passed or not revocation_passed:
        failed_gates = []
        if not revocation_passed:
            failed_gates.append("revocation")
        if not isolation_passed:
            failed_gates.append("cross_tenant_isolation")
        raise RuntimeError(
            "external connector security gates failed "
            f"(gates={','.join(failed_gates)}; post_status={post_status}; "
            f"isolation_status={isolation_status})"
        )

    result = json.loads(json.dumps(native))
    result["schema"] = SCHEMA
    result["client"]["native_evidence_sha256"] = native_sha256
    result["signer"] = {"label": args.signer_label, "independent": True}
    result["server_operator"] = args.server_operator
    result["base_url"] = args.base_url.rstrip("/")
    result["ended_at"] = _now()
    result["revocation"] = {
        "passed": revocation_passed,
        "post_revoke_status": post_status,
    }
    result["cross_tenant_isolation"] = {
        "passed": isolation_passed,
        "status": isolation_status,
    }
    return validate_external_connector_receipt(
        result,
        expected_candidate={"commit": args.commit, "tree": args.tree},
        expected_connector=args.connector,
    )


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
    raw_scopes = identity.get("scopes")
    if not isinstance(raw_scopes, list) or not raw_scopes:
        raise RuntimeError("hosted connector identity returned no scope list")
    scopes = sorted({str(scope) for scope in raw_scopes})
    if any(not scope.strip() or scope != scope.strip() for scope in scopes):
        raise RuntimeError("hosted connector identity returned an invalid scope list")

    discovery = None
    if args.connector == "independent_mcp":
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
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
            "protocol_version": MCP_PROTOCOL_VERSION,
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
    revocation_passed = post_status == 401
    gates_passed = revocation_passed and isolation_passed
    if not gates_passed:
        failed_gates = []
        if not revocation_passed:
            failed_gates.append("revocation")
        if not isolation_passed:
            failed_gates.append("cross_tenant_isolation")
        raise RuntimeError(
            "external connector security gates failed "
            f"(gates={','.join(failed_gates)}; post_status={post_status}; "
            f"isolation_status={isolation_status})"
        )

    result: dict[str, Any] = {
        "schema": "agent-economy-external-connector-rehearsal-v1",
        "connector": args.connector,
        "execution_scope": "local",
        "status": "passed",
        "candidate": {"commit": args.commit, "tree": args.tree},
        "client": {
            "implementation": "python_protocol_probe",
            "name": args.client_name,
            "version": args.client_version,
        },
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
            "passed": revocation_passed,
            "post_revoke_status": post_status,
        },
        "cross_tenant_isolation": {
            "passed": isolation_passed,
            "status": isolation_status,
        },
        "notes": (
            "Local urllib protocol rehearsal only; it is ineligible for native "
            "external connector release gates."
        ),
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
    return result


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    """Finalize native evidence or run an explicitly ineligible rehearsal."""
    if args.connector not in CONNECTORS:
        raise ValueError("unsupported connector")
    if not _public_https_origin(args.base_url):
        raise ValueError("base URL must be a public HTTPS origin")
    if not is_lowercase_hex(args.commit, 40) or not is_lowercase_hex(args.tree, 40):
        raise ValueError("candidate commit and tree must be lowercase 40-character hex IDs")
    if not _resolved_origin_is_public(args.base_url):
        raise ValueError("base URL must resolve only to public network addresses")
    native_path = getattr(args, "native_result", None)
    native = None
    native_sha256 = None
    if native_path is not None:
        native, native_sha256 = load_native_result_file(
            native_path,
            expected_candidate={"commit": args.commit, "tree": args.tree},
            expected_connector=args.connector,
        )
        expected_origin_hash = hosted_origin_sha256(args.base_url)
        if native["hosted_origin_sha256"] != expected_origin_hash:
            raise ValueError("native result hosted origin differs from --base-url")
    credential = load_credential_file(args.credential_file)
    revoker = _CredentialRevoker(args.base_url, credential)
    flow_failed = False
    try:
        if native is not None and native_sha256 is not None:
            return _run_native_acceptance(
                args,
                credential,
                revoker,
                native,
                native_sha256,
            )
        return _run_authenticated_acceptance(args, credential, revoker)
    except BaseException:
        flow_failed = True
        raise
    finally:
        if not revoker.revoked:
            try:
                revoker.revoke()
            except BaseException as revoke_exc:
                if not flow_failed:
                    raise
                print(
                    "warning: credential revocation failed and the credential "
                    "may still be active "
                    f"({type(revoke_exc).__name__})",
                    file=sys.stderr,
                )


def is_lowercase_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Finalize one native hosted connector result, or run an explicitly "
            "ineligible urllib rehearsal."
        )
    )
    parser.add_argument("--connector", required=True, choices=sorted(CONNECTORS))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--output", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--native-result",
        help="sanitized JSON emitted by the selected native client",
    )
    mode.add_argument(
        "--rehearsal",
        action="store_true",
        help="run the urllib protocol probe with local, release-ineligible scope",
    )
    parser.add_argument(
        "--release-gate-output",
        help="generic release-gate wrapper path; required with --native-result",
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--signer-label", required=True)
    parser.add_argument("--server-operator", required=True)
    parser.add_argument("--client-name", default="urllib-protocol-rehearsal")
    parser.add_argument("--client-version", default="1")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    if args.timeout < 10 or args.timeout > 900:
        parser.error("--timeout must be between 10 and 900 seconds")
    if args.native_result and not args.release_gate_output:
        parser.error("--release-gate-output is required with --native-result")
    if args.rehearsal and args.release_gate_output:
        parser.error("--release-gate-output is not valid with --rehearsal")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        release_paths = None
        if args.native_result:
            root = Path(args.repo_root).resolve()
            native_path = Path(args.native_result).resolve()
            detailed_path = Path(args.output).resolve()
            release_path = Path(args.release_gate_output).resolve()
            try:
                native_relative = native_path.relative_to(root).as_posix()
                detailed_relative = detailed_path.relative_to(root).as_posix()
                release_path.relative_to(root)
            except ValueError:
                raise ValueError(
                    "native, detailed, and release receipt paths must stay under --repo-root"
                ) from None
            if len({native_path, detailed_path, release_path}) != 3:
                raise ValueError(
                    "native, detailed, and release receipt paths must be distinct"
                )
            if detailed_path.is_symlink() or release_path.is_symlink():
                raise ValueError("release receipt outputs must not be symlinks")
            release_paths = (
                native_path,
                native_relative,
                detailed_path,
                detailed_relative,
                release_path,
            )
        result = run_acceptance(args)
        output = write_external_connector_receipt(result, args.output)
        release_output = None
        if args.native_result:
            if release_paths is None:
                raise RuntimeError("native release paths were not validated")
            (
                native_path,
                native_relative,
                detailed_path,
                detailed_relative,
                release_path,
            ) = release_paths
            client = result["client"]
            environment = {
                "os": platform.system().lower(),
                "architecture": platform.machine().lower(),
                "tool_versions": {
                    client["implementation"]: client["version"],
                },
                "hosted_origin_sha256": result["hosted_origin_sha256"],
            }
            wrapper = build_external_release_gate_receipt(
                result,
                detailed_artifact={
                    "path": detailed_relative,
                    "sha256": hashlib.sha256(detailed_path.read_bytes()).hexdigest(),
                },
                native_artifact={
                    "path": native_relative,
                    "sha256": hashlib.sha256(native_path.read_bytes()).hexdigest(),
                },
                environment=environment,
                verifier={
                    "name": "external-connector-finalizer",
                    "version": "2",
                },
                reviewer_notes="Native result and security verification retained by hash.",
            )
            release_output = write_external_connector_receipt(wrapper, release_path)
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
        "release_gate_receipt": str(release_output) if release_output else None,
        "execution_scope": result["execution_scope"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
