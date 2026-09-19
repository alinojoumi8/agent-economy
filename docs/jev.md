# Jev bounded agent decisions through OpenRouter

Jev is an opt-in selector for routine shopping and job bundles. It chooses from
IDs compiled by this application. The existing action executor checks the chosen
bundle and applies all economic effects through the ledger. Existing profiles
keep their original policy. Production adoption remains an experiment until
actual provider measurements support it.

The pinned model is `typesafe/jev-1.13`. The transport calls
`https://openrouter.ai/api/alpha/decisions`, using typed `state`, `questions` and
`answers`, rather than the chat endpoint. The dated resolved model is recorded
and checked against the profile's explicit allowlist. The mutable
`~typesafe/jev-latest` alias is deliberately excluded from these fixed pilots.
OpenRouter calls this interface Alpha. See its
[Decisions reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request).

## Start with an offline rehearsal

Run commands from the repository root using its Python environment:

```powershell
.\.venv\Scripts\python.exe run.py --config runs/jev-offline.yaml --ticks 3
.\.venv\Scripts\python.exe run.py --config runs/jev-offline.yaml --serve --port 8000
```

The second command starts a new paused world. Open the local app and choose
**Step** or **Run**. In **Experiments → Decisions**, inspect the selected action
types, selection/abstention status, execution acceptance, model, latency and cost.
The view respects the selected historical tick and shows the newest 200 records.
Its totals describe recorded bounded-policy decisions, not every citizen turn.

## Set the API key privately

Set `OPENROUTER_API_KEY` in the Python process environment or an ignored local
`.env`. Both `run.py` and the decision-study CLI load `.env`. The example file
contains only the blank variable name. Never put the key in YAML, browser
variables, a research manifest, Git or a chat message. No TypeSafe-specific key
is required. Recheck `.env` is ignored with `git check-ignore .env`.

```powershell
# Checks presence and configuration; makes no inference request.
.\.venv\Scripts\python.exe run.py --config runs/jev-live.yaml --preflight
# A metered typed smoke request; requires a working key and credits.
.\.venv\Scripts\python.exe run.py --config runs/jev-live.yaml --preflight-live
# Three actual simulated days, with a five-dollar total run cap.
.\.venv\Scripts\python.exe run.py --config runs/jev-live.yaml --ticks 3 --approve-live-inference
# Interactive test, initially paused, with the same live route.
.\.venv\Scripts\python.exe run.py --config runs/jev-live.yaml --serve --approve-live-inference
```

The model is absent from the ordinary chat model catalog; a successful catalog
lookup is not its readiness test. Missing keys fail before dispatch. 401/403 and
402 responses pause visibly; they do not trigger another model. 429/529 and
transient failures use bounded retries within the logical request deadline.

Live typed preflights keep their receipts and budget evidence in the ignored
`data/runs/preflight/` directory. The result prints the evidence path. This
separate smoke allowance is capped by the selected profile and is not the later
world's allowance; retain it when reconciling total test spend.

## Profiles and capability boundaries

| Profile | Routine selector | Background | Run cap |
|---|---|---|---|
| `runs/jev-offline.yaml` | Deterministic equal-menu rule | Scripted | Inherited offline governor |
| `runs/jev-live.yaml` | Jev 1.13 | Scripted | USD 5 |
| `runs/jev-comparator.yaml` | Deterministic equal-menu rule | Scripted | Inherited offline governor |
| `runs/jev-hybrid.yaml` | Jev; low confidence produces a local wait | Scripted | USD 5 |
| `runs/jev-hermes-baseline.yaml` | Existing unrestricted DeepSeek/MiniMax policy | Existing DeepSeek/MiniMax M3 Hermes routes | USD 1 |
| `runs/jev-hermes-live.yaml` | Jev for eligible bounded routine choices | Same DeepSeek/MiniMax M3 Hermes routes | USD 1 |

