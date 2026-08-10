from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_installer_wraps_existing_hook_before_running_secret_scan(tmp_path):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    installer = scripts / "install_precommit_hook.sh"
    shutil.copy2(ROOT / "scripts" / installer.name, installer)
    scanner = scripts / "secret_scan.sh"
    scanner.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'scan %s\\n' \"$*\" >> \"$TRACE_FILE\"\n",
        encoding="utf-8",
    )
    scanner.chmod(0o755)

    hook = repo / ".git" / "hooks" / "pre-commit"
    original = (
        "#!/usr/bin/env bash\n"
        "printf 'original\\n' >> \"$TRACE_FILE\"\n"
        "exit 0\n"
    )
    hook.write_text(original, encoding="utf-8")
    hook.chmod(0o755)

    trace = tmp_path / "hook.trace"
    env = {**os.environ, "TRACE_FILE": str(trace)}
    subprocess.run([str(installer)], cwd=repo, env=env, check=True)
    installed = hook.read_text(encoding="utf-8")

    subprocess.run([str(hook)], cwd=repo, env=env, check=True)

    backup = hook.with_name("pre-commit.agent-economy-original")
    assert backup.read_text(encoding="utf-8") == original
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "original",
        "scan --staged",
    ]
    assert "# agent-economy: secret scan" in installed

    subprocess.run([str(installer)], cwd=repo, env=env, check=True)
    assert hook.read_text(encoding="utf-8") == installed
