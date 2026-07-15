import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
