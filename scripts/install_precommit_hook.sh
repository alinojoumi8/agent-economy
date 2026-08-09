#!/usr/bin/env bash
# Install (idempotently) the pre-commit secret-scan hook for this clone.
#
# .git/hooks is per-clone and not version-controlled, so run this once per
# fresh checkout:  scripts/install_precommit_hook.sh
#
# The hook invokes scripts/secret_scan.sh --staged, which runs
# `gitleaks protect --staged` with the repository's .gitleaks.toml and
# blocks the commit on any detection (fail-closed).
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
hook="${repo_root}/.git/hooks/pre-commit"
marker="# agent-economy: secret scan (scripts/secret_scan.sh)"

if [[ -f "$hook" ]] && grep -qF "$marker" "$hook"; then
  echo "pre-commit secret scan already installed."
  exit 0
fi

if [[ -f "$hook" ]]; then
  # Preserve an existing hook; append the scan step.
  printf '\n%s\nscripts/secret_scan.sh --staged\n' "$marker" >> "$hook"
  echo "appended secret scan to existing pre-commit hook: ${hook}"
else
  cat > "$hook" <<EOF
#!/usr/bin/env bash
${marker}
set -e
scripts/secret_scan.sh --staged
EOF
  echo "installed pre-commit secret scan hook: ${hook}"
fi
chmod +x "$hook"
