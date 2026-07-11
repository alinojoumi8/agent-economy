# Documentation maintenance loop

This repository adapts the published Loop Library workflow
[The docs sweep](https://signals.forwardfuture.ai/loop-library/loops/overnight-docs-sweep/).
The live catalog returned no usable content during the 2026-07-10 pass, so the
bundled dated catalog entry was used as the fallback source.

## Agent Economy docs sweep

Keeps operator, API, architecture, provider, and developer documentation aligned
with implementation, stopping when no material drift remains or progress stalls.

Prompt:
> Review the current branch, PRD/spec, CLI, routes, configs, CI, and maintained docs. Fix the highest-impact documentation drift, verify commands and local links, and repeat only while the same checks find measurable gaps. Preserve unrelated work; never expose secrets or change runtime behavior. Stop cleanly when no material gap remains, or report the exact blocker. Ask before pushing, opening a pull request, publishing, or changing production.

Record the source revision, surfaces examined, gaps closed, files changed,
verification results, remaining gaps, and any approval-required handoff.

This is an on-request loop. This document does not enable a schedule or
authorize external GitHub actions.
