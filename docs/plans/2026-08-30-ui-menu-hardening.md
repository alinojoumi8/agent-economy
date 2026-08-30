# UI menu hardening plan

Date: 2026-08-30
Working branch: `codex/ui-menu-hardening`
Backend policy: freeze economic semantics and paid-provider work unless a UI
failure proves that a read contract is missing or incorrect.

Status: implementation and UI verification complete; awaiting review and merge.

## Outcome

Every product destination and every workspace menu must be discoverable,
selectable, reload-safe, keyboard-operable, usable at 390 px, and honest about
loading, empty, unavailable, historical, disabled, and stale data. Shared
observer context (`fork`, `tick`, and committed-event focus) must survive route
changes. Private fields and current-only telemetry must never appear in a
historical or unauthorized view.

## Acceptance contract

A menu is complete only when all applicable checks pass:

1. Its destination is visible without knowing a keyboard shortcut.
2. The selected item has a programmatic state (`aria-current`,
   `aria-pressed`, or a native selected value).
3. A copied URL and a reload restore the same authorized view.
4. Discrete view changes participate in browser Back and Forward; high-volume
   text/filter edits may replace the current history entry.
5. Route changes preserve the selected run, fork, and tick and discard only
   workspace-local parameters.
6. Loading, empty, error, disabled, historical, and stale states contain no
   invented data and leave safe navigation available.
7. Keyboard operation, focus return, reduced motion, and 390 px layout work.
8. Mocked browser contracts and a real provider-free deterministic run both
   pass without console errors or failed requests.
9. Source, tests, user documentation, and the committed production bundle agree.

## Menu inventory and verification ledger

| Surface | Menus and controls in scope | Required proof | State |
|---|---|---|---|
| Product menu | Observatory, World OS, Commons, Join, My Agents | Server-advertised links, active state, same-tab routing, hosted omissions | Existing unit/browser coverage passes; hosted-only destinations remain outside local smoke scope |
| Workspace rail | Pulse, City, People, Commons, Evidence Lab, City evidence, Institutions, Markets, Politics & Law, Communications, Experiments | All 11 links visible, grouped, active, and preserving fork/tick on desktop, collapsed rail, and mobile | Fixed; focused browser regression passes |
| Command menu | Route search, authorized people/firms/events/threads, keyboard selection, empty/error states | Ctrl/Command-K, focus trap/return, route fallback when entity search fails, privacy-safe results | Existing browser coverage passes |
| Shared cursor | Live, numeric tick travel, fork preservation, freshness disclosure | Reload and cross-workspace preservation; historical views do not consume live telemetry | Existing unit/browser coverage passes |
| Pulse | Signal selection, region atlas, evidence links, Run/Pause/Step | Fail-closed controls, selected event URL, historical read-only boundary, empty/error states | Mocked browser coverage and provider-free real-run smoke pass |
| City | Full-screen recorded-day renderer and Workspaces return link | Run context, safe return navigation, no invented current state | Mocked browser coverage and provider-free real-run smoke pass |
| People | Directory search, person selection, paging, project kind/status, project/person evidence links | Validated IDs, stale-request rejection, URL/reload/history, empty/error states, mobile stacking | Fixed; focused browser regression and provider-free real-run smoke pass |
| Commons | Chronological/Hot, causal-trace links | Selected state, canonical URL, reload/history, historical no-poll boundary | Fixed; focused browser regression passes |
| Evidence Lab | Investigation selection/create, graph/table selection, zoom, edit, pin, hypothesis, export, conflict and navigation guards | Operator authority, CSRF, version conflict recovery, redacted export, mutation failures | Existing unit/browser coverage passes; provider-free real-run read smoke passes |
| City evidence | Region/place selection plus Atlas/2.5D and All/Work/Comms/Markets/Civic/Health controls | Invalid selection cleanup, place precedence, URL history, table containment | Existing browser coverage and provider-free real-run menu smoke pass |
| Institutions | Search; type, sector, region, status, active-only filters; typed detail selection; contracts/disclosures | Typed canonical IDs, ambiguous legacy-ID recovery, URL/reload/history, keyboard selection, private-field omission | Fixed; focused browser regression and provider-free real-run smoke pass |
| Markets | Orders, Trades, FX, Circuit breakers; side/status filters; institution/evidence links | Every view renders, filters reset by view, reload/history, units and empty evidence | Fixed; focused browser regression passes |
| Politics & Law | Legislation, Lobbying, Legal, M&A | Every view renders, reload/history, retained rows hidden when systems are disabled | Fixed; focused browser regression passes |
| Communications | Ordinary, Agent view, Truth inspector; agent ID, thread filter, thread/message selection | Access mode and agent scope in URL, deep-link reload/history, audit warning, unauthorized 404 | Fixed; focused browser regression passes |
| Experiments | Evidence, Rehearsals, Forecasts, Campaigns, Inputs; campaign selection | Every view renders, reload/history, historical action guard, current-only omission | Fixed; focused browser regression passes |
| Classic Observatory | Section links, run controls, participant actions, Oracle/report actions | Pending-request interruption, failures, modal focus, canonical World OS handoff | Existing browser coverage passes; provider-free real-run handoff smoke passes |
| Hosted access and owner tools | Sign in/Use invite, agent connection lifecycle | Role/scope gating, CSRF, no browser credential persistence, mutation failure recovery | Existing unit/browser coverage passes; out of deterministic local smoke scope |

