# Playable construction (semantics 13)

Start the provider-free profile with `.venv/bin/python run.py --config runs/simcity.yaml`.
The profile inherits the deterministic civic rehearsal, enables participant mode,
and creates 300 agents (297 population target plus three civic clerks). It leaves historical/base profiles unchanged.

A living founder of a private or listed firm that consumed a business permit may
claim one vacant commercial parcel in that firm's region. Each region receives
six buildable commercial parcels, one blocked commercial parcel, and one
residential parcel. This is a region-granted construction right, not citizen land
ownership. One firm can hold one building or pending project at a time.

The only template is `workplace`: 50,000 cents in the firm's settlement currency,
12 occupancy slots, and three ticks to completion. These values are server-owned.
The firm deposits the entire quote into a project-owned escrow account. Completion
transfers escrow to the construction-service system account during FINALIZE,
after civic maintenance. Cancellation refunds all escrow to the funding firm;
demolition of completed work has no refund. Both release the parcel.

Founder death cancels pending construction before estate settlement. Firm
bankruptcy cancels pending work and returns escrow before its creditor waterfall;
completed workplaces close. Completed buildings survive founder succession unless
the firm closes. Blocked parcels discovered at completion cancel with full refund.
Replacement workplaces use new place identities; old places and leases close.
Civic maintenance never reopens a demolished constructed workplace.

All three participant commands require a stable, nonblank `request_key` of at most
120 characters. Retry the same key and payload to obtain the saved receipt;
accepted retries carry `idempotent_retry: true` and do not award skill XP or
repeat economic effects. Each retry remains an accepted audit proposal. Changing
payload under the same key rejects. New intentional actions need new
keys. The strict commands are:

- `construct_building`: `firm_id`, `parcel_id`, `template_key: "workplace"`, `request_key`.
- `cancel_construction`: `project_id`, `request_key`.
- `demolish_building`: `project_id`, `request_key`.

The participant catalog supplies currently selectable firms, parcels and projects;
execution checks authority, state and funds again. Queueing replaces the
citizen's pending next-tick command. The authoritative engine receipt determines
whether construction happened.

`GET /api/v2/urban-development?tick=live` (or a completed numeric tick) returns the
standard lineage envelope with `enabled`, `catalog`, `parcels`, and `projects`.
It exposes public geometry, fixed quotes and lifecycle evidence, never firm cash,
escrow accounts, founder identity or idempotency keys. Persisted valid-time views
prevent current buildings or ownership from appearing in past ticks. Reading the
projection does not write or migrate the run.

Schema 19 adds four tables without changing frozen prior migrations. Replay
compares every construction table and normalizes event references; semantics 13
also replays recorded participant idle days so waiting for completion does not
invoke a native provider. The construction regression includes a recorded build,
restart while escrow is pending, deterministic completion, exact replay and a
source-file hash check. No traffic, utilities or production multiplier is implied.
