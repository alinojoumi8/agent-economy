# Civic Atlas dashboard

Civic Atlas is the observer interface served at `http://127.0.0.1:8000` during
a local run. It reads authorized projections of a stored world; it does not own
economic mutation, bypass the ledger, or turn private provider/event payloads
into display data.

![World Pulse live briefing in Civic Atlas](images/civic-atlas-world-pulse.png)

## Start with the safe profile

```powershell
python run.py --config runs/base.yaml
```

Open <http://127.0.0.1:8000>, select the run, and enter Civic Atlas. The base
profile is provider-free. Any live-provider profile can incur cost and requires
its own preflight and authorization; see [configuration](configuration.md).

## Primary navigation

The permanent rail contains the five tasks used most often:

| Destination | Route | Use |
|---|---|---|
| Pulse | `/runs/:runId/overview` | Read the current or historical briefing, regional atlas, ledger invariant, and evidence-ranked events |
| City | `/runs/:runId/live-city` | Explore the recorded day in the full-screen city view |
| People | `/runs/:runId/people` | Inspect the Living Agents directory, journeys, projects, and evidence classes |
| Commons | `/runs/:runId/commons` | Read the public information economy |
| Evidence Lab | `/runs/:runId/investigations` | Trace committed events and maintain authorized investigation records |

Press `Ctrl+K` (or `Command+K` on macOS) to open the command palette. It also
reaches the deeper City evidence, Institutions, Markets, Politics & Law,
Communications, and Experiments workspaces. Hiding those routes from the main
rail does not remove them or change their URLs.

## World Pulse

World Pulse is the default briefing. It combines two observer-scoped sources:

- `/api/v2/workspaces/world` for public regions, residents, organizations, and
  aggregate flows;
- `/api/v2/snapshot?domains=summary,alerts,events` for the ledger invariant,
  alerts, and the public committed-event envelope.

The briefing ranks salience; it does not claim causation. **Open evidence**
links to Evidence Lab only when the projection supplies a valid committed event
identifier. Event payloads are not read. Region links require valid region
identifiers, and the atlas plots only coordinates exposed by the projection.
Missing positions stay visibly unpositioned; the client does not invent them.

The ledger invariant is reported as balanced only when the projected balance
is exactly zero. Missing evidence is shown as not reported, never as a measured
zero.

## Live and historical boundaries

The shared observer cursor is encoded in the URL. `tick=live` follows the
current projection; a numeric `tick` pins the interface to historical state.
`fork` preserves the selected lineage. Workspace-specific selections such as
`agent`, `place`, `project`, and `view` are validated before use.

A historical World Pulse is read-only. It does not request current run status,
show live run controls, or reconstruct current provider activity. Use **Return
to live** deliberately to leave the historical boundary.

On a live cursor, World Pulse offers Run, Pause, and Step. All controls remain
disabled until `/api/run/status` returns an authoritative state, while a
control request is in flight, and after a terminal status. A missing, stale, or
failed status therefore cannot enable mutation. Server-side validation remains
authoritative even when a button is enabled.

## Evidence, privacy, and display states

- Canonical settlement comes from stored events, receipts, and the ledger.
- Read-time projections expose only caller-authorized public fields.
- Ephemeral runtime activity is live-only and never substitutes for committed
  settlement or appears on a historical cursor.
- Loading, empty, unavailable, historical, stale, and disabled states keep
  explicit wording. A blank panel is not treated as evidence of zero activity.
- Hosted access, tenant scoping, CSRF, and private-field filtering remain server
  responsibilities; Civic Atlas does not infer identifiers or credentials.

For the broader ownership model, read [architecture](architecture.md). For
field-level REST and WebSocket contracts, read the [API reference](api-reference.md).

## Keyboard and narrow screens

Interactive regions, events, people, and command results are ordinary links or
buttons with visible focus. The rail collapses without removing navigation.
On narrow screens the evidence inspector moves below the primary field and the
reading order remains Pulse/City content before supporting evidence. Reduced
motion settings suppress nonessential motion without hiding state.

## Dashboard development verification

From `dashboard/`:

```powershell
npm ci
npm test
npm run typecheck
npm run licenses:check
npm run build
npm run test:e2e -- --project=chromium
```

The build writes the production bundle to `server/static/`. Commit source,
tests, documentation, and regenerated static assets together. The full local
gate and focused CI layers are documented in [development](development.md).

To refresh the maintained screenshot after an intentional World Pulse visual
change, set `CAPTURE_CIVIC_ATLAS_SCREENSHOT=1` while running the Playwright test
named `overview enters the exact causal chain`, then review the image before
committing it.
