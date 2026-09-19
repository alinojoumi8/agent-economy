# Geography, exploration and settlements

Frontier version 1 adds a persistent map to the semantics-11 Hermes world.
Enable it in a fresh configuration with `frontier: {version: 1, activation_tick: 0}`.
It is opt-in: legacy runs and other semantics retain their behavior. Version 1
rejects existing regional economies and other semantics; later household/time
contracts require their own integration before this option can be used there.

## Existing saved world

Stop the local server at a completed day, then run:

```powershell
.\.venv\Scripts\python.exe scripts/enable_frontier.py --run-id e2e31f1f15
.\.venv\Scripts\python.exe scripts/enable_frontier.py --run-id e2e31f1f15 --apply
.\Start-Hermes-City.ps1 -Days 3
```

The first command rehearses activation on a SQLite backup. The second performs
the same checks, adds schema 28 and saves an activation tick for the next day.
It refuses an active/partial day, an already configured frontier, a changed
source, existing regions or a non-USD world. Keep the server stopped throughout
the upgrade. Backups and verification hashes are under `data/backups/frontier-*`.
Restarting alone does not advance time; Northstar becomes visible when the next
simulation day commits. Nothing is backdated. Do not replace the new database
with an older copy after agents have acted unless deliberately discarding those
later days.

All living people receive a Northstar region and settlement assignment at
activation. New arrivals are registered at the nightly boundary. Existing
balances, identities, credentials and memories remain intact. Historical
views before activation continue to show no recorded region.

## Agent actions

The same strict action registry powers native model context, participant forms
and Hermes MCP catalogs. Actions are offered only when currently eligible.
Native scripted policies keep their existing priorities; Hermes citizens make
their own choices. The supervisor advertises these activities without forcing
an agent to found a town or vote.

| Action | Requirements and effect |
|---|---|
| `explore_site {site_id}` | An unexplored site; consumes 100 cents of supplies per Manhattan-distance unit and takes distance + 1 ticks. Reveals terrain, resource and housing capacity on completion. |
| `found_settlement {site_id,name}` | A discovered, unclaimed site; consumes 2,000 cents in initial materials. Reserves a unique 2–48 character name and starts a construction record. |
| `build_settlement {settlement_id}` | Consumes 250 cents of materials for one work unit completed next tick. Three completed work units make the settlement habitable. Pending units reserve work to prevent overcharging concurrent builders. |
| `move_settlement {settlement_id}` | A completed settlement with housing capacity; consumes 100 cents per distance unit and takes that many ticks. Residence changes on arrival. |
| `charter_region {settlement_id}` | At least three living residents; each resident may cast one affirmative vote. A majority of current residents creates a region with the settlement's name and existing USD currency. |

Distance has a minimum of one. Frontier expeditions, building and moves are
available to living adult citizens without employment commitments. Pending
tasks occupy subsequent turns; only waiting is allowed until they finish.
Death or a conflicting employment commitment cancels a task at its due tick;
consumed supplies are not refunded. Government officials retain their work.
One frontier action per citizen per tick and one pending task per citizen are
enforced by the engine. Failed actions roll back all partial writes and ledger
effects. Network retry protection remains the gateway's idempotency contract.

## Map and history

Nine sites are generated once using an independent seed stream. Coordinates
are visible from the start; undiscovered terrain, resources and capacities are
withheld from agent observations and the public UI. All settlements initially
belong to Northstar. A charter creates a new region without issuing currency
or creating financial reserves. Resources describe the surveyed site; version
1 does not yet add resource extraction or terrain-specific firm production.

The City workspace's **Beyond Northstar** panel shows the saved map, founders,
construction progress, residents and pending tasks. Tick travel reads committed
snapshots. People uses prospective residence records. Task completion,
discoveries, construction, founding, residence and charter votes also produce
events. Settlement IDs remain stable. Renaming is not yet an available action.

Schema 28 adds six frontier tables and `regions.created_tick`. Hash contract
v10 includes the authoritative frontier records and derived map history; empty
extensions preserve older hash contracts. Paid actions use the existing
double-entry ledger. Stop/restart reloads pending tasks and their original due
ticks; the map is not regenerated. Exact replay uses the stored decisions and
activation tick.

Focused checks: `tests/test_frontier.py`, `tests/test_frontier_upgrade.py`,
the ordinary research-export and recorded-replay suites, and
`dashboard/tests/e2e/frontier.spec.ts`.
