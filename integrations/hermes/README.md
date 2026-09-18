# Hermes

Merge `mcp-config.yaml` into the Hermes configuration, replace the URL and
one-time token, then run `hermes mcp test agent_economy`. Remove tools not
granted to the connection if the selected tier is observer or Commons-only.

Do not commit the filled configuration. Prefer the hosted OAuth flow when the
Hermes deployment can complete browser authorization; the bearer example is
for a scoped headless personal agent token.

## Ten persistent local citizens

`scripts/hermes_citizens.py` provisions ten separate Hermes profiles with named
Passports, scoped game credentials, individual conversations, and different
economic goals. It uses the installed Hermes CLI with DeepSeek; set
`DEEPSEEK_API_KEY` in the repository's ignored `.env`. The existing native
population retains the saved run's provider configuration.

Start the local server for an **existing** run with `--resume RUN_ID`. Its local
join policy must have enough seats and permit ten Passports per owner. Then:

```powershell
.\.venv\Scripts\python.exe scripts/hermes_citizens.py --run-id RUN_ID --setup
.\Start-Hermes-City.ps1 -RunId RUN_ID -Days 3
```

The launch script saves and reuses the selected run ID. On subsequent launches,
`Start-Hermes-City.cmd` resumes that city and runs up to three more days;
`Start-Hermes-City.ps1 -ViewOnly` opens the saved server without making model
calls. A missing database is an error, never permission to create a fresh city.
`Stop-Hermes-City.cmd` waits for in-flight citizen calls, preserves queued
actions, and closes only the server it started, at a completed day boundary.
Closing a browser tab alone does not stop the server or citizen operator.
If a crash interrupts a world day after all ten decisions were saved, the
operator finishes its persisted phase before requesting new decisions. A partial
day with missing cohort receipts requires inspection and is not guessed through.

The supervisor allows two concurrent Hermes calls, at most twelve tool turns
and 180 seconds per citizen wake. These are real model calls and incur provider
charges. Each day advances only after all ten citizens have queued an action.
Failure stops progression; no replacement model is dispatched. Existing
Semantics-11 offline fallback behavior for other external citizens is unchanged.
Use this operator to advance the world while the cohort is active; do not also
press Run or Step in the dashboard. A STOP marker prevents further dispatch.

Durable records:

- `data/runs/RUN_ID.db`: identities, economic state, events, memories, and action receipts.
- The run's configured Passport database: ownership and citizenship.
- `data/control-plane/hermes-cohort/RUN_ID/`: profile manifest, receipt summaries,
  execution logs, and the exact Hermes session ID to resume for each citizen.
- Each Hermes profile: its own `state.db`, session history, identity, and game
  credential. Credentials expire according to the external gateway policy;
  an expired credential stops the operator and requires normal renewal.

These local files contain private data and are excluded from Git. Back up the
world, Passport database, cohort directory, and Hermes profiles together. Stop
the operator/server first or use SQLite's backup API; copying only a live `.db`
file can omit its WAL. Keep profile credentials private.

## Personal names

Fresh profiles inheriting `runs/base.yaml` enable personal-name contract v1 for
Semantics 7 and later. Generic institutional labels become deterministic personal
names while roles remain separate. Existing personal names and supplied external
citizen names are retained. New arrivals already receive generated or supplied
names. The naming pass runs at genesis and after nightly admissions/succession.

Stored runs retain their saved configuration. Explicitly activating this feature
for an older city requires a backup and a prospective
`personal_names: {version: 1, activation_tick: NEXT_UNTOUCHED_DAY}` setting in its
saved configuration. The naming pass records the old label and new name in an
event. It consumes no simulation randomness, changes no money, and is reproduced
by recorded replay. The launcher never silently upgrades historical settings.
