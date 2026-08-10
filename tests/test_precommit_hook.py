from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
V2_MARKER = "# agent-economy: secret scan wrapper v2 (scripts/secret_scan.sh)"
V1_HOOK = (
    "#!/usr/bin/env bash\n"
    "# agent-economy: secret scan (scripts/secret_scan.sh)\n"
    "set -e\n"
    "scripts/secret_scan.sh --staged\n"
)


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _prepared_repo(tmp_path: Path, *, hooks_path: str | None = None):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    configured_hooks_path = hooks_path or ".git/hooks"
    subprocess.run(
        ["git", "config", "core.hooksPath", configured_hooks_path],
        cwd=repo,
        check=True,
    )

    installer = scripts / "install_precommit_hook.sh"
    shutil.copy2(ROOT / "scripts" / installer.name, installer)
    scanner = scripts / "secret_scan.sh"
    _write_executable(
        scanner,
        "#!/usr/bin/env bash\n"
        "printf 'scan %s\\n' \"$*\" >> \"$TRACE_FILE\"\n",
    )
    hook_dir = repo / configured_hooks_path
    return repo, installer, scanner, hook_dir


def _run(path: Path, repo: Path, trace: Path, *, check: bool = True):
    env = {**os.environ, "TRACE_FILE": str(trace)}
    return subprocess.run(
        [str(path)], cwd=repo, env=env, check=check, capture_output=True,
        text=True,
    )


def test_installer_wraps_existing_hook_before_running_secret_scan(tmp_path):
    repo, installer, _scanner, hook_dir = _prepared_repo(tmp_path)
    hook = hook_dir / "pre-commit"
    original = (
        "#!/usr/bin/env bash\n"
        "printf 'original\\n' >> \"$TRACE_FILE\"\n"
        "exit 0\n"
    )
    _write_executable(hook, original)

    trace = tmp_path / "hook.trace"
    _run(installer, repo, trace)
    installed = hook.read_text(encoding="utf-8")
    _run(hook, repo, trace)

    backup = hook.with_name("pre-commit.agent-economy-original")
    assert backup.read_text(encoding="utf-8") == original
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "original",
        "scan --staged",
    ]
    assert V2_MARKER in installed

    _run(installer, repo, trace)
    assert hook.read_text(encoding="utf-8") == installed


def test_wrapper_propagates_scanner_failure(tmp_path):
    repo, installer, scanner, hook_dir = _prepared_repo(tmp_path)
    _write_executable(scanner, "#!/usr/bin/env bash\nexit 9\n")
    trace = tmp_path / "hook.trace"
    _run(installer, repo, trace)

    result = _run(hook_dir / "pre-commit", repo, trace, check=False)

    assert result.returncode == 9


def test_original_hook_failure_aborts_before_scanner(tmp_path):
    repo, installer, _scanner, hook_dir = _prepared_repo(tmp_path)
    hook = hook_dir / "pre-commit"
    _write_executable(
        hook,
        "#!/usr/bin/env bash\n"
        "printf 'original\\n' >> \"$TRACE_FILE\"\n"
        "exit 7\n",
    )
    trace = tmp_path / "hook.trace"
    _run(installer, repo, trace)

    result = _run(hook, repo, trace, check=False)

    assert result.returncode == 7
    assert trace.read_text(encoding="utf-8").splitlines() == ["original"]


def test_installer_upgrades_managed_v1_hook_without_backup(tmp_path):
    repo, installer, _scanner, hook_dir = _prepared_repo(tmp_path)
    hook = hook_dir / "pre-commit"
    _write_executable(hook, V1_HOOK)
    trace = tmp_path / "hook.trace"

    _run(installer, repo, trace)
    _run(hook, repo, trace)

    assert V2_MARKER in hook.read_text(encoding="utf-8")
    assert not hook.with_name("pre-commit.agent-economy-original").exists()
    assert trace.read_text(encoding="utf-8").splitlines() == ["scan --staged"]


def test_installer_honors_configured_hooks_path(tmp_path):
    repo, installer, _scanner, hook_dir = _prepared_repo(
        tmp_path, hooks_path=".custom-hooks")
    trace = tmp_path / "hook.trace"

    _run(installer, repo, trace)
    hook = hook_dir / "pre-commit"
    _run(hook, repo, trace)

    assert V2_MARKER in hook.read_text(encoding="utf-8")
    assert not (repo / ".git/hooks/pre-commit").exists()
    assert trace.read_text(encoding="utf-8").splitlines() == ["scan --staged"]


def test_secret_scan_invokes_gitleaks_with_redaction():
    source = (ROOT / "scripts" / "secret_scan.sh").read_text(encoding="utf-8")

    assert "--verbose --redact" in source
    assert 'required_version="8.30.1"' in source


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_gitleaks_allowlisted_path_still_detects_unexpected_key(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    shutil.copy2(ROOT / ".gitleaks.toml", repo / ".gitleaks.toml")
    candidate = repo / ".env.example"
    candidate.write_text("KIMI_API_KEY=\n", encoding="utf-8")
    subprocess.run(["git", "add", ".env.example"], cwd=repo, check=True)

    configured_command = [
        "gitleaks", "protect", "--source", str(repo),
        "--config", str(repo / ".gitleaks.toml"), "--staged",
        "--no-banner", "--verbose", "--redact",
    ]
    allowed = subprocess.run(
        configured_command, cwd=repo, capture_output=True, text=True)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr

    credential_value = hashlib.sha256(
        b"agent-economy-credential-regression").hexdigest()
    creds_value = hashlib.sha256(b"agent-economy-creds-regression").hexdigest()
    fixture = (
        f"credential={credential_value}\n"
        f"creds={creds_value}\n"
    )
    candidate.write_text(fixture, encoding="utf-8")
    subprocess.run(["git", "add", ".env.example"], cwd=repo, check=True)

    default_repo = tmp_path / "default-repo"
    default_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=default_repo, check=True)
    (default_repo / ".env.example").write_text(fixture, encoding="utf-8")
    subprocess.run(
        ["git", "add", ".env.example"], cwd=default_repo, check=True)
    default_command = [
        "gitleaks", "protect", "--source", str(default_repo), "--staged",
        "--no-banner", "--verbose", "--redact",
    ]

    for command, source_repo in (
        (default_command, default_repo),
        (configured_command, repo),
    ):
        detected = subprocess.run(
            command, cwd=source_repo, capture_output=True, text=True)
        output = detected.stdout + detected.stderr
        plain_output = re.sub(r"\x1b\[[0-9;]*m", "", output)
        assert detected.returncode != 0
        assert credential_value not in output
        assert creds_value not in output
        assert "credential=REDACTED" in plain_output
        assert "creds=REDACTED" in plain_output
