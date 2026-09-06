import json
from contextlib import nullcontext
from pathlib import Path
import stat
import zipfile

import pytest

from research.artifacts import file_sha256, publish_copy
from research.study_bundle import export_study_bundle, import_study_bundle
from research.study_results import StudyArtifactError, load_study_result
from tests.test_study_results import study_snapshot, copied_study  # noqa: F401


@pytest.fixture(scope="module")
def evidence_bundle(study_snapshot, tmp_path_factory):
    root, payload = study_snapshot
    output = tmp_path_factory.mktemp("bundle") / "evidence.zip"
    exported = export_study_bundle(payload["artifacts"]["json"], output,
        data_root=root / "d", out_dir=root / "o")
    assert exported["verification_status"] == "verified"
    return output, exported


def _rewrite(source, target, *, extra=None, edit=None):
    with zipfile.ZipFile(source) as incoming, zipfile.ZipFile(target, "w") as output:
        for info in incoming.infolist():
            data = incoming.read(info)
            if edit:
                data = edit(info.filename, data)
            output.writestr(info, data)
        if extra:
            output.writestr(*extra)
    return target


def test_bundle_roundtrip_verifies_replay_outcomes_and_preserves_source(evidence_bundle, study_snapshot, tmp_path):
    source, exported = evidence_bundle
    original = file_sha256(study_snapshot[1]["artifacts"]["json"])
    receipt = import_study_bundle(source, tmp_path / "imported", expected_sha256=exported["sha256"])
    assert receipt["status"] == "verified"
    assert receipt["study_verification"]["status"] == "verified"
    loaded = load_study_result(receipt["result_path"], data_root=tmp_path / "imported/data",
                               out_dir=tmp_path / "imported/reports")
    assert loaded["summary"] == study_snapshot[1]["summary"]
    assert file_sha256(receipt["result_path"]) == original
    assert file_sha256(study_snapshot[1]["artifacts"]["json"]) == original
    assert not list((tmp_path / "imported").rglob("*.py"))
    with pytest.raises(FileExistsError):
        import_study_bundle(source, tmp_path / "imported")
    assert file_sha256(source) == exported["sha256"]


def test_export_is_exclusive_and_cannot_write_into_source(copied_study, tmp_path):
    result, roots = copied_study
    target = tmp_path / "existing.zip"
    target.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        export_study_bundle(result, target, **roots)
    assert target.read_bytes() == b"keep"
    with pytest.raises(StudyArtifactError, match="outside its source"):
        export_study_bundle(result, result.parent / "nested.zip", **roots)
    with pytest.raises(StudyArtifactError, match="size or file limit"):
        export_study_bundle(result, tmp_path / "small.zip", **roots, max_bytes=100)
    assert not (tmp_path / "small.zip").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "data/../escape",
                                  "data\\escape", "data/file:stream", "data/CON.txt"])
def test_unsafe_archive_paths_are_rejected_before_destination_creation(evidence_bundle, tmp_path, name):
    source, _ = evidence_bundle
    forged = _rewrite(source, tmp_path / "unsafe.zip", extra=(name, b"unsafe"))
    with pytest.raises(StudyArtifactError):
        import_study_bundle(forged, tmp_path / "unpacked")
    assert not (tmp_path / "unpacked").exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("kind", ["symlink", "duplicate", "unlisted", "case_alias"])
def test_link_duplicate_and_unlisted_members_are_rejected(evidence_bundle, tmp_path, kind):
    source, _ = evidence_bundle
    name = "bundle.json" if kind == "duplicate" else "BUNDLE.JSON" if kind == "case_alias" else "extra.txt"
    member = zipfile.ZipInfo(name)
    if kind == "symlink":
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.warns(UserWarning) if kind == "duplicate" else nullcontext():
        forged = _rewrite(source, tmp_path / "unsupported.zip", extra=(member, b"x"))
    with pytest.raises(StudyArtifactError):
        import_study_bundle(forged, tmp_path / "unpacked")
    assert not (tmp_path / "unpacked").exists()


