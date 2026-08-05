"""Offline, fail-closed release evidence collection and rendering."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


MANIFEST_SCHEMA = "agent-economy-release-manifest-v1"
RECEIPT_SCHEMA = "agent-economy-release-gate-v1"
EXECUTION_SCOPES = {"local", "live_provider", "independent_external"}
STATUSES = {"passed", "failed", "blocked", "not_run"}
REQUIRED_GATES = {
    "independent_mcp",
    "hermes_connector",
    "openclaw_connector",
    "python_connector",
    "typescript_connector",
    "semantics10_experiment",
    "semantics10_hosted_ui",
    "semantics10_hosted_ops",
    "oracle_v9",
    "rumor_pilot",
    "production_acceptance",
    "provenance_audit",
    "dependency_license_secret_audit",
    "hosted_backup_restore",
    "tenant_isolation_load",
    "deployment_receipt",
}
EXTERNAL_CONNECTOR_GATES = {
    "independent_mcp",
    "hermes_connector",
    "openclaw_connector",
    "python_connector",
    "typescript_connector",
}
_REQUIRED_RECEIPT_FIELDS = {
    "schema",
    "gate_id",
    "candidate",
    "execution_scope",
    "status",
    "started_at",
    "ended_at",
    "command",
    "configuration_sha256",
    "environment",
    "summary",
    "artifacts",
    "verifier",
    "reviewer_notes",
}
_ALLOWED_ENVIRONMENT_FIELDS = {
    "os",
    "architecture",
    "tool_versions",
    "deployment_digest",
    "hosted_origin_sha256",
}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."
    r"[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
)
_SECRET_PATTERNS = (
    re.compile(r"AE_RELEASE_SECRET_CANARY_7b42", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bauthorization\s*[:=]", re.IGNORECASE),
    re.compile(r"\bcookie\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|oauth[_-]?code)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:MINIMAX_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\b", re.IGNORECASE),
    re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{16,}\b"),
    _JWT,
)


def _error(gate_id: str, code: str, message: str) -> dict[str, str]:
    return {"gate_id": gate_id, "code": code, "message": message}


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _published_artifact_mode() -> int:
    current_umask = os.umask(0)
    os.umask(current_umask)
    return 0o666 & ~current_umask


def _valid_candidate(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("commit"), str)
        and isinstance(value.get("tree"), str)
        and bool(_HEX_40.fullmatch(value["commit"]))
        and bool(_HEX_40.fullmatch(value["tree"]))
    )


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def _contains_secret(value: Any) -> bool:
    try:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _safe_file(
    repo_root: Path,
    value: Any,
    *,
    gate_id: str,
    kind: str,
) -> tuple[Path | None, dict[str, str] | None]:
    if not isinstance(value, str) or not value.strip():
        return None, _error(gate_id, f"missing_{kind}", f"{kind} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None, _error(gate_id, "unsafe_path", f"unsafe {kind} path")
    lowered = relative.name.lower()
    if lowered.endswith(("-wal", "-shm", ".sqlite-wal", ".sqlite-shm")):
        return None, _error(gate_id, "sqlite_sidecar", f"{kind} is a SQLite sidecar")
    candidate = repo_root / relative
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None, _error(gate_id, f"missing_{kind}", f"{kind} file is missing")
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return None, _error(gate_id, "unsafe_path", f"{kind} escapes repository root")
    if candidate.is_symlink() or not resolved.is_file():
        return None, _error(gate_id, "unsafe_path", f"{kind} must be a regular file")
    return resolved, None


def load_release_manifest(path: str | Path) -> dict[str, Any]:
    """Load a release manifest without resolving receipts or calling external tools."""
    manifest_path = Path(path)
    try:
        value = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"could not load release manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("release manifest must be a mapping")
    return value


def _validate_artifacts(
    receipt: dict[str, Any],
    *,
    repo_root: Path,
    gate_id: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    collected: list[dict[str, str]] = []
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return [], [_error(gate_id, "missing_artifacts", "receipt has no artifacts")]
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            errors.append(_error(gate_id, "invalid_artifact", f"artifact {index} is invalid"))
            continue
        path_value = artifact.get("path")
        expected = artifact.get("sha256")
        path, path_error = _safe_file(
            repo_root, path_value, gate_id=gate_id, kind="artifact"
        )
        if path_error:
            errors.append(path_error)
            continue
        if not isinstance(expected, str) or not _HEX_64.fullmatch(expected):
            errors.append(_error(gate_id, "invalid_artifact_hash", f"artifact {index} hash is invalid"))
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            errors.append(_error(gate_id, "artifact_read_failed", f"artifact {index} cannot be read"))
            continue
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            errors.append(_error(gate_id, "artifact_hash_mismatch", f"artifact {index} hash differs"))
            continue
        text = raw.decode("utf-8", errors="ignore")
        if text and _contains_secret(text):
            errors.append(_error(gate_id, "secret_detected", f"artifact {index} contains sensitive text"))
        collected.append({"path": str(path_value), "sha256": actual})
    return collected, errors


def _validate_receipt(
    receipt: Any,
    *,
    repo_root: Path,
    gate_id: str,
    candidate: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    fallback = {
        "gate_id": gate_id,
        "execution_scope": "local",
        "status": "not_run",
        "receipt": "",
        "receipt_sha256": "",
        "artifacts": [],
        "summary": "receipt validation failed",
    }
    if not isinstance(receipt, dict):
        return fallback, [_error(gate_id, "invalid_receipt", "receipt must be a mapping")]
    missing = sorted(_REQUIRED_RECEIPT_FIELDS - receipt.keys())
    for field in missing:
        errors.append(_error(gate_id, "missing_receipt_field", f"receipt field {field} is required"))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        errors.append(_error(gate_id, "unknown_receipt_schema", "receipt schema is unsupported"))
    if receipt.get("gate_id") != gate_id:
        errors.append(_error(gate_id, "gate_id_mismatch", "receipt gate ID differs"))
    receipt_candidate = receipt.get("candidate")
    if not _valid_candidate(receipt_candidate):
        errors.append(_error(gate_id, "invalid_candidate", "receipt candidate is invalid"))
    elif (
        receipt_candidate.get("commit") != candidate.get("commit")
        or receipt_candidate.get("tree") != candidate.get("tree")
    ):
        errors.append(_error(gate_id, "candidate_mismatch", "receipt candidate differs from manifest"))
    if not isinstance(receipt_candidate, dict) or receipt_candidate.get("dirty") is not False:
        errors.append(_error(gate_id, "dirty_candidate", "receipt must attest a clean candidate"))
    scope = receipt.get("execution_scope")
    if scope not in EXECUTION_SCOPES:
        errors.append(_error(gate_id, "invalid_execution_scope", "execution scope is invalid"))
    elif gate_id in EXTERNAL_CONNECTOR_GATES and scope != "independent_external":
        errors.append(_error(gate_id, "ineligible_scope", "external connector evidence must be independent"))
    status = receipt.get("status")
    if status not in STATUSES:
        errors.append(_error(gate_id, "invalid_receipt_status", "receipt status is invalid"))
    elif status != "passed":
        errors.append(_error(gate_id, "gate_not_passed", f"gate status is {status}"))
    started = _parse_utc(receipt.get("started_at"))
    ended = _parse_utc(receipt.get("ended_at"))
    if started is None or ended is None or ended < started:
        errors.append(_error(gate_id, "invalid_timestamps", "receipt UTC timestamps are invalid"))
    config_hash = receipt.get("configuration_sha256")
    if not isinstance(config_hash, str) or not _HEX_64.fullmatch(config_hash):
        errors.append(_error(gate_id, "invalid_configuration_hash", "configuration hash is invalid"))
    environment = receipt.get("environment")
    if not isinstance(environment, dict) or not environment:
        errors.append(_error(gate_id, "invalid_environment", "bounded environment identity is required"))
    elif set(environment) - _ALLOWED_ENVIRONMENT_FIELDS:
        errors.append(_error(gate_id, "unbounded_environment", "environment contains unsupported fields"))
    if _contains_secret(receipt):
        errors.append(_error(gate_id, "secret_detected", "receipt contains sensitive text"))
    artifacts, artifact_errors = _validate_artifacts(
        receipt, repo_root=repo_root, gate_id=gate_id
    )
    errors.extend(artifact_errors)
    result = {
        "gate_id": gate_id,
        "execution_scope": scope if scope in EXECUTION_SCOPES else "local",
        "status": status if status in STATUSES else "not_run",
        "started_at": receipt.get("started_at", ""),
        "ended_at": receipt.get("ended_at", ""),
        "configuration_sha256": config_hash if isinstance(config_hash, str) else "",
        "summary": receipt.get("summary", "") if isinstance(receipt.get("summary"), str) else "",
        "artifacts": artifacts,
        "verifier": receipt.get("verifier", {}),
    }
    return result, errors


def collect_release_evidence(
    manifest_path: str | Path,
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Validate every required gate and return a deterministic offline aggregate."""
    root = Path(repo_root).resolve()
    manifest = load_release_manifest(manifest_path)
    errors: list[dict[str, str]] = []
    candidate = manifest.get("candidate")
    if not _valid_candidate(candidate):
        errors.append(_error("_manifest", "invalid_candidate", "manifest candidate is invalid"))
        candidate = {"commit": "", "tree": ""}
    else:
        candidate = {"commit": candidate["commit"], "tree": candidate["tree"]}
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(_error("_manifest", "unknown_manifest_schema", "manifest schema is unsupported"))
    generated_at = manifest.get("generated_at")
    if _parse_utc(generated_at) is None:
        generated_at = "1970-01-01T00:00:00Z"
        errors.append(_error("_manifest", "invalid_generated_at", "manifest generated_at must be UTC"))
    if _contains_secret(manifest):
        errors.append(_error("_manifest", "secret_detected", "manifest contains sensitive text"))
    rows = manifest.get("gates")
    if not isinstance(rows, list):
        rows = []
        errors.append(_error("_manifest", "invalid_gates", "manifest gates must be a list"))
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("gate_id"), str):
            errors.append(_error("_manifest", "invalid_gate", f"manifest gate {index} is invalid"))
            continue
        gate_id = row["gate_id"]
        if gate_id in by_id:
            errors.append(_error(gate_id, "duplicate_gate", "manifest gate ID is duplicated"))
            continue
        if gate_id not in REQUIRED_GATES:
            errors.append(_error(gate_id, "unknown_gate", "manifest gate ID is not required"))
            continue
        by_id[gate_id] = row

    gates: list[dict[str, Any]] = []
    for gate_id in sorted(REQUIRED_GATES):
        row = by_id.get(gate_id)
        if row is None:
            errors.append(_error(gate_id, "missing_gate", "required gate is absent"))
            gates.append({
                "gate_id": gate_id,
                "execution_scope": "local",
                "status": "not_run",
                "receipt": "",
                "receipt_sha256": "",
                "artifacts": [],
                "summary": "required gate is absent",
            })
            continue
        manifest_status = row.get("status")
        if manifest_status not in STATUSES:
            errors.append(_error(gate_id, "invalid_manifest_status", "manifest gate status is invalid"))
        receipt_path, path_error = _safe_file(
            root, row.get("receipt"), gate_id=gate_id, kind="receipt"
        )
        if path_error:
            errors.append(path_error)
            gates.append({
                "gate_id": gate_id,
                "execution_scope": "local",
                "status": manifest_status if manifest_status in STATUSES else "not_run",
                "receipt": row.get("receipt", "") if isinstance(row.get("receipt"), str) else "",
                "receipt_sha256": "",
                "artifacts": [],
                "summary": "receipt is unavailable",
            })
            continue
        expected_hash = row.get("sha256")
        try:
            receipt_raw = receipt_path.read_bytes()
        except OSError:
            errors.append(_error(gate_id, "invalid_receipt", "receipt JSON cannot be loaded"))
            gates.append({
                "gate_id": gate_id,
                "execution_scope": "local",
                "status": manifest_status if manifest_status in STATUSES else "not_run",
                "receipt": row.get("receipt", ""),
                "receipt_sha256": "",
                "artifacts": [],
                "summary": "receipt is unreadable",
            })
            continue
        actual_hash = hashlib.sha256(receipt_raw).hexdigest()
        if not isinstance(expected_hash, str) or not _HEX_64.fullmatch(expected_hash):
            errors.append(_error(gate_id, "invalid_receipt_hash", "manifest receipt hash is invalid"))
        elif actual_hash != expected_hash:
            errors.append(_error(gate_id, "receipt_hash_mismatch", "receipt content hash differs"))
            gates.append({
                "gate_id": gate_id,
                "execution_scope": "local",
                "status": manifest_status if manifest_status in STATUSES else "not_run",
                "receipt": row.get("receipt", ""),
                "receipt_sha256": actual_hash,
                "artifacts": [],
                "summary": "receipt hash mismatch",
            })
            continue
        try:
            receipt = json.loads(
                receipt_raw.decode("utf-8"),
                parse_constant=_reject_non_finite,
            )
        except (UnicodeError, ValueError):
            errors.append(_error(gate_id, "invalid_receipt", "receipt JSON cannot be loaded"))
            receipt = None
        gate, receipt_errors = _validate_receipt(
            receipt, repo_root=root, gate_id=gate_id, candidate=candidate
        )
        gate["receipt"] = row.get("receipt", "")
        gate["receipt_sha256"] = actual_hash
        gates.append(gate)
        errors.extend(receipt_errors)
        if manifest_status in STATUSES and gate["status"] != manifest_status:
            errors.append(_error(gate_id, "status_mismatch", "manifest and receipt statuses differ"))

    errors.sort(key=lambda item: (item["gate_id"], item["code"], item["message"]))
    gates.sort(key=lambda item: item["gate_id"])
    return {
        "schema": MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "candidate": candidate,
        "overall_status": "passed" if not errors else "failed",
        "gates": gates,
        "errors": errors,
    }


