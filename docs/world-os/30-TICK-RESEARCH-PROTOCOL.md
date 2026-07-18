# World OS 30-Tick Causal Research Protocol

**Protocol ID:** `world-os-v8-supplier-warning-v1`<br>
**Date frozen:** 2026-07-18<br>
**Status:** Proposed protocol; must be approved with the design package before T1<br>
**Semantics/schema:** engine semantics 8, world schema 12<br>
**Provider:** deterministic scripted provider only; live-provider behavior is a separate smoke

## 1. Research question

Can a private warning, visible to exactly one authorized buyer, produce a predeclared change
in an ordinary conserved goods purchase while leaving a complete replayable evidence chain
and no information leak?

This protocol tests causal isolation and simulator plumbing. It does not claim that the
scripted response estimates human behavior.

## 2. Frozen fixture

All branches start from the same checkpoint after tick 4 and use the same code commit,
configuration, seed `20260718`, PRNG state, scripted-provider version, semantics, schema,
projection version, and fixture manifest.

The fixture contains:

- `supplier_officer`, a living agent authorized to represent `supplier_firm`;
- `retailer_manager`, a living agent with a funded checking account;
- `outside_agent`, a living non-recipient with no relevant organization membership;
- `supplier_firm`, an active seller with at least 100 units of the fixture good;
- a unit price fixed at 100 cents through tick 8;
- enough retailer cash to buy at least 10 units;
- no competing price, inventory, death, membership, policy, or news shock through tick 8;
- one scheduled retailer goods-purchase decision at tick 6.

The fixture verifier fails before branching if any precondition is false. `buy_goods` is the
existing validated action with `firm_id` and positive `qty`; its normal ledger transfer,
inventory update, and `goods_sale` event remain authoritative.

## 3. Branches and intervention

Create three explicit forks from the tick-4 checkpoint:

| Branch | Tick-5 intervention | Scripted tick-6 decision |
|---|---|---|
| `control-none` | No message is created | `buy_goods(firm_id=supplier_firm, qty=10)` |
| `control-neutral` | Subject `Shipment notice`; body `Batch 2026-07 is cleared. Continue the scheduled 10-unit purchase.` | `buy_goods(firm_id=supplier_firm, qty=10)` |
| `treatment-warning` | Subject `Shipment notice`; body `Batch 2026-07 may be contaminated. Limit the scheduled purchase to 5 units.` | `buy_goods(firm_id=supplier_firm, qty=5)` |

Both messages are created in tick 5, have the same audience, delivery tick 6, priority,
and exact subject. They differ only in the exact body above. No semantic/intervention tag is
stored in the world or supplied to cognition. Neither triggers an extra model call.

### 3.1 Branch-blind policy contract

The scripted purchase policy receives only the authorized knowledge projection plus the
listed economic fields. It cannot receive `run_id`, `fork_id`, branch/control/treatment
labels, protocol expectations, or a semantic tag. The canonical contract JSON is:

```json
{"excluded_fields":["branch_label","control_label","fork_id","protocol_expected_qty","run_id","semantic_tag"],"id":"supplier-warning-policy-v1","input_fields":["authorized_inbox.sender_role","authorized_inbox.subject","authorized_inbox.body","authorized_inbox.delivery_tick","cash_cents","firm_id","firm_inventory","unit_price_cents"],"rule":"qty=5 iff an authorized delivered unread message at tick 6 from supplier_officer has subject Shipment notice and body Batch 2026-07 may be contaminated. Limit the scheduled purchase to 5 units.; otherwise qty=10"}
```

Its SHA-256 is
`f29339c7ff21c653419226f2aee4c25eaeb99ccbc2886674519f9d24b05fc9a2`.
The implementation records this contract hash and the canonical policy-input hash beside
the proposal. Extra input fields fail the fixture rather than being ignored.

Before the three 30-tick branches may pass, metamorphic probes must prove:

1. randomly relabeling run/fork/branch metadata does not change quantity;
2. swapping only the two exact bodies makes quantity follow the body (warning -> 5,
   neutral -> 10), not the fork;
3. retaining the warning row in world truth but withholding delivery/grant makes quantity
   10 because the warning is absent from authorized input;
4. giving the same authorized warning under a differently labeled fork still makes
   quantity 5;
5. the recorded policy-input JSON contains no excluded field or protocol expected output.

## 4. Required temporal sequence

```text
tick 4 FINALIZE  common checkpoint and hashes
tick 5 EXECUTION treatment/neutral message command commits
tick 6 NIGHT_CLOSE lifecycle ordering completes
tick 6 INBOX_DELIVERY resolves direct audience and grant exactly once
tick 6 MORNING authorized inbox enters persisted decision context
tick 6 EXECUTION validated buy_goods proposal executes
tick 6 MARKET goods_sale event and balanced ledger transfer exist
tick 6 FINALIZE projection and authoritative hashes commit
ticks 7-30 no scenario-specific intervention; ordinary fixture continues
```

