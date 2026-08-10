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
hook_path="$(git rev-parse --git-path hooks/pre-commit)"
if [[ "$hook_path" = /* ]]; then
  hook="$hook_path"
else
  hook="${repo_root}/${hook_path}"
fi
backup="$(dirname -- "$hook")/pre-commit.agent-economy-original"
marker="# agent-economy: secret scan wrapper v2 (scripts/secret_scan.sh)"
legacy_marker="# agent-economy: secret scan (scripts/secret_scan.sh)"

if [[ -f "$hook" ]] && grep -qF "$marker" "$hook"; then
  echo "pre-commit secret scan already installed."
  exit 0
fi

legacy_managed=false
if [[ -f "$hook" ]] && grep -qF "$legacy_marker" "$hook"; then
  if diff -q "$hook" <(printf '%s\n' \
    '#!/usr/bin/env bash' \
    "$legacy_marker" \
    'set -e' \
    'scripts/secret_scan.sh --staged') >/dev/null; then
    legacy_managed=true
  fi
fi

if [[ -f "$hook" ]] && [[ "$legacy_managed" != true ]]; then
  if [[ -e "$backup" ]]; then
    echo "pre-commit backup already exists; refusing to overwrite: ${backup}" >&2
    exit 1
  fi
  # Run the existing hook as a child process so its `exit` cannot skip the
  # mandatory scan in the wrapper. Preserve its contents and mode verbatim.
  cp -p -- "$hook" "$backup"
fi

mkdir -p -- "$(dirname -- "$hook")"
cat > "$hook" <<'EOF'
#!/usr/bin/env bash
# agent-economy: secret scan wrapper v2 (scripts/secret_scan.sh)
set -u

repo_root="$(git rev-parse --show-toplevel)" || exit 1
hook_path="$(git rev-parse --git-path hooks/pre-commit)" || exit 1
if [[ "$hook_path" = /* ]]; then
  hook_dir="$(dirname -- "$hook_path")"
else
  hook_dir="$(cd -- "${repo_root}/$(dirname -- "$hook_path")" && pwd)" || exit 1
fi
original_hook="${hook_dir}/pre-commit.agent-economy-original"

if [[ -x "$original_hook" ]]; then
  "$original_hook" "$@" || exit $?
fi
"${repo_root}/scripts/secret_scan.sh" --staged
EOF
chmod +x "$hook"

if [[ -f "$backup" ]]; then
  echo "installed secret-scan wrapper; preserved existing hook: ${backup}"
else
  echo "installed pre-commit secret-scan wrapper: ${hook}"
fi
