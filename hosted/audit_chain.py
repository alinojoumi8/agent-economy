"""Canonical hashing and verification for hosted control-plane audit rows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


GENESIS_AUDIT_HASH = "0" * 64
_HASH_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class AuditChainVerification:
    valid: bool
    tenant_id: str | None
    chained_entries: int
    legacy_entries: int
    error: str | None = None
    failed_sequence: int | None = None


def _value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    try:
        value = row[name]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _canonical_timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("audit created_at must be ISO-8601") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("audit created_at must be timezone-aware")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _details(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("audit details_json must be valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("audit details_json must be an object")
    # Round-trip rejects non-JSON values and detaches caller-owned mappings.
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise ValueError("audit details_json must be an object")
    return loaded


def canonical_audit_entry(entry: Any) -> bytes:
    """Return the exact tenant-chain hash preimage for one audit row."""

    sequence = int(_value(entry, "tenant_sequence"))
    if sequence <= 0:
        raise ValueError("audit tenant_sequence must be positive")
    previous_hash = str(_value(entry, "previous_entry_hash", ""))
    if _HASH_RE.fullmatch(previous_hash) is None:
        raise ValueError("audit previous_entry_hash must be lowercase SHA-256")
    payload = {
        "version": 1,
        "tenant_id": str(_value(entry, "tenant_id")),
        "tenant_sequence": sequence,
        "previous_entry_hash": previous_hash,
        "actor_user_id": (
            str(_value(entry, "actor_user_id"))
            if _value(entry, "actor_user_id") is not None else None
        ),
        "action": str(_value(entry, "action")),
        "target_type": str(_value(entry, "target_type")),
        "target_id": (
            str(_value(entry, "target_id"))
            if _value(entry, "target_id") is not None else None
        ),
        "request_id": (
            str(_value(entry, "request_id"))
            if _value(entry, "request_id") is not None else None
        ),
        "details": _details(_value(entry, "details_json", {})),
        "created_at": _canonical_timestamp(_value(entry, "created_at")),
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def audit_entry_hash(entry: Any) -> str:
    return hashlib.sha256(canonical_audit_entry(entry)).hexdigest()


def build_chained_audit_entry(
    *,
    tenant_id: str,
    tenant_sequence: int,
    previous_entry_hash: str,
    actor_user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    request_id: str | None,
    details: Mapping[str, Any] | None,
    created_at: datetime,
) -> dict[str, Any]:
    entry = {
        "tenant_id": str(tenant_id),
        "tenant_sequence": int(tenant_sequence),
        "previous_entry_hash": str(previous_entry_hash),
        "actor_user_id": (
            str(actor_user_id) if actor_user_id is not None else None),
        "action": str(action),
        "target_type": str(target_type),
        "target_id": str(target_id) if target_id is not None else None,
        "request_id": str(request_id) if request_id is not None else None,
        "details_json": _details(details),
        "created_at": created_at,
    }
    entry["entry_hash"] = audit_entry_hash(entry)
    return entry


def verify_audit_chain(
    entries: Iterable[Any],
    *,
    tenant_id: str | None = None,
) -> AuditChainVerification:
    """Verify one tenant's rows in ascending chain order.

    Rows with all three chain columns null predate migration 003. They are
    reported as legacy and cannot be authenticated retroactively.
    """

    expected_tenant = str(tenant_id) if tenant_id is not None else None
    expected_sequence = 1
    expected_previous = GENESIS_AUDIT_HASH
    chained = 0
    legacy = 0
    for row in entries:
        sequence = _value(row, "tenant_sequence")
        previous = _value(row, "previous_entry_hash")
        entry_hash = _value(row, "entry_hash")
        chain_values = (sequence, previous, entry_hash)
        if all(value is None for value in chain_values):
            legacy += 1
            continue
        if any(value is None for value in chain_values):
            return AuditChainVerification(
                False, expected_tenant, chained, legacy,
                "partially chained audit row", None)
        row_tenant = str(_value(row, "tenant_id"))
        if expected_tenant is None:
            expected_tenant = row_tenant
        if row_tenant != expected_tenant:
            return AuditChainVerification(
                False, expected_tenant, chained, legacy,
                "audit row crosses the requested tenant boundary",
                int(sequence),
            )
        if int(sequence) != expected_sequence:
            return AuditChainVerification(
                False, expected_tenant, chained, legacy,
                (
                    f"audit sequence expected {expected_sequence} "
                    f"but found {int(sequence)}"
                ),
                int(sequence),
            )
        if str(previous) != expected_previous:
            return AuditChainVerification(
                False, expected_tenant, chained, legacy,
                "audit previous hash does not match the prior entry",
                int(sequence),
            )
        observed_hash = str(entry_hash)
        if _HASH_RE.fullmatch(observed_hash) is None:
            return AuditChainVerification(
                False, expected_tenant, chained, legacy,
                "audit entry hash is not lowercase SHA-256",
                int(sequence),
            )
        try:
            computed_hash = audit_entry_hash(row)
        except (TypeError, ValueError) as exc:
            return AuditChainVerification(
                False, expected_tenant, chained, legacy,
                f"audit entry is not canonical: {exc}",
                int(sequence),
            )
        if observed_hash != computed_hash:
            return AuditChainVerification(
                False, expected_tenant, chained, legacy,
                "audit entry hash does not match canonical content",
                int(sequence),
            )
        chained += 1
        expected_sequence += 1
        expected_previous = observed_hash
    return AuditChainVerification(
        True, expected_tenant, chained, legacy)
