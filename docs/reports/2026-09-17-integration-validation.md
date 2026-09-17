# September 17 local integration validation

Candidate: `codex/verified-integration-20260917`, based on main `d3dc044`,
integrating the staging/storage/UI and operations line through `f3d84eb`.
Runtime fixes through `b6910cd`; private Docker context exclusions in `72a5dea`.
Original worktrees and branches remain intact. This receipt is local evidence,
not a main-branch merge, full release package, hosted certification or deployment.

## Completed in order

1. Combined the tested branches and native Passport callback fix in an isolated
   worktree; retained the current README and city guidance.
2. Reconciled the implementation/release ledgers with Semantics 17–20 and actual
   local provider/Hermes evidence.
3. Added a real Chromium OAuth test: approval reaches a second-port callback,
   PKCE exchange succeeds, denial returns correctly and an unregistered callback
   is rejected. A negative control with the former CSP failed as expected.
4. Ran installed Hermes with DeepSeek, two isolated citizens and three sessions
   each. Six actions executed, expiry/refresh/rotation worked, missed attendance
   remained distinct from submitted no-ops, and replay matched exactly. See the
   [native-client receipt](../integrations/hermes-local-validation.md).
5. Reviewed and exercised the integrated operations controls. A replacement
   PostgreSQL/world restore preserved receipts, balances and idempotency; the
   restored world advanced from tick 2 to tick 3. Six HTTPS load rounds passed
   all 600 requests with tenant-isolation denials. Alertmanager delivered both
   firing and resolved notifications to a disposable receiver.

## Checks executed

Python commands used the repository's existing `.venv/Scripts/python.exe`.
Each pytest command supplied a fresh ignored `--basetemp`.

| Command | Result |
|---|---|
| `python -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py tests/test_passport_citizenship.py` | 154 passed before the added arrival regression |
| `python -m pytest -q tests/test_external_agent_gateway.py tests/test_recorded_replay_golden.py tests/test_passport_citizenship.py` | 42 passed after the replay fix |
| `python -m pytest -q tests/test_ops_monitoring.py tests/test_hosted_load_test.py tests/test_hosted_app.py tests/test_hosted_storage.py tests/test_hosted_supervisor.py tests/test_security_review.py` | 66 passed, one environment-dependent skip |
| `npm --prefix dashboard test` | 280 passed |
| `npm --prefix dashboard run typecheck` | Passed |
| `npm --prefix dashboard run build` | Passed; committed bundle content unchanged; existing large-chunk advisory |
| `npm --prefix dashboard run test:e2e` with `AE_TEST_PYTHON` | 146 passed, two opt-in real-backend tests skipped |
| `python -m scripts.run_ops_drill --output .tmp/final-recovery-clean` | Passed; local disposable replacement, about 85 seconds of drill execution |
| `python -m scripts.alert_delivery_drill --output .tmp/final-alerts-clean` | Passed; firing and resolved delivery |
| `python run.py --replay native-hermes-rehearsal --replay-source-dir .tmp/native-hermes-replay-source --ticks 5` | Exact replay `replay-native-hermes-rehearsal-ef91ab88ce`, zero provider spend |
| `python run.py --verify-datasets config/data-manifest.yaml` | Passed |
| `python -m pip check` | Passed |
| `uvx pip-audit -r requirements.lock` | No known vulnerabilities |
| `npm --prefix dashboard audit --audit-level=high` | No vulnerabilities |
| `npm --prefix dashboard run licenses:check` | Passed |
| Gitleaks 8.30.1, current tracked tree and all Git refs, current `.gitleaks.toml`, redacted output | No leaks found |
| `git diff --check` | Passed |

The rebuilt operations image was inspected: `.tmp`, `tmp`, `.env`, `.git`,
browser failure artifacts and the local Graft cache are absent from `/app`.
Private profiles, raw native logs, databases and diagnostic logs remain ignored
local artifacts; they are not part of this receipt or a publication bundle.

## Failures retained and resolved

- Initial pytest setup lacked the parent temporary directory; rerun passed after
  creating it. This was not a product failure.
- The 16-worker browser run had five failures. Bounded-worker reruns passed;
  the style test now waits for its rendered element and the suite defaults to
  two workers. The final entire suite passed.
- The old consent CSP failed the browser negative control, as intended.
- Native token expiry exposed the installed Hermes clock race; a source patch
  and regression are preserved in the integration guide. The next attempt
  exposed the harness counting rejected submissions as accepted; the assertion
  was corrected. Failed attempts were not relabelled as successes.
- Native-world replay exposed attendance being imported before first-day
  arrival. Replay now defers attendance to MORNING; submitted/missed regression
  cases and the actual five-tick recording passed.
- The first alert attempt preceded creation of its required Docker test image.
  It was rerun after the image build and passed.
- `.tmp` was absent from Docker exclusions. The image was rebuilt with private
  artifacts excluded and replacement recovery repeated successfully.
- A tracked-tree secret scan treated adjacent empty API-key assignments in the
  env template as one multiline value. Separating the quoted empty placeholders fixed
  this false positive; no detector was disabled or broadened.

## Remaining release boundaries

Full cross-platform Python CI was not run locally. These focused checks do not
constitute the nine-gate reproducibility package or the 16-gate production package.
Public HTTPS, independent Hermes/OpenClaw/MCP/Python/TypeScript certification,
real off-server backup/alert destinations, and paid calibration/long-horizon
campaigns retain the requirements in the release ledger. No production service
was deployed. The local app and regular Hermes gateway are left stopped.
