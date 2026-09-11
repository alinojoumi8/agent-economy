"""Cross-branch storage and command boundaries for the local integration."""
import pytest

from engine.commands.registry import default_registry
from engine.store import Store
from research.hashing import HashContractError, load_hash_contract, verify_hash_contract


def test_construction_commands_have_distinct_schemas():
    registry = default_registry({"cancel_construction", "cancel_urban_construction"})
    from engine.commands.models import CancelConstruction, CancelUrbanConstruction
    assert registry.resolve("cancel_construction", 13).model is CancelConstruction
    assert registry.resolve("cancel_urban_construction", 13).model is CancelUrbanConstruction
    assert CancelUrbanConstruction.model_validate({
        "type": "cancel_urban_construction", "project_id": 1, "request_key": "cancel-1",
    }).type == "cancel_urban_construction"


def test_urban_storage_is_additive_and_requires_its_hash_contract(tmp_path):
    store = Store(":memory:")
    try:
        store.init_run_meta("urban-hash", 1, {
            "engine_semantics_version": 13, "urban_development": {"enabled": True},
        })
        old_columns = {row[1] for row in store.query("PRAGMA table_info(construction_projects)")}
        urban_columns = {row[1] for row in store.query("PRAGMA table_info(urban_construction_projects)")}
        assert "target_place_type" in old_columns and "parcel_id" not in old_columns
        assert "parcel_id" in urban_columns and "target_place_type" not in urban_columns
        assert verify_hash_contract(store)["contract_id"] == "hash-contract-v9"
        with pytest.raises(HashContractError, match="requires hash-contract-v9"):
            verify_hash_contract(store, load_hash_contract())
        from research.export_bundle import export_bundle, validate_bundle
        bundle = export_bundle(store, tmp_path / "export")
        manifest = validate_bundle(bundle, database=store)
        assert manifest["contract_id"] == "hash-contract-v9"
        assert manifest["schema_version"] == 27
    finally:
        store.close()
