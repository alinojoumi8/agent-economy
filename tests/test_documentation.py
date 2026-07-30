import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_CASES_PATH = ROOT / "docs" / "test-cases.md"
VALID_TIERS = {
    "fast-offline",
    "full-offline",
    "hosted-integration",
    "live-provider",
    "release-evidence",
}
VALID_STATUSES = {
    "existing-coverage",
    "newly-automated",
    "opt-in-gate",
    "contractual-gap",
}
EXTENSION_GROUPS = (
    "EXT-GATEWAY",
    "EXT-COMMONS",
    "EXT-COGNITION",
    "EXT-CITIZENSHIP",
    "EXT-LIVECITY",
)
ENTRY_HEADING = re.compile(r"^### (AE-[A-Z0-9-]+)\s*$", re.MULTILINE)
FIELD = re.compile(r"^- \*\*([a-z_]+)\*\*: (.+)$", re.MULTILINE)
MAINTAINED_ROOT_DOCS = (
    "README.md", "PRD.md", "TECH-SPEC.md", "TASKS.md",
    "CONTRIBUTING.md", "SECURITY.md",
)
HANDBOOK_DOCS = (
    "README.md", "getting-started.md", "research-guide.md",
    "architecture.md", "configuration.md", "api-reference.md",
    "operator-runbook.md", "troubleshooting.md", "development.md",
    "implementation-status.md", "live-provider-validation.md",
    "live-run-f7c6238bf5.md", "v2-guide.md", "implementation-status.html",
)
CLOSURE_STATUS_DOCS = (
    "README.md", "TECH-SPEC.md", "TASKS.md",
    "docs/implementation-status.md", "docs/v2-guide.md",
    "docs/implementation-status.html",
)
SEMANTICS_7_MERGE_COMMIT = "255555c2b24530c0bd39aed2f501277a468adc0a"
SEMANTICS_7_POST_MERGE_CI = "29368193807"
STALE_SEMANTICS_7_MERGE_PHRASES = (
    "codex/legal-political-economy-v2",
    "merge after exact-head ci",
    "must still pass all five github actions jobs before merge",
    "require five of five successful jobs before ready/merge",
    "exact pushed head must pass",
    "required immediately before merge",
    "required at merge",
    "the merge procedure requires",
    "before pr #15 is made ready and merged",
)


def _local_links(document: Path):
    text = document.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = target.strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        yield target
    if document.suffix == ".html":
        for target in re.findall(r'href=["\']([^"\']+)["\']', text):
            target = target.strip()
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            yield target


def test_maintained_documentation_has_no_broken_local_links():
    documents = [ROOT / name for name in MAINTAINED_ROOT_DOCS]
    documents.extend(ROOT / "docs" / name for name in HANDBOOK_DOCS)
    missing = []
    for document in documents:
        assert document.exists(), f"missing maintained document: {document}"
        for target in _local_links(document):
            local_path = target.split("#", 1)[0]
            if not (document.parent / local_path).exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not missing, "broken local documentation links:\n" + "\n".join(missing)


def test_readme_exposes_safe_entrypoint_and_complete_handbook():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python run.py --config runs/base.yaml" in readme
    assert "without `--config` selects the live production" in readme
    for filename in (
        "getting-started.md", "research-guide.md", "architecture.md",
        "configuration.md", "api-reference.md", "operator-runbook.md",
        "troubleshooting.md", "development.md",
    ):
        assert f"docs/{filename}" in readme


def test_documented_profiles_exist():
    for profile in (
        "runs/base.yaml", "runs/production.yaml",
        "runs/acceptance/rehearsal.yaml", "runs/acceptance/pilot.yaml",
        "runs/acceptance/production.yaml",
        "runs/experiments/rumor_vs_control.yaml",
    ):
        assert (ROOT / profile).exists(), f"documented profile is missing: {profile}"


def test_semantics_7_closure_status_records_merged_main_and_post_merge_ci():
    for relative_path in CLOSURE_STATUS_DOCS:
        document = ROOT / relative_path
        text = document.read_text(encoding="utf-8")
        lowered = text.lower()
        assert SEMANTICS_7_MERGE_COMMIT in text, (
            f"{relative_path} is missing the semantics-7 merge commit")
        assert SEMANTICS_7_POST_MERGE_CI in text, (
            f"{relative_path} is missing the post-merge CI run")
        assert "merged" in lowered, f"{relative_path} does not record the merged state"
        assert "tag" in lowered and "publication" in lowered, (
            f"{relative_path} does not preserve the no-tag/publication boundary")
        for stale_phrase in STALE_SEMANTICS_7_MERGE_PHRASES:
            assert stale_phrase not in lowered, (
                f"{relative_path} retains stale pending-merge text: {stale_phrase}")


