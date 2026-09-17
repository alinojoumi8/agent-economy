# Branch merge readiness, September 11, 2026

Requested scope: fetch and assess `simcity`, merge the research branch if
complete, update DeepSeek and launch a bounded local demonstration.

The initial working tree was clean. `git fetch origin` fetched `origin/simcity`.
No source branch, worktree, stored run or remote ref was deleted or rewritten.

## Research branch

`codex/research-city-price-lab` at `7bb8aa144da3ad8fee4ea89e9e997b42eb93382b`
contains 39 commits above `origin/main`, with no main-only commits. PR #82 is
still a draft. Most current checks passed, but the saved-world study execution
and operator recovery check was cancelled. The execution record explicitly
leaves scenario admission, native horizon/full-prefix verification, inventory
completion and W6-W9 open. Its PR description still describes the earlier
`ca6c1cf` checkpoint. It does not satisfy the requested completion condition.

## Simcity

`origin/simcity` at `669dc37` has four unique commits relative to the research
branch, which has 87 commits absent from Simcity. No Simcity PR exists.
Read-only `git merge-tree --write-tree` trials against both main and the
research branch report conflicts in engine/schema/migrations, replay/export
contracts, API and dashboard files.

The Simcity change reuses migration 19 for urban development and changes the
existing `research/hash-contract-v2.json` schema inventory and table lists.
These require a deliberate additive port with a new semantics/schema/hash
contract compatible with current main, preserving frozen replay contracts.
Choosing one side of the conflicts wholesale is not an acceptable integration.

Neither branch was merged. A separate `codex/deepseek-v41-demo` branch preserves
the provider update on the current research baseline. The demo uses the
existing Semantics 7 smoke world and does not claim to demonstrate Simcity's
unmerged Blender assets or the research branch's newer demographic semantics.