def test_checksum_failure_retains_diagnostic_without_success_receipt(evidence_bundle, tmp_path):
    source, _ = evidence_bundle
    forged = _rewrite(source, tmp_path / "changed.zip", edit=lambda name, data:
        (b"x" * len(data)) if name.endswith("findings.md") else data)
    with pytest.raises(StudyArtifactError, match="checksum mismatch"):
        import_study_bundle(forged, tmp_path / "unpacked")
    assert (tmp_path / "unpacked/import-failed.json").is_file()
    assert not (tmp_path / "unpacked/import.json").exists()


def test_external_hash_and_size_guards_precede_extraction(evidence_bundle, tmp_path):
    source, _ = evidence_bundle
    with pytest.raises(StudyArtifactError, match="externally bound"):
        import_study_bundle(source, tmp_path / "unpacked", expected_sha256="0" * 64)
    with pytest.raises(StudyArtifactError, match="size limit"):
        import_study_bundle(source, tmp_path / "unpacked", max_bytes=100)
    assert not (tmp_path / "unpacked").exists()


def test_false_export_proof_is_not_trusted(evidence_bundle, tmp_path):
    def edit(name, data):
        if name == "bundle.json":
            payload = json.loads(data)
            payload["proof"]["summary_sha256"] = "0" * 64
            return json.dumps(payload).encode()
        return data
    forged = _rewrite(evidence_bundle[0], tmp_path / "false-proof.zip", edit=edit)
    with pytest.raises(StudyArtifactError, match="freshly verified"):
        import_study_bundle(forged, tmp_path / "unpacked")
    assert not (tmp_path / "unpacked/import.json").exists()


def test_degraded_study_keeps_exclusions_after_bundle_roundtrip(copied_study, tmp_path):
    result, roots = copied_study
    loaded = load_study_result(result, **roots)
    data = Path(loaded["verification"]["data_dir"])
    worker = next(data.glob("worker-*.json"))
    payload = json.loads(worker.read_text())
    excluded_arm = payload["arm"]
    payload["eligibility"] = {"status": "ineligible", "reasons": ["inputs_changed_during_attempt"]}
    worker.write_text(json.dumps(payload))
    exported = export_study_bundle(result, tmp_path / "degraded.zip", **roots)
    assert exported["verification_status"] == "degraded"
    imported = import_study_bundle(exported["path"], tmp_path / "restored")
    assert imported["status"] == "verified"  # The transport, not a repaired experiment.
    assert imported["study_verification"]["status"] == "degraded"
    loaded = load_study_result(imported["result_path"], data_root=tmp_path / "restored/data",
                               out_dir=tmp_path / "restored/reports")
    assert loaded["summary"]["coverage"][excluded_arm]["eligible"] == 0


def test_source_change_during_export_prevents_publication(copied_study, tmp_path, monkeypatch):
    import research.study_bundle as bundles
    result, roots = copied_study
    inventory = bundles._inventory
    calls = 0

    def changing_inventory(*args, **kwargs):
        nonlocal calls
        entries = inventory(*args, **kwargs)
        calls += 1
        if calls == 1:
            (result.parent / "retained-diagnostic.txt").write_text("created during copy")
        return entries

    monkeypatch.setattr(bundles, "_inventory", changing_inventory)
    with pytest.raises(StudyArtifactError, match="changed during bundle export"):
        export_study_bundle(result, tmp_path / "changed.zip", **roots)
    assert not (tmp_path / "changed.zip").exists()
    assert (result.parent / "retained-diagnostic.txt").is_file()


def test_streaming_copy_does_not_publish_unbound_or_oversize_bytes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"bound evidence")
    with pytest.raises(ValueError, match="size limit"):
        publish_copy(target, source, expected_sha256=file_sha256(source), max_bytes=2)
    with pytest.raises(ValueError, match="changed while"):
        publish_copy(target, source, expected_sha256="0" * 64, max_bytes=100)
    assert not target.exists()
    assert source.read_bytes() == b"bound evidence"