def test_current_release_status_has_one_authoritative_ledger():
    status = (ROOT / "docs/implementation-status.md").read_text(encoding="utf-8")
    lowered = status.lower()
    assert "single maintained release-status" in lowered
    assert "ledger" in lowered
    assert "schema 17 / semantics 12" in lowered
    assert "semantics 8 / schema 12" in lowered
    assert "**released deterministic causal baseline**" in lowered
    assert "semantics 9 / schema 13" in lowered
    assert "semantics 10 / schema 14" in lowered
    assert lowered.count("**rollout-gated**") >= 2
    assert "semantics 11 / schema 15" in lowered
    assert "semantics 12 / schema 17" in lowered
    assert "historical semantics-7 closure matrix" in lowered

    status_indexes = (
        "README.md",
        "docs/README.md",
        "docs/implementation-status.html",
        "docs/world-os/README.md",
        "docs/world-os/PRD.md",
        "docs/world-os/TECH-SPEC.md",
        "docs/world-os/REQUIREMENTS-MATRIX.md",
        "docs/world-os/SEMANTICS-8-RELEASE-STATUS.md",
    )
    for relative_path in status_indexes:
        text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        assert "implementation-status" in text, (
            f"{relative_path} does not defer current release labels to the ledger")


def test_full_suite_ci_uses_deterministic_cross_platform_shards():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "shard: [0, 1, 2, 3, 4, 5, 6, 7]" in workflow
    assert "python -m pytest tests/ -q" in workflow
    assert "-p scripts.pytest_shard" in workflow
    assert "--ci-shard-index ${{ matrix.shard }}" in workflow
    assert "--ci-shard-count 8" in workflow


def _parse_test_case_catalog(text: str) -> dict[str, dict[str, str]]:
    matches = list(ENTRY_HEADING.finditer(text))
    entries: dict[str, dict[str, str]] = {}
    for index, match in enumerate(matches):
        entry_id = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        fields = {key: value.strip() for key, value in FIELD.findall(body)}
        entries[entry_id] = fields
    return entries


def test_prd_traceable_test_catalog_structure_and_references():
    assert TEST_CASES_PATH.exists(), "docs/test-cases.md is required"
    text = TEST_CASES_PATH.read_text(encoding="utf-8")
    entries = _parse_test_case_catalog(text)
    assert entries, "catalog must contain AE-* entries"

    requirements = {
        fields.get("requirement", "") for fields in entries.values()
        if fields.get("requirement", "").startswith("R")
    }
    missing_requirements = [
        f"R{number}" for number in range(1, 33)
        if f"R{number}" not in requirements
    ]
    assert not missing_requirements, (
        "catalog is missing requirements: " + ", ".join(missing_requirements))

    extension_requirements = {
        fields.get("requirement", "") for fields in entries.values()
        if fields.get("requirement", "").startswith("EXT-")
    }
    missing_extensions = [
        group for group in EXTENSION_GROUPS if group not in extension_requirements
    ]
    assert not missing_extensions, (
        "catalog is missing extension groups: " + ", ".join(missing_extensions))

    required_fields = (
        "requirement", "risk", "preconditions", "given", "when", "then",
        "oracle", "test", "tier", "status",
    )
    problems = []
    for entry_id, fields in sorted(entries.items()):
        for field in required_fields:
            if field not in fields or not fields[field]:
                problems.append(f"{entry_id}: missing {field}")
        tier = fields.get("tier", "")
        status = fields.get("status", "")
        if tier not in VALID_TIERS:
            problems.append(f"{entry_id}: invalid tier {tier!r}")
        if status not in VALID_STATUSES:
            problems.append(f"{entry_id}: invalid status {status!r}")
        test_ref = fields.get("test", "").strip()
        if status == "contractual-gap" or test_ref in {"", "none", "-"}:
            continue
        # Catalog may reference a file or a directory-like path relative to repo root.
        candidate = ROOT / test_ref
        if not candidate.exists():
            problems.append(f"{entry_id}: missing test reference {test_ref}")
    assert not problems, "catalog structural issues:\n" + "\n".join(problems)
