from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from reports.release_evidence import (
    REQUIRED_GATES,
    canonical_release_json,
    collect_release_evidence,
    render_release_markdown,
    write_release_evidence_package,
)


COMMIT = "1" * 40
TREE = "2" * 40
V1_REQUIRED_GATES = frozenset({
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
})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_fixture(
    root: Path,
    *,
    omit: set[str] | None = None,
    status: str = "passed",
) -> tuple[Path, Path]:
    repo = root / "repo"
    receipts = repo / "receipts"
    artifacts = repo / "artifacts"
    receipts.mkdir(parents=True)
    artifacts.mkdir()
    omitted = omit or set()
    gates = []
    for gate_id in sorted(V1_REQUIRED_GATES):
        if gate_id in omitted:
            continue
        artifact = artifacts / f"{gate_id}.txt"
        artifact.write_text(f"public evidence for {gate_id}\n", encoding="utf-8")
        scope = (
            "independent_external"
            if gate_id in {
                "independent_mcp",
                "hermes_connector",
                "openclaw_connector",
                "python_connector",
                "typescript_connector",
            }
            else "local"
        )
        receipt = {
            "schema": "agent-economy-release-gate-v1",
            "gate_id": gate_id,
            "candidate": {"commit": COMMIT, "tree": TREE, "dirty": False},
            "execution_scope": scope,
            "status": status,
            "started_at": "2026-08-05T12:00:00Z",
            "ended_at": "2026-08-05T12:01:00Z",
            "command": f"verify {gate_id}",
            "configuration_sha256": "3" * 64,
            "environment": {
                "os": "linux",
                "architecture": "x86_64",
                "tool_versions": {"python": "3.12"},
            },
            "summary": "eligible evidence passed",
            "artifacts": [{
                "path": artifact.relative_to(repo).as_posix(),
                "sha256": _sha256(artifact),
            }],
            "verifier": {"name": "fixture", "version": "1"},
            "reviewer_notes": "fixture evidence only",
        }
        receipt_path = receipts / f"{gate_id}.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        gates.append({
            "gate_id": gate_id,
            "receipt": receipt_path.relative_to(repo).as_posix(),
            "sha256": _sha256(receipt_path),
            "status": status,
        })
    manifest = {
        "schema": "agent-economy-release-manifest-v1",
        "generated_at": "2026-08-05T12:02:00Z",
        "candidate": {"commit": COMMIT, "tree": TREE},
        "gates": gates,
    }
    manifest_path = repo / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return repo, manifest_path


def test_complete_manifest_passes_only_for_exact_candidate(tmp_path):
    repo, manifest = release_fixture(tmp_path)

    result = collect_release_evidence(manifest, repo_root=repo)

    assert result["overall_status"] == "passed"
    assert result["candidate"] == {"commit": COMMIT, "tree": TREE}
    assert len(result["gates"]) == len(V1_REQUIRED_GATES)
    assert result["errors"] == []


def test_production_required_gates_match_independent_v1_contract():
    assert REQUIRED_GATES == V1_REQUIRED_GATES


def test_collector_decodes_the_same_bytes_used_for_hashing(tmp_path, monkeypatch):
    repo, manifest = release_fixture(tmp_path)
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path.suffix in {".json", ".txt"}:
            raise AssertionError("receipt and artifact text must come from hashed bytes")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    result = collect_release_evidence(manifest, repo_root=repo)

    assert result["overall_status"] == "passed"


def test_collector_reports_all_missing_required_gates(tmp_path):
    repo, manifest = release_fixture(
        tmp_path, omit={"oracle_v9", "rumor_pilot"}
    )

    result = collect_release_evidence(manifest, repo_root=repo)

    assert result["overall_status"] == "failed"
    assert {
        error["gate_id"]
        for error in result["errors"]
        if error["code"] == "missing_gate"
    } == {"oracle_v9", "rumor_pilot"}