## Execution order

1. Repair global discoverability and shared route behavior.
2. Verify every internal menu with URL, reload, Back/Forward, and state checks.
3. Exercise all workspaces against a real provider-free run.
4. Run desktop, 390 px, keyboard, reduced-motion, privacy, and accessibility gates.
5. Update the Civic Atlas user guide and documentation index.
6. Regenerate the production bundle, run the full repository gate appropriate to
   the changed surface, commit, push, and open a focused pull request.

## Evidence log

- Baseline on `main` commit `b426255e2f58903582a89bca1a9997ab3c2164fe`:
  193 dashboard unit tests passed; TypeScript passed; production build passed;
  60 Playwright tests passed.
- Branch fixes: all 11 rail destinations render; Commons exposes selected state;
  deep-dive view changes use browser history; Communications persists its access
  mode and agent scope; People and Institutions preserve filters across detail,
  reload, and browser history; rapid filter changes no longer collapse People.
- Provider-free real-backend smoke passed against run `cd7f21fb54`: the UI
  advanced the run to tick 3 and exercised every workspace, every deep-dive view,
  product navigation, command-menu focus return, People project filters, City
  evidence layers, the full-screen City return path, and the Classic Observatory
  handoff without browser console errors or failed browser requests.
- Complete operator documentation now lives in [Civic Atlas](../civic-atlas.md),
  with an opt-in real-backend test recipe in that guide and
  [development](../development.md).
- Final local gates: 193 dashboard unit tests passed; TypeScript passed; the
  clean-install license check passed; `npm audit --audit-level=high` reported
  zero vulnerabilities; the production bundle built; 65 mocked Playwright tests
  passed with the one opt-in real test skipped; that real test passed separately;
  and the focused Python gate passed 142 tests with one upstream Starlette
  deprecation warning.
- Paid/network-provider validation remains deliberately paused.

## Non-blocking follow-up

Loading Classic Observatory during the real-backend smoke produced two
`server.loop.stalled` watchdog warnings (1.50 s and 1.75 s) while
`oracle_calibration` ran `aggregate_calibration`. The browser contract still
passed. Profile or move that read off the event loop in a separate backend
performance change; it is not a menu correctness failure and this branch does
not alter the backend.

Vite also logged `ws proxy ECONNABORTED` while the smoke deliberately moved
quickly between pages and closed their sockets. The browser-side collector saw
no request failures or console errors. Keep the warning visible in future smoke
reviews in case it begins to coincide with a user-visible reconnect failure.
