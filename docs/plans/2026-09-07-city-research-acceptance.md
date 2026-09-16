# Production city and price-study acceptance

This closes the automated W4 workflow check using the actual production frontend,
FastAPI projections, deterministic world engine, supervised studies and private
bundle verifier. Goods and equities remain equally primary. It does not establish
economic realism, research-scale performance or completion of the proposed human
usability sessions; W5-W9 remain on the roadmap.

## Command and isolation

After installing the locked Python dependencies and `dashboard` dependencies,
install Chromium with `npm --prefix dashboard exec playwright install chromium`.
Build changed frontend source with `npm --prefix dashboard run build`, then run:

```powershell
python scripts/city_research_acceptance.py
```

The driver prints a fresh output directory. `--output-root <new-directory>` may
choose its location but refuses an existing target. Windows requires 40 GiB free;
the bounded Linux CI run requires 5 GiB. Each execution owns its server on an
ephemeral loopback port, all simulation/replay/checkpoint/report paths, operator
workspace and child processes. It stops only those processes and retains output
on failure. No cleanup of earlier evidence is part of this command.

The `city-research-acceptance.yaml` profile extends the scripted Semantics 16 price
profile with one region and city places. Fourteen ordinary residents plus the
institutional roles currently produce 25 agents. Three real simulation days
produce places, goods sales and an equity execution. The world pauses before
the browser starts. The driver rejects external-provider activity in this fixture.

The separate Playwright config uses the committed `server/static` bundle. It has
no Vite server, HTTP mocks or application test-control endpoints. The normal
mocked browser suite is unchanged. Freeze source files throughout this command:
study admission and replay verification retain the real source identity.

## Required observations

1. At the historical execution day, select an employed person, save an observation
   or event bookmark, change renderer, and follow a firm into goods/equity prices.
   Check the displayed equity price against the actual fixture trade.
2. Return to the city and use browser Back without losing the recorded day or
   firm. Reload the page and restore the operator bookmark.
3. At 390 px, find the person in List and select them with the keyboard. All
   historical navigation must avoid live runtime/status/conversation requests.
4. Return explicitly to Live. Draft, validate, reload the reviewed protocol and
   launch one G2 and one F2 study sequentially through ordinary UI controls. Each
   uses seeds 1 and 2, an eight-day horizon, intervention day 3, a 180-second wall
   limit and a 128-MiB evidence budget. Every comparison contains both domains.
5. Require four completed, eligible attempts per study and zero external calls
   or spend. Inspect both comparison panels and the preserved-attempt table.
6. Download each private archive, bind its bytes and SHA-256 to the export receipt,
   then import it into another new directory with the independent bundle verifier.
7. Compare full SQLite logical dumps before and after the workflow, including
   the independent imports. The original world must remain paused at day 3 with
   exactly unchanged contents. Only operator bookmark/research writes are allowed
   through the browser. Browser runtime errors and cleanup failures fail the gate.

The driver caps the browser at ten minutes; Playwright uses short action timeouts
and a longer explicit allowance only for supervised study completion. A failed
assertion is not retried into a new study inside the same evidence directory.

## Evidence and CI

`acceptance.json` records the original world hash, final hash, population/day,
study IDs, eligible-attempt counts, archive hashes, independent import verdicts
and elapsed time. `browser.log`, screenshots and failure traces aid diagnosis.
Private study archives, databases and traces remain in the local output directory.
The required CI job runs the same command and retains only the receipt and browser
log for seven days. The dashboard job separately verifies source/build parity.

Executed results and remaining limitations are recorded in the
[implementation log](2026-09-06-research-city-execution.md).
