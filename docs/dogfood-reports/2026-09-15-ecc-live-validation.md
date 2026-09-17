# ECC live validation — 15 September 2026

Scope: exercise the running app, fix observed UI defects, and keep live simulation work below the user's 150-tick ceiling. Used ECC's e2e-testing and verification-loop skills. Automated test fixtures are separate from the live simulation allocation.

## Fixes

- Provider budget display preserves fractional dollar caps and four-decimal recorded spend. A $0.50 cap previously appeared as $1.
- Freshness badges distinguish the event feed cursor from the projection's committed simulation tick.
- Geography-free 3D worlds no longer call Three.js `add()` with no objects. The console-error regression failed before the fix and passed afterward.
- Stopping during an incomplete day now explains why no report was produced, in Pulse, 3D controls, and Classic Observatory. The explanation survives page reload. Checkpoint and economic semantics are unchanged.
- Rebuilt the production dashboard assets in `server/static`.

## Real app coverage

Exercised the workspace navigation, Pulse controls, 2D/3D city, keyboard entity selection, camera/filter controls, agent evidence, market price history, and a narrow mobile viewport. Verified actual API status and SQLite records in addition to mocked browser tests.

Live-provider run `053c8ee6b3` used `runs/hermes-deepseek-minimax.yaml` with a 30-tick ceiling. DeepSeek and MiniMax preflight inference succeeded. Stopped after six complete ticks, during day seven EVENING, while testing pause/stop behavior. Its 375 recorded model calls cost $0.16165412 (API display $0.1617); preflight billing is outside that run ledger. SQLite quick_check returned `ok`; all 384 ledger entries reconcile by transaction. The preserved checkpoint is `data/checkpoints/053c8ee6b3_t6.db`. The backend deliberately deferred its report because day seven is incomplete.

Populated-city run `c1550910fe` used `runs/simcity.yaml`, 300 agents, a 120-tick ceiling, and the scripted provider. It automatically paused at tick 120 with no active partial day or remaining ticks. Stop + report succeeded (HTTP 200), creating `reports/out/run_c1550910fe_t120.html` and checkpoint `data/checkpoints/c1550910fe_t120.db`. All 69,820 ledger entries reconcile by transaction; SQLite quick_check returned `ok`. There were 19,738 scripted calls at zero provider cost before report completion.

Total live exercise: 126 complete simulation ticks plus the partial seventh day of the provider run, below 150. Both runs ended with `running=false`. No ERROR or CRITICAL events were found in either run log. Servers remain on localhost ports 8000 and 8001 for inspection; neither simulation is advancing.

## Verification

- `npm --prefix dashboard test`: 280 passed.
- `npm --prefix dashboard run typecheck`: passed.
- `npm --prefix dashboard run build`: passed; existing large-chunk warning remains.
- `npm --prefix dashboard run test:e2e -- city-viewport.spec.ts world-os.spec.ts --workers=2`: 52 passed before the added incomplete-day notice test.
- The added World Pulse incomplete-day notice browser test: 1 passed, including reload persistence.
- `./.venv/Scripts/python.exe -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py --basetemp tmp/ecc-pytest-20260915`: 145 passed in 166.41 seconds; one existing Starlette/httpx deprecation warning.
- Gitleaks 8.30.1 scans of `dashboard/src`, `dashboard/tests`, and `server/static`: no leaks found.
- `git diff --check`: passed.
- No dashboard lint script is configured; coverage percentage was not measured. This is bounded validation, not a full release audit.

Local raw logs are in ignored `tmp/ecc-*.log`; simulation databases and checkpoints remain local.

## Limits observed

Semantics-11 household finances correctly report that complete Semantics-20 history is required. Scripted stock/job/capacity rejections and live action-budget rejections were enforced outcomes, not engine exceptions. The 300-agent run records occasional synchronous event-loop stalls; this UI patch does not alter economic execution or claim to resolve throughput performance. Mobile coverage used browser emulation, not a physical device.
