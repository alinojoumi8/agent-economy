# Draft PR #10 reconciliation

PR #10 (`release/v1-acceptance`) diverged from the hardened release line: nine
PR-only commits versus twelve local-main-only commits at review time. A dry
merge produced content and generated-asset conflicts across runtime control,
provider configuration, acceptance, tests, and dashboard code. It must not be
merged directly.

## Disposition

| PR area | Disposition | Reason |
|---|---|---|
| `acceptance/campaigns.py`, `acceptance/evidence.py`, `runs/acceptance/v1.yaml` | Superseded | The current `reports/acceptance.py` uses one inherited production profile, phase-aware durable progress, reviewed phenomena input, experiment attachment, and JSON/Markdown receipts. Importing the PR package would create a second acceptance authority. |
| K2.6 and MiniMax-only production profiles | Not ported | Current live preflight proves the configured MiniMax M3 plus Kimi Code routes. The PR itself records that its required K2.6 Platform credential was unavailable. |
| Finalized/halted run controls and speed synchronization | Ported into the refactored controller/dashboard | These are useful operator safeguards, but PR #10 changed the pre-refactor route closure. The behavior now lives in `server/controller.py` with focused API coverage. |
| Complete handbook additions | Selectively ported and rewritten | `docs/README.md`, `operator-runbook.md`, and `troubleshooting.md` now document the current CLI, phase cursor, 429/529 cooldowns, uncapped production, and evidence contract. Outdated campaign commands were not copied. |
| Conversation-diversity prompt expansion | Deferred from this reconciliation | The current conversation phase gathers responses before deterministic writes and has resume-safe request keys. A prompt-contract change during a live acceptance would invalidate a single-commit evidence claim; any future diversity change must land before a fresh acceptance run with its own regression gate. |
| Generated Vite assets | Rebuilt from current source | Bundles are never selected from the divergent branch by filename.

## Verification required for the replacement PR

- current full Python and dashboard suites;
- production dashboard build;
- focused controller transition tests;
- live provider preflight;
- resumed-run proof with unique request keys;
- fresh CI against the replacement branch;
- completed acceptance and exact replay evidence before release.
