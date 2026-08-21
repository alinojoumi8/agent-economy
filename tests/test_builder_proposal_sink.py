from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest

from builder_workspace.proposal_sink import (
    CheckEvidence,
    ProposalAuthorityError,
    ProposalOnlyActionSink,
    ProposalRequest,
    ProposalValidationError,
    ReplayEvidence,
    build_proposal_bundle,
    proposal_artifact_key,
    validate_proposal_artifact_key,
)
from hosted.artifacts import ArtifactConflict, FilesystemArtifactStore


def _request(**overrides) -> ProposalRequest:
    values = {
        "tenant_id": "tenant-a",
        "proposal_id": "proposal-17",
        "run_id": "run-4",
        "builder_actor_id": "builder-2",
        "mandate_id": "mandate-9",
        "skill_pack_version": "civic-builder-v1",
        "base_commit": "a" * 40,
        "candidate_commit": "b" * 40,
        "title": "Improve the city health projection",
        "rationale": "Expose an aggregate health trend without private records.",
        "patch": (
            "diff --git a/engine/city_health.py b/engine/city_health.py\n"
            "--- a/engine/city_health.py\n"
            "+++ b/engine/city_health.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
            "diff --git a/tests/test_city_health.py b/tests/test_city_health.py\n"
            "--- a/tests/test_city_health.py\n"
            "+++ b/tests/test_city_health.py\n"
            "@@ -1 +1 @@\n-old_test\n+new_test\n"
        ),
        "changed_paths": (
            "engine/city_health.py",
            "tests/test_city_health.py",
        ),
        "invariants": (
            "No ledger mutation",
            "Historical projections remain tick-bounded",
        ),
        "checks": (
            CheckEvidence(
                check_id="focused_pytest",
                command=(
                    "python", "-m", "pytest", "-q",
                    "tests/test_city_health.py",
                ),
                exit_code=0,
                duration_ms=1250,
                output_sha256="c" * 64,
                runner_platform="windows",
            ),
            CheckEvidence(
                check_id="git_diff_check",
                command=("git", "diff", "--check"),
                exit_code=0,
                duration_ms=40,
                output_sha256="d" * 64,
                runner_platform="windows",
            ),
        ),
        "replay": ReplayEvidence(
            status="not_applicable",
            comparison_scope="projection_only",
            reason="Read-time projection only; no canonical engine output changes.",
        ),
    }
    values.update(overrides)
    return ProposalRequest(**values)


def _store(tmp_path: Path) -> FilesystemArtifactStore:
    return FilesystemArtifactStore(
        tmp_path / "artifacts",
        key_validator=validate_proposal_artifact_key,
    )


def test_proposal_bundle_is_deterministic_complete_and_immutable(tmp_path):
    request = _request()
    first_bundle = build_proposal_bundle(request)
    second_bundle = build_proposal_bundle(request)
    assert first_bundle.archive_bytes == second_bundle.archive_bytes
    assert first_bundle.bundle_hash == second_bundle.bundle_hash

    store = _store(tmp_path)
    sink = ProposalOnlyActionSink(store, staging_directory=tmp_path / "staging")
    receipt = sink.handle("proposal.create", request)
    assert receipt.artifact_key == proposal_artifact_key(
        "tenant-a", "proposal-17")
    assert receipt.bundle_hash == first_bundle.bundle_hash
    assert store.head(receipt.artifact_key).sha256 == receipt.artifact_sha256
    assert set(vars(sink)) == {"artifact_store", "staging_directory"}

    downloaded = tmp_path / "proposal.zip"
    store.get_file(
        receipt.artifact_key,
        downloaded,
        expected_sha256=receipt.artifact_sha256,
    )
    with zipfile.ZipFile(io.BytesIO(downloaded.read_bytes())) as archive:
        assert archive.namelist() == [
            "manifest.json",
            "change.patch",
            "rationale.md",
            "invariants.json",
            "tests.json",
            "replay.json",
            "policy.json",
        ]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "agent-economy-proposal-bundle/v1"
        assert manifest["changed_paths"] == list(request.changed_paths)
        assert manifest["base_commit"] == "a" * 40
        assert set(manifest["content_hashes"]) == {
            "change.patch",
            "rationale.md",
            "invariants.json",
            "tests.json",
            "replay.json",
            "policy.json",
        }
        tests = json.loads(archive.read("tests.json"))
        assert tests["checks"][0]["command"] == [
            "python", "-m", "pytest", "-q", "tests/test_city_health.py"]
        assert tests["checks"][0]["passed"] is True
        policy = json.loads(archive.read("policy.json"))
        assert policy["allowlist_version"] == "civic-builder-proposal-v1"
        assert policy["authority"] == "proposal_only"

    assert sink.handle("proposal.create", request) == receipt


def test_proposal_retry_recovers_after_ambiguous_immutable_upload(tmp_path):
    durable_store = _store(tmp_path)

    class AmbiguousUploadStore:
        def put_file(self, key, source, *, expected_sha256=None):
            durable_store.put_file(
                key, source, expected_sha256=expected_sha256)
            raise ArtifactConflict("upload response was lost")

        def head(self, key):
            return durable_store.head(key)

        def get_file(self, key, destination, *, expected_sha256=None):
            return durable_store.get_file(
                key, destination, expected_sha256=expected_sha256)

        def delete(self, key):
            durable_store.delete(key)

    sink = ProposalOnlyActionSink(
        AmbiguousUploadStore(), staging_directory=tmp_path / "staging")

    receipt = sink.handle("proposal.create", _request())

    assert durable_store.head(receipt.artifact_key).sha256 == (
        receipt.artifact_sha256)


