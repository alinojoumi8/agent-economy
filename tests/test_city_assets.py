import copy
import json
from pathlib import Path

import pytest

from city.validate_assets import AssetValidationError, validate_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "city" / "assets" / "catalog.json"


def write_catalog(tmp_path, payload):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload))
    return path


def test_committed_asset_catalog_and_files_are_valid():
    result = validate_catalog(CATALOG)
    assert result["assets"] == 7
    assert result["variants"] == 14
    assert result["bytes"] <= 10_000_000


def test_duplicate_asset_keys_are_rejected(tmp_path):
    payload = json.loads(CATALOG.read_text())
    payload["assets"].append(copy.deepcopy(payload["assets"][0]))
    with pytest.raises(AssetValidationError, match="duplicate asset key"):
        validate_catalog(write_catalog(tmp_path, payload), check_files=False)


def test_oversized_variant_is_rejected(tmp_path):
    payload = json.loads(CATALOG.read_text())
    payload["assets"][0]["variants"]["low"]["bytes"] = 2_000_001
    with pytest.raises(AssetValidationError, match="oversized"):
        validate_catalog(write_catalog(tmp_path, payload), check_files=False)


@pytest.mark.parametrize("bad_dimensions", [[1, float("nan"), 1], [1, 0, 1], [1, 2]])
def test_invalid_dimensions_are_rejected(tmp_path, bad_dimensions):
    payload = json.loads(CATALOG.read_text())
    payload["assets"][0]["dimensions"] = bad_dimensions
    with pytest.raises(AssetValidationError, match="dimensions"):
        validate_catalog(write_catalog(tmp_path, payload), check_files=False)


def test_exporter_hash_drift_is_rejected_before_loading_assets(tmp_path):
    payload = json.loads(CATALOG.read_text())
    payload['generator']['source_sha256'] = '0' * 64
    with pytest.raises(AssetValidationError, match='exporter source hash mismatch'):
        validate_catalog(write_catalog(tmp_path, payload))