OpenRouter is reserved for Jev. Readiness and the physical-dispatch guard reject
other OpenRouter models and chat routes, including routes in older live profiles.
Recorded replay remains keyless and does not dispatch those routes. DeepSeek and
MiniMax retain their existing direct endpoints. The comparator profile is now a
provider-free baseline; the hybrid filename is retained for the Jev-plus-local-wait
configuration, which has no second model route.

The tariff checked September 19, 2026 is USD 0.042/M input and zero output for
[Jev](https://openrouter.ai/typesafe/jev-1.13). This is a declaration, not a measured
invoice. Actual returned costs take precedence in call receipts;
missing cost uses the declared tariff and is labelled accordingly.

For a small comparison against the existing app setup:

```powershell
.\.venv\Scripts\python.exe run.py --config runs/jev-hermes-baseline.yaml --ticks 3 --preflight-live --approve-live-inference
.\.venv\Scripts\python.exe run.py --config runs/jev-hermes-live.yaml --ticks 3 --preflight-live --approve-live-inference
```

Both profiles inherit `hermes-local-live-deepseek.yaml`, retain its seed, population,
gateway and background routes, and use prospective engine semantics 16. The
original semantics-11 profile and existing worlds are not migrated. The Jev arm
adds only the bounded decision policy and its provider/tariff. Hermes denotes the
external-agent gateway/profile here; these commands do not launch a Hermes worker.
They require the existing private DeepSeek and MiniMax keys as well as the Jev key.
Each world has its own cap; preflight spend is additional and must be included in
the final accounting. These are operational smoke comparisons, not the scripted
background research protocol below. The unrestricted baseline and bounded Jev
policy have different action spaces, so differences cannot be attributed solely
to model quality.

The compiler uses one actor's existing authorized observation. It bounds
shopping quantities, stock, spending, currency and job eligibility, and emits
compatible whole-turn bundles. Waiting and requesting escalation are explicit
choices. Specialized institutional work, firm management, required civic work,
available legal/construction actions, pending household decisions, needed care
plans, portfolio reviews and other
declared priorities retain their existing route. The receipts identify those
outside-menu turns. Scheduling, background conversation, memory compression and
compute eligibility remain in the ordinary runtime.

Routine matched choices produce no invented in-character reasoning and no
choice-driven belief updates. This deliberately changes cognition compared with
the original unrestricted policy. Compare the supplied arms with one another
before comparing this experiment with existing production configurations.

Jev confidence is **answer-distribution concentration**, not a probability of
economic success. The hybrid's 0.70 threshold is provisional. Missing confidence
with a positive threshold produces a visible wait in the supplied profiles.
Invalid schemas, unknown
candidate IDs and unexpected model changes pause the run instead of being
silently repaired into actions. Stock may change before execution; that is an
observable engine rejection, not authority for the model to bypass validation.

## Accounting, private evidence and replay

Every physical typed call reserves its full declared token/cost ceiling before
HTTP dispatch. The adjacent `RUN.jev-budget.db` and `RUN.jev-budget.json` retain
that allowance across restart. Keep these files with the run. HTTP failures,
cancellation, missing usage and process death retain a conservative charge.
Missing or changed allowance evidence stops dispatch. Provider-reported charges
above the reservation stop further budgeted calls. The governor also checks the
ordinary run spend. Receipt cost covers returned calls; the sidecar separately
shows unknown/pending charges that cannot be established from a response.

Full observations, typed answers, candidates and execution receipts are private
scientific artifacts in the run database. Observer event, causal and Decisions
views expose a reduced summary. Public external-agent/newsroom paths do not
publish these private events. No authorization headers are recorded.

```powershell
.\.venv\Scripts\python.exe run.py --replay RUN_ID --ticks 3
```

Recorded replay requires neither an API key nor a running provider. It binds the
exact observation, question IDs, menu, model route and policy. A changed menu
cannot use the legacy approximate replay lookup. A replay creates its own run;
the source database remains unchanged. Copying a live run to a new location is
not permission to replenish or duplicate its spending allowance.

## Prospective comparison workflow

`research.decision_studies` uses `bounded-decision-study-v1` and the additive
`typed-provider-budget-v1`. Existing v3 policy-study contracts remain unchanged.
The first pilot supports fresh worlds and identical scripted background
cognition; saved-world policy migration and the v3 study-launch UI are separate
workflows. Jev results are available through this CLI and the run's Decisions
view.

Prepare freezes configurations, code identity, candidate policy, seeds, horizons,
metrics, optional snapshots, all model routes and tariffs. It makes no calls.
The first named arm is the reference. Execution requires an explicit live flag,
uses one shared durable allowance across every arm and seed, and refuses a second
execution of the same study. Live account access is required only at execution.

```powershell
.\.venv\Scripts\python.exe -m research.decision_studies prepare --arm baseline=runs/jev-offline.yaml --arm jev=runs/jev-live.yaml --arm conservative=runs/jev-hybrid.yaml --seeds 1,2 --ticks 3 --max-calls 200 --max-usd 1 --out data/studies/jev-smoke
.\.venv\Scripts\python.exe -m research.decision_studies execute data/studies/jev-smoke --approve-live
```

The small allowance is for a smoke comparison. The proposed exploratory study
uses ten paired seeds and thirty ticks, with a separately reviewed Jev allowance.
This runner's cap is aggregate across its declared routes. Each completed cell must
reconcile and pass exact recorded replay. `result.json` retains every assigned
cell, explicit failures/exclusions, available terminal macro observations and
per-seed paired differences. Standard errors use independent seed pairs, never
individual agents as independent experimental replications. Unavailable metrics
remain null with their registry explanation. No adoption verdict is inferred.

For frozen-input comparison, close a recorded run and export its eligible menus:

```powershell
.\.venv\Scripts\python.exe -m research.decision_studies freeze --run data/runs/RUN_ID.db --out data/studies/observations.json --limit 2000
```

Use `--snapshots data/studies/observations.json` when preparing the next study.
Inputs are selected by stable hash; all observations of an actor/seed stay in
the same calibration or held-out split. Outside-menu records and sample counts
are retained. This is a convenience pilot corpus, not a representative sample
of every economic regime. Build stress/regime cohorts before a production claim.

Frozen reports include schema completion, abstention, escalation, latency p50/p95,
cost and agreement with the deterministic reference. Agreement is not accuracy.
To measure calibration, independently adjudicate candidate choices using a
documented rubric. Supply a private JSON mapping of snapshot ID to candidate ID:

```powershell
.\.venv\Scripts\python.exe -m research.decision_studies label --snapshots data/studies/observations.json --labels data/studies/labels.json --definition "Owner-reviewed shopping/job suitability rubric v1" --out data/studies/labelled-observations.json
```

Prepare against that new sealed file. Brier/ECE and reliability bins describe
agreement with those labels, separately for each split. They remain null without
labels. Choose a threshold on calibration data, then prepare a new held-out
evaluation without tuning on its results. Interrupted studies retain their
original reservations and partial files and cannot resume or reset their budget.
The wall budget bounds awaited calls; it is not a hard operating-system kill of
synchronous engine work.

## Whole-app acceptance

Check an offline world, a small Jev world, and the existing-Hermes/Jev pair. In each, verify
Decisions receipts, historical tick filtering, accepted/rejected actions, private
input omission, pause/resume and exact replay after removing the key. Exercise a
missing key and credit failure before a longer run. Measure actual account cost,
latency, menu coverage, model-resolution stability and background-call share.
Scale only after those results and the paired-world outcomes justify adoption.

Live validation on September 19, 2026 confirmed key access, native Decisions
responses, mixed-provider operation and exact offline replay. The three-day
Hermes-profile comparison recorded USD 0.118618 for the existing policy and
USD 0.052526 with Jev, excluding preflights. Jev selected wait in 77 of 78 menus,
including menus with active alternatives; 75 of those turns belonged to staff.
Keep the existing default pending a better scoped and independently evaluated
decision policy. These are one-seed operational measurements, not evidence that
Jev makes better economic decisions. See the [live validation and next-test plan](plans/2026-09-19-jev-live-validation.md).
