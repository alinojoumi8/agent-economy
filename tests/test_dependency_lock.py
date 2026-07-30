"""Guard the requirements.txt -> requirements.lock contract.

CI and the Docker image install with `pip install --require-hashes -r
requirements.lock`, so a direct requirement that never made it into the lock is
invisible locally and fails only in those environments. That happened with
Jinja2: it was added to requirements.txt on 2026-07-23 but the lock was last
regenerated on 2026-07-18, so `import server.citizenship_api` raised
ImportError in every lock-installed environment.
"""

import re
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _normalize(name: str) -> str:
    """PEP 503 normalization, minus any extras marker."""
    return re.sub(r"[-_.]+", "-", name.split("[")[0].strip()).lower()


def _direct_requirements() -> set[str]:
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        names.add(_normalize(re.split(r"[<>=!~;]", line)[0]))
    return names


def _locked_requirements() -> set[str]:
    locked = set()
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==", line)
        if match:
            locked.add(_normalize(match.group(1)))
    return locked


def test_every_direct_requirement_is_pinned_in_the_lock():
    missing = sorted(_direct_requirements() - _locked_requirements())
    assert not missing, (
        f"requirements.txt declares {missing} with no pin in requirements.lock; "
        "regenerate with `uv pip compile requirements.txt --universal "
        "--python-version 3.11 --generate-hashes -o requirements.lock`"
    )


def test_lock_pins_are_exact_and_hashed():
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==\S+", text, flags=re.MULTILINE)
    assert pins, "requirements.lock contains no pinned requirements"
    unhashed = [
        pkg for pkg, tail in re.findall(
            r"^([A-Za-z0-9_.-]+)==[^\n]*\n((?:[ \t]+[^\n]*\n)*)", text, flags=re.MULTILINE)
        if "--hash=" not in tail
    ]
    assert not unhashed, f"lock entries without hashes: {unhashed}"


def test_template_rendering_modules_import_under_the_lock():
    """The module whose dependency the lock previously omitted."""
    module = import_module("server.citizenship_api")
    assert hasattr(module, "install_citizenship_routes")
    assert hasattr(module, "navigation_document")
