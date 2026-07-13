# Operator runbook

## Safe startup

Run offline before using paid providers:

```powershell
python run.py --config runs/base.yaml --ticks 1
python -m pytest -q
```

Validate the production routes before a paid run:

```powershell
python run.py --config runs/acceptance/production.yaml --preflight-live
```

The production acceptance profile is uncapped but fully metered. Record the Git
commit, resolved profile, seed, population, provider/model catalog result, and
intended evidence gate before starting it.

Run the free acceptance rehearsal and inspect its failed/live-only gates before
authorizing inference:

```powershell
python run.py --config runs/acceptance/rehearsal.yaml `
  --acceptance-run `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json
```

## Capped research-validity pilot

The 30-tick pilot is the first paid gate. It targets the current depositors of
the largest bank, hides private reserve ratios from citizens, and caps recorded
spend at $25:

```powershell
python run.py --config runs/acceptance/pilot.yaml `
  --acceptance-run --approve-live-inference
```

Do not start the full run unless this receipt passes its rumor, conversation,
belief-history, deposit-outflow, ledger, provider, latency, and spend gates. Do
not resume `f7c6238bf5`; it is preserved as a pre-fix diagnostic pilot.

## Production acceptance

Start a fresh acceptance run only with explicit live-inference authorization:

```powershell
python run.py --config runs/acceptance/production.yaml `
  --acceptance-run --approve-live-inference `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json `
  --phenomena-evidence reports/out/<reviewed-phenomena>.yaml
```

The driver runs to scheduled Oracle checkpoints and then the configured
365-tick horizon. It schedules six questions and requires at least five Oracle
latency samples. The profile is uncapped for runtime continuity but has a
separate $200 efficiency completion gate. On success it writes the complete
HTML report plus JSON and Markdown acceptance receipts.

Copy `runs/acceptance/phenomena.template.yaml` to a run-specific reviewed file,
set its top-level `run_id` to the exact reviewed run, and replace the pending
examples with phenomena visible in that run's persisted metrics. Evidence for a
different run fails closed even when its metric direction happens to match.

During a run, `GET /api/acceptance/status` and the dashboard show completed
gates, actual/projected spend, Oracle sample count, shock traces, and rumor
window evidence. The status endpoint evaluates large databases off the server
event loop and may return evidence cached for up to two seconds. Once a final
receipt exists for the exact run ID and completed tick, the endpoint returns
that artifact so experiment and reviewed-phenomena gates remain visible.

## Cooldown, pause, and resume

HTTP 429 throttling and explicit provider overloads such as MiniMax HTTP 529
enter one provider-wide cooldown. The dashboard/status surface shows provider,
attempt count, remaining cooldown, and next retry. The run waits until recovery
or operator stop.

Other continuing provider failures use bounded retries and then pause cleanly.
`run_meta.tick` remains the last fully completed tick; `active_tick` and
`next_phase` identify the exact work to resume. Successful LLM responses are
already durable and are reused by request key.

Resume a stored production acceptance run with its original profile:

```powershell
python run.py --config runs/acceptance/production.yaml `
  --resume <RUN_ID> --acceptance-run --approve-live-inference `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json `
  --phenomena-evidence reports/out/<reviewed-phenomena>.yaml
```

Do not replace or edit a partial database. Preserve it and resume it. Legacy
databases with ambiguous partial-tick semantics are marked `legacy_partial` and
must be treated explicitly rather than silently advanced.

## Dashboard controls

- **Run** starts or resumes continuous ticks.
- **Pause** interrupts a provider cooldown or requests a safe phase pause.
- **Step** executes one tick and leaves the run paused.
- **Speed** changes wall-clock delay only; status is authoritative after refresh.
- **Stop + report** finishes the current run and generates a report.

A reported run can be reopened through Run or Step; the previous report path is
cleared and a later stop generates a fresh report. A `halted` run cannot be
mutated because halt represents an invariant failure requiring investigation.

## Reports and exact replay

Regenerate a report from a stored run:

```powershell
python run.py --report <RUN_ID>
```

The HTML file is the canonical standalone report. Markdown is its
reviewer-oriented companion.

Rebuild a run without provider calls and verify canonical table digests:

```powershell
python run.py --replay <RUN_ID>
```

Replay re-asks persisted Oracle questions at their original ticks. Historical
prompt changes use the source call's semantic identity and copy its original
request and cache key. A missing stored response fails closed; replay never
falls back to a live provider.

## Experiments and acceptance-only evaluation

```powershell
python run.py --experiment runs/experiments/rumor_vs_control.yaml
python run.py --acceptance-report <RUN_ID> `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json `
  --phenomena-evidence reports/out/<reviewed-phenomena>.yaml
```

The first command creates isolated treatment/control worlds. The second derives
an evidence receipt from persisted run data without advancing the simulation.

## Evidence retention

For a release candidate, retain:

1. `data/runs/<run-id>.db` and its latest checkpoint;
2. the HTML report and JSON/Markdown acceptance receipts;
3. the experiment JSON/Markdown/HTML artifacts;
4. the reviewed phenomena YAML and shock traces;
5. the exact Git commit, resolved profile, and provider preflight result.

Never call a provider pause, partial report, failed replay, or incomplete
evidence package a successful acceptance.
