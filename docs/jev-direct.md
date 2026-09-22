# Direct JEV validation

The opt-in `typesafe_decisions` adapter sends typed evaluations directly to
`https://api.typesafe.ai/v1/systemone` using `TYPESAFE_API_KEY` and pinned model
`jev-1.13.0`. Existing OpenRouter profiles and production defaults are unchanged.
Only typed decisions are supported; this is not a general chat provider.

Set `TYPESAFE_API_KEY` in your ignored `.env`. Do not paste it into commands or
reports. The optional `runs/jev-direct-live.yaml` profile keeps other decisions
scripted and explicitly disables retries. It is not an instruction to start or
resume a world. Attaching a new provider to an existing recorded run is outside
this change.

## API and accounting

The implementation uses the published direct HTTP protocol through the existing
`httpx` dependency, rather than introducing the SDK's transport and retry layer.
The official [API schema](https://api.typesafe.ai/openapi.json) defines
`model`, `state`, `questions` and returns typed answers with token usage. The
[Python client documentation](https://docs.typesafe.ai/sdk/python/api/clients/async)
describes the same service. No new dependency is required.

The adapter rejects arbitrary endpoints, redirects, unpinned models and prose
requests. Explicit loopback endpoints remain available for offline tests. It
does not retry internally. The normal gateway still owns configured retry policy;
the supplied direct profile and comparison command set it to zero.

Gateway validation, bounded candidates, durable budget reservations, settlement,
cache identity and recorded replay remain in force. Missing reported dollar cost
uses the declared tariff of $0.042 per million input tokens and $0 output tokens,
as published on the [model page](https://docs.typesafe.ai/models). Such amounts
are application estimates, not provider billing confirmations. A timeout may have
incurred unknown usage; it stays unresolved rather than becoming a free retry.

## Small transport comparison

Use preserved **original** evaluation JSON (`state` and `questions`), not a new
world. Supply one to four distinct inputs. The command alternates route order,
uses identical evaluations, a 20-second timeout, no retries and separate durable
$0.025 allowances per route ($0.05 total). It stops on the first error. A new
output directory is mandatory, preventing accidental resume or overwrite.
Each call declares a 2,048-token output allowance, matching the typed decision
profile. This is an accounting ceiling, not a wire-level output truncation option.

```powershell
python scripts/compare_jev_transports.py --input C:/evidence/case-A.json --out C:/evidence/transport-plan
# Explicit execution, after reviewing the inputs:
python scripts/compare_jev_transports.py --input C:/evidence/case-A.json --out C:/evidence/transport-results --env-file C:/project/.env --execute
```

Without `--execute` the command only saves a plan and copies inputs. Execution
saves pre-dispatch attempt receipts, individual outcomes/latencies, recorded
responses, budget databases, a summary and before/after input hashes. It creates
isolated gateway evidence stores only: no economic world, tick, Hermes process,
admission, preflight or action execution.

Direct `jev-1.13.0` and OpenRouter's recorded `typesafe/jev-1.13-20260917` have
different identifiers. Weight equivalence is not established. Results compare
the complete routes, not a proven identical model served through two transports.
Small samples can identify compatibility or obvious latency issues, but cannot
prove that OpenRouter caused earlier timeouts. Do not mix these observations into
the frozen memory-intervention experiment or silently resume its ambiguous call.
