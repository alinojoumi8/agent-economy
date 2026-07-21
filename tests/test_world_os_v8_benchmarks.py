import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from benchmarks import provider_smoke
from benchmarks import world_os_v8 as benchmark


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_protocol_manifest_matches_canonical_document_bytes():
    manifest = json.loads(
        (ROOT / "docs" / "world-os" / "protocol-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    protocol = (ROOT / manifest["protocol_path"]).read_text(encoding="utf-8")
    canonical_bytes = protocol.replace("\r\n", "\n").encode("utf-8")
    assert manifest["protocol_hash_canonicalization"] == "utf-8-lf"
    assert hashlib.sha256(canonical_bytes).hexdigest() == manifest["protocol_sha256"]


def test_nearest_rank_hashing_and_process_tree_sampling(tmp_path):
    assert benchmark.nearest_rank([4, 1, 2, 3], 50) == 2
    assert benchmark.nearest_rank([4, 1, 2, 3], 100) == 4
    with pytest.raises(ValueError, match="must not be empty"):
        benchmark.nearest_rank([], 95)
    with pytest.raises(ValueError, match="percentile must"):
        benchmark.nearest_rank([1], 0)
    with pytest.raises(ValueError, match="percentile must"):
        benchmark.nearest_rank([1], 101)

    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"semantics-8")
    assert benchmark.sha256_file(payload) == (
        "31c5271d1037f87560c619e5d78e894717d908e67a6e9f4211d9e0e2914fdb00")

    class Gone:
        def memory_info(self):
            raise psutil.NoSuchProcess(99)

    class Root:
        def children(self, recursive):
            assert recursive is True
            return [SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=7)), Gone()]

        def memory_info(self):
            return SimpleNamespace(rss=11)

    assert benchmark.process_tree_rss_bytes(Root()) == 18


def test_machine_class_and_gate_evaluation_cover_pass_and_failure():
    actual = benchmark.machine_receipt()
    expected = {
        key: actual[key]
        for key in (
            "platform", "processor_signature", "python", "sqlite", "physical_cores",
            "logical_cores", "memory_bytes",
        )
    }
    assert benchmark.machine_class_matches(expected, actual) is True
    expected["logical_cores"] = -1
    assert benchmark.machine_class_matches(expected, actual) is False

    measurements = {
        "interactive_tick_p95_seconds": 1.0,
        "interactive_tick_p99_seconds": 1.0,
        "scale_run_max_seconds": 1.0,
        "peak_process_tree_rss_bytes": 1.0,
        "run_footprint_bytes": 1.0,
        "projection_freshness_p95_seconds": 1.0,
        "route_bootstrap_p95_seconds": 1.0,
        "inbox_p95_seconds": 1.0,
        "causal_p95_seconds": 1.0,
    }
    budgets = {
        "interactive_tick_p95_seconds": 2.0,
        "interactive_tick_p99_seconds": 2.0,
        "scale_run_seconds": 2.0,
        "peak_process_tree_rss_bytes": 2.0,
        "run_footprint_bytes": 2.0,
        "projection_freshness_p95_seconds": 2.0,
        "route_bootstrap_p95_seconds": 2.0,
        "inbox_p95_seconds": 2.0,
        "causal_p95_seconds": 2.0,
    }
    passing = benchmark.evaluate_gates(
        measurements, budgets, canonical_hashes_equal=True, machine_match=True)
    assert all(item["passed"] for item in passing.values())
    failing = benchmark.evaluate_gates(
        {key: 3.0 for key in measurements},
        budgets,
        canonical_hashes_equal=False,
        machine_match=False,
    )
    assert not any(item["passed"] for item in failing.values())