Semantics 8 forbids same-tick delivery: every message has
`deliver_at_tick >= created_tick + 1`.

## 5. Predeclared causal edges

The treatment branch must contain the following directed edges. The neutral branch contains
the delivery/observation edge but no warning-motivated quantity-change edge. The no-message
branch contains none of the message edges.

| Source -> target | Relation | Authority | Required provenance |
|---|---|---|---|
| warning message -> retailer observation memory | `observed` | `engine` | delivery/grant stable reference |
| observation memory -> contamination belief update | `triggered` | `engine` | scripted knowledge-update rule |
| belief update -> `buy_goods(qty=5)` proposal | `motivated` | `actor_claim` | retailer ID and scripted-policy version |
| accepted action proposal -> `goods_sale` event | `triggered` | `engine` | action-result stable reference |
| `goods_sale` event -> ledger transaction | `settled` | `engine` | transaction ID plus its two entry IDs as evidence |

Every engine edge has confidence 1.0. The actor-claim edge proves the motivation was
recorded, not that the claim is objective truth. No `model_inference` edge is needed for
this protocol.

## 6. Predeclared outcomes and refutation thresholds

The protocol passes only if all outcomes hold:

1. `treatment-warning` executes exactly one successful `buy_goods` for 5 units at tick 6.
2. `control-none` and `control-neutral` each execute exactly one successful `buy_goods` for
   10 units at tick 6.
3. Each branch debits/credits exactly `executed_qty * 100` cents and leaves the ledger
   balanced; inventory falls by exactly the executed quantity.
4. Treatment minus either control is exactly -5 purchased units. Any other quantity,
   clipping, rejected action, extra purchase, or price change refutes the fixture.
5. The five treatment causal edges above exist once with the stated direction, relation,
   authority, and provenance. A missing, duplicate, dangling, or differently qualified edge
   refutes the trace.
6. Pre-fork canonical authoritative hashes are identical. Within each branch,
   uninterrupted, phase-fault-resumed, checkpoint-resumed, and replayed executions have
   identical authoritative and projection hashes at tick 30.
7. Cross-branch differences are confined to the predeclared allowlist: communication,
   delivery/read, affected memory/belief/decision/action, causal, goods-sale event,
   inventory, ledger, derived projection, and derived metric rows. Any unrelated world row
   difference refutes isolation.
8. Every privacy assertion in section 8 passes with zero exceptions.

This is deliberately binary. “The story looked plausible” is not a passing result.

## 7. Alternative explanations and controls

| Alternative explanation | Control |
|---|---|
| Merely receiving any message changes the action | `control-neutral` receives the same delivery shape but retains quantity 10 |
| Price, stock, cash, death, or membership changed | Fixture verifier freezes/asserts those values through tick 8 |
| PRNG or provider sampling changed after the fork | Scripted provider, identical seed/state, stable request keys, and the same scheduled slot; only exact body/absence differs outside policy metadata |
| Policy keyed directly on the branch label | Branch labels are excluded from input; body-swap, withheld-delivery, and relabeling metamorphic probes must pass |
| The UI inferred the quantity change | Outcome is asserted from action result, event, inventory row, and balanced ledger before any projection is built |
| Resume duplicated or skipped work | Fault injection and checkpoint resume must reproduce the uninterrupted branch hashes |
| Analyst annotation caused the result | Operator workspace is absent from world inputs and excluded from authoritative hashes |

## 8. As-of privacy assertions

Private subject, body, participant identities, stable message URL, thread chronology entry,
and existence are tested independently; a safe aggregate count is not message existence.

This is the complete six-basis oracle used by generated policy tests:

| `AccessBasis` | Grant/effective tick | Fields permitted at/after that tick | Explicit exclusions and persistence |
|---|---|---|---|
| `sender` | Committed `created_tick` | Existence, subject, body, thread entry/URL, declared audience; for organization mail the organization label, not expanded membership | No access before commit; survives sender death as historical sent mail |
| `direct_delivery` | Successful delivery tick | Existence, subject, body, thread entry/URL, sender, and explicit direct addressee list | Uniform not-found before delivery; dead-before-delivery gets no basis |
| `organization_at_delivery` | Successful delivery tick for the snapshotted member | Existence, subject, body, thread entry/URL, sender, and organization label | Never exposes expanded recipient membership; join after delivery gets no basis; leave after delivery keeps it; dead-before-delivery gets none |
| `public_release` | Audience `published` resolution tick | Public existence, subject, body, thread entry/URL, and public sender identity | Nothing is public at creation; no private recipient list or per-agent delivery fan-out |
| `legal_disclosure` | Granted tick of typed same-case court order/agreement | Existence, subject, body, thread entry/URL, sender, and only participant fields named by the disclosure scope | No access before grant; does not grant unrelated thread messages; revocation is a new legal event and never rewrites historical as-of access |
| `operator_truth` | Truth capability plus successfully appended inspection audit | Full stored fields at requested historical tick | Never enters agent/news/report/default-export views; audit contains no body and lives outside replay truth |

