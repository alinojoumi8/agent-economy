# Dirty Living-Economy Worktree Inventory — 2026-08-05

## Preservation boundary

The registered `feature/living-economy-map` worktree remains dirty and unmodified at `c86a9cf2662345209f6fa4698e149705678a9087`. Its registered `/home/ali/...` path resolves to `/mnt/data/projects/agent-economy/.worktrees/living-economy-map` on this machine.

The restorable package is `/home/ali/.codex/worktree-snapshots/agent-economy/living-economy-map-20260805/`. It contains the binary tracked patch, the empty staged patch, all three untracked files, literal metadata, and SHA-256 checksums. Gitleaks 8.30.1 found no leaks. A detached restoration rehearsal reproduced the tracked, staged, and untracked hashes exactly before its temporary worktree was removed.

Allowed dispositions are `equivalent`, `superseded`, `portable`, `needs-design`, and `generated`.

## Path and contract matrix

| Dirty path | Hunk/contract | Current-main evidence | Disposition | Destination task | Verification |
|---|---|---|---|---|---|
| `run.py` | `_hydrate_resumed_world` restores terminal report and normalizes stale `running` | Current `run.py:_hydrate_resumed_world`; `tests/test_compatibility_guards.py` already asserts both contracts and all 30 compatibility tests pass. | equivalent | Resume closure | Compatibility and report-narrative tests. |
| `tests/test_compatibility_guards.py` | Resume hydration regressions | Equivalent tests are already on current main. | equivalent | Resume closure | 30/30 current tests pass. |
| `run.py` | `activate_entrepreneurship_for_run` and resume-only CLI | Current main has forward-only activation patterns for supply recovery and output budgets, but no entrepreneurship activation helper. | portable | Entrepreneurship activation | New paused/idempotent/boundary tests plus replay guards. |
| `run.py` | `activate_numeric_grounding_for_run` and resume-only CLI | No equivalent helper; current `open_run` already has multiple guarded forward-only activations that must be preserved. | portable | Numeric grounding | Activation tests and compatibility replay. |
| `runs/base.yaml` | Numeric grounding defaults | No current grounding config. Enabling from tick zero changes only new runs; persisted runs retain stored config. | portable | Numeric grounding | Profile validation and feature-off replay tests. |
| `runs/native-entrepreneurship.yaml` | Formation cap, pre-seed, and merger policy settings | Existing profile has bounded native entry but lacks these lifecycle settings. | portable | Entrepreneurship lifecycle | Profile plus end-to-end lifecycle tests. |
| `agents/numeric_grounding.py` | Pure numeric extraction, source comparison, and sanitization | No current module; engine projections remain authoritative. | portable | Numeric grounding | Pure decimal/currency/percent tests, including malformed and boundary cases. |
| `agents/memory.py` | Step-bound LLM updates to existing reserved beliefs | Current main enforces finite/ranged values and provenance but not per-call model step limits. | portable | Numeric grounding | Reserved-belief baseline, feature-off, and provenance tests. |
| `agents/prompts.py` | Grounding suffix, authoritative facts, unit-aware money, stale-memory labels | Current prompts have current structured facts and public projections but no explicit numeric hierarchy. Must integrate with semantics 12, recovery context, and current cent rendering. | portable | Numeric grounding | Prompt snapshot/behavior tests; no source-text assertions alone. |
| `agents/runtime.py` | Sanitize public reasoning and condensed memories while retaining raw `llm_calls` | Current runtime persists raw governed calls and public rationale; no numeric sanitizer. Must integrate after current communication/civic/workforce paths. | portable | Numeric grounding | Real parsed-envelope and persisted-proposal tests. |
| `world/newsroom.py` | Reject editor arithmetic, sanitize conversations, and project stored articles | Current newsroom already validates source event identity and public visibility but does not validate copied numeric claims. | portable | Public narratives | Grounded/ungrounded article and conversation tests. |
| `reports/generate.py` | Reject report arithmetic absent from bounded summary | Current report path has bounded summary and provenance fallback. | portable | Public narratives | Provider-adapter regression with persisted call and engine fallback. |
| `server/replay.py` | Redact unsupported stored news numbers during replay projection | Current replay projection is public but has no numeric claim marker. | portable | Public narratives | Historical replay projection regression. |
| `server/app.py` | `/api/news` uses the public grounded projection | Current endpoint returns stored rows directly. | portable | Public narratives | API test at pre/post activation boundaries. |
| `server/app.py` | Local `/api/v2/mode` returns `api_base: /api` | Current main already implements local and hosted-safe mode probing with `api_base: /api/v2`; dirty value is obsolete. | superseded | None | Existing `tests/test_r21_api.py` local/hosted probes. |
| `tests/test_information_completion.py` | Numeric newsroom grounding and stored projection | Unique behavior test. | portable | Public narratives | Focused newsroom suite. |
| `tests/test_report_narrative.py` | Ungrounded report arithmetic fallback | Unique behavior test. | portable | Public narratives | Focused report suite. |
| `tests/test_p1_harness_and_tools.py` | Replay redacts unsupported historical news number | Unique public-replay behavior. | portable | Public narratives | Replay reader suite. |
| `tests/test_research_validity.py` | Belief bounds, prompt hierarchy, public reasoning, activation | Unique behavior, but pure-function tests need expanded source-grounding coverage. | portable | Numeric grounding | Focused research-validity suite. |
| `world/metrics.py` | Entrepreneurship metrics begin only at activation | Current metrics expose entrepreneurship whenever config exists, including pre-boundary ticks. | portable | Entrepreneurship activation | Pre/post activation metrics regression. |
| `agents/prompts.py` | Entrepreneurship activation and staggered review schedule | Current opportunity is enabled immediately and arrival-relative. Staggering is needed for an established population. | portable | Entrepreneurship activation | Six-agent review distribution and pre-boundary absence tests. |
| `engine/actions.py` | Per-tick native formation cap | Current executor validates authorization/ownership but does not cap same-tick native formations. | portable | Entrepreneurship activation | Two-authorized-founder atomic capacity test. |
| `agents/prompts.py` | Autonomous pre-seed pitch | Current startup work exists, but model-free progression from native formation is absent. | portable | Entrepreneurship lifecycle | Engine-owned action exposure and stale/duplicate rejection tests. |
| `agents/prompts.py` | IP registration after any financing work | Dirty code permits IP after a pending pitch; the approved invariant requires completed financing. | needs-design | Entrepreneurship lifecycle | Add a failing test that IP is absent until a funding round is closed. |
| `agents/prompts.py` | State-derived autonomous merger proposal/approve/close | Current merger engine owns validation and pricing surfaces. Dirty deterministic candidate logic is useful but must not bypass civic/competition authorization or current semantics 12 contexts. | needs-design | Entrepreneurship lifecycle | Engine-derived terms, capacity, stale marker, regulator review, and exact replay tests. |
| `tests/test_native_entrepreneurship.py` | Activation, cap, and historical pre-boundary formation | Unique compatible contracts. | portable | Entrepreneurship activation | Focused native entrepreneurship suite. |
| `tests/test_native_entrepreneurship.py` | Lifecycle test expects IP while financing is merely open | Contradicts the approved completed-financing invariant. | superseded | Entrepreneurship lifecycle | Replace with a test that requires a closed round. |
| `dashboard/src/api.js` | Unit-aware metric deltas, bank trust precision, belief formatting | Current helpers format generic numbers and can mislabel unemployment deltas as raw values. | portable | Public UI | Helper unit tests and component rendering. |
| `dashboard/src/components/MacroOverview.jsx` | Correct macro units and unemployment definition | Current delta path uses generic decimals. | portable | Public UI | SSR and browser snapshot. |
| `dashboard/src/components/AgentsPanel.jsx` | Trust precision plus provenance/staleness labels | Current panel shows generic precision and no numeric-authority warning. | portable | Public UI | SSR and Chrome modal flow. |
| `dashboard/src/components/InformationPanels.jsx` | Unsupported-number badge | Requires the public article projection flag. | portable | Public UI | API plus SSR/browser test. |
| `dashboard/src/components/ReplayModal.jsx` | Metric units and redaction marker | Current replay modal uses generic two-decimal formatting. | portable | Public UI | SSR/browser replay flow. |
| `dashboard/src/components/RunHeader.jsx` | Distinguish completed tick from partial active tick | Current API exposes both values but header shows only completed day. | portable | Public UI | SSR and Chrome paused-partial-run state. |
| `dashboard/src/components/WorldPanels.jsx` | Bank trust precision | Current panel truncates to two decimals. | portable | Public UI | SSR and browser bank panel. |
| `dashboard/tests/living-economy-map.test.js` | Partial-day header regression | Unique compatible test. | portable | Public UI | Dashboard unit gate. |
| `dashboard/tests/observatory-interaction.test.js` | Units, precision, authority labels, redaction badge | Unique compatible tests. | portable | Public UI | Dashboard unit gate. |
| `tests/test_r21_api.py` | Local mode probe with `/api` base | Current main has stronger local and hosted-safe probes using `/api/v2`. | superseded | None | Existing R21 API tests. |
| `server/static/index.html` | Vite asset references | Generated from dirty dashboard source and stale against current dependency graph. | generated | Static rebuild | Byte-identity freshness check after accepted source ports. |
| `server/static/assets/MacroOverview-DbuP8jkX.js` | Removed old generated chunk | Generated. | generated | Static rebuild | Vite build and static diff. |
| `server/static/assets/index-1fE8mSIa.js` | Removed old generated chunk | Generated. | generated | Static rebuild | Vite build and static diff. |
| `server/static/assets/MacroOverview-EGrWjdWA.js` | New untracked generated chunk | Hash-preserved in snapshot; never port directly. | generated | Static rebuild | Vite build output owns final name. |
| `server/static/assets/index-C-RDqS0J.js` | New untracked generated chunk | Hash-preserved in snapshot; never port directly. | generated | Static rebuild | Vite build output owns final name. |

## Closure rules

- No hunk is ported merely because it existed in the dirty tree; every `portable` or redesigned contract begins with a failing test on current main.
- The obsolete feature branch will not be merged.
- Generated assets are rebuilt only from accepted source and verified byte-for-byte against a second build.
- Historical runs remain feature-off before their persisted activation ticks.