def _small_manifest(tmp_path: Path) -> Path:
    sandbox_root = tmp_path / "sandbox"
    manifest_path = sandbox_root / "benchmarks" / "standard.json"
    manifest_path.parent.mkdir(parents=True)
    for relative in (
        "requirements.lock",
        "dashboard/package-lock.json",
        "docs/world-os/protocol-manifest.json",
        "research/hash-contract-v1.json",
    ):
        destination = sandbox_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)

    manifest = json.loads(
        (ROOT / "benchmarks" / "world-os-v8-standard.json").read_text(encoding="utf-8"))
    manifest["interactive"].update({
        "agents": 4,
        "ticks_per_repetition": 2,
        "repetitions": 1,
    })
    manifest["scale"].update({
        "agents": 10,
        "strategic_agents": 4,
        "periphery_agents": 6,
        "ticks": 3,
        "repetitions": 1,
        "strategic_senders_per_tick": 2,
        "periphery_wakes_per_tick": 2,
    })
    manifest["projections"].update({
        "freshness_samples": 2,
        "route_samples": 3,
    })
    actual = benchmark.machine_receipt()
    manifest["machine_class"].update({
        key: actual[key]
        for key in (
            "platform", "processor_signature", "python", "sqlite", "physical_cores",
            "logical_cores", "memory_bytes",
        )
    })
    for key in manifest["budgets"]:
        manifest["budgets"][key] = 10**12
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_standard_benchmark_runs_production_communication_and_writes_receipt(tmp_path):
    manifest_path = _small_manifest(tmp_path)
    output = tmp_path / "receipt.json"
    receipt = benchmark.run_standard(manifest_path, output)
    assert receipt["status"] == "passed"
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert receipt["schema"] == benchmark.RECEIPT_SCHEMA
    assert len(receipt["manifest_sha256"]) == 64
    assert all(item["passed"] for item in receipt["gates"].values())
    scale = receipt["raw_samples"]["scale_runs"][0]
    assert scale["counts"] == {
        "agents": 10,
        "action_proposals": 12,
        "comm_messages": 12,
        "comm_deliveries": 8,
        "comm_disclosures": 0,
        "memories": 8,
        "causal_links": 20,
        "events": 20,
    }
    assert len(scale["projection_freshness_seconds"]) == 2
    assert len(scale["route_bootstrap_seconds"]) == 3
    assert "INDEX ix_comm_messages_due" in " ".join(
        scale["query_plans"]["due_messages"])


def test_benchmark_rejects_failed_communication():
    class Executor:
        def execute_action(self, *args, **kwargs):
            return {"ok": False, "error": "synthetic"}

    with pytest.raises(RuntimeError, match="communication rejected"):
        benchmark._send_direct(
            Executor(), tick=1, sender=1, recipient=2, body_characters=10)


def test_provider_receipts_cover_unavailable_pass_fail_and_validation(tmp_path):
    assert provider_smoke.missing_provider_keys({}) == ["MINIMAX_API_KEY", "KIMI_API_KEY"]
    assert provider_smoke.missing_provider_keys({
        "MINIMAX_API_KEY": "a", "KIMI_API_KEY": "b",
    }) == []

    unavailable = provider_smoke.build_provider_receipt(
        build_identifier="build", environ={})
    assert unavailable["status"] == "unavailable"
    assert unavailable["credential_values_recorded"] is False
    available_without_run = provider_smoke.build_provider_receipt(
        build_identifier="build",
        environ={"MINIMAX_API_KEY": "a", "KIMI_API_KEY": "b"},
    )
    assert "no completed" in available_without_run["reason"]

    with pytest.raises(ValueError, match="missing fields"):
        provider_smoke.build_provider_receipt(
            build_identifier="build", evidence={}, environ={})

    evidence = {
        "ticks_completed": 10,
        "command_validity_rate": 0.99,
        "persona_consistent_replies": True,
        "causal_decision_influence": True,
        "knowledge_boundary_violations": 0,
        "pause_resume_passed": True,
        "providers": [
            {"provider": "minimax", "model": "MiniMax-M3"},
            {"provider": "kimi", "model": "kimi-k2"},
        ],
    }
    passed = provider_smoke.build_provider_receipt(
        build_identifier="build", evidence=evidence, environ={})
    assert passed["status"] == "passed"
    failed_evidence = dict(evidence)
    failed_evidence.update({
        "ticks_completed": 9,
        "command_validity_rate": 0.5,
        "persona_consistent_replies": False,
        "causal_decision_influence": False,
        "knowledge_boundary_violations": 1,
        "pause_resume_passed": False,
        "providers": [],
    })
    failed = provider_smoke.build_provider_receipt(
        build_identifier="build", evidence=failed_evidence, environ={})
    assert failed["status"] == "failed"
    destination = tmp_path / "provider" / "receipt.json"
    written = provider_smoke.write_provider_receipt(
        destination, build_identifier="build", evidence=evidence, environ={})
    assert json.loads(destination.read_text(encoding="utf-8"))["status"] == "passed"
    assert written["reason"] == "all provider gates passed"
