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
  echo "secret-scan: install Gitleaks 8.21 or newer from the official releases." >&2
  echo "secret-scan: https://github.com/gitleaks/gitleaks/releases" >&2
  echo "secret-scan: commit blocked; install gitleaks or bypass deliberately with git commit --no-verify." >&2
  exit 1
fi

version_text="$(gitleaks version 2>/dev/null || true)"
if [[ ! "$version_text" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
  echo "secret-scan: cannot determine Gitleaks version: ${version_text:-unknown}." >&2
  echo "secret-scan: Gitleaks 8.21 or newer is required for fail-closed AND allowlists." >&2
  exit 1
fi
major="${BASH_REMATCH[1]}"
minor="${BASH_REMATCH[2]}"
if (( major < 8 || (major == 8 && minor < 21) )); then
  echo "secret-scan: Gitleaks ${BASH_REMATCH[0]} is too old; 8.21 or newer is required." >&2
  echo "secret-scan: the scan is blocked because older releases can over-allow configured paths." >&2
  exit 1
fi

if [[ ! -f "$config" ]]; then
  echo "secret-scan: ${config} missing; refusing to scan without the repository ruleset." >&2
  exit 1
fi

# --staged makes gitleaks diff the index, so partially staged files are
# judged exactly as they will be committed.
if ! gitleaks protect --source "$repo_root" --config "$config" --staged --no-banner --verbose --redact; then
  echo "" >&2
  echo "secret-scan: potential secrets in staged changes; commit blocked." >&2
  echo "secret-scan: remove the secrets, then 'git add' the fixed files again." >&2
  echo "secret-scan: false positive? Add a narrow allowlist entry to .gitleaks.toml." >&2
  exit 1
fi