def test_proposal_retry_preserves_conflict_for_different_existing_bundle(tmp_path):
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")
    sink.handle("proposal.create", _request())

    with pytest.raises(ArtifactConflict):
        sink.handle("proposal.create", _request(title="A different proposal"))


def test_embedded_patch_paths_must_match_declared_paths(tmp_path):
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")

    with pytest.raises(ProposalValidationError, match="exactly match"):
        sink.handle(
            "proposal.create",
            _request(changed_paths=("engine/city_health.py",)),
        )
    assert not list((tmp_path / "artifacts").rglob("payload"))


def test_forbidden_path_hidden_inside_patch_is_rejected(tmp_path):
    hidden_change = (
        "diff --git a/.env.production b/.env.production\n"
        "--- a/.env.production\n"
        "+++ b/.env.production\n"
        "@@ -1 +1 @@\n-old_secret\n+new_secret\n"
    )
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")

    with pytest.raises(ProposalValidationError, match="secret-bearing"):
        sink.handle(
            "proposal.create",
            _request(patch=_request().patch + hidden_change),
        )
    assert not list((tmp_path / "artifacts").rglob("payload"))


def test_unsupported_diff_file_headers_are_rejected(tmp_path):
    patch = _request().patch.replace(
        "--- a/engine/city_health.py\n",
        "rename from engine/city_health.py\n--- a/engine/city_health.py\n",
        1,
    )
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")

    with pytest.raises(ProposalValidationError, match="unsupported"):
        sink.handle("proposal.create", _request(patch=patch))


def test_traditional_file_header_cannot_be_hidden_after_a_hunk(tmp_path):
    hidden_header = (
        "--- a/.env.production\n"
        "+++ b/.env.production\n"
        "@@ -1 +1 @@\n-old_secret\n+new_secret\n"
    )
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")

    with pytest.raises(ProposalValidationError, match="unsupported"):
        sink.handle(
            "proposal.create",
            _request(patch=_request().patch + hidden_header),
        )


def test_new_file_diff_safely_accepts_dev_null_old_path():
    request = _request(
        patch=(
            "diff --git a/docs/new-projection.md b/docs/new-projection.md\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/docs/new-projection.md\n"
            "@@ -0,0 +1 @@\n+Privacy-safe projection.\n"
        ),
        changed_paths=("docs/new-projection.md",),
    )

    bundle = build_proposal_bundle(request)

    assert bundle.archive_bytes


@pytest.mark.parametrize(
    "path",
    [
        "engine/ledger.py",
        "world/loop.py",
        "agents/external.py",
        "hosted/deploy.py",
        ".env.production",
        "data/live.db",
        "../outside.py",
        "dashboard/src/Unrelated.tsx",
    ],
)
def test_proposal_sink_refuses_forbidden_or_unallowlisted_paths(tmp_path, path):
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")

    with pytest.raises(ProposalValidationError):
        sink.handle("proposal.create", _request(changed_paths=(path,)))
    assert not list((tmp_path / "artifacts").rglob("payload"))


def test_proposal_sink_accepts_only_allowlisted_check_evidence(tmp_path):
    injected = CheckEvidence(
        check_id="focused_pytest",
        command=(
            "python", "-m", "pytest", "-q",
            "tests/test_city_health.py", ";", "git", "push",
        ),
        exit_code=0,
        duration_ms=1,
        output_sha256="e" * 64,
        runner_platform="linux",
    )
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")

    with pytest.raises(ProposalValidationError, match="allowlisted"):
        sink.handle("proposal.create", _request(checks=(injected,)))


@pytest.mark.parametrize(
    "action",
    [
        "git.push",
        "git.merge",
        "deploy",
        "secrets.read",
        "engine.mutate",
        "ledger.post",
        "action.execute",
    ],
)
def test_proposal_sink_refuses_every_non_proposal_authority(tmp_path, action):
    sink = ProposalOnlyActionSink(
        _store(tmp_path), staging_directory=tmp_path / "staging")

    with pytest.raises(ProposalAuthorityError, match="proposal-only"):
        sink.handle(action, _request())
    assert not list((tmp_path / "artifacts").rglob("payload"))


@pytest.mark.parametrize(
    "key",
    [
        "tenants/tenant-a/proposals/proposal-1.zip",
        "tenants/tenant-b/proposals/proposal-2.zip",
    ],
)
def test_proposal_keys_are_tenant_scoped(key):
    assert validate_proposal_artifact_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "tenants/tenant-a/runs/run/proposals/proposal.zip",
        "tenants/../proposals/proposal.zip",
        "tenants/tenant-a/proposals/../../secret.zip",
        "tenants/tenant-a/proposals/proposal.exe",
    ],
)
def test_proposal_key_validation_rejects_namespace_escape(key):
    with pytest.raises(ProposalValidationError):
        validate_proposal_artifact_key(key)
