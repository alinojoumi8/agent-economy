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
    "README.md", "getting-started.md", "civic-atlas.md", "research-guide.md",
    "architecture.md", "configuration.md", "api-reference.md",
    "operator-runbook.md", "troubleshooting.md", "development.md",
    "implementation-status.md", "live-provider-validation.md",
    "live-run-f7c6238bf5.md", "v2-guide.md", "implementation-status.html",
    "buzz-derived-architecture.md", "branch-lifecycle.md",
    "documentation-maintenance.md", "reproducibility-release-profile.md",
    "semantics14-external-turn-attendance.md", "adr/README.md",
    "adr/0001-owner-run-citizens-use-external-runtimes.md",
    "adr/0002-offline-owner-run-citizens-are-not-impersonated.md",
    "adr/0003-owner-run-citizen-profiles-are-generated-per-city.md",
    "adr/0004-civic-builder-authority-stops-at-the-world-boundary.md",
    "adr/0005-city-expansion-is-threshold-triggered-and-bounded.md",
    "adr/0006-city-scale-uses-a-strategic-core-and-deterministic-periphery.md",
    "adr/0007-builder-code-scope-is-allowlisted.md",
    "adr/0008-each-city-has-an-isolated-civic-builder.md",
    "adr/0009-builder-authority-has-independent-safety-and-governance-revocation.md",
    "adr/0010-cohort-personas-use-deterministic-bases-and-bounded-enrichment.md",
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
        "getting-started.md", "civic-atlas.md", "research-guide.md", "architecture.md",
        "configuration.md", "api-reference.md", "operator-runbook.md",
        "troubleshooting.md", "development.md",
        "reproducibility-release-profile.md",
    ):
        assert f"docs/{filename}" in readme


def test_reproducibility_profile_guide_keeps_local_and_release_claims_separate():
    guide = (ROOT / "docs/reproducibility-release-profile.md").read_text(
        encoding="utf-8"
    ).lower()
    for phrase in (
        "local-only evidence profile",
        "unknown profile fails closed",
        "every referenced receipt must use `execution_scope: local`",
        "passing `reproducibility-v1` cannot satisfy or waive any production gate",
        "does not run tests",
    ):
        assert phrase in guide


def test_civic_atlas_guide_preserves_projection_and_history_boundaries():
    guide = (ROOT / "docs/civic-atlas.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "the client does not invent them",
        "event payloads are not read",
        "a historical world pulse is read-only",
        "does not request current run status",
        "cannot enable mutation",
        "ephemeral runtime activity is live-only",
    ):
        assert phrase in guide


def test_readme_is_concise_and_research_first():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) <= 300
    assert readme.index("## Run one experiment") < readme.index(
        "## World OS expansion")
    for target in (
        "docs/branch-lifecycle.md",
        "docs/documentation-maintenance.md",
        "docs/semantics14-external-turn-attendance.md",
        "docs/adr/README.md",
    ):
        assert target in readme


def test_branch_and_documentation_workflows_preserve_safety_boundaries():
    branch = (ROOT / "docs/branch-lifecycle.md").read_text(
        encoding="utf-8").lower()
    assert "a dirty worktree is protected" in branch
    assert "git branch -d" in branch
    assert "explicit remote-deletion authorization" in branch
    assert "force deletion" in branch

    maintenance = (ROOT / "docs/documentation-maintenance.md").read_text(
        encoding="utf-8").lower()
    assert "source-of-truth hierarchy" in maintenance
    assert "frozen semantics-7 printable snapshot" in maintenance
    assert "implementation and release status are not conflated" in maintenance


def test_semantics14_guide_preserves_authorship_and_replay_contract():
    guide = (ROOT / "docs/semantics14-external-turn-attendance.md").read_text(
        encoding="utf-8").lower()
    for phrase in (
        "engine_semantics_version: 14",
        "explicitly submits",
        "safe_do_nothing_v1",
        "semantics 1–13",
        "no separate public attendance mutation endpoint",
        "never update, delete, or reconstruct source attendance",
    ):
        assert phrase in guide
    assert "do_nothing" in guide


