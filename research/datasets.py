"""Pinned dataset manifests with fail-closed verification and explicit refresh."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
    dataset_keys: set[str] = set()
    for item in manifest["datasets"]:
        missing = sorted(REQUIRED_FIELDS - set(item))
        required = bool(item.get("required", False) or require_all)
        if missing:
            errors.append(f"{item.get('key', '<unknown>')}: missing {', '.join(missing)}")
            continue
        dataset_key = str(item["key"])
        if dataset_key in dataset_keys:
            errors.append(f"{dataset_key}: duplicate dataset key")
            continue
        dataset_keys.add(dataset_key)
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
        try:
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            _validate_snapshot_payload(item, payload)
        except (json.JSONDecodeError, DatasetError) as exc:
            errors.append(f"{item['key']}: {exc}")
            continue
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
    prepared: list[tuple[dict[str, Any], Path, dict[str, Any]]] = []
    for item in manifest["datasets"]:
        if not item.get("snapshot_path"):
            continue
        snapshot = (Path(manifest["_root"]) / item["snapshot_path"]).resolve()
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        _validate_snapshot_payload(item, payload)
        prepared.append((item, snapshot, payload))
    with store.savepoint("dataset_manifest_ingest"):
        for item, snapshot, payload in prepared:
            old_ids = [int(row["id"]) for row in store.query(
                "SELECT id FROM dataset_manifests WHERE dataset_key=?", (item["key"],))]
            for old_id in old_ids:
                store.execute(
                    "DELETE FROM calibration_targets WHERE dataset_manifest_id=?",
                    (old_id,))
            store.execute(
                "DELETE FROM dataset_manifests WHERE dataset_key=?", (item["key"],))
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
                    target_key=target["key"],
                    value_json=json.dumps(target["value"], sort_keys=True,
                                          allow_nan=False),
                    unit=target["unit"],
                    dimensions_json=json.dumps(
                        target.get("dimensions", {}), sort_keys=True, allow_nan=False))
    store.commit()
    return verification


def _validate_snapshot_payload(item: dict[str, Any], payload: Any) -> None:
    key = str(item.get("key", "<unknown>"))
    if not isinstance(payload, dict):
        raise DatasetError("snapshot must be a JSON object")
    metadata = item.get("metadata")
    if isinstance(metadata, dict) and "source_checksum_sha256" in metadata:
        expected_source = metadata["source_checksum_sha256"]
        if (not isinstance(expected_source, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_source) is None):
            raise DatasetError(
                "manifest source_checksum_sha256 must be a 64-character "
                "lowercase SHA-256")
        actual_source = payload.get("raw_sha256")
        if actual_source is None:
            raise DatasetError(
                "snapshot raw_sha256 is required when the manifest pins a source checksum")
        if (not isinstance(actual_source, str)
                or re.fullmatch(r"[0-9a-f]{64}", actual_source) is None):
            raise DatasetError(
                "snapshot raw_sha256 must be a 64-character lowercase SHA-256")
        if actual_source != expected_source:
            raise DatasetError(
                "snapshot raw_sha256 does not match manifest source_checksum_sha256")
    if payload.get("dataset_key") is not None and payload.get("dataset_key") != key:
        raise DatasetError("snapshot dataset_key does not match manifest")
    if payload.get("vintage_date") != item.get("vintage_date"):
        raise DatasetError("snapshot vintage does not match manifest")
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise DatasetError("snapshot targets must be a list")
    seen: set[tuple[str, str]] = set()
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise DatasetError(f"target {index} must be an object")
        if not {"key", "value", "unit"} <= set(target):
            raise DatasetError(f"target {index} is missing key, value, or unit")
        target_key = str(target["key"]).strip()
        unit = str(target["unit"]).strip()
        dimensions = target.get("dimensions", {})
        if not target_key or not unit or not isinstance(dimensions, dict):
            raise DatasetError(f"target {index} has invalid metadata")
        try:
            dimensions_key = json.dumps(
                dimensions, sort_keys=True, separators=(",", ":"), allow_nan=False)
            json.dumps(target["value"], sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise DatasetError(f"target {index} contains non-finite JSON") from exc
        signature = (target_key, dimensions_key)
        if signature in seen:
            raise DatasetError(f"duplicate target {target_key} with identical dimensions")
        seen.add(signature)


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


def _decimal(value: Any, *, key: str, field: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise DatasetError(f"{key}: invalid {field}") from exc
    if not number.is_finite():
        raise DatasetError(f"{key}: invalid {field}")
    return number


def _rounded_integer(values: list[Decimal]) -> int:
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    return int(mean.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _stable_mode(values: list[int]) -> int:
    counts = Counter(values)
    return min(counts, key=lambda value: (-counts[value], value))


def _scf_household_distributions_v1(item: dict[str, Any], body: bytes) -> bytes:
    """Collapse the SCF's five implicates into public, weighted family records."""
    key = str(item.get("key", "<unknown>"))
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        raise DatasetError(f"{key}: scf-household-distributions-v1 requires metadata")
    member_name = str(metadata.get("archive_member", "SCFP2022.csv"))
    expected_implicates = int(metadata.get("implicates_per_family", 5))
    if expected_implicates <= 0:
        raise DatasetError(f"{key}: implicates_per_family must be positive")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            matches = [name for name in archive.namelist()
                       if name.replace("\\", "/").split("/")[-1].lower()
                       == member_name.lower()]
            if len(matches) != 1:
                raise DatasetError(
                    f"{key}: expected exactly one {member_name} archive member")
            csv_body = archive.read(matches[0])
    except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise DatasetError(f"{key}: invalid SCF ZIP archive") from exc

    try:
        text = csv_body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError(f"{key}: SCF CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    required = {
        "YY1", "Y1", "WGT", "AGE", "KIDS", "OCCAT1", "OCCAT2",
        "INCOME", "LIQ", "NETWORTH",
    }
    missing = sorted(required - set(reader.fieldnames or []))
    if missing:
        raise DatasetError(f"{key}: SCF CSV missing {', '.join(missing)}")

    families: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line_number, row in enumerate(reader, start=2):
        try:
            family_id = int(str(row["YY1"]).strip())
            implicate_id = int(str(row["Y1"]).strip())
            age = int(str(row["AGE"]).strip())
            dependents = int(str(row["KIDS"]).strip())
            work_status = int(str(row["OCCAT1"]).strip())
            occupation_category = int(str(row["OCCAT2"]).strip())
        except (TypeError, ValueError) as exc:
            raise DatasetError(
                f"{key}: invalid SCF integer at line {line_number}") from exc
        if (family_id <= 0 or implicate_id <= 0 or not 18 <= age <= 110
                or dependents < 0 or work_status not in {1, 2, 3, 4}
                or occupation_category not in {1, 2, 3, 4}):
            raise DatasetError(f"{key}: out-of-range SCF value at line {line_number}")
        families[family_id].append({
            "implicate_id": implicate_id,
            "weight": _decimal(row["WGT"], key=key, field="WGT"),
            "age": age,
            "dependents": dependents,
            "work_status": work_status,
            "occupation_category": occupation_category,
            "annual_income_dollars": _decimal(
                row["INCOME"], key=key, field="INCOME"),
            "liquid_assets_dollars": _decimal(row["LIQ"], key=key, field="LIQ"),
            "net_worth_dollars": _decimal(
                row["NETWORTH"], key=key, field="NETWORTH"),
        })

    if not families:
        raise DatasetError(f"{key}: SCF CSV contains no family records")
    records: list[dict[str, Any]] = []
    for family_id in sorted(families):
        rows = families[family_id]
        implicate_ids = {int(row["implicate_id"]) for row in rows}
        if len(rows) != expected_implicates or len(implicate_ids) != expected_implicates:
            raise DatasetError(
                f"{key}: family {family_id} must have {expected_implicates} unique implicates")
        weights = [row["weight"] for row in rows]
        if any(weight <= 0 for weight in weights):
            raise DatasetError(f"{key}: family {family_id} has a non-positive weight")
        records.append({
            "family_id": family_id,
            # Public WGT is divided across the five implicates. Collapsing them
            # therefore sums the weights to retain the published population mass.
            "weight": float(sum(weights, Decimal(0)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP)),
            "age": _rounded_integer([Decimal(row["age"]) for row in rows]),
            "dependents": _rounded_integer([
                Decimal(row["dependents"]) for row in rows]),
            "work_status": _stable_mode([int(row["work_status"]) for row in rows]),
            "occupation_category": _stable_mode([
                int(row["occupation_category"]) for row in rows]),
            "annual_income_dollars": _rounded_integer([
                row["annual_income_dollars"] for row in rows]),
            "liquid_assets_dollars": _rounded_integer([
                row["liquid_assets_dollars"] for row in rows]),
            "net_worth_dollars": _rounded_integer([
                row["net_worth_dollars"] for row in rows]),
        })

    expected_families = metadata.get("expected_public_families")
    if expected_families is not None and len(records) != int(expected_families):
        raise DatasetError(
            f"{key}: expected {expected_families} public families, got {len(records)}")
    payload = {
        "dataset_key": key,
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "targets": [{
            "dimensions": {
                "geography": "United States",
                "implicates_collapsed": expected_implicates,
                "survey_year": int(metadata.get("survey_year", 2022)),
            },
            "key": "household_microdata.records",
            "unit": "family_record_2022_usd",
            "value": {"record_count": len(records), "records": records},
        }],
        "vintage_date": str(item["vintage_date"]),
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")


_SUSB_ATOMIC_SIZE_CLASSES: dict[str, tuple[int, int | None]] = {
    "02": (1, 4), "03": (5, 9), "04": (10, 14), "05": (15, 19),
    "06": (20, 24), "07": (25, 29), "08": (30, 34), "09": (35, 39),
    "10": (40, 49), "11": (50, 74), "12": (75, 99), "13": (100, 149),
    "14": (150, 199), "15": (200, 299), "16": (300, 399),
    "17": (400, 499), "18": (500, 749), "19": (750, 999),
    "31": (1000, 1499), "22": (1500, 1999), "23": (2000, 2499),
    "24": (2500, 4999), "25": (5000, None),
}


def _susb_firm_size_sector_v1(item: dict[str, Any], body: bytes) -> bytes:
    """Extract mutually exclusive national enterprise-size classes from SUSB."""
    key = str(item.get("key", "<unknown>"))
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        raise DatasetError(f"{key}: susb-firm-size-sector-v1 requires metadata")
    encoding = str(metadata.get("encoding", "utf-8-sig"))
    if encoding not in {"utf-8-sig", "windows-1252"}:
        raise DatasetError(f"{key}: unsupported SUSB encoding {encoding}")
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError as exc:
        raise DatasetError(f"{key}: SUSB text must be {encoding}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    required = {
        "STATE", "NAICS", "ENTRSIZE", "FIRM", "EMPL", "EMPLFL_N",
        "ENTRSIZEDSCR",
    }
    missing = sorted(required - set(reader.fieldnames or []))
    if missing:
        raise DatasetError(f"{key}: SUSB data missing {', '.join(missing)}")

    total_firms: int | None = None
    classes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, row in enumerate(reader, start=2):
        if str(row.get("STATE", "")).strip() != "00" \
                or str(row.get("NAICS", "")).strip() != "--":
            continue
        code = str(row.get("ENTRSIZE", "")).strip()
        try:
            firms = int(str(row.get("FIRM", "")).strip())
            employment = int(str(row.get("EMPL", "")).strip())
        except ValueError as exc:
            raise DatasetError(
                f"{key}: invalid SUSB count at line {line_number}") from exc
        if code == "01":
            total_firms = firms
            continue
        if code not in _SUSB_ATOMIC_SIZE_CLASSES:
            continue
        if code in seen:
            raise DatasetError(f"{key}: duplicate SUSB enterprise-size class {code}")
        if firms <= 0 or employment < firms:
            raise DatasetError(f"{key}: invalid SUSB class totals for {code}")
        lower, upper = _SUSB_ATOMIC_SIZE_CLASSES[code]
        representative = int(
            (Decimal(employment) / Decimal(firms)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
        representative = max(lower, representative)
        if upper is not None:
            representative = min(upper, representative)
        classes.append({
            "code": code,
            "description": str(row.get("ENTRSIZEDSCR", "")).strip(),
            "employment": employment,
            "employment_noise_flag": str(row.get("EMPLFL_N", "")).strip(),
            "firm_count": firms,
            "max_employees": upper,
            "min_employees": lower,
            "representative_employees": representative,
        })
        seen.add(code)

    expected_codes = set(_SUSB_ATOMIC_SIZE_CLASSES)
    if seen != expected_codes:
        raise DatasetError(
            f"{key}: missing SUSB enterprise-size classes "
            f"{', '.join(sorted(expected_codes - seen))}")
    classes.sort(key=lambda row: (int(row["min_employees"]), str(row["code"])))
    class_firms = sum(int(row["firm_count"]) for row in classes)
    if total_firms is None or total_firms != class_firms:
        raise DatasetError(
            f"{key}: atomic firm counts {class_firms} do not match total {total_firms}")
    payload = {
        "dataset_key": key,
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "targets": [{
            "dimensions": {
                "geography": "United States",
                "reference_year": int(metadata.get("reference_year", 2022)),
            },
            "key": "firm_size_distribution.classes",
            "unit": "employer_firm_count",
            "value": {"class_count": len(classes), "classes": classes,
                      "total_firms": total_firms},
        }],
        "vintage_date": str(item["vintage_date"]),
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")


REFRESH_TRANSFORMS: dict[str, RefreshTransform] = {
    "fred-monthly-targets-v1": _fred_monthly_targets_v1,
    "scf-household-distributions-v1": _scf_household_distributions_v1,
    "susb-firm-size-sector-v1": _susb_firm_size_sector_v1,
}


def _refresh_transform(item: dict[str, Any]) -> RefreshTransform:
    version = str(item.get("transform_version", ""))
    transform = REFRESH_TRANSFORMS.get(version)
    if transform is None:
        raise DatasetError(
            f"{item.get('key', '<unknown>')}: unsupported refresh transform_version "
            f"{version or '<missing>'}")
    return transform


def refresh_datasets(path: str | Path, *, keys: set[str] | None = None) -> dict[str, Any]:
    """Networked refresh. This function is never called by normal runs or tests."""
    manifest = load_manifest(path)
    available = {str(item.get("key")) for item in manifest["datasets"]}
    unknown = sorted((keys or set()) - available)
    if unknown:
        raise DatasetError(f"unknown dataset key(s): {', '.join(unknown)}")
    retrieval_time = _utc_now().isoformat()
    refreshed, skipped, candidates = [], [], []
    for item in manifest["datasets"]:
        if keys is not None and item.get("key") not in keys:
            skipped.append({"key": item["key"], "reason": "not selected"})
            continue
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
        metadata = prepared.get("metadata")
        expected_source = (str(metadata.get("source_checksum_sha256", "")).lower()
                           if isinstance(metadata, dict) else "")
        actual_source = hashlib.sha256(body).hexdigest()
        if expected_source and actual_source != expected_source:
            raise DatasetError(
                f"{item['key']}: source checksum mismatch "
                f"(expected {expected_source}, got {actual_source})")
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
