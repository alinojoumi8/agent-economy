#!/usr/bin/env bash
# Commit-time secret scan using the repository's .gitleaks.toml.
#
# Runs `gitleaks protect --staged` so only staged changes are scanned, which
# matches what a pre-commit hook is authorizing. Fails closed: any detection
# or a missing gitleaks binary aborts the commit.
#
# Usage: scripts/secret_scan.sh [--staged]
#   --staged  scan staged changes only (default, and the pre-commit mode)
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
config="${repo_root}/.gitleaks.toml"

if [[ "${1:-}" != "--staged" && -n "${1:-}" ]]; then
  echo "usage: $0 [--staged]" >&2
  exit 2
fi

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "secret-scan: gitleaks not found on PATH." >&2
  echo "secret-scan: install it (Ubuntu: sudo apt-get install gitleaks)" >&2
  echo "secret-scan: https://github.com/gitleaks/gitleaks/releases" >&2
  echo "secret-scan: commit blocked; install gitleaks or bypass deliberately with git commit --no-verify." >&2
  exit 1
fi

if [[ ! -f "$config" ]]; then
  echo "secret-scan: ${config} missing; refusing to scan without the repository ruleset." >&2
  exit 1
fi

# --staged makes gitleaks diff the index, so partially staged files are
# judged exactly as they will be committed.
if ! gitleaks protect --source "$repo_root" --config "$config" --staged --no-banner --verbose; then
  echo "" >&2
  echo "secret-scan: potential secrets in staged changes; commit blocked." >&2
  echo "secret-scan: remove the secrets, then 'git add' the fixed files again." >&2
  echo "secret-scan: false positive? Add a narrow allowlist entry to .gitleaks.toml." >&2
  exit 1
fi
