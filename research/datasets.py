"""Pinned dataset manifests with fail-closed verification and explicit refresh."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

import yaml

from engine.store import Store


class DatasetError(ValueError):
    pass


REQUIRED_FIELDS = {
    "key", "source_url", "release_date", "vintage_date", "retrieval_time",
    "checksum_sha256", "transform_version", "usage_terms", "snapshot_path",
}


RefreshTransform = Callable[[dict[str, Any], bytes], bytes]


def sha256_path(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _prepare_refresh_item(item: dict[str, Any], retrieval_time: str) -> dict[str, Any]:
    """Return refresh metadata without mutating the manifest before all downloads pass."""
    prepared = dict(item)
    policy = str(item.get("refresh_vintage_policy", "preserve")).strip().lower()
    if policy == "retrieval_date":
        prepared["vintage_date"] = retrieval_time[:10]
    elif policy != "preserve":
        raise DatasetError(
            f"{item.get('key', '<unknown>')}: unsupported refresh_vintage_policy "
            f"{policy or '<missing>'}")
    return prepared


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    manifest["_path"] = str(manifest_path)
    manifest["_root"] = str(manifest_path.parent)
    if int(manifest.get("manifest_version", 0)) != 1:
        raise DatasetError("dataset manifest_version must be 1")
    if not isinstance(manifest.get("datasets"), list):
        raise DatasetError("datasets must be a list")
    return manifest


def verify_manifest(path: str | Path, *, require_all: bool = False) -> dict[str, Any]:
    manifest = load_manifest(path)
    results, errors = [], []
    for item in manifest["datasets"]:
        missing = sorted(REQUIRED_FIELDS - set(item))
        required = bool(item.get("required", False) or require_all)
        if missing:
            errors.append(f"{item.get('key', '<unknown>')}: missing {', '.join(missing)}")
            continue
        if not str(item["release_date"]).strip() or not str(item["vintage_date"]).strip():
            errors.append(f"{item['key']}: release_date and vintage_date are mandatory")
            continue
        snapshot_text = str(item.get("snapshot_path", "")).strip()
        if not snapshot_text:
            status = "optional-unpinned"
            if required:
                errors.append(f"{item['key']}: required pinned snapshot is missing")
            results.append({"key": item["key"], "status": status})
            continue
        snapshot = (Path(manifest["_root"]) / snapshot_text).resolve()
        if not snapshot.exists():
            errors.append(f"{item['key']}: snapshot not found: {snapshot}")
            continue
        actual = sha256_path(snapshot)
        expected = str(item["checksum_sha256"]).lower()
        if len(expected) != 64 or actual != expected:
            errors.append(f"{item['key']}: checksum mismatch (expected {expected}, got {actual})")
            continue
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        if payload.get("vintage_date") != item["vintage_date"]:
            errors.append(f"{item['key']}: snapshot vintage does not match manifest")
            continue
        results.append({"key": item["key"], "status": "verified", "path": str(snapshot),
                        "checksum_sha256": actual, "targets": len(payload.get("targets", []))})
    if errors:
        raise DatasetError("; ".join(errors))
    return {"ok": True, "manifest": str(Path(path).resolve()), "datasets": results}


def ingest_manifest(store: Store, path: str | Path) -> dict[str, Any]:
    verification = verify_manifest(path)
    manifest = load_manifest(path)
    for item in manifest["datasets"]:
        if not item.get("snapshot_path"):
            continue
        snapshot = (Path(manifest["_root"]) / item["snapshot_path"]).resolve()
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        store.execute("DELETE FROM dataset_manifests WHERE dataset_key=?", (item["key"],))
        manifest_id = store.insert(
            "dataset_manifests", dataset_key=item["key"], source_url=item["source_url"],
            retrieval_time=item["retrieval_time"], release_date=item["release_date"],
            vintage_date=item["vintage_date"], checksum_sha256=item["checksum_sha256"],
            transform_version=item["transform_version"], usage_terms=item["usage_terms"],
            snapshot_path=str(snapshot), status="verified",
            metadata_json=json.dumps(item.get("metadata", {}), sort_keys=True))
        for target in payload.get("targets", []):
            store.insert(
                "calibration_targets", dataset_manifest_id=manifest_id,
                target_key=target["key"], value_json=json.dumps(target["value"], sort_keys=True),
                unit=target["unit"], dimensions_json=json.dumps(target.get("dimensions", {}), sort_keys=True))
    store.commit()
    return verification


def _fred_monthly_targets_v1(item: dict[str, Any], body: bytes) -> bytes:
    """Convert a FRED monthly CSV into the repository's pinned target JSON."""
    key = str(item.get("key", "<unknown>"))
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        raise DatasetError(f"{key}: fred-monthly-targets-v1 requires metadata")
    series_id = str(metadata.get("series_id", "")).strip()
    target_key_prefix = str(metadata.get("target_key_prefix", "")).strip()
    target_months = metadata.get("target_months")
    if series_id != "FEDFUNDS" or target_key_prefix != "policy_rate":
        raise DatasetError(
            f"{key}: fred-monthly-targets-v1 only supports FEDFUNDS policy_rate")
    if not isinstance(target_months, list) or not target_months:
        raise DatasetError(
            f"{key}: fred-monthly-targets-v1 requires target_months")

    months = [str(month) for month in target_months]
    if (len(months) != len(set(months))
            or any(not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month)
                   for month in months)):
        raise DatasetError(f"{key}: target_months must be unique YYYY-MM values")

    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError(f"{key}: FRED CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != ["observation_date", series_id]:
        raise DatasetError(
            f"{key}: unexpected FRED CSV columns {reader.fieldnames!r}")

    selected: dict[str, int | float] = {}
    for row in reader:
        observation_date = str(row.get("observation_date", "")).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", observation_date):
            raise DatasetError(f"{key}: invalid FRED observation_date")
        month = observation_date[:7]
        if month not in months:
            continue
        if month in selected:
            raise DatasetError(f"{key}: duplicate FRED observation for {month}")
        raw_value = str(row.get(series_id, "")).strip()
        try:
            value = Decimal(raw_value)
        except InvalidOperation as exc:
            raise DatasetError(f"{key}: invalid FRED value for {month}") from exc
        if not value.is_finite():
            raise DatasetError(f"{key}: invalid FRED value for {month}")
        numeric = int(value) if value == value.to_integral() else float(value)
        if isinstance(numeric, float) and not math.isfinite(numeric):
            raise DatasetError(f"{key}: invalid FRED value for {month}")
        selected[month] = numeric

    missing = [month for month in months if month not in selected]
    if missing:
        raise DatasetError(f"{key}: FRED CSV is missing {', '.join(missing)}")
    payload = {
        "dataset_key": key,
        "series_id": series_id,
        "targets": [{
            "dimensions": {"frequency": "monthly"},
            "key": f"{target_key_prefix}.{month}",
            "unit": "percent",
            "value": selected[month],
        } for month in months],
        "vintage_date": str(item["vintage_date"]),
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")


REFRESH_TRANSFORMS: dict[str, RefreshTransform] = {
    "fred-monthly-targets-v1": _fred_monthly_targets_v1,
}


def _refresh_transform(item: dict[str, Any]) -> RefreshTransform:
    version = str(item.get("transform_version", ""))
    transform = REFRESH_TRANSFORMS.get(version)
    if transform is None:
        raise DatasetError(
            f"{item.get('key', '<unknown>')}: unsupported refresh transform_version "
            f"{version or '<missing>'}")
    return transform


def refresh_datasets(path: str | Path) -> dict[str, Any]:
    """Networked refresh. This function is never called by normal runs or tests."""
    manifest = load_manifest(path)
    retrieval_time = _utc_now().isoformat()
    refreshed, skipped, candidates = [], [], []
    for item in manifest["datasets"]:
        if item.get("refresh_mode", "get") != "get" or not item.get("snapshot_path"):
            skipped.append({"key": item["key"], "reason": "manual adapter or no snapshot path"})
            continue
        candidates.append((
            item,
            _prepare_refresh_item(item, retrieval_time),
            _refresh_transform(item),
        ))

    pending = []
    for item, prepared, transform in candidates:
        url = str(item.get("refresh_url") or item["source_url"])
        request = Request(url, headers={"User-Agent": "Agent Economy research contact: repository maintainers"})
        with urlopen(request, timeout=60) as response:
            body = response.read()
        transformed = transform(prepared, body)
        target = (Path(manifest["_root"]) / item["snapshot_path"]).resolve()
        pending.append((item, prepared, target, transformed))

    for item, prepared, target, transformed in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(transformed)
        item["vintage_date"] = prepared["vintage_date"]
        item["checksum_sha256"] = sha256_path(target)
        item["retrieval_time"] = retrieval_time
        refreshed.append({"key": item["key"], "path": str(target),
                          "checksum_sha256": item["checksum_sha256"],
                          "vintage_date": item["vintage_date"]})
    output = {k: v for k, v in manifest.items() if not k.startswith("_")}
    Path(path).write_text(yaml.safe_dump(output, sort_keys=False), encoding="utf-8")
    return {"refreshed": refreshed, "skipped": skipped,
            "verification": verify_manifest(path)}