def canonical_release_json(result: dict[str, Any]) -> str:
    """Return canonical, reviewer-stable UTF-8 JSON text."""
    return json.dumps(
        result,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def render_release_markdown(result: dict[str, Any]) -> str:
    """Render a deterministic human review of the authoritative JSON result."""
    candidate = result.get("candidate", {})
    lines = [
        "# Agent Economy release evidence",
        "",
        f"- Overall status: `{result.get('overall_status', 'failed')}`",
        f"- Candidate commit: `{candidate.get('commit', '')}`",
        f"- Candidate tree: `{candidate.get('tree', '')}`",
        f"- Generated at: `{result.get('generated_at', '')}`",
        "",
        "| Gate | Scope | Status | Receipt SHA-256 |",
        "|---|---|---|---|",
    ]
    for gate in result.get("gates", []):
        lines.append(
            f"| `{gate.get('gate_id', '')}` | `{gate.get('execution_scope', '')}` | "
            f"`{gate.get('status', '')}` | `{gate.get('receipt_sha256', '')}` |"
        )
    lines.extend(["", "## Validation errors", ""])
    errors = result.get("errors", [])
    if errors:
        for error in errors:
            lines.append(
                f"- `{error.get('gate_id', '')}` / `{error.get('code', '')}`: "
                f"{error.get('message', '')}"
            )
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, _published_artifact_mode())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_release_evidence_package(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    repo_root: str | Path,
) -> tuple[Path, Path]:
    """Collect and atomically publish canonical JSON and Markdown offline."""
    result = collect_release_evidence(manifest_path, repo_root=repo_root)
    target = Path(output_dir)
    json_path = target / "release-evidence.json"
    markdown_path = target / "release-evidence.md"
    _atomic_write(json_path, canonical_release_json(result))
    _atomic_write(markdown_path, render_release_markdown(result))
    return json_path, markdown_path