Derived-message rules are separate policy cases, not implicit grants:

| Case | New access | Old access |
|---|---|---|
| Reply | Immediate parent sender receives a new `direct_delivery` basis at N+1 | No new grant to the parent or any older thread message; chronology may contain gaps |
| Forward | New audience receives the forwarded message through its own basis at N+1/publication | No grant to `source_message_id`; quoted text is content of the new message and has a `cited` provenance edge |

The direct supplier-warning fixture additionally asserts these concrete consumer views:

| Principal/view | Before tick-6 delivery | At/after successful delivery | Audit rule |
|---|---|---|---|
| Sender | Own subject/body/audience from committed tick 5 | Same | World provenance; no truth-inspection audit needed |
| Intended recipient | Uniform not-found for message-specific lookup | Own granted message fields; no unrelated recipient expansion | Delivery/read provenance |
| `outside_agent` | Uniform not-found | Uniform not-found | Safe denied-access audit only; no message ID in response |
| Join-after-delivery org member | Not applicable to direct fixture | Uniform not-found | Policy-matrix assertion |
| Newsroom, Oracle, end report | No subject/body/participants/existence | Public consequences only after the goods event | Projection-policy test |
| Ordinary dashboard observer | No message-specific existence or URL | Aggregate private-message counts/status only | Operational audit without private fields |
| Truth inspector | Only through explicit truth capability | Full message view | Append-only inspection record in operator workspace, excluded from replay truth |
| Replay verifier | Internal row access only | Internal row access only | Never serializes body to a user projection or log |
| Default research export | No private fields | Redacted/pseudonymous metadata per manifest | Export audit and redaction counts |

No private subject, body, unredacted participant list, or stable message-specific URL/query
key may appear in public events, application logs, exception text, metrics labels, browser
persistence, screenshots/traces for unauthorized roles, or default exports.

## 9. Canonical evidence hashes

The release implements `hash-contract-v1`. It discovers every world table and column and
fails if either is not classified as authoritative, derived, or excluded.

Authoritative hash inputs include, when present:

- agents/lifecycle and organization membership rows;
- firms, inventory, accounts, ledger transactions, and ledger entries;
- action proposals/results, events, memories, beliefs, communications, audience
  resolutions, delivery grants/outcomes, disclosures, causal links, tick/phase cursor, PRNG
  state, and persisted provider/script receipts.

Excluded from the authoritative hash:

- migration `applied_at` wall time after its version/name/checksum/source-schema fields are
  separately verified;
- HTTP/WebSocket connection state, caches, generated projection rows, browser state;
- application logs, benchmark timing samples, operator workspace/audit rows, and exports;
- OS paths, process IDs, and other wall-clock operational metadata.

Canonicalization rules:

1. tables order lexicographically; rows use declared primary-key/composite order;
2. columns follow the checked-in hash manifest, never `SELECT *` discovery order;
3. integers remain decimal integers, blobs become lowercase hex, text is UTF-8 NFC, null is
   typed null, and floats use their IEEE-754 hexadecimal representation;
4. JSON fields are parsed and serialized with sorted keys, no insignificant whitespace, and
   the same typed number rules;
5. each typed row is length-prefixed before SHA-256 aggregation to prevent concatenation
   ambiguity;
6. new/changed tables or columns fail CI until the manifest classifies them.

Projection hashes use canonical JSON over the full authorized envelope and data, including
run/fork, tick, semantics, projection/policy versions, cursor, and snapshot identity. They
are compared only within the same principal view.

## 10. Required artifacts

The scenario produces:

- branch manifests and common checkpoint hash;
- treatment/control canonical table hashes and classified row-level diff;
- causal-edge receipt;
- role-by-field privacy matrix receipt;
- phase-fault, checkpoint-resume, and replay equality receipt;
- live/rebuilt authorized projection hash receipt;
- browser trace for the treatment investigator path with private fields redacted;
- human-readable Markdown summary that links these machine-verifiable artifacts.

No live-provider output participates in the pass/fail decision. A separate ten-tick smoke
may cite this fixture but is reported independently.
