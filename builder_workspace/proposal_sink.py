"""Immutable proposal bundles with no engine or deployment authority."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
import zipfile

from hosted.artifacts import (
    ArtifactConflict,
    ArtifactError,
    ArtifactMetadata,
    ArtifactStore,
)


ALLOWLIST_VERSION = "civic-builder-proposal-v1"
PROPOSAL_FORMAT = "agent-economy-proposal-bundle/v1"
PROPOSAL_ENTRY_ORDER = (
    "manifest.json",
    "change.patch",
    "rationale.md",
    "invariants.json",
    "tests.json",
    "replay.json",
    "policy.json",
)

_IDENTIFIER_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,126}[A-Za-z0-9])?")
_PROPOSAL_KEY_RE = re.compile(
    r"tenants/(?P<tenant>[A-Za-z0-9][A-Za-z0-9_-]{0,127})/"
    r"proposals/(?P<proposal>[A-Za-z0-9][A-Za-z0-9_-]{0,127})\.zip")
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_TEST_TARGET_RE = re.compile(
    r"tests/[A-Za-z0-9_./-]+\.py"
    r"(?:::[A-Za-z0-9_\[\]-]+)*")
_DIFF_HEADER_RE = re.compile(
    r"diff --git a/(?P<old>[^\s]+) b/(?P<new>[^\s]+)")
_INDEX_HEADER_RE = re.compile(
    r"index [0-9a-f]+\.\.[0-9a-f]+(?: [0-7]{6})?")
_MODE_HEADER_RE = re.compile(
    r"(?:new file mode|deleted file mode|old mode|new mode) [0-7]{6}")
_HUNK_HEADER_RE = re.compile(
    r"@@ -(?P<old_start>[0-9]+)(?:,(?P<old_count>[0-9]+))? "
    r"\+(?P<new_start>[0-9]+)(?:,(?P<new_count>[0-9]+))? @@(?: .*)?")

_ALLOWED_EXACT_PATHS = frozenset({
    "agents/cohorts.py",
    "engine/city_health.py",
    "engine/city_expansion.py",
    "engine/builder_commands.py",
})
_ALLOWED_PREFIXES = (
    "agents/personas/",
    "agents/cohort_generators/",
    "server/projections/",
    "tests/",
    "fixtures/",
    "docs/",
    "engine/migration_proposals/",
)
_DENIED_EXACT_PATHS = frozenset({
    "engine/ledger.py",
    "world/loop.py",
    "world/replay_verify.py",
    "agents/external.py",
})
_DENIED_PREFIXES = (
    "hosted/",
    "data/",
    ".git/",
    ".github/workflows/",
    "deploy/",
    "deployment/",
    "infrastructure/",
)

_FIXED_CHECKS: dict[str, tuple[str, ...]] = {
    "dashboard_test": ("npm.cmd", "test", "--prefix", "dashboard"),
    "dashboard_typecheck": (
        "npm.cmd", "run", "typecheck", "--prefix", "dashboard"),
    "dashboard_build": (
        "npm.cmd", "run", "build", "--prefix", "dashboard"),
    "git_diff_check": ("git", "diff", "--check"),
    "forbidden_path_revalidation": ("policy", "validate-paths"),
    "exact_replay": ("python", "scripts/replay_compare.py"),
}


class ProposalValidationError(ValueError):
    """Proposal content falls outside the fixed Builder support policy."""


class ProposalAuthorityError(PermissionError):
    """The caller requested authority the proposal-only sink cannot hold."""


@dataclass(frozen=True, slots=True)
class CheckEvidence:
    check_id: str
    command: tuple[str, ...]
    exit_code: int
    duration_ms: int
    output_sha256: str
    runner_platform: str = "unknown"


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    status: str
    comparison_scope: str
    source_run_id: str | None = None
    source_hash: str | None = None
    candidate_hash: str | None = None
    mismatches: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalRequest:
    tenant_id: str
    proposal_id: str
    run_id: str
    builder_actor_id: str
    mandate_id: str
    skill_pack_version: str
    base_commit: str
    candidate_commit: str
    title: str
    rationale: str
    patch: str
    changed_paths: tuple[str, ...]
    invariants: tuple[str, ...]
    checks: tuple[CheckEvidence, ...]
    replay: ReplayEvidence


@dataclass(frozen=True, slots=True)
class ProposalBundle:
    archive_bytes: bytes
    bundle_hash: str
    content_hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ProposalReceipt:
    tenant_id: str
    proposal_id: str
    artifact_key: str
    artifact_sha256: str
    artifact_size_bytes: int
    bundle_hash: str
    changed_paths: tuple[str, ...]
    check_ids: tuple[str, ...]


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ProposalValidationError(
            f"{label} must be a safe 1-128 character ASCII identifier")
    return value


def proposal_artifact_key(tenant_id: str, proposal_id: str) -> str:
    tenant = _identifier(tenant_id, "tenant_id")
    proposal = _identifier(proposal_id, "proposal_id")
    return f"tenants/{tenant}/proposals/{proposal}.zip"


def validate_proposal_artifact_key(key: str) -> str:
    match = _PROPOSAL_KEY_RE.fullmatch(key) if isinstance(key, str) else None
    if match is None:
        raise ProposalValidationError(
            "proposal key must be tenants/<tenant>/proposals/<proposal>.zip")
    _identifier(match.group("tenant"), "tenant_id")
    _identifier(match.group("proposal"), "proposal_id")
    return key


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _bounded_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProposalValidationError(f"{label} is required")
    if len(value.encode("utf-8")) > maximum:
        raise ProposalValidationError(f"{label} exceeds {maximum} UTF-8 bytes")
    return value.strip()


def _normalize_changed_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ProposalValidationError("changed paths must be POSIX relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ProposalValidationError(f"unsafe changed path: {value!r}")
    normalized = path.as_posix()
    if normalized in _DENIED_EXACT_PATHS or normalized.startswith(_DENIED_PREFIXES):
        raise ProposalValidationError(f"forbidden Builder path: {normalized}")
    if any(part.startswith(".env") for part in path.parts):
        raise ProposalValidationError(f"secret-bearing path is forbidden: {normalized}")
    dashboard_allowed = (
        normalized.startswith("dashboard/src/features/builder/")
        or normalized.startswith("dashboard/src/components/builder/")
        or (
            normalized.startswith("dashboard/src/")
            and Path(normalized).name.startswith("Builder")
        )
    )
    allowed = (
        normalized in _ALLOWED_EXACT_PATHS
        or normalized.startswith(_ALLOWED_PREFIXES)
        or (
            normalized.startswith("runs/")
            and normalized.endswith((".yaml", ".yml"))
        )
        or dashboard_allowed
    )
    if not allowed:
        raise ProposalValidationError(
            f"changed path is not allowlisted for Builder proposals: {normalized}")
    return normalized


def _patch_marker_path(
    line: str,
    *,
    marker: str,
    path_prefix: str,
) -> str | None:
    value = line.removeprefix(marker)
    if value == "/dev/null":
        return None
    if not value.startswith(path_prefix) or value == path_prefix:
        raise ProposalValidationError(
            f"unsupported unified diff file header: {line!r}")
    return _normalize_changed_path(value.removeprefix(path_prefix))


def _validate_patch_paths(patch: str) -> frozenset[str]:
    """Return every allowlisted path in a deliberately narrow Git text diff."""
    lines = patch.splitlines()
    if not lines:
        raise ProposalValidationError("patch must contain a unified Git diff")

    embedded_paths: set[str] = set()
    index = 0
    while index < len(lines):
        diff_match = _DIFF_HEADER_RE.fullmatch(lines[index])
        if diff_match is None:
            raise ProposalValidationError(
                f"unsupported patch header at line {index + 1}: {lines[index]!r}")
        diff_old = _normalize_changed_path(diff_match.group("old"))
        diff_new = _normalize_changed_path(diff_match.group("new"))
        embedded_paths.update((diff_old, diff_new))
        index += 1

        while index < len(lines) and not lines[index].startswith("--- "):
            header = lines[index]
            if header.startswith("diff --"):
                raise ProposalValidationError(
                    f"missing unified file headers before line {index + 1}")
            if (
                _INDEX_HEADER_RE.fullmatch(header) is None
                and _MODE_HEADER_RE.fullmatch(header) is None
            ):
                raise ProposalValidationError(
                    f"unsupported unified diff file header: {header!r}")
            index += 1

        if index >= len(lines):
            raise ProposalValidationError("patch is missing an old-file header")
        marker_old = _patch_marker_path(
            lines[index], marker="--- ", path_prefix="a/")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ProposalValidationError("patch is missing a new-file header")
        marker_new = _patch_marker_path(
            lines[index], marker="+++ ", path_prefix="b/")
        index += 1

        if marker_old is None and marker_new is None:
            raise ProposalValidationError(
                "old and new patch paths cannot both be /dev/null")
        if (marker_old is None or marker_new is None) and diff_old != diff_new:
            raise ProposalValidationError(
                "new and deleted file diff paths must use one canonical path")
        if marker_old is not None:
            embedded_paths.add(marker_old)
            if marker_old != diff_old:
                raise ProposalValidationError(
                    "old-file header does not match diff --git path")
        if marker_new is not None:
            embedded_paths.add(marker_new)
            if marker_new != diff_new:
                raise ProposalValidationError(
                    "new-file header does not match diff --git path")

        saw_hunk = False
        while index < len(lines) and not lines[index].startswith("diff --git "):
            hunk_match = _HUNK_HEADER_RE.fullmatch(lines[index])
            if hunk_match is None:
                raise ProposalValidationError(
                    f"unsupported unified diff content at line {index + 1}: "
                    f"{lines[index]!r}")
            saw_hunk = True
            old_remaining = int(hunk_match.group("old_count") or 1)
            new_remaining = int(hunk_match.group("new_count") or 1)
            index += 1
            while old_remaining or new_remaining:
                if index >= len(lines):
                    raise ProposalValidationError("patch hunk ended before its line counts")
                hunk_line = lines[index]
                if hunk_line == r"\ No newline at end of file":
                    index += 1
                    continue
                if hunk_line.startswith(" "):
                    old_remaining -= 1
                    new_remaining -= 1
                elif hunk_line.startswith("-"):
                    old_remaining -= 1
                elif hunk_line.startswith("+"):
                    new_remaining -= 1
                else:
                    raise ProposalValidationError(
                        f"unsupported patch hunk line at {index + 1}")
                if old_remaining < 0 or new_remaining < 0:
                    raise ProposalValidationError("patch hunk exceeds its declared line counts")
                index += 1
            if (
                index < len(lines)
                and lines[index] == r"\ No newline at end of file"
            ):
                index += 1
        if not saw_hunk:
            raise ProposalValidationError(
                "proposal patches must contain unified text hunks")

    return frozenset(embedded_paths)


def _validate_check(check: CheckEvidence) -> dict[str, Any]:
    command = tuple(check.command)
    fixed = _FIXED_CHECKS.get(check.check_id)
    focused_pytest = (
        check.check_id == "focused_pytest"
        and command[:4] == ("python", "-m", "pytest", "-q")
        and len(command) >= 5
        and all(
            _TEST_TARGET_RE.fullmatch(target) is not None
            and ".." not in PurePosixPath(target.split("::", 1)[0]).parts
            for target in command[4:]
        )
    )
    if not focused_pytest and command != fixed:
        raise ProposalValidationError(
            f"check {check.check_id!r} is not an allowlisted command template")
    if isinstance(check.exit_code, bool) or not isinstance(check.exit_code, int):
        raise ProposalValidationError("check exit_code must be an integer")
    if (
        isinstance(check.duration_ms, bool)
        or not isinstance(check.duration_ms, int)
        or not 0 <= check.duration_ms <= 86_400_000
    ):
        raise ProposalValidationError("check duration_ms is invalid")
    if _HASH_RE.fullmatch(check.output_sha256) is None:
        raise ProposalValidationError("check output_sha256 must be lowercase SHA-256")
    if check.runner_platform not in {"windows", "linux", "darwin", "unknown"}:
        raise ProposalValidationError("check runner_platform is not allowlisted")
    return {
        "check_id": check.check_id,
        "command": list(command),
        "exit_code": check.exit_code,
        "passed": check.exit_code == 0,
        "duration_ms": check.duration_ms,
        "output_sha256": check.output_sha256,
        "runner_platform": check.runner_platform,
    }


def _validate_replay(replay: ReplayEvidence) -> dict[str, Any]:
    if replay.status not in {"passed", "failed", "not_applicable"}:
        raise ProposalValidationError("replay status is invalid")
    if replay.status == "not_applicable" and not replay.reason:
        raise ProposalValidationError(
            "not_applicable replay evidence requires a reason")
    for label, value in (
        ("source_hash", replay.source_hash),
        ("candidate_hash", replay.candidate_hash),
    ):
        if value is not None and _HASH_RE.fullmatch(value) is None:
            raise ProposalValidationError(f"replay {label} must be lowercase SHA-256")
    return {
        "status": replay.status,
        "comparison_scope": _bounded_text(
            replay.comparison_scope, "replay comparison_scope", 500),
        "source_run_id": replay.source_run_id,
        "source_hash": replay.source_hash,
        "candidate_hash": replay.candidate_hash,
        "mismatches": list(replay.mismatches),
        "reason": replay.reason,
    }


def _proposal_content(request: ProposalRequest) -> dict[str, bytes]:
    tenant_id = _identifier(request.tenant_id, "tenant_id")
    proposal_id = _identifier(request.proposal_id, "proposal_id")
    run_id = _identifier(request.run_id, "run_id")
    builder_actor_id = _identifier(
        request.builder_actor_id, "builder_actor_id")
    mandate_id = _identifier(request.mandate_id, "mandate_id")
    skill_pack_version = _identifier(
        request.skill_pack_version, "skill_pack_version")
    if _COMMIT_RE.fullmatch(request.base_commit) is None:
        raise ProposalValidationError("base_commit must be a full Git object id")
    if _COMMIT_RE.fullmatch(request.candidate_commit) is None:
        raise ProposalValidationError(
            "candidate_commit must be a full Git object id")
    title = _bounded_text(request.title, "title", 500)
    rationale = _bounded_text(request.rationale, "rationale", 32_000)
    patch = _bounded_text(request.patch, "patch", 5_000_000)
    if not request.changed_paths:
        raise ProposalValidationError("at least one changed path is required")
    paths = tuple(_normalize_changed_path(path) for path in request.changed_paths)
    if len(set(paths)) != len(paths):
        raise ProposalValidationError("changed paths must be unique")
    patch_paths = _validate_patch_paths(patch)
    if patch_paths != frozenset(paths):
        raise ProposalValidationError(
            "embedded patch paths must exactly match declared changed_paths")
    checks = [_validate_check(check) for check in request.checks]
    replay = _validate_replay(request.replay)
    invariants = [
        _bounded_text(item, "invariant", 2_000)
        for item in request.invariants
    ]

    content: dict[str, bytes] = {
        "change.patch": (patch.rstrip("\n") + "\n").encode("utf-8"),
        "rationale.md": (
            f"# {title}\n\n{rationale}\n"
        ).encode("utf-8"),
        "invariants.json": _canonical_json({
            "declared": invariants,
            "authority_boundaries": [
                "proposal only",
                "no engine or ledger mutation",
                "no push, merge, deployment, or secret access",
                "ActionExecutor remains the only action execution path",
            ],
        }),
        "tests.json": _canonical_json({"checks": checks}),
        "replay.json": _canonical_json(replay),
        "policy.json": _canonical_json({
            "allowlist_version": ALLOWLIST_VERSION,
            "authority": "proposal_only",
            "changed_path_validation": [
                {"path": path, "allowed": True} for path in paths
            ],
            "network_access": False,
            "arbitrary_shell": False,
        }),
    }
    content_hashes = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in content.items()
    }
    content["manifest.json"] = _canonical_json({
        "format": PROPOSAL_FORMAT,
        "tenant_id": tenant_id,
        "proposal_id": proposal_id,
        "run_id": run_id,
        "builder_actor_id": builder_actor_id,
        "mandate_id": mandate_id,
        "skill_pack_version": skill_pack_version,
        "base_commit": request.base_commit,
        "candidate_commit": request.candidate_commit,
        "changed_paths": list(paths),
        "content_hashes": content_hashes,
        "bundle_hash_algorithm": "sha256(canonical ordered entry hashes)",
    })
    return content


def build_proposal_bundle(request: ProposalRequest) -> ProposalBundle:
    content = _proposal_content(request)
    entry_hashes = tuple(
        (name, hashlib.sha256(content[name]).hexdigest())
        for name in PROPOSAL_ENTRY_ORDER
    )
    bundle_hash = hashlib.sha256(
        _canonical_json([
            {"name": name, "sha256": digest}
            for name, digest in entry_hashes
        ])
    ).hexdigest()
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name in PROPOSAL_ENTRY_ORDER:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content[name])
    return ProposalBundle(output.getvalue(), bundle_hash, entry_hashes)


def _verify_stored_bundle(
    artifact_store: ArtifactStore,
    key: str,
    destination: Path,
    archive_bytes: bytes,
    expected_sha256: str,
) -> ArtifactMetadata | None:
    metadata = artifact_store.head(key)
    if metadata != ArtifactMetadata(
        key=key,
        sha256=expected_sha256,
        size_bytes=len(archive_bytes),
    ):
        return None
    downloaded = artifact_store.get_file(
        key, destination, expected_sha256=expected_sha256)
    if downloaded != metadata or destination.read_bytes() != archive_bytes:
        return None
    return metadata


class ProposalOnlyActionSink:
    """Accept exactly one non-authoritative action: immutable proposal creation."""

    def __init__(
        self,
        artifact_store: ArtifactStore,
        *,
        staging_directory: str | os.PathLike[str],
    ):
        self.artifact_store = artifact_store
        self.staging_directory = Path(staging_directory).resolve()

    def handle(
        self,
        action: str,
        request: ProposalRequest,
    ) -> ProposalReceipt:
        if action != "proposal.create":
            raise ProposalAuthorityError(
                f"proposal-only sink refuses authority action {action!r}")
        bundle = build_proposal_bundle(request)
        key = proposal_artifact_key(request.tenant_id, request.proposal_id)
        artifact_sha = hashlib.sha256(bundle.archive_bytes).hexdigest()
        self.staging_directory.mkdir(parents=True, exist_ok=True)
        fd, upload_name = tempfile.mkstemp(
            prefix=".proposal-", suffix=".zip", dir=self.staging_directory)
        upload = Path(upload_name)
        os.close(fd)
        fd, verify_name = tempfile.mkstemp(
            prefix=".proposal-verify-", suffix=".zip",
            dir=self.staging_directory)
        verify = Path(verify_name)
        os.close(fd)
        verify.unlink(missing_ok=True)
        try:
            with upload.open("wb") as handle:
                handle.write(bundle.archive_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                metadata = self.artifact_store.put_file(
                    key, upload, expected_sha256=artifact_sha)
            except ArtifactConflict as conflict:
                try:
                    metadata = _verify_stored_bundle(
                        self.artifact_store,
                        key,
                        verify,
                        bundle.archive_bytes,
                        artifact_sha,
                    )
                except (ArtifactError, OSError) as verification_error:
                    raise conflict from verification_error
                if metadata is None:
                    raise
            else:
                verified = _verify_stored_bundle(
                    self.artifact_store,
                    key,
                    verify,
                    bundle.archive_bytes,
                    artifact_sha,
                )
                if verified != metadata:
                    raise ProposalValidationError(
                        "uploaded proposal failed metadata or byte verification")
            return ProposalReceipt(
                tenant_id=request.tenant_id,
                proposal_id=request.proposal_id,
                artifact_key=key,
                artifact_sha256=metadata.sha256,
                artifact_size_bytes=metadata.size_bytes,
                bundle_hash=bundle.bundle_hash,
                changed_paths=request.changed_paths,
                check_ids=tuple(check.check_id for check in request.checks),
            )
        finally:
            upload.unlink(missing_ok=True)
            verify.unlink(missing_ok=True)
