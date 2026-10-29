# Road-following citizens

Citizens now use the same deterministic street graph that draws the district.
Routes turn around building footprints, including four-house district copies,
with 2.6 world units of clearance for the largest articulated display body.
Outside-place waiting positions sit on the graph. Routes are cached per committed
projection; there is no path search or building rebuild during animation.

This is a presentation-only route between authorized morning/business/evening
places, not measured movement. Private, missing, unknown or disconnected
itineraries stay still. A blocked leg holds the whole itinerary to prevent a
teleport at the next slot. Regions do not gain invented intercity routes.
Engine, ledger, stored coordinates and saved research worlds are unchanged.

## Verification in progress

- Dashboard: 50 unit files, TypeScript and production build passed.
- Ten walking browser cases passed, including a full cycle sampled against
  painted roads and all building footprints, turn headings, moving selection,
  follow, keyboard controls, reduced motion, privacy and 300 citizens.
- Fresh scripted run `5ac23ce96d` on port 4185 was observed from day 0 to its
  hard cap at day 20 and automatically paused. It displays 25 citizens,
  24 moving itineraries and 11 connected street segments.
- Final live video, resource measurements, broader checks and CodeRabbit review
  are being recorded under `starnet-district/road-walking-20day` in this task's
  local artifact directory. This document will record their final outcomes.

MW-33 remains In Progress for the broader researcher workflow and dependencies.
