"""Private policy evidence preserves completed and unfinished scientific work."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile

import pytest

from research.artifacts import file_sha256
from research.policy_evidence import load_policy_evidence, load_policy_progress
from research.process_lock import ProcessLockBusy, process_lock
from research.study_bundle import export_study_bundle, import_study_bundle
from research.study_library import StudyLibrary
from research.study_results import StudyArtifactError, verification_identity
from research.study_runner import run_study
from research.working_evidence import load_study_evidence
from tests.test_policy_origins import sources_and_spec
from tests.test_policy_recovery import options
from tests.test_policy_studies import base_policy_setup, policy_http_fixture


CASES = [f"{origin}_{mode}" for origin in ("fresh", "saved") for mode in ("frozen", "day", "phase")]


def tree_hashes(*roots):
    return {path: file_sha256(path) for root in roots for path in Path(root).rglob("*") if path.is_file()}


def archive_snapshot(payload, args, root, label):
    path = Path(payload["artifacts"]["json"])
    roots = {key: args[key] for key in ("data_root", "out_dir")}
    before = tree_hashes(*roots.values())
    verified = load_policy_evidence(path, **roots)
    assert verified["verification"]["status"] == "verified", verified["verification"]
    archive = export_study_bundle(path, root / f"{label}.zip", **roots,
        expected_sha256=file_sha256(path), expected_verification=verification_identity(verified))
    received = import_study_bundle(archive["path"], root / label, expected_sha256=archive["sha256"])
    assert received["status"] == received["study_verification"]["status"] == "verified"
    copied_roots = {"data_root": root / label / "data", "out_dir": root / label / "reports"}
    read = load_study_evidence(received["result_path"], **copied_roots)
    assert verification_identity(read) == verification_identity(verified)
    assert tree_hashes(*roots.values()) == before
    with zipfile.ZipFile(archive["path"]) as stream:
        index = json.loads(stream.read("bundle.json"))
    expected = "policy-working-evidence-bundle-v1" if payload.get("status") == "paused" else "policy-study-evidence-bundle-v1"
    assert index["contract"] == expected
    assert any(name.endswith("provider-budget.db") for name in index["files"])
    return {"path": Path(received["result_path"]), "roots": copied_roots, "read": read,
        "archive": Path(archive["path"]), "root": root / label, "original": path}


@pytest.fixture(scope="module")
def campaigns(tmp_path_factory):
    cache = {}

    def campaign(case):
        if case in cache:
            return cache[case]
        root = tmp_path_factory.mktemp(case)
        origin, mode = case.split("_")
        policy = {"frozen": "preserve_and_stop", "day": "preserve_and_resume",
            "phase": "preserve_and_resume_phases"}[mode]
        with policy_http_fixture(base_policy_setup(), draws=["draw1", "draw2"] if case == "saved_phase" else ["draw1"]) as (config, initial, posts):
            sources = []
            if origin == "saved":
                sources, spec = sources_and_spec(config, initial, root, policy,
                    replicates=2 if case == "saved_phase" else 1)
                args = dict(spec=spec, config=config, input_root=root, data_root=root / "d", out_dir=root / "o")
            else:
                args = options(config, initial, root, policy)
                args.update(data_root=root / "d", out_dir=root / "o")
            original_hashes = {path: file_sha256(path) for path in sources}
            pending = []
            if mode != "frozen":
                controls = {"pause_after_ticks": 1} if mode == "day" else {"pause_after_phase": "MORNING"}
                first = run_study(**args, **controls, approve_live_inference=True)
                assert first["status"] == "paused", first
                calls = len(posts)
                pending.append(archive_snapshot(first, args, root, "p1"))
                assert len(posts) == calls
                current = run_study(**args, resume_batch=first["batch"]["data_dir"],
                    pause_after_ticks=2, approve_live_inference=True)
                if mode == "phase":
                    assert current["status"] == "paused"
                    current = run_study(**args, resume_batch=first["batch"]["data_dir"],
                        pause_after_ticks=2, approve_live_inference=True)
                assert current["status"] == "paused"
                assert {"completed", "paused", "planned"} <= {row["execution_status"] for row in current["results"]}
                calls = len(posts)
                pending.append(archive_snapshot(current, args, root, "p2"))
                assert len(posts) == calls
                final = run_study(**args, resume_batch=first["batch"]["data_dir"], approve_live_inference=True)
            else:
                final = run_study(**args, approve_live_inference=True)
            assert all(row["eligibility"]["status"] == "eligible" for row in final["results"]), final
            for domain in ("goods_price", "equity_price"):
                assert final["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 2
            calls = len(posts)
            finished = archive_snapshot(final, args, root, "f")
            assert len(posts) == calls
            assert all(file_sha256(path) == digest for path, digest in original_hashes.items())
        cache[case] = {"root": root, "args": args, "pending": pending, "final": finished,
            "posts": posts, "calls": calls, "sources": original_hashes}
        return cache[case]

    return campaign


@pytest.mark.parametrize("case", CASES)
def test_private_policy_roundtrip_reads_both_prices_and_pending_costs(campaigns, case, monkeypatch):
    campaign = campaigns(case)
    snapshots = [*campaign["pending"], campaign["final"]]
    before = tree_hashes(campaign["root"])

    def forbidden(*_args, **_kwargs):
        pytest.fail("historical evidence must not construct a world or contact a provider")

    monkeypatch.setattr("world.loop.World.__init__", forbidden)
    monkeypatch.setattr("llm.gateway.Gateway.preflight", forbidden)
    monkeypatch.setattr("research.policy_studies.prompt_source_identity", lambda: "f" * 64)
    for snapshot in snapshots:
        current = load_policy_evidence(snapshot["path"], **snapshot["roots"])
        assert verification_identity(current) == verification_identity(snapshot["read"])
        if snapshot is not campaign["final"]:
            assert current["verification"]["publication"] == "working"
            assert current["verification"]["eligibility"] == "pending"
            assert current["verification"]["provider_budget"]["sealed"] is False
        else:
            assert current["verification"]["provider_budget"]["sealed"] is True
        assert len(current["results"]) == (8 if case == "saved_phase" else 4)
        if case.startswith("saved"):
            for row in current["results"]:
                if row["execution_status"] != "planned":
                    assert row["inherited_provider_calls"] == 1 and row["inherited_spend_usd"] == 7.5
                    assert row["spend_usd"] < .1
        library = StudyLibrary(**snapshot["roots"], export_root=snapshot["root"] / "exports")
        catalog = library.public_catalog()
        assert len(catalog["items"]) == 1 and catalog["items"][0]["protocol_version"] == "research-study-v3"
        item = catalog["items"][0]
        view = library.verify(item["id"], item["result_sha256"])
        assert len({row["cell_key"] for row in view["attempts"]}) == len(current["results"])
        assert view["provider_allowance"]["usage"]["provider_calls"] == current["verification"]["provider_budget"]["provider_calls"]
        assert view["provider_allowance"]["verified"] is True
        if snapshot is not campaign["final"]:
            assert view["contract"] == "operator-policy-working-study-v1" and view["comparison_available"] is False
            assert not any(key in view for key in ("summary", "measurements", "outcomes"))
        else:
            assert view["contract"] == "operator-policy-study-comparison-v1"
            for rows in view["measurements"].values():
                assert len({row["cell_key"] for row in rows}) == len(current["results"])
        public = json.dumps(view)
        assert not any(value in public for value in ("base_url", "endpoint_reference", "source_database", '"llm"', '"auth"', "provider-budget.db"))
        assert str(campaign["root"]).replace("\\", "\\\\") not in public
    assert tree_hashes(campaign["root"]) == before and len(campaign["posts"]) == campaign["calls"]


def copied_snapshot(snapshot, tmp_path):
    root = tmp_path / "c"
    for name in ("data", "reports"):
        shutil.copytree(snapshot["root"] / name, root / name)
    path = root / snapshot["path"].relative_to(snapshot["root"])
    return path, {"data_root": root / "data", "out_dir": root / "reports"}


def copied_pending(campaigns, tmp_path):
    campaign = campaigns("saved_phase")
    path, roots = copied_snapshot(campaign["pending"][-1], tmp_path)
    return path, roots, campaign


def reseal_progress(path, roots, payload):
    """Rewrite the diagnostic envelope so the reader must inspect its evidence."""
    from research.policy_recovery import PROGRESS
    from research.working_evidence import working_location
    location = working_location(path, payload, **roots, progress_contract=PROGRESS)
    number = payload["operations"]["supervision"]["invocation"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    end_path = location.data_file(f"supervision/invocation-{number:06d}-end.json")
    end = json.loads(end_path.read_text())
    end["report"]["sha256"] = file_sha256(path)
    for ref in end["workers"]:
        ref["sha256"] = file_sha256(location.data_file(ref["path"]))
    end_path.write_text(json.dumps(end), encoding="utf-8")
    location.data_file(f"supervision/invocation-{number:06d}-seal.json").write_text(
        json.dumps({"end_sha256": file_sha256(end_path)}), encoding="utf-8")


@pytest.mark.parametrize("owner", ["supervisor.lock", "working.lock"])
def test_policy_archive_respects_each_mutable_owner(campaigns, tmp_path, owner):
    path, roots, _ = copied_pending(campaigns, tmp_path)
    checked = load_policy_progress(path, **roots)
    before = tree_hashes(*roots.values())
    with process_lock(Path(checked["verification"]["data_dir"]) / owner):
        with pytest.raises(ProcessLockBusy):
            export_study_bundle(path, tmp_path / "busy.zip", **roots)
        library = StudyLibrary(**roots, export_root=tmp_path / "exports")
        item = library.public_catalog()["items"][0]
        view = library.verify(item["id"], item["result_sha256"])
        assert view["state"] == "running" and view["export_available"] is False
        assert view["provider_allowance"]["verified"] is False
        assert view["provider_allowance"]["usage"]["provider_calls"] is None
        assert len({row["cell_key"] for row in view["attempts"]}) == 8
        assert all(row["eligibility"]["status"] == "pending" and "position" not in row for row in view["attempts"])
    assert not (tmp_path / "busy.zip").exists() and tree_hashes(*roots.values()) == before


@pytest.mark.parametrize("change", ["missing_budget", "changed_budget", "sealed_budget", "unfinished", "source", "origin", "transition", "promoted", "assignment"])
def test_altered_policy_pause_cannot_be_read_or_exported(campaigns, tmp_path, change):
    from research.policy_recovery import PROGRESS
    from research.working_evidence import working_location
    path, roots, _ = copied_pending(campaigns, tmp_path)
    payload = json.loads(path.read_text())
    location = working_location(path, payload, **roots, progress_contract=PROGRESS)
    row = next(row for row in payload["results"] if row["execution_status"] == "paused")
    claim_path = location.locate(row["attempt_claim"])
    claim = json.loads(claim_path.read_text())
    budget = location.data_file("provider-budget.db")
    if change == "missing_budget":
        budget.rename(budget.with_name("retained-budget.db"))
    elif change in {"changed_budget", "sealed_budget"}:
        with sqlite3.connect(budget) as conn:
            conn.execute("UPDATE reservations SET reserved_input=reserved_input+1" if change == "changed_budget"
                else "UPDATE budget_status SET sealed=1")
        conn.close()
    elif change == "unfinished":
        number = payload["operations"]["supervision"]["invocation"] + 1
        location.data_file(f"supervision/invocation-{number:06d}-start.json").write_text("{}")
    elif change in {"source", "origin"}:
        target = location.locate(row["source_database"] if change == "source" else claim["checkpoint_origin"]["database"])
        with target.open("ab") as stream:
            stream.write(b"changed fixture")
    elif change == "transition":
        claim["checkpoint_origin"]["policy_transition"]["effective_tick"] += 1
        claim_path.write_text(json.dumps(claim), encoding="utf-8")
    else:
        if change == "promoted":
            row["eligibility"] = {"status": "eligible", "reasons": []}
        else:
            payload["results"].pop()
        reseal_progress(path, roots, payload)
    before = tree_hashes(*roots.values())
    with pytest.raises(StudyArtifactError):
        load_policy_progress(path, **roots)
    with pytest.raises(StudyArtifactError):
        export_study_bundle(path, tmp_path / "refused.zip", **roots)
    assert not (tmp_path / "refused.zip").exists() and tree_hashes(*roots.values()) == before


@pytest.mark.parametrize("state", ["pending", "final"])
def test_policy_archive_cannot_be_relabelled_as_scripted_evidence(campaigns, tmp_path, state):
    campaign = campaigns("saved_phase")
    snapshot = campaign["pending"][-1] if state == "pending" else campaign["final"]
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(snapshot["archive"]) as original, zipfile.ZipFile(changed, "w") as output:
        for info in original.infolist():
            data = original.read(info)
            if info.filename == "bundle.json":
                index = json.loads(data)
                index["contract"] = "study-working-evidence-bundle-v1" if state == "pending" else "study-evidence-bundle-v1"
                data = json.dumps(index).encode()
            output.writestr(info, data)
    destination = tmp_path / "refused"
    with pytest.raises(StudyArtifactError, match="proof differs"):
        import_study_bundle(changed, destination)
    assert not (destination / "import.json").exists()
    assert json.loads((destination / "import-failed.json").read_text())["status"] == "failed"


def test_imported_pending_allowance_does_not_grant_another_execution(campaigns, tmp_path, monkeypatch):
    path, roots, campaign = copied_pending(campaigns, tmp_path)
    loaded = load_policy_progress(path, **roots)
    before = tree_hashes(campaign["root"], *roots.values())

    def forbidden(*_args, **_kwargs):
        pytest.fail("an imported allowance cannot launch a worker or provider")

    monkeypatch.setattr("research.working_studies.multiprocessing.get_context", forbidden)
    with pytest.raises(ValueError, match="working progress contract changed"):
        run_study(**{**campaign["args"], **roots},
            resume_batch=loaded["verification"]["data_dir"], approve_live_inference=True)
    assert tree_hashes(campaign["root"], *roots.values()) == before


def test_original_progress_becomes_stale_but_its_import_stays_pending(campaigns):
    campaign = campaigns("saved_phase")
    before = tree_hashes(campaign["root"])
    original_roots = {key: campaign["args"][key] for key in ("data_root", "out_dir")}
    for snapshot in campaign["pending"]:
        with pytest.raises(StudyArtifactError, match="current closed pause"):
            load_policy_progress(snapshot["original"], **original_roots)
        read = load_policy_progress(snapshot["path"], **snapshot["roots"])
        assert read["verification"]["status"] == "verified"
        assert read["verification"]["eligibility"] == "pending"
    assert tree_hashes(campaign["root"]) == before


def test_resealed_provider_totals_cannot_override_original_usage(campaigns, tmp_path):
    path, roots, _ = copied_pending(campaigns, tmp_path)
    payload = json.loads(path.read_text())
    expected = load_policy_progress(path, **roots)["verification"]["provider_budget"]
    payload["operations"].update(provider_calls=0, usage_cost_usd=0, encumbered_usd=0, provider_spend_usd=0)
    reseal_progress(path, roots, payload)
    before = tree_hashes(*roots.values())
    read = load_policy_progress(path, **roots)
    assert read["verification"]["status"] == "degraded"
    assert read["verification"]["provider_budget"] == expected and expected["provider_calls"] > 0
    assert {"reason": "stored_provider_totals_disagree_with_original_accounting"} in read["verification"]["issues"]
    assert tree_hashes(*roots.values()) == before


def test_resealed_completed_price_is_checked_against_the_database(campaigns, tmp_path):
    from research.policy_recovery import PROGRESS
    from research.working_evidence import working_location
    path, roots, _ = copied_pending(campaigns, tmp_path)
    payload = json.loads(path.read_text())
    location = working_location(path, payload, **roots, progress_contract=PROGRESS)
    row = next(row for row in payload["results"] if row["execution_status"] == "completed")
    row["metrics"]["goods_price"] = 1_000_000
    receipt_path = location.locate(row["source_receipt"])
    receipt = json.loads(receipt_path.read_text())
    receipt["metrics"] = copy.deepcopy(row["metrics"])
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    row["source_receipt_sha256"] = file_sha256(receipt_path)
    directory = location.locate(row["attempt_claim"]).parent
    result_path = directory / "result.json"
    result_path.write_text(json.dumps(row), encoding="utf-8")
    seal_path = directory / "finalized.json"
    seal = json.loads(seal_path.read_text())
    seal["result_sha256"] = file_sha256(result_path)
    seal_path.write_text(json.dumps(seal), encoding="utf-8")
    number = payload["operations"]["supervision"]["invocation"]
    for name in (f"worker-{row['cell_key']}.json", f"supervision/invocation-{number:06d}-worker-{row['cell_key']}.json"):
        location.data_file(name).write_text(json.dumps(row), encoding="utf-8")
    reseal_progress(path, roots, payload)
    before = tree_hashes(*roots.values())
    read = load_policy_progress(path, **roots)
    checked = next(item for item in read["results"] if item["cell_key"] == row["cell_key"])
    assert checked["eligibility"] == {"status": "ineligible", "reasons": ["independent_measurement_mismatch"]}
    assert read["verification"]["status"] == "degraded" and read["verification"]["eligibility"] == "pending"
    for domain in ("goods_price", "equity_price"):
        assert read["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 0
    archive = export_study_bundle(path, tmp_path / "diagnostic.zip", **roots)
    copied = import_study_bundle(archive["path"], tmp_path / "diagnostic")
    assert copied["status"] == "verified" and copied["study_verification"]["status"] == "degraded"
    assert copied["study_verification"]["eligibility"] == "pending"
    assert tree_hashes(*roots.values()) == before


@pytest.mark.parametrize("target", ["provider-budget.db", "source"])
def test_policy_archive_is_not_published_if_evidence_changes_during_copy(campaigns, tmp_path, monkeypatch, target):
    import research.study_bundle as bundle
    path, roots, _ = copied_pending(campaigns, tmp_path)
    inventory = bundle._inventory
    changed = []

    def alter_after_inventory(result, **options):
        entries = inventory(result, **options)
        if not changed:
            if target == "source":
                row = next(row for row in result["results"] if row["execution_status"] == "paused")
                source_name = Path(row["source_database"]).name
                source = next(item["path"] for item in entries.values() if item["path"].name == source_name)
            else:
                source = Path(result["verification"]["data_dir"]) / target
            with source.open("ab") as stream:
                stream.write(b"changed fixture")
            changed.append(source)
        return entries

    monkeypatch.setattr(bundle, "_inventory", alter_after_inventory)
    destination = tmp_path / "refused.zip"
    with pytest.raises(StudyArtifactError, match="changed during bundle export"):
        export_study_bundle(path, destination, **roots)
    assert len(changed) == 1 and not destination.exists()
    assert not list(tmp_path.glob(".refused.zip.*"))


def test_final_policy_reader_rejects_a_result_replaced_during_verification(campaigns, tmp_path, monkeypatch):
    import research.policy_results as results
    path, roots = copied_snapshot(campaigns("fresh_frozen")["final"], tmp_path)
    original = results.verify_policy_cell
    changed = []

    def replace_result(*args, **options):
        if not changed:
            path.write_bytes(path.read_bytes() + b"\n")
            changed.append(True)
        return original(*args, **options)

    monkeypatch.setattr(results, "verify_policy_cell", replace_result)
    with pytest.raises(StudyArtifactError, match="result changed during verification"):
        load_policy_evidence(path, **roots)
    assert changed == [True]


@pytest.mark.parametrize("state", ["pending", "final"])
def test_private_policy_cli_reads_and_transports_both_publication_states(campaigns, tmp_path, monkeypatch, capsys, state):
    from research.policy_results import main as reader_main
    from research.study_bundle import main as bundle_main
    campaign = campaigns("saved_phase")
    snapshot = campaign["pending"][-1] if state == "pending" else campaign["final"]
    roots = snapshot["roots"]
    common = [str(snapshot["path"]), "--data-root", str(roots["data_root"]), "--out-dir", str(roots["out_dir"])]
    monkeypatch.setattr(sys, "argv", ["policy_results", *common])
    assert reader_main() == 0
    assert json.loads(capsys.readouterr().out)["verification"]["status"] == "verified"
    archive = tmp_path / "cli.zip"
    monkeypatch.setattr(sys, "argv", ["study_bundle", "export", common[0], str(archive), *common[1:],
        "--expected-sha256", file_sha256(snapshot["path"])])
    assert bundle_main() == 0
    exported = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "argv", ["study_bundle", "import", str(archive), str(tmp_path / "cli"),
        "--expected-sha256", exported["sha256"]])
    assert bundle_main() == 0
    received = json.loads(capsys.readouterr().out)
    assert received["study_verification"]["publication"] == ("working" if state == "pending" else "verified")


@pytest.mark.parametrize("payload", [None, "{", '{"contract":[]}'])
def test_missing_or_malformed_policy_cli_input_has_a_bounded_error(tmp_path, monkeypatch, capsys, payload):
    from research.policy_results import main
    path = tmp_path / "input.json"
    if payload is not None:
        path.write_text(payload)
    monkeypatch.setattr(sys, "argv", ["policy_results", str(path), "--out-dir", str(tmp_path)])
    assert main() == 2 and json.loads(capsys.readouterr().out)["status"] == "invalid"


def test_policy_export_requires_the_existing_working_owner(campaigns, tmp_path):
    path, roots, _ = copied_pending(campaigns, tmp_path)
    checked = load_policy_progress(path, **roots)
    owner = Path(checked["verification"]["data_dir"]) / "working.lock"
    owner.rename(owner.with_name("retained-owner.lock"))
    before = tree_hashes(*roots.values())
    with pytest.raises(StudyArtifactError, match="ownership record is missing"):
        export_study_bundle(path, tmp_path / "refused.zip", **roots)
    assert not (tmp_path / "refused.zip").exists() and tree_hashes(*roots.values()) == before
