# Documentation maintenance

Documentation is part of the product contract. Update it in the same branch as
the behavior it describes, and verify it before merge.

## Source-of-truth hierarchy

When documents disagree, use this order:

1. committed code, migrations, tests, and generated interface contracts for
   what the current checkout actually does;
2. [implementation-status.md](implementation-status.md) for current
   implemented/released/rollout-gated labels;
3. root [PRD.md](../PRD.md) and [TECH-SPEC.md](../TECH-SPEC.md) for the
   maintained product and engineering contract;
4. accepted [architecture decisions](adr/README.md) for durable design choices;
5. handbook guides for workflows and explanations;
6. dated plans, receipts, and historical snapshots for point-in-time evidence.

The World OS PRD and technical specification are successor direction, not
duplicates of the root contracts. Proposed ADRs and plans express intent; they
must not be written as implemented behavior.

The frozen Semantics-7 printable snapshot at
[implementation-status.html](implementation-status.html) has an intentional
banner and link to the current Markdown ledger. Do not synchronize its
historical tables to newer semantics.

## Document ownership

| Change | Update at minimum |
|---|---|
| First-run command or dependency | Root README, getting started, development |
| Profile, provider, cost, or environment variable | Configuration; README if it changes a recommended path |
| Route, request, response, OAuth/MCP behavior | API reference, generated OpenAPI/client docs, security if applicable |
| Engine phase, ownership, projection, replay, or persistence | Architecture, technical specification, relevant semantics guide |
| Schema or semantics version | Migration, compatibility tests, configuration, architecture, implementation status |
| Hosted deployment, backup, audit, or incident behavior | Operator runbook and security policy |
| Research gate, metric, or interpretation boundary | Research guide, test catalog, implementation status |
| Durable design decision | New or superseding ADR with explicit status |
| Branch/worktree policy | Branch lifecycle and a dated audit plan |
| Dashboard behavior | DESIGN.md, API/architecture if contracts changed, screenshots when useful |

Keep the root README concise and research-first. Put operational detail in the
runbook, contributor detail in development, and status evidence in the
implementation ledger. Link instead of copying long evidence blocks.

## Required workflow

1. **Identify audiences and contracts.** Name the user, operator, researcher,
   developer, and security surfaces affected by the change.
2. **Inspect implementation truth.** Verify exact routes, flags, fields,
   versions, and failure behavior in code/tests before writing.
3. **Classify maturity.** Use implemented, released, rollout-gated, proposed,
   historical, or diagnostic precisely.
4. **Patch all affected documents together.** Add cross-links from the handbook
   index and the nearest existing guide.
5. **Update decision records.** Accepted ADRs describe implemented decisions;
   proposed ADRs describe future direction. Add consequences and limitations.
6. **Add documentation assertions** for safety-critical commands, version
   labels, maintained links, and known historical boundaries.
7. **Run verification** and report exact results without hiding warnings or
   environment-related failures.

## Writing rules

- Lead with the safe default, then explain optional live or hosted paths.
- Mark network use, provider credentials, and cost before a command that can
  incur them.
- Distinguish economic truth, canonical simulation evidence, read-time
  projection, and ephemeral runtime telemetry.
- State whether a feature mutates state, proposes an action, or only reads.
- State version gates and historical behavior for new semantics.
- Avoid claiming public production readiness from local implementation tests.
- Use repository-relative links and stable headings.
- Use exact filenames, commands, profile names, and route paths.
- Do not place secrets, private prompts, provider payloads, or tenant data in
  examples.
- Preserve failed and diagnostic evidence as failed/diagnostic; do not recast it
  as a partial pass.

## Verification

Run the documentation contract:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_documentation.py
```

For changes that affect a feature guide, run that feature's tests as well. The
repository smoke contract is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py
```

Finish with:

```powershell
git diff --check
git status --short
```

The maintained-link test checks the root contracts and handbook list. Add every
new durable guide to `HANDBOOK_DOCS` in `tests/test_documentation.py`; do not
let an untested guide become an orphan. Generated run reports and dated plans
may link to transient evidence and therefore are not automatically part of that
maintained set.

If frontend source changed, also run dashboard tests, typecheck/build, and
verify the committed `server/static/` bundle. Documentation-only edits do not
require regenerating that bundle.

## Review checklist

- [ ] Safe offline entry point is obvious.
- [ ] Paid/live/hosted boundaries are explicit.
- [ ] Implementation and release status are not conflated.
- [ ] Version, replay, and historical behavior are stated.
- [ ] Authority and privacy limits are stated.
- [ ] Root README links to detail instead of duplicating it.
- [ ] Handbook index and relevant cross-links are updated.
- [ ] ADR status matches current implementation truth.
- [ ] Local links and documentation tests pass.
- [ ] Test commands and results are recorded in the commit/PR handoff.
