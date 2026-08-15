# Semantics 13: agent-built construction economy

Semantics 13 adds an opt-in construction economy in which agents propose,
permit, fund, and build places through the normal action executor. Living
Agents and Live City remain observer-only: neither surface can assign work,
fund a project, or mutate a run.

The contract uses schema 19. Runs recorded with Semantics 1–12 keep their
original mechanics and exact replay behavior. The migration is additive and
does not rewrite a stored source run.

## Lifecycle and physical stages

The canonical lifecycle is:

`proposed → permitting → funding → building → completed`

`cancelled` is the terminal alternative. A project records its owner,
initiating agent, region, stable site key and coordinates, target place type,
permit case, escrow account, funding and work requirements, exact
contributions, milestone ticks, resulting place, and evidence references.

Physical construction is derived only from stored work units:

| Stage | Exact condition |
|---|---|
| Foundation | Project is fully funded and stored work is below one third of the requirement |
| Frame | Stored work is at least `ceil(required_work_units / 3)` |
| Shell | Stored work is at least `ceil(2 * required_work_units / 3)` |
| Completed | Stored work meets the requirement and the operational place is created |

Before building, the map labels the lifecycle state rather than inventing a
physical completion percentage. A cancelled project retains its last stored
physical stage when work exists.

## Ownership, actions, and authorization

Projects support agent-owned private homes, firm-owned workplaces, and
agency-owned public facilities. The strict Semantics 13 commands are:

- `propose_construction`
- `apply_construction_permit`
- `decide_construction_permit`
- `contribute_construction_funding`
- `perform_construction_work`
- `cancel_construction`

An agent may propose or cancel its own home. A founder or authorized manager
controls a firm workplace. An active regional permit clerk controls an agency
facility and decides submitted permits. Living agents may contribute funding
or work to eligible projects. Every command carries a durable deduplication key;
reusing it with a different payload fails with an idempotency-conflict receipt.

A site key resolves to deterministic coordinates and cannot host another
non-cancelled project. Work costs cannot exceed the deterministic share of the
project budget for the submitted work units. Currency mismatches, missing
permits, incomplete funding, insufficient balances, unauthorized decisions,
overfunding, excessive work, and terminal-project actions reject without
partial writes.

## Ledger and place boundary

Funding moves from the contributor's checking account to the project escrow.
Wages move from escrow to the worker, procurement moves from escrow to the
construction-materials system account, and unspent escrow is refunded
proportionally to the original funding accounts on cancellation or completion.
All movements are ordinary balanced ledger transactions.

An unfinished project is never inserted into `places`. Completion creates the
operational place exactly once, links it to the project, records a completion
event, refunds remaining escrow, and refreshes routine residence/workplace
leases. This keeps a construction silhouette distinct from a usable building.

## Observer projections and privacy

- `GET /api/v2/construction-projects` accepts `tick`, `fork_id`,
  `project_kind`, `status`, `after`, and `limit`.
- `GET /api/v2/construction-projects/{project_id}` returns one historical-safe
  project plus contribution-type totals.
- `GET /api/v2/world-map` exposes construction through the optional
  `construction_projects` layer.
- The World and Living Agents workspaces include the same projection.

Public facilities, workplaces, and policy-authorized core homes retain exact
project and site identifiers. Peripheral private homes are aggregated by
region, lifecycle status, and physical stage. The aggregate omits owners,
initiators, exact sites, permit links, place links, contributor identities, and
reversible evidence references. Historical visibility reconstructs the
owner's tier at the selected tick; a later promotion cannot reveal an earlier
private site.

Live City accepts stable `project=<id>` observer state alongside `agent` and
`place`; these selections are mutually exclusive and survive refresh and
browser history. Atlas and deck.gl render the same stored-unit stages. QTown
informed only the map/feed/list composition: no QTown code or assets were
copied, and PixiJS is not a dependency.

## Opt-in profile

[`runs/construction-live.yaml`](../runs/construction-live.yaml) extends the
bounded live civic profile and enables Semantics 13. It still requires the live
provider preflight inherited from `civic-live.yaml`.

```yaml
engine_semantics_version: 13
construction:
  enabled: true
  agent_initiation: true
  private_home_funding_cents: 20000
  workplace_funding_cents: 60000
  public_facility_funding_cents: 80000
  private_home_work_units: 4
  workplace_work_units: 8
  public_facility_work_units: 10
  funding_contribution_cents: 10000
  work_units_per_action: 2
```

## Verification

```powershell
python -m pytest -q tests/test_semantics13_construction.py tests/test_semantics8_foundations.py
npm.cmd --prefix dashboard test
npm.cmd --prefix dashboard run typecheck
npm.cmd --prefix dashboard run build
npm.cmd --prefix dashboard run test:e2e -- --project=chromium
```
