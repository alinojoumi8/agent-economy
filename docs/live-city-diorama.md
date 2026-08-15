# Live City 2.5D Diorama

The Live City is one evidence surface with two views:

- **Atlas** is the lightweight SVG/DOM projection and the safe fallback.
- **2.5D Diorama** is a lazy-loaded deck.gl projection with a fixed tilted
  orthographic camera, extruded buildings, agent marks, peripheral clusters,
  and migration/trade paths.

Both views use the same CivicCity shell, filters, instrumentation, and evidence
lens. Switching views does not change simulation state.

## Shareable observer state

The city validates view, agent, place, population, and layer query parameters.
The default view is Atlas. Agent and place identifiers must be positive
integers and are mutually exclusive. Invalid values fail closed, and browser
back/forward restores the prior evidence selection.

## Evidence and privacy contract

- Place and organization marks come from public projections. Building height
  is a labelled visual encoding derived from exposed capacity, occupancy, queue,
  or employee counts. It is not canonical geometry.
- Migration and trade curves connect committed public region endpoints. Their
  bend is deterministic display geometry and does not claim a traveled street.
- Named occupants appear only where the public presence projection exposes
  them. Licensing-office occupants remain a count, and peripheral resident
  placement is withheld.
- The evidence lens distinguishes direct projected records, labelled
  associations, and derived encodings.
- Projection version 2 adds the optional flows layer to the world-map API and
  reconstructs historical civic queues from creation and terminal timestamps.
  Historical intermediate case stages are labelled terminal_and_open; the
  current tick remains exact.

## Motion and historical views

Live queued/thinking runtime telemetry may pulse when motion is allowed.
Historical views never inherit that telemetry and display motion off.
Reduced-motion preferences suppress pulses. The city does not invent movement
between arbitrary historical ticks. Position interpolation is limited to
consecutive live projections; non-consecutive and historical changes snap.

## Accessibility and fallback

The Diorama includes pan, zoom, and reset controls plus a keyboard object
explorer for agents and places. Tooltip information is duplicated in the shared
evidence lens. If WebGL2 or the lazy renderer is unavailable, the interface
offers the Atlas without changing the current run.

## Performance budget

The 300-agent fixture target is:

- first rendered Diorama frame at or below 1.5 seconds;
- p95 browser frame interval below 33 milliseconds.

The Diorama reports both measurements in its status strip. Validate the target
against runs/civic-city-300.yaml in Chromium after a production build. The
deck.gl packages are exact-pinned and emitted as a separate lazy chunk.

## Local validation

    npm.cmd --prefix dashboard test
    npm.cmd --prefix dashboard run typecheck
    npm.cmd --prefix dashboard run licenses:check
    npm.cmd --prefix dashboard run build
    npm.cmd --prefix dashboard run test:e2e -- --project=chromium
    python -m pytest -q tests/test_semantics12_civic_city.py tests/test_world_os_workspace_projections.py tests/test_civic_city_300.py
