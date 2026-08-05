# Agent Economy PRD-Traceable Test Suite

## Summary

- Create `docs/test-cases.md`, mapping PRD requirements R1-R32 and the Gateway, Commons, cognition, citizenship, and Live City specifications to automated evidence.
- Preserve existing coverage and add only missing high-risk tests. The planning baseline was 879 Python tests collected, 59 focused Python tests passed, 44 dashboard tests passed, and 9 Playwright tests passed.
- Prioritize restore/cursor recovery, privacy outside primary responses, and duplicate or late action completion.

## Implementation changes

### Test catalog and traceability

- Give every catalog entry a stable ID using `AE-R01-001` for numbered requirements or `AE-EXT-GATEWAY-001` for extension contracts.
- Record the requirement, risk, preconditions, Given/When/Then steps, expected oracle, automated test reference, execution tier, and status.
- Use these execution tiers:
  - `fast-offline`
  - `full-offline`
  - `hosted-integration`
  - `live-provider`
  - `release-evidence`
- Use statuses that distinguish existing coverage, newly automated coverage, opt-in gates, and contractual gaps.
- Extend `tests/test_documentation.py` with a structural guard that verifies:
  - Every requirement from R1 through R32 appears.
  - Gateway, Commons, cognition, citizenship, and Live City extension groups appear.
  - Referenced local test files exist.
  - Execution tier and status values are valid.

### Deterministic automated cases

#### Projection recovery

- Extend the dashboard cursor reducer tests to start from cursor N, receive the existing `cursor_ahead` message with cursor M where M is less than N, and verify that the cursor resets to M.
- Mark the projection stale, invalidate the World OS query once, and refetch canonical data.
- Ignore delayed deltas from an old run, fork, semantics version, projection version, policy version, or view key.
- Accept the next contiguous M-to-M+1 delta.
- Clear the stale warning only after canonical data arrives.
- Add a Playwright scenario that simulates checkpoint restore or server restart and verifies that old payloads never render and recovery does not enter a refetch loop.

#### Live City truth states

- Add focused Playwright coverage for loading, empty, API error, disconnected, paused, failed, historical, and live states.
- Cover observed, derived, and mixed coordinate provenance.
- Assert that status labels, alerts, marks, and fallback explanations match the actual transport and run state.
- Assert that failed or empty responses do not invent agents.
- Verify that clearing search restores visible marks and that navigation preserves the selected run and tick.
- Retain keyboard, reduced-motion, responsive mobile, and focus behavior checks.

#### Browser privacy

- Seed unique privacy canaries into private communications and restricted metadata.
- Verify that an unauthorized thread detail request returns 404.
- Prove that canaries do not appear in the DOM, URL, local storage, session storage, console output, or transport error messages.
- Verify the same behavior after navigation, reconnect, and historical-tick changes.

#### External-action exactly-once behavior

- Retry a submission with the same idempotency key and assert that the same receipt is returned.
- Deterministically interleave two calls to `ExternalAgentService.complete()` after both observe a queued submission.
- Assert one terminal database transition, one terminal event, one result set, one resulting state hash, and one action or ledger effect.
- Call `complete()` again after execution, rejection, revocation, and decision-window expiry and assert that it is a no-op.
- Replay the run without client network access and assert equality of the action, event IDs, ledger effects, state hash, and final canonical replay hash.

#### Secondary-channel and export privacy

- Reuse unique canaries across unauthorized API and projection responses, errors, logs, metrics, traces, replay artifacts, and default research exports.
- Add canaries to external-action `action_json`, `rationale_summary`, `result_json`, and `validator_results_json`.
- Add all four fields to `external_action_submissions` in hash-contract-v2's `default_export_redactions`.
- Assert that default exports contain no canary bytes and that the manifest records the redactions.
- Preserve non-sensitive status, event IDs, and integrity evidence.
- Keep hash-contract-v1 unchanged.

### Minimal production corrections

Only make these production changes when required by the new tests:

- Teach the dashboard cursor reducer and socket hook to recover from the existing `cursor_ahead` transport message.
- Make external-action completion atomic with `UPDATE ... WHERE id=? AND status='queued'`, and emit the terminal event only when exactly one row changes.
- Extend hash-contract-v2's default-export redaction policy for external-action data.

Do not add a new public API, database migration, operation ID, source key, stream epoch, or wire format as part of this work.

### CI policy

- Add a `pull_request` trigger to `.github/workflows/ci.yml`.
- Run focused PRD, replay, documentation, gateway, and export Python tests on every pull request.
- Run dashboard unit tests, typecheck, build, license and audit checks, and the critical Chromium Playwright specifications routinely.
- Keep the full Python matrix, PostgreSQL/S3/Docker integrations, real-provider smoke, 100/1,000-agent benchmarks, and 365-day release evidence behind their existing explicit opt-in gates.
- Never report an opt-in gate as passing unless it was executed successfully for the current checkout.

## Public interfaces

- No intentional public API, database schema, client interface, or transport-envelope changes.
- The new stable test-case IDs and execution-tier values become the documentation contract used by the structural guard.
- The `cursor_ahead` behavior remains within the existing WebSocket message format.

## Verification

Run the focused suite:

```powershell
python -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py
```

Run the full offline Python suite:

```powershell
python -m pytest tests/ -q
```

Run the dashboard gates from `dashboard`:

```powershell
npm.cmd test
npm.cmd run typecheck
npm.cmd run test:e2e -- world-os.spec.ts world-os-states.spec.ts world-os-privacy.spec.ts agent-connections.spec.ts
npm.cmd run build
npm.cmd run licenses:check
npm.cmd audit --audit-level=high
```

Run repository hygiene checks:

```powershell
git diff --check
```

Acceptance requires:

- The catalog contains R1-R32 and every named extension group.
- Every catalog reference and classification passes the documentation guard.
- All new deterministic tests pass.
- The full offline Python suite passes or every failure is reported with exact evidence.
- Dashboard unit, typecheck, build, and critical Playwright gates pass.
- Routine CI is green.
- Every unexecuted hosted, live-provider, load, or long-duration gate is clearly identified as pending.

## Assumptions and boundaries

- Preserve all existing dirty work on the `ui` branch.
- Existing tests remain the source of truth where they already prove a requirement; do not duplicate them only to increase test count.
- Missing product surfaces, including browser-level investigation conflict and export workflows, are recorded as contractual gaps rather than implemented under this test-focused plan.
- Apply the smallest in-scope fix for a real defect exposed by a new test.
- Document larger architectural or product gaps separately instead of expanding implementation scope.
