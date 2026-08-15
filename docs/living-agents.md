# Living Agents

Living Agents is the observer-only progression workspace at
`/runs/:runId/people`. Existing agent detail URLs remain valid at
`/runs/:runId/people/:agentId`; only the navigation label changed.

![Living Agents workspace and construction-stage review mockup](images/living-agents-review.png)

The review mockup above is documentation, not runtime artwork. It records the
approved composition: an agent list, selected journey, evidence-labelled
progress streams, and the four construction silhouettes. QTown informed this
layout only; no QTown source, assets, fixed-grid renderer, or PixiJS dependency
is used.

## Evidence contract

- **Committed** means stored actions, transactions, cases, skills, and outcomes.
- **Runtime** means ephemeral current work and appears only for a live view.
- **Derived** means a summary calculated from committed evidence.

The workspace reports exact stages, counts, ticks, cents, and evidence
references. It does not manufacture completion percentages. Historical views
reconstruct the selected tick and fork. Prompts, private reasoning, message
bodies, memory contents, and reversible peripheral-agent locations are omitted.
Peripheral residence and workplace activity is aggregated by region for the
ordinary workspace projection.

## Observer APIs

- `GET /api/v2/workspaces/living-agents` accepts `tick`, `fork_id`, `agent_id`,
  `project_kind`, `status`, `after`, and `limit`.
- `GET /api/v2/agents/{agent_id}/journey` accepts the same historical lineage
  parameters and returns the selected profile, state, milestones, public
  outputs, and evidence references.
- The compatibility `/api/agents` endpoints remain available, but Living Agents
  does not use them.

Links back to Live City preserve the observer fork and tick and use stable
`agent`, `place`, organization-layer, and `view=diorama` parameters so refresh
and browser history retain the same evidence focus.