def test_collector_rejects_hash_candidate_scope_and_secret_mutations(tmp_path):
    repo, manifest = release_fixture(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    by_id = {row["gate_id"]: row for row in payload["gates"]}

    wrong_hash = by_id["oracle_v9"]
    wrong_hash["sha256"] = "0" * 64

    mismatch_row = by_id["rumor_pilot"]
    mismatch_path = repo / mismatch_row["receipt"]
    mismatch = json.loads(mismatch_path.read_text(encoding="utf-8"))
    mismatch["candidate"]["tree"] = "4" * 40
    mismatch_path.write_text(json.dumps(mismatch, sort_keys=True) + "\n", encoding="utf-8")
    mismatch_row["sha256"] = _sha256(mismatch_path)

    local_external = by_id["independent_mcp"]
    external_path = repo / local_external["receipt"]
    external = json.loads(external_path.read_text(encoding="utf-8"))
    external["execution_scope"] = "local"
    external_path.write_text(json.dumps(external, sort_keys=True) + "\n", encoding="utf-8")
    local_external["sha256"] = _sha256(external_path)

    secret_row = by_id["deployment_receipt"]
    secret_path = repo / secret_row["receipt"]
    secret = json.loads(secret_path.read_text(encoding="utf-8"))
    secret["summary"] = "contains AE_RELEASE_SECRET_CANARY_7b42"
    secret_path.write_text(json.dumps(secret, sort_keys=True) + "\n", encoding="utf-8")
    secret_row["sha256"] = _sha256(secret_path)

    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    result = collect_release_evidence(manifest, repo_root=repo)
    codes = {(error["gate_id"], error["code"]) for error in result["errors"]}

    assert ("oracle_v9", "receipt_hash_mismatch") in codes
    assert ("rumor_pilot", "candidate_mismatch") in codes
    assert ("independent_mcp", "ineligible_scope") in codes
    assert ("deployment_receipt", "secret_detected") in codes
    assert result["overall_status"] == "failed"


def test_collector_rejects_duplicate_invalid_enum_and_escaping_paths(tmp_path):
    repo, manifest = release_fixture(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    duplicate = dict(payload["gates"][0])
    payload["gates"].append(duplicate)
    payload["gates"][1]["status"] = "maybe"
    payload["gates"][2]["receipt"] = "../outside.json"
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = collect_release_evidence(manifest, repo_root=repo)
    codes = {error["code"] for error in result["errors"]}

    assert "duplicate_gate" in codes
    assert "invalid_manifest_status" in codes
    assert "unsafe_path" in codes
    assert result["overall_status"] == "failed"


def test_blocked_receipt_is_visible_and_fails_aggregate(tmp_path):
    repo, manifest = release_fixture(tmp_path, status="blocked")

    result = collect_release_evidence(manifest, repo_root=repo)

    assert result["overall_status"] == "failed"
    assert {gate["status"] for gate in result["gates"]} == {"blocked"}
    assert {
        (error["gate_id"], error["code"]) for error in result["errors"]
    } == {
        (gate_id, "gate_not_passed") for gate_id in V1_REQUIRED_GATES
    }


def test_canonical_renderers_are_deterministic(tmp_path):
    repo, manifest = release_fixture(tmp_path)
    result = collect_release_evidence(manifest, repo_root=repo)

    first_json = canonical_release_json(result)
    second_json = canonical_release_json(result)
    first_markdown = render_release_markdown(result)

    assert first_json == second_json
    assert first_json.endswith("\n")
    assert json.loads(first_json)["overall_status"] == "passed"
    assert first_markdown.startswith("# Agent Economy release evidence\n")
    assert "| Gate | Scope | Status |" in first_markdown
    assert first_markdown.endswith("\n")


def test_package_writer_is_byte_identical_across_repeated_output(tmp_path):
    repo, manifest = release_fixture(tmp_path)
    output = tmp_path / "out"

    first_json, first_markdown = write_release_evidence_package(
        manifest, output, repo_root=repo
    )
    first_bytes = (first_json.read_bytes(), first_markdown.read_bytes())
    second_json, second_markdown = write_release_evidence_package(
        manifest, output, repo_root=repo
    )

    assert first_bytes == (second_json.read_bytes(), second_markdown.read_bytes())
    assert not list(output.glob(".*.tmp"))
