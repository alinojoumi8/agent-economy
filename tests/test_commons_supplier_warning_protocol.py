from research.commons_supplier_warning_experiment import run_protocol


def test_commons_supplier_warning_three_branch_protocol(tmp_path):
    result = run_protocol(tmp_path / "protocol")
    assert result["quantities"] == {
        "control-none": 10,
        "control-neutral": 10,
        "treatment-warning": 5,
    }
    assert result["receipts"]["control-none"]["post_count"] == 0
    assert result["receipts"]["control-none"]["exposure_count"] == 0
    assert result["receipts"]["control-neutral"]["read_count"] == 1
    treatment = result["receipts"]["treatment-warning"]
    assert treatment["read_count"] == treatment["exposure_count"] == 1
    assert treatment["causal_relations"] == [
        "delivered", "observed", "triggered", "triggered", "settled", "motivated"]
