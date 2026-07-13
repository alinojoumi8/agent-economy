"""Pinned dataset manifests with fail-closed verification and explicit refresh."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import yaml

from engine.store import Store


class DatasetError(ValueError):
    pass


REQUIRED_FIELDS = {
    "key", "source_url", "release_date", "vintage_date", "retrieval_time",
    "checksum_sha256", "transform_version", "usage_terms", "snapshot_path",
}


def sha256_path(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def refresh_datasets(path: str | Path) -> dict[str, Any]:
    """Networked refresh. This function is never called by normal runs or tests."""
    manifest = load_manifest(path)
    refreshed, skipped = [], []
    for item in manifest["datasets"]:
        if item.get("refresh_mode", "get") != "get" or not item.get("snapshot_path"):
            skipped.append({"key": item["key"], "reason": "manual adapter or no snapshot path"})
            continue
        url = str(item.get("refresh_url") or item["source_url"])
        request = Request(url, headers={"User-Agent": "Agent Economy research contact: repository maintainers"})
        with urlopen(request, timeout=60) as response:
            body = response.read()
        target = (Path(manifest["_root"]) / item["snapshot_path"]).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        item["checksum_sha256"] = sha256_path(target)
        item["retrieval_time"] = datetime.now(timezone.utc).isoformat()
        refreshed.append({"key": item["key"], "path": str(target),
                          "checksum_sha256": item["checksum_sha256"]})
    output = {k: v for k, v in manifest.items() if not k.startswith("_")}
    Path(path).write_text(yaml.safe_dump(output, sort_keys=False), encoding="utf-8")
    return {"refreshed": refreshed, "skipped": skipped,
            "verification": verify_manifest(path)}
