# Semantics 12: civic places and permit services

Semantics 12 adds a narrow vertical causal proof for a living city: a citizen
applies for permission to found a business, a capacity-limited regional office
processes the case, and only an active authorization can create the firm.
Historical profiles keep their recorded semantics and behavior.

## Versioned state

Schema 17 adds:

- `places`, `occupancy_leases`, and `effective_presence`;
- `agency_staff`, `service_cases`, and `service_appointments`;
- `institution_tasks` and `civic_authorizations`;
- privacy-bounded `attention_contexts` and `attention_context_items`;
- the authoritative attention-context key on agent decisions.

Migration `engine/migrations/v017_civic_city.py` is atomic and verified before
the schema marker advances. Semantics 1–11 remain replayable without enabling
permit behavior.

## Permit causal chain

The maintained chain is:

```text
eligible founder
  -> apply_business_permit
  -> balanced application-fee posting
  -> regional service case
  -> capacity-ranked appointment
  -> assigned permit-clerk task
  -> deterministic or governed decision
  -> payload-bound expiring authorization
  -> exactly-once authorization consumption
  -> firm creation and committed events
```

Cases preserve their region and agency across migration. Applicant death closes
work safely. Clerk death or reassignment triggers deterministic succession.
Three no-shows abandon the case while preserving the already paid application
fee. Authorization payload, holder, expiry, and consumption are checked
together; a mismatch cannot found a company.

## Attention and privacy

The scheduler builds bounded attention lanes from authorized civic work.
Participant, REST, MCP, map, and causal projections expose only the viewer's
permitted case and task fields. Private attention items are not copied into
public events, logs, exports, or replay diagnostics.

## Profiles and experiment

- `runs/civic-rehearsal.yaml` is the free deterministic acceptance profile.
- `runs/civic-live.yaml` routes durable borderline permit work through the live
  provider gateway.
- `scenarios/permit-office-day.yaml` compares immediate incorporation with one
  permit appointment per region and records queue, latency, denial, utilization,
  lost-production, and firm-entry metrics.
- `scripts/benchmark_civic_city.py` measures bounded query plans at scale.

The scenario is a fictional policy mechanism inside Agent Economy. It is not a
forecast of real licensing systems.

## Acceptance evidence

`tests/test_semantics12_civic_city.py` covers:

- atomic schema-17 migration;
- FIFO, priority, capacity, and business-presence overrides;
- no-show abandonment and fee preservation;
- migration, death, and staff succession;
- authorization payload binding, expiry, and exactly-once consumption;
- attention privacy, map projection, and the causal chain;
- participant catalogs plus REST/MCP submission;
- exact offline replay.

The release gate also includes the maintained passport, research-export,
semantics-8 compatibility, dashboard, typecheck, build, and hash-contract tests.
