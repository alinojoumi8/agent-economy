# Saved Hermes citizens

The ten local cohort profiles use `openai-codex` / `gpt-5.6-luna` through the
existing Hermes ChatGPT login. Each citizen keeps its own identity, memory,
session, and Agent Economy MCP credential. Hermes resolves shared provider
authentication through its supported global auth-store fallback; do not copy
rotating OAuth tokens into individual profiles.

`scripts/hermes_citizens.py` reads the provider and model from each profile's
`config.yaml` for every wake, including resumed conversations. It no longer
forces DeepSeek over the profile's selected model.
The ongoing session is taken from that invocation's CLI session receipt,
not the newest database conversation; Desktop chats and connection checks
cannot silently replace the citizen's ongoing conversation.

A completed model turn without a queued action receives up to two corrective
wakes in the same citizen session. Each wake requests a fresh `ae_turn_wait`
envelope and requires the complete observation hash. Existing queued receipts
are checked before every attempt. STOP or an externally advanced world prevents
another attempt; provider/process failures remain visible for investigation.
No action or observation hash is fabricated by the operator. Attempt logs have
unique names and `decision-retries.jsonl` records bounded recovery attempts.

An expired window is not renewed by normal polling. Before a local cohort wake,
the operator calls authenticated `POST /api/v2/agent/turn/renew` for its next
tick. This endpoint is unavailable in hosted mode and supports only a paused
semantics-11 world. It refuses active days, unavailable actors, previously
consumed decisions and queued/executed submissions. An open unexpired window
is returned unchanged. An expired open/fallback window gets fresh observations
and a five-minute deadline (or the configured deadline when longer), with the
previous deadline, status and projection hash retained in `external_security_audit`.
Stale receipts remain stored. The agent must still submit its own action with
the exact renewed hash before the new deadline. This accommodates the cohort's
180-second model budget without weakening normal polling or submission checks.

Start the existing world with `Start-Hermes-City.ps1 -Days N` (1–100 additional
days), or use `-ViewOnly` to inspect it without advancing. If interrupted, use
the remaining number of days, not the original total. For the day-41 to day-141
experiment, a restart at saved day 63 needs 78 days. Previously queued actions
are reused. The app must remain running and the computer awake.

The launcher starts an independent Python watcher around the cohort worker.
The watcher records actual PIDs, requested end tick, a five-second health file,
and append-only start/exit events under the run's private cohort directory.
It records nonzero exits, abrupt worker termination, and premature zero exits
as errors with the last saved tick. It never automatically retries or advances
the world. The normal completed boundary, or an explicit STOP file, permits a
paused result. Worker output is appended rather than erased on restart.

Files to inspect: `operator-process.json`, `supervisor-health.json`,
`supervisor-events.jsonl`, `status.json`, `operator.err.log`. A stale health
timestamp plus a missing watcher process indicates an interruption of the
watcher itself. No process can journal after it is forcibly killed or the
computer loses power; the external monitor must detect that case.

The September 18 worker disappeared at saved day 63 with no Python exception.
Existing evidence does not identify what terminated it. Separately, Hermes
Desktop logged three occupied backend slots and profile-switch timeouts.
Desktop's Settings → Advanced backend pool limit controls simultaneous open
profile backends; it is independent of the operator's two concurrent citizens.
Changing a default model does not rewrite historical conversation records.

Validation: the operator tests cover 100-day automatic pause, queued-action
reuse, partial-day recovery, provider configuration, and refusal to advance
after a cohort failure. The watcher tests launch real test subprocesses for
completion, abrupt exit, and premature clean exit. The live Luna check used all
ten actual profiles to call identity and world-observation MCP tools without
submitting actions; its private evidence is `luna-connection-verification.json`.
