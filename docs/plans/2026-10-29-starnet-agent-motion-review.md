# StarNet comparison: recognizable citizens and visible movement

Status: accepted; the first citizen readability and recorded walking increment
is implemented. See [implementation evidence](../qa/2026-10-29-citizen-walking.md).
Tracking: MW-33, still In Progress. Branch: `codex/starnet-ui-redesign`.

## Finding

The user's criticism of the `9eb7966` baseline was correct. The district preview improved the scenery,
camera and inspector but retained static citizen markers. It does not yet
deliver StarNet's recognizable, moving characters. The previous 20-day test
proved simulation updates, selection and panel contrast; it did not prove
walking, character readability or a convincing sense of activity.

## What was checked

- Manyworld candidate `9eb79666ba86603d72a01479a16670e124aeb5b4`, with the
  user's 1440px city view of temporary run `99bcc63987` at day 20.
- Current StarNet default-branch head
  [`74fcd5040ba0eb93c8f9fa07b2d0a9fcfddd1475`](https://github.com/androoAGI/starnet/tree/74fcd5040ba0eb93c8f9fa07b2d0a9fcfddd1475).
  GitHub comparison against the earlier `ab5fa2c` snapshot showed the relevant
  world, geometry and sprite files unchanged, so their local indexed source
  remains applicable. The upstream head advanced by 43 commits.
- StarNet's [published station replay](https://starnetos.com/#station), including
  frames at 5 and 15 seconds showing a worker change location and pose. This is
  explicitly a scripted harness-event replay, not a live model execution.
- Read-only inspection of the existing day-20 map response, plus a short
  presentation-only playback in Manyworld's separate Recorded day view.
  No simulation step, saved-run replay or new provider run was performed.

## Concrete gaps

| Area | StarNet | Current Manyworld 3D |
| --- | --- | --- |
| Character representation | Directional sprite tracks for standing, walking, sitting, working and talking; per-body appearance | One generic 60-triangle agent asset with base, body and head; no skin/skeleton or animation clips |
| Readability | Characters occupy a substantial part of the station view; overlays follow the visible head | Loader normalizes citizens to 0.9 world units: approximately 11.7 CSS pixels tall at the inspected camera. Large landmark labels also obscure nearby people |
| Locomotion | Per-body paths, targets, heading, acceleration/turning and stride phase; path checks against walkable floor | Instance matrices are set when the scene rebuilds. The render loop changes activity rings, not citizen positions or limbs |
| Display clock | Continuous visual updates feed body state and pose | 3D has no day-playback clock. Running a world updates snapshots and may pulse rings; it does not create walking |
| Movement data | Station geometry and worker goals feed movement | The map already has morning/business/evening presence, but `projectCity` uses each agent's single effective `place_id` and ignores the itinerary |
| State expression | Working at a desk, facing a conversation and other recognizable poses | Most activity is expressed in the evidence inspector, labels and outcome rings |
| Scene architecture | Cached scenery plus independently updated bodies | Citizens share the static asset/instance assembly; the loader merges parts by material and has no character animation path |

Local source: `assetLoader.ts:40` sets the 0.9 height; `CityScene.ts:117–129`
renders and animates rings; `CityScene.ts:144–166` assembles fixed instance
matrices; `cityProjectionCore.js:49–78` chooses a single place and agent asset.
The height estimate uses the actual 480px canvas, 3.619 camera zoom and camera
inclination, rather than treating world units as screen pixels.

## Useful capability already present

The paused world has 25 citizens and 75 raw presence rows. Twenty-four citizens
have different places across their daily slots. Editor B, for example, is at
Residential District 2 in the morning/evening and the Public Commons for the
business slot. The data needed for a first visible commute is already present.

The existing `liveCity.js` helpers provide `dayClock`, `recordedPointAt` and
placement-aware separation. `RecordedDayCity` provides Play, Pause, Restart and
speed controls, with an explicit distinction between display time and world
time. During the browser check, Editor B moved 30.01 screen pixels, then playback
paused successfully; the world stayed at day 20 and no API writes were observed.
That view still draws small chips, so it supplies timing/data logic rather than
the finished character appearance.

## Recommended next increment

Keep the existing Three.js district and build a dedicated citizen layer using
original stylized 3D characters. Their articulated bodies fit the current
rotatable camera; StarNet's pose, facing and gait ideas guide the implementation.

1. **Make people readable first.** Give citizens distinct heads, torsos, arms,
   legs, clothing and stable identity colors. Target roughly 28–40px visible
   height in the normal district framing and a closer selected-person view.
   Reduce persistent label occlusion; expose names on hover/selection and keep
   the HTML explorer. At distant zoom, use deliberate aggregate markers.
2. **Share recorded-day playback with 3D.** Reuse the existing authorized
   presence normalization and interpolation. Add the same explicit Play/Pause
   and speed controls to the 3D scene. Keep display time independent of the
   simulation clock so the user can watch day 20 without advancing it.
3. **Animate the body as it moves.** Preserve per-agent render state between
   frames, face the travel direction and drive gait from distance traveled.
   Stop the walk cycle when stationary. Update only the dynamic citizen layer;
   avoid rebuilding the ground and buildings each animation frame.
4. **Add supported activity poses.** Introduce brief, labeled replay cues for
   recorded work and conversations after walking works. Employment alone does
   not mean someone is working now, and a completed event is not ongoing work.

The first demonstration should follow two recognizable citizens through
home → business/public place → home, with selection and their dossiers retained.
Review that moving sequence before expanding art or redesigning more panels.

## Movement boundaries and later work

The current recorded-day contract interpolates directly between known placements;
it does not record street routes, transit duration or continuous physical motion.
Reuse that honest contract first. Following illustrated roads, avoiding buildings
and milling around a workplace would require an explicitly illustrative route
layer and an update to the presentation contract. Do not silently pass those
paths off as recorded travel. Private/aggregate placements remain aggregate.

StarNet's idle wandering contributes to its atmosphere. Small stationary poses
can make citizens recognizable without inventing economic actions; random travel
is not a substitute for integrating the available daily placements. Pausing
playback, reduced-motion mode and hidden-tab behavior must remain explicit.

Use original characters. The upstream README excludes StarNet's sprites and
station artwork from its MIT code grant. No upstream art or code was imported
by this review.

## Revised acceptance criteria

- At default desktop and phone framing, people are recognizable as people;
  selection, heading and body pose remain legible without reading a nameplate.
- A captured sequence shows a known person translate between two authorized
  placements and change walking pose; a stationary person does not walk in place.
- Play, Pause, Restart, speed, follow and selection work in 3D while the world
  tick remains unchanged. Run/fork changes reset animation state correctly.
- No hidden/private itinerary is reconstructed. Missing placement data has an
  explicit stationary/aggregate representation.
- Keyboard, reduced-motion, WebGL fallback and 390/768/1440 widths are checked.
  Measure frame time with the moving population; do not reuse a static-scene
  performance claim.
- Capture a short video and compare the experience with the reference. A passing
  build, advancing tick counter or contrast check does not satisfy movement.

## Evidence and upstream code

The original comparison screenshots and receipt remain under the task artifact
directory `starnet-district/agent-motion-review`. New implementation evidence is
separate under `starnet-district/citizen-walking-20day`. Activity poses, street
routing, distant aggregation and the broader MW-33 acceptance remain later work.

- [Gait and travel heading](https://github.com/androoAGI/starnet/blob/74fcd5040ba0eb93c8f9fa07b2d0a9fcfddd1475/frontend/app/world.js#L545-L562).
- [Crew movement and work state](https://github.com/androoAGI/starnet/blob/74fcd5040ba0eb93c8f9fa07b2d0a9fcfddd1475/frontend/app/world.js#L3323-L3450).
- [Walkable paths](https://github.com/androoAGI/starnet/blob/74fcd5040ba0eb93c8f9fa07b2d0a9fcfddd1475/frontend/app/worldmodel.js#L4441-L4487).
- [Directional poses and distance-based walk frames](https://github.com/androoAGI/starnet/blob/74fcd5040ba0eb93c8f9fa07b2d0a9fcfddd1475/frontend/agent-demo/sprites.js#L418-L568).
