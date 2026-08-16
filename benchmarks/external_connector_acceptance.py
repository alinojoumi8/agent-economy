"""Pure validation and durable writing for independent connector receipts."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit


SCHEMA = "agent-economy-external-connector-v2"
NATIVE_RESULT_SCHEMA = "agent-economy-native-connector-result-v1"
RELEASE_GATE_SCHEMA = "agent-economy-release-gate-v1"
CONNECTORS = {"independent_mcp", "hermes", "openclaw", "python", "typescript"}
CONNECTOR_GATE_IDS = {
    "independent_mcp": "independent_mcp",
    "hermes": "hermes_connector",
    "openclaw": "openclaw_connector",
    "python": "python_connector",
    "typescript": "typescript_connector",
}
GATE_CONNECTORS = {gate_id: connector for connector, gate_id in CONNECTOR_GATE_IDS.items()}
CONNECTOR_IMPLEMENTATIONS = {
    "independent_mcp": "official_mcp_conformance",
    "hermes": "hermes_cli",
    "openclaw": "openclaw_cli",
    "python": "agent_economy_python_client",
    "typescript": "agent_economy_typescript_client",
}
MCP_PROTOCOL_VERSION = "2025-11-25"
_NATIVE_RESULT_FIELDS = {
    "schema",
    "connector",
    "execution_scope",
    "status",
    "candidate",
    "client",
    "hosted_origin_sha256",
    "tenant_id",
    "run_id",
    "actor_id",
    "scopes",
    "started_at",
    "ended_at",
    "public_exchange",
    "executed_receipts",
    "notes",
}
_EXTERNAL_RECEIPT_FIELDS = _NATIVE_RESULT_FIELDS | {
    "signer",
    "server_operator",
    "base_url",
    "revocation",
    "cross_tenant_isolation",
}
_CONNECTOR_PROOF_FIELDS = {
    "independent_mcp": "discovery",
    "hermes": "wakes",
    "openclaw": "wakes",
    "python": "flows",
    "typescript": "flows",
}
_RELEASE_ENVIRONMENT_FIELDS = {
    "os",
    "architecture",
    "tool_versions",
    "deployment_digest",
    "hosted_origin_sha256",
}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_TEXT = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]+", re.IGNORECASE),
    re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
)
_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "client_secret",
    "api_key",
    "private_payload",
    "private_body",
    "private_reasoning",
    "raw_request",
    "raw_response",
    "oauth_code",
}


class ExternalConnectorReceiptError(ValueError):
    """An external connector receipt is unsafe or ineligible."""


def _fail(message: str) -> None:
    raise ExternalConnectorReceiptError(message)


def _hex(value: Any, length: int) -> bool:
    if not isinstance(value, str):
        return False
    return bool((_HEX_40 if length == 40 else _HEX_64).fullmatch(value))


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _sensitive_path(value: Any, path: tuple[str, ...] = ()) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            current = (*path, str(key))
            if normalized in _SENSITIVE_KEYS:
                qualifier = "private" if normalized.startswith("private") else "sensitive"
                return f"{qualifier} receipt field {'.'.join(current)} is forbidden"
            nested = _sensitive_path(item, current)
            if nested:
                return nested
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested = _sensitive_path(item, (*path, str(index)))
            if nested:
                return nested
    elif isinstance(value, str):
        for pattern in _SECRET_TEXT:
            if pattern.search(value):
                return f"sensitive receipt text at {'.'.join(path)} is forbidden"
    return None


def _public_https_origin(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        hostname_value = parsed.hostname
        invalid = (
            parsed.scheme != "https"
            or not hostname_value
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        )
    except ValueError:
        return False
    if invalid:
        return False
    hostname = str(hostname_value).lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return "." in hostname
    if isinstance(address, ipaddress.IPv6Address):
        embedded = (
            address.ipv4_mapped
            or address.sixtofour
            or (address.teredo[1] if address.teredo else None)
        )
        if embedded is not None:
            address = embedded
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def hosted_origin_sha256(value: Any) -> str:
    """Return the canonical public-origin hash shared by clients and finalizer."""
    if not _public_https_origin(value):
        _fail("base_url must be a public HTTPS origin")
    content = (
        json.dumps(
            {"origin": value.rstrip("/")},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _require_hash_record(value: Any, *, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "request_sha256",
        "response_sha256",
    }:
        _fail(f"{label} must be an object")
    if not _hex(value.get("request_sha256"), 64):
        _fail(f"{label} request hash is invalid")
    if not _hex(value.get("response_sha256"), 64):
        _fail(f"{label} response hash is invalid")


def _validate_candidate_identity(
    candidate: Any, *, expected_candidate: dict[str, str]
) -> None:
    if not isinstance(candidate, dict) or not all(
        _hex(candidate.get(field), 40) for field in ("commit", "tree")
    ):
        _fail("candidate identity is invalid")
    if candidate != {
        "commit": expected_candidate.get("commit"),
        "tree": expected_candidate.get("tree"),
    }:
        _fail("candidate identity differs from the expected candidate")


def _validate_client_provenance(
    client: Any,
    *,
    connector: str,
    require_native_evidence_hash: bool,
) -> None:
    required_fields = {
        "implementation",
        "name",
        "version",
        "executable_sha256",
        "invocation_sha256",
    }
    if require_native_evidence_hash:
        required_fields.add("native_evidence_sha256")
    if not isinstance(client, dict) or set(client) != required_fields or not all(
        _nonempty(client.get(field)) for field in ("name", "version")
    ):
        _fail("client provenance fields are incomplete or unbounded")
    expected_implementation = CONNECTOR_IMPLEMENTATIONS[connector]
    if client.get("implementation") != expected_implementation:
        _fail("client implementation does not match the selected connector")
    for field in ("executable_sha256", "invocation_sha256"):
        if not _hex(client.get(field), 64):
            _fail(f"client {field} is invalid")
    if require_native_evidence_hash and not _hex(
        client.get("native_evidence_sha256"), 64
    ):
        _fail("client native_evidence_sha256 is invalid")


def _validate_behavioral_proof(receipt: dict[str, Any], *, connector: str) -> None:
    if not _hex(receipt.get("hosted_origin_sha256"), 64):
        _fail("hosted origin hash is invalid")
    for field in ("tenant_id", "run_id", "actor_id"):
        if not _nonempty(receipt.get(field)):
            _fail(f"{field} is required")
    scopes = receipt.get("scopes")
    if (
        not isinstance(scopes, list)
        or not scopes
        or any(not _nonempty(scope) for scope in scopes)
        or scopes != sorted(set(scopes))
    ):
        _fail("scopes must be a sorted nonempty unique list")
    started = _timestamp(receipt.get("started_at"))
    ended = _timestamp(receipt.get("ended_at"))
    if started is None or ended is None or ended < started:
        _fail("UTC start/end timestamps are invalid")
    _require_hash_record(receipt.get("public_exchange"), label="public exchange")
    executed = receipt.get("executed_receipts")
    if not isinstance(executed, list) or not executed:
        _fail("at least one executed receipt read is required")
    for item in executed:
        if (
            not isinstance(item, dict)
            or set(item) != {"receipt_id", "sha256", "status"}
            or not _nonempty(item.get("receipt_id"))
            or not _hex(item.get("sha256"), 64)
            or item.get("status") != "executed"
        ):
            _fail("executed receipt IDs, hashes, and status are required")
    if connector == "independent_mcp":
        discovery = receipt.get("discovery")
        if (
            not isinstance(discovery, dict)
            or set(discovery)
            != {
                "passed",
                "protocol_version",
                "authorization_server_sha256",
                "protected_resource_sha256",
                "initialize_sha256",
            }
            or discovery.get("passed") is not True
            or discovery.get("protocol_version") != MCP_PROTOCOL_VERSION
            or not all(
                _hex(discovery.get(field), 64)
                for field in (
                    "authorization_server_sha256",
                    "protected_resource_sha256",
                    "initialize_sha256",
                )
            )
        ):
            _fail("MCP discovery and protected-resource proof is incomplete")
    elif connector in {"hermes", "openclaw"}:
        wakes = receipt.get("wakes")
        if not isinstance(wakes, list) or len(wakes) != 3:
            _fail("Hermes and OpenClaw require exactly three executed wakes")
        for wake in wakes:
            if (
                not isinstance(wake, dict)
                or set(wake)
                != {
                    "target_tick",
                    "submission_id",
                    "receipt_id",
                    "status",
                }
                or not isinstance(wake.get("target_tick"), int)
                or isinstance(wake.get("target_tick"), bool)
                or wake["target_tick"] < 0
                or not _nonempty(wake.get("submission_id"))
                or not _nonempty(wake.get("receipt_id"))
                or wake.get("status") != "executed"
            ):
                _fail(
                    "each Hermes and OpenClaw wake requires a tick, submission ID, "
                    "receipt ID, and executed status"
                )
        if (
            len({wake["target_tick"] for wake in wakes}) != 3
            or len({wake["submission_id"] for wake in wakes}) != 3
            or len({wake["receipt_id"] for wake in wakes}) != 3
        ):
            _fail(
                "Hermes and OpenClaw wakes require unique target ticks, submission IDs, "
                "and receipt IDs"
            )
        if len(executed) != 3:
            _fail("Hermes and OpenClaw require exactly three executed receipt reads")
        if {wake["receipt_id"] for wake in wakes} != {
            item["receipt_id"] for item in executed
        }:
            _fail("Hermes and OpenClaw wake receipts must match executed receipt reads")
    else:
        flows = receipt.get("flows")
        if (
            not isinstance(flows, dict)
            or set(flows) != {"authorized_submit", "receipt_read"}
            or flows.get("authorized_submit") is not True
            or flows.get("receipt_read") is not True
        ):
            _fail("Python and TypeScript require authorized submit/read flows")
    if not isinstance(receipt.get("notes"), str):
        _fail("sanitized notes are required")


def validate_native_connector_result(
    result: Any,
    *,
    expected_candidate: dict[str, str],
    expected_connector: str,
) -> dict[str, Any]:
    """Validate the sanitized output emitted by the selected native client."""
    if not isinstance(result, dict):
        _fail("native connector result must be an object")
    sensitive = _sensitive_path(result)
    if sensitive:
        _fail(sensitive)
    if result.get("schema") != NATIVE_RESULT_SCHEMA:
        _fail("native connector result schema is unsupported")
    connector = result.get("connector")
    if expected_connector not in CONNECTORS or connector != expected_connector:
        _fail("connector identity does not match the expected connector")
    if set(result) != _NATIVE_RESULT_FIELDS | {_CONNECTOR_PROOF_FIELDS[connector]}:
        _fail("native connector result fields are incomplete or unbounded")
    if result.get("execution_scope") != "independent_external":
        _fail("execution_scope must be independent_external")
    if result.get("status") != "passed":
        _fail("native connector status must be passed")
    _validate_candidate_identity(
        result.get("candidate"), expected_candidate=expected_candidate
    )
    _validate_client_provenance(
        result.get("client"),
        connector=connector,
        require_native_evidence_hash=False,
    )
    _validate_behavioral_proof(result, connector=connector)
    return result


def validate_external_connector_receipt(
    receipt: Any,
    *,
    expected_candidate: dict[str, str],
    expected_connector: str,
) -> dict[str, Any]:
    """Validate one sanitized, transport-independent external receipt."""
    if not isinstance(receipt, dict):
        _fail("receipt must be an object")
    sensitive = _sensitive_path(receipt)
    if sensitive:
        _fail(sensitive)
    if receipt.get("schema") != SCHEMA:
        _fail("external connector receipt schema is unsupported")
    connector = receipt.get("connector")
    if expected_connector not in CONNECTORS or connector != expected_connector:
        _fail("connector identity does not match the expected connector")
    if set(receipt) != _EXTERNAL_RECEIPT_FIELDS | {
        _CONNECTOR_PROOF_FIELDS[connector]
    }:
        _fail("external connector receipt fields are incomplete or unbounded")
    if receipt.get("execution_scope") != "independent_external":
        _fail("execution_scope must be independent_external")
    if receipt.get("status") != "passed":
        _fail("external connector status must be passed")
    _validate_candidate_identity(
        receipt.get("candidate"), expected_candidate=expected_candidate
    )
    client = receipt.get("client")
    _validate_client_provenance(
        client,
        connector=connector,
        require_native_evidence_hash=True,
    )
    signer = receipt.get("signer")
    operator = receipt.get("server_operator")
    if (
        not isinstance(signer, dict)
        or set(signer) != {"label", "independent"}
        or not _nonempty(signer.get("label"))
        or signer.get("independent") is not True
        or not _nonempty(operator)
        or signer["label"].casefold() == operator.casefold()
    ):
        _fail("signer must be independent from the server operator")
    if hosted_origin_sha256(receipt.get("base_url")) != receipt.get(
        "hosted_origin_sha256"
    ):
        _fail("hosted origin hash differs from base_url")
    _validate_behavioral_proof(receipt, connector=connector)
    revocation = receipt.get("revocation")
    if (
        not isinstance(revocation, dict)
        or set(revocation) != {"passed", "post_revoke_status"}
        or revocation.get("passed") is not True
        or revocation.get("post_revoke_status") != 401
    ):
        _fail("revocation proof must pass with a post-revoke 401")
    isolation = receipt.get("cross_tenant_isolation")
    if (
        not isinstance(isolation, dict)
        or set(isolation) != {"passed", "status"}
        or isolation.get("passed") is not True
        or isolation.get("status") not in {403, 404}
    ):
        _fail("cross-tenant isolation proof must pass with 403 or 404")
    return receipt


def external_configuration_sha256(receipt: dict[str, Any]) -> str:
    """Hash the bounded connector configuration used by a release wrapper."""
    configuration = {
        "candidate": receipt.get("candidate"),
        "client": receipt.get("client"),
        "connector": receipt.get("connector"),
        "hosted_origin_sha256": receipt.get("hosted_origin_sha256"),
        "scopes": receipt.get("scopes"),
        "server_operator": receipt.get("server_operator"),
        "signer": receipt.get("signer"),
    }
    return hashlib.sha256(_canonical_bytes(configuration)).hexdigest()


def _validated_artifact_record(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        _fail(f"{label} artifact record is invalid")
    path = value.get("path")
    if not _nonempty(path) or "\\" in path:
        _fail(f"{label} artifact path is invalid")
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or path in {".", ""}:
        _fail(f"{label} artifact path is invalid")
    if not _hex(value.get("sha256"), 64):
        _fail(f"{label} artifact hash is invalid")
    return {"path": path, "sha256": value["sha256"]}


def build_external_release_gate_receipt(
    receipt: dict[str, Any],
    *,
    detailed_artifact: dict[str, str],
    native_artifact: dict[str, str],
    environment: dict[str, Any],
    verifier: dict[str, str],
    reviewer_notes: str,
) -> dict[str, Any]:
    """Build the generic release-gate wrapper around native connector evidence."""
    connector = receipt.get("connector")
    candidate = receipt.get("candidate")
    validate_external_connector_receipt(
        receipt,
        expected_candidate=candidate if isinstance(candidate, dict) else {},
        expected_connector=connector if isinstance(connector, str) else "",
    )
    detailed = _validated_artifact_record(detailed_artifact, label="detailed")
    native = _validated_artifact_record(native_artifact, label="native")
    if detailed["sha256"] == native["sha256"]:
        _fail("detailed and native artifacts must be distinct")
    if receipt["client"]["native_evidence_sha256"] != native["sha256"]:
        _fail("native artifact hash differs from the client provenance")
    if (
        not isinstance(environment, dict)
        or not environment
        or set(environment) - _RELEASE_ENVIRONMENT_FIELDS
        or environment.get("hosted_origin_sha256")
        != receipt.get("hosted_origin_sha256")
    ):
        _fail("release environment is unbounded or differs from hosted evidence")
    tool_versions = environment.get("tool_versions")
    implementation = receipt["client"]["implementation"]
    if (
        not isinstance(tool_versions, dict)
        or set(tool_versions) != {implementation}
        or tool_versions.get(implementation) != receipt["client"]["version"]
    ):
        _fail("release environment does not identify the native client version")
    if (
        not isinstance(verifier, dict)
        or set(verifier) != {"name", "version"}
        or not all(_nonempty(verifier.get(field)) for field in ("name", "version"))
    ):
        _fail("release verifier identity is invalid")
    if not isinstance(reviewer_notes, str):
        _fail("release reviewer notes must be a string")
    result = {
        "schema": RELEASE_GATE_SCHEMA,
        "gate_id": CONNECTOR_GATE_IDS[connector],
        "candidate": {**candidate, "dirty": False},
        "execution_scope": "independent_external",
        "status": "passed",
        "started_at": receipt["started_at"],
        "ended_at": receipt["ended_at"],
        "command": f"verify native external connector: {connector}",
        "configuration_sha256": external_configuration_sha256(receipt),
        "environment": environment,
        "summary": f"native {connector} connector evidence passed",
        "artifacts": [detailed, native],
        "verifier": verifier,
        "reviewer_notes": reviewer_notes,
    }
    sensitive = _sensitive_path(result)
    if sensitive:
        _fail(sensitive)
    return result


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_external_connector_receipt(
    result: dict[str, Any], output_path: str | Path
) -> Path:
    """Atomically publish a receipt, refusing any different overwrite."""
    target = Path(output_path)
    content = _canonical_bytes(result)
    if target.is_symlink():
        raise FileExistsError(f"refusing to publish receipt through a symlink: {target}")
    if target.exists():
        if not target.is_file() or target.read_bytes() != content:
            raise FileExistsError(
                f"refusing to overwrite existing receipt with different bytes: {target}"
            )
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != content:
                raise FileExistsError(
                    "refusing to overwrite existing receipt with different bytes: "
                    f"{target}"
                )
        if os.name != "nt":
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
    return target
