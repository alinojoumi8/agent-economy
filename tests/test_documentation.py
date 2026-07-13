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
    "live-run-f7c6238bf5.md",
)


def _local_links(document: Path):
    text = document.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = target.strip().strip("<>")
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
