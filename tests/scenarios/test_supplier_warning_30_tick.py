"""Release-gate execution of the frozen 30-tick causal protocol."""
from __future__ import annotations

from research.supplier_warning_experiment import (
    ARMS,
    _prepare_branch,
    canonical_hashes,
    create_common_checkpoint,
    phase_names_for_semantics,
    run_branch,
    run_protocol,
)


def test_frozen_three_arm_protocol_passes_every_declared_outcome(tmp_path):
    receipt = run_protocol(tmp_path / "protocol")
    assert receipt["status"] == "passed"
    assert receipt["quantities"] == {
        "control-none": 10,
        "control-neutral": 10,
        "treatment-warning": 5,
    }
    assert receipt["treatment_effect_units"] == -5
    assert receipt["source_checkpoint_unchanged"] is True
    assert receipt["unrelated_difference_tables"] == []
    assert receipt["branches"]["treatment-warning"]["causal"][
        "warning_chain_edges"] == 5
    assert receipt["branches"]["control-neutral"]["causal"][
        "message_observation_edges"] == 1
    assert receipt["branches"]["control-none"]["causal"][
        "message_observation_edges"] == 0
    for arm in ARMS:
        variants = receipt["variants"][arm]
        assert len({item["authoritative_sha256"] for item in variants.values()}) == 1
        assert len({item["derived_sha256"] for item in variants.values()}) == 1
        assert len({item["projection_sha256"] for item in variants.values()}) == 1
    assert (tmp_path / "protocol" / "protocol-receipt.json").is_file()
    assert (tmp_path / "protocol" / "SUMMARY.md").is_file()


def test_fault_before_and_after_every_semantics8_phase_replays_once(tmp_path):
    common, identity = create_common_checkpoint(tmp_path / "common.db")
    try:
        baseline = tmp_path / "baseline.db"
        _prepare_branch(common, baseline, "control-none")
        run_branch(baseline, arm="control-none", identity=identity)
        from engine.store import Store
        baseline_store = Store(str(baseline), create=False)
        try:
            baseline_hash = canonical_hashes(baseline_store)["authoritative_sha256"]
        finally:
            baseline_store.close()

        for phase in phase_names_for_semantics(8):
            for boundary in ("before", "after"):
                candidate = tmp_path / f"fault-{phase}-{boundary}.db"
                _prepare_branch(common, candidate, "control-none")
                run_branch(
                    candidate, arm="control-none", identity=identity,
                    faults={(6, phase, boundary)},
                )
                candidate_store = Store(str(candidate), create=False)
                try:
                    assert canonical_hashes(candidate_store)[
                        "authoritative_sha256"] == baseline_hash
                    assert candidate_store.scalar(
                        "SELECT COUNT(*) FROM action_proposals "
                        "WHERE tick=6 AND action_type='buy_goods' "
                        "AND validation_status='accepted'") == 1
                    assert candidate_store.scalar(
                        "SELECT COUNT(*) FROM transactions "
                        "WHERE tick=6 AND kind='goods_purchase'") == 1
                finally:
                    candidate_store.close()
    finally:
        common.close()
