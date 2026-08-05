from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import run


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "runs" / "release" / "manifest-v1.template.yaml"


def test_release_evidence_cli_is_offline_and_writes_failed_package(
    tmp_path, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline release reporting invoked an external boundary")

    monkeypatch.setattr(run, "load_config", forbidden)
    monkeypatch.setattr(run, "provider_preflight", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--release-evidence-report",
            str(TEMPLATE),
            "--output",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run.main()

    assert exc.value.code == 5
    payload = json.loads((tmp_path / "release-evidence.json").read_text())
    assert payload["overall_status"] == "failed"
    assert {gate["gate_id"] for gate in payload["gates"]} == {
        "dependency_license_secret_audit",
        "deployment_receipt",
        "hermes_connector",
        "hosted_backup_restore",
        "independent_mcp",
        "openclaw_connector",
        "oracle_v9",
        "production_acceptance",
        "provenance_audit",
        "python_connector",
        "rumor_pilot",
        "semantics10_experiment",
        "semantics10_hosted_ops",
        "semantics10_hosted_ui",
        "tenant_isolation_load",
        "typescript_connector",
    }
    assert (tmp_path / "release-evidence.md").is_file()


@pytest.mark.parametrize(
    "conflict",
    [
        ["--ticks", "1"],
        ["--serve"],
        ["--resume", "run-id"],
        ["--replay", "run-id"],
        ["--fork", "run-id@1"],
        ["--experiment", "experiment.yaml"],
        ["--acceptance-run"],
        ["--oracle-campaign-run"],
        ["--preflight-live"],
        ["--approve-live-inference"],
    ],
)
def test_release_evidence_cli_rejects_runtime_conflicts(
    conflict, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--release-evidence-report",
            str(TEMPLATE),
            "--output",
            str(tmp_path),
            *conflict,
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run.main()

    assert exc.value.code == 2
    assert not (tmp_path / "release-evidence.json").exists()


def test_release_evidence_cli_requires_output(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "--release-evidence-report", str(TEMPLATE)],
    )

    with pytest.raises(SystemExit) as exc:
        run.main()

    assert exc.value.code == 2