def test_architecture_decisions_have_explicit_status_and_structure():
    adr_paths = sorted((ROOT / "docs/adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert len(adr_paths) == 10
    statuses = []
    for path in adr_paths:
        text = path.read_text(encoding="utf-8")
        assert "## Context" in text
        assert "## Decision" in text
        assert "## Consequences" in text
        match = re.search(r"^- \*\*Status:\*\* (Accepted|Proposed)$", text,
                          re.MULTILINE)
        assert match, f"{path.relative_to(ROOT)} lacks a valid ADR status"
        statuses.append(match.group(1))
    assert statuses.count("Accepted") == 3
    assert statuses.count("Proposed") == 7


def test_normative_contracts_cover_current_additive_boundaries_and_queue():
    prd = (ROOT / "PRD.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "maintained additive boundaries",
        "semantics 14 attendance",
        "proposal-only builder seam",
        "hosted audit chain",
    ):
        assert phrase in prd

    spec = (ROOT / "TECH-SPEC.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "projection, attendance, proposal, and audit boundaries",
        "external_turn_attendance",
        "builder_workspace/proposal_sink.py",
        "hosted migration 003",
    ):
        assert phrase in spec

    tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8").lower()
    assert "current consolidation queue — 2026-08-20" in tasks
    assert "historical execution backlog snapshot — 2026-08-05" in tasks
    assert (
        "docs/plans/2026-08-20-branch-and-documentation-consolidation-plan.md"
        in tasks
    )


def test_documented_profiles_exist():
    for profile in (
        "runs/base.yaml", "runs/production.yaml",
        "runs/acceptance/rehearsal.yaml", "runs/acceptance/pilot.yaml",
        "runs/acceptance/production.yaml",
        "runs/experiments/rumor_vs_control.yaml",
    ):
        assert (ROOT / profile).exists(), f"documented profile is missing: {profile}"


def test_hosted_compose_commands_pin_the_root_environment_file():
    runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
    compose_lines = [
        line.strip()
        for line in runbook.splitlines()
        if line.strip().startswith("docker compose")
        and "deploy/compose.yaml" in line
    ]
    assert compose_lines
    assert all(
        line.startswith("docker compose --env-file .env -f deploy/compose.yaml")
        for line in compose_lines
    )


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
    assert "schema 20 / semantics 14" in lowered
    assert "semantics 8 / schema 12" in lowered
    assert "**released deterministic causal baseline**" in lowered
    assert "semantics 9 / schema 13" in lowered
    assert "semantics 10 / schema 14" in lowered
    assert lowered.count("**rollout-gated**") >= 2
    assert "semantics 11 / schema 15" in lowered
    assert "semantics 12 / schema 17" in lowered
    assert "semantics 14 / schema 20" in lowered
    assert "historical semantics-7 closure matrix" in lowered

    status_indexes = {
        "README.md": "docs/implementation-status.md",
        "docs/README.md": "implementation-status.md",
        "docs/implementation-status.html": "implementation-status.md",
        "docs/world-os/README.md": "../implementation-status.md",
        "docs/world-os/PRD.md": "../implementation-status.md",
        "docs/world-os/TECH-SPEC.md": "../implementation-status.md",
        "docs/world-os/REQUIREMENTS-MATRIX.md": "../implementation-status.md",
        "docs/world-os/SEMANTICS-8-RELEASE-STATUS.md":
            "../implementation-status.md",
    }
    for relative_path, expected_target in status_indexes.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        escaped_target = re.escape(expected_target)
        markdown_link = re.search(
            rf"\[[^\]]+\]\({escaped_target}(?:#[^)]+)?\)",
            text,
        )
        html_link = re.search(
            rf"""href=["']{escaped_target}(?:#[^"']+)?["']""",
            text,
        )
        assert markdown_link or html_link, (
            f"{relative_path} does not link to {expected_target}")


def test_buzz_derived_architecture_documents_authority_and_history_boundaries():
    guide = (ROOT / "docs/buzz-derived-architecture.md").read_text(
        encoding="utf-8"
    ).lower()
    assert "does not copy buzz source code" in guide
    assert "historical projection drops it" in guide
    assert "explicitly submitted `do_nothing` remains submitted" in guide
    assert "no truthful civic builder runtime or mandate surface" in guide
    assert "not externally anchored" in guide
    assert "no nostr relay" in guide
    assert "no acp identity model" in guide
    assert "no randomized engine retry policy" in guide
    assert "no use of presence as economic truth" in guide


def test_full_suite_ci_uses_deterministic_cross_platform_shards():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"shard":[0,1,2,3,4,5,6,7]' in workflow
    assert "matrix: ${{ fromJSON(inputs.full_suite_matrix) }}" in workflow
    assert "python -m pytest tests/ -q" in workflow
    assert "-p scripts.pytest_shard" in workflow
    assert "--ci-shard-index ${{ matrix.shard }}" in workflow
    assert "--ci-shard-count 8" in workflow
    assert workflow.count("persist-credentials: false") == workflow.count(
        "uses: actions/checkout@v7")


def test_static_bundle_advisory_cannot_fail_when_diff_is_truncated():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    capture = workflow.index(
        'git --no-pager diff -- server/static > "$diff_file"')
    truncate = workflow.index('head -c 200000 "$diff_file"')
    summary = workflow.index('} >> "$GITHUB_STEP_SUMMARY"', truncate)
    assert capture < truncate < summary
    assert "git --no-pager diff -- server/static | head -c" not in workflow


def test_setup_docs_contain_supported_python_guard_and_uv_prerequisite():
    for relative_path in ("README.md", "docs/development.md"):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "sys.version_info[:2] in {(3, 11), (3, 12)}" in text

    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    assert "uv --version" in development


def test_scale_270_acceptance_commands_and_artifact_boundaries_are_documented():
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    lowered = development.lower()

    for profile in (
        "runs/acceptance/scale-270-baseline-120.yaml",
        "runs/acceptance/scale-270-recovery-120.yaml",
        "runs/acceptance/scale-270-recovery-1000.yaml",
    ):
        assert profile in development
        assert (ROOT / profile).is_file()
    for command_fragment in (
        "python scripts/run_scale_validation.py",
        "python -m reports.scale_economic_health",
        "--approve-live-inference",
        "reports/out/scale-270/",
        "benchmarks/receipts/scale-270/",
    ):
        assert command_fragment in development
    assert "provider-free profiles reject" in lowered
    assert "paid profiles require" in lowered
    assert "sqlite databases" in lowered
    assert "checkpoint bodies stay local" in lowered


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


def _catalog_reference_problem(reference: str, *, root: Path = ROOT) -> str | None:
    if not reference:
        return "missing test reference "
    resolved_root = root.resolve()
    candidate = (resolved_root / reference).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        return f"test reference is outside repository {reference}"
    if not candidate.exists():
        return f"missing test reference {reference}"
    return None


def test_catalog_reference_validation_rejects_paths_outside_repository(tmp_path):
    inside = tmp_path / "inside.py"
    inside.write_text("pass\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    escaped_link = tmp_path / "escaped.py"
    escaped_link.symlink_to(outside)

    assert _catalog_reference_problem("inside.py", root=tmp_path) is None
    assert "outside repository" in _catalog_reference_problem(
        "../outside.py", root=tmp_path)
    assert "outside repository" in _catalog_reference_problem(
        str(outside.resolve()), root=tmp_path)
    assert "outside repository" in _catalog_reference_problem(
        "escaped.py", root=tmp_path)
    assert "missing test reference" in _catalog_reference_problem(
        "missing.py", root=tmp_path)


def test_dirty_worktree_inventory_names_all_three_untracked_paths():
    text = (ROOT / "docs" / "reconciliation" /
            "2026-08-05-dirty-worktree-inventory.md").read_text(encoding="utf-8")
    for path in (
        "agents/numeric_grounding.py",
        "server/static/assets/MacroOverview-EGrWjdWA.js",
        "server/static/assets/index-C-RDqS0J.js",
    ):
        assert f"`{path}` (untracked)" in text


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
        # A catalog row may name a semicolon-separated verification matrix.
        for reference in (item.strip() for item in test_ref.split(";")):
            if problem := _catalog_reference_problem(reference):
                problems.append(f"{entry_id}: {problem}")
    assert not problems, "catalog structural issues:\n" + "\n".join(problems)
