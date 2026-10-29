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

## Fresh 20-day demonstration

Run `5ac23ce96d` was created from `runs/city-research-acceptance.yaml` in a new
temporary directory, served on loopback port 4185, and observed from day 0 to the
hard 20-day cap. It automatically paused. Read-only database queries found 523
scripted call records, zero provider attempts, zero external submissions and
$0 spend. No saved research world was advanced.

The final production video covers application commit `016af73`, including a
whole daily cycle and camera follow for Editor B. Across 96 samples, all 2,304
located-citizen positions stayed on the painted roads. Minimum clearance from
the conservative building footprints was 2.79824 world units, above the 2.6
requirement. Heading visited all four street directions and limb matrices changed.
World day stayed 20 and the video session made zero API writes.

The city displays 25 citizens and 24 moving itineraries on 11 street segments.
Citizen 25 has no public place: it remained stationary in its separate unlocated
display slot for every sample. It is deliberately excluded from road-adherence
counts; no location or journey was invented. The first video receipt counts that
unlocated citizen as off-road; the final receipt records this case separately.

Actual production UI was inspected at 390/768/1440px in light and dark themes.
There was no horizontal overflow or cropped located citizen at default framing.
Bodies measured 28px on the phone and 32.2px at larger widths; playback buttons
were 44px high. In the final video's 240 frame intervals, p50 was 33.3ms and p95
33.4ms; renderer submission p50 was 1.3ms and p95 1.8ms. These are local browser
measurements during video recording, not a general hardware performance claim.

Artifacts, video, receipts and logs are retained in this task's local artifact
directory at `starnet-district/road-walking-20day`. This is provider-free local
UI evidence, not hosted acceptance or a claim about provider decision quality.

## Verification

- Dashboard: 50 unit files, TypeScript and production build passed.
- All 153 surrounding critical/district browser cases passed. Ten walking
  cases passed, including a full cycle sampled against
  painted roads and all building footprints, turn headings, moving selection,
  follow, keyboard controls, reduced motion, privacy and 300 citizens.
- After the review fix, the 50 unit files, typecheck/build and all 16
  walking/district browser cases passed again. The final video uses that build.
- The 170 focused backend smoke tests and 22 documentation tests passed.
  Dataset verification and Python dependency consistency passed. Compileall
  completed with warnings for inaccessible pre-existing report directories.
- The ECC evidence-record check passed after actual rendered inspection.
- CodeRabbit completed its review of `85f251c` against the PR's verified
  `main` base `ed20ff4`. Its minor stationary-citizen overlap finding was
  reproduced with a failing test and fixed in `016af73`: incomplete itineraries
  now receive separate road waiting nodes at their public place. They do not move.
- Three other minor review findings remain outside this request: keyboard access
  to 2D recorded-day chips, division by zero in vendored `div_fp64`, and positive
  infinity in vendored `sqrt_fp64`. The 2D source is unchanged from `c819dca`,
  and the two flagged shader function bodies are byte-identical to that commit.
  No generated vendor shader was hand-edited. No findings were suppressed.
- The required CodeRabbit recheck was attempted but rejected by its review quota
  (14-minute wait / unassigned provider seat). It did not complete; local
  regression checks are not represented as a completed follow-up AI review.

## Broader gate limits

The full Python suite exceeded its 300-second local bound. Existing third-party
notices are stale; the Python audit reports certifi advisory `PYSEC-2026-4320`;
the TypeScript client lacks installed dependencies; pnpm audit cannot use the
repository's npm lockfile. No dashboard lint script is configured. No dependency
or lockfile migration was made. `graft` is unavailable, so its graph refresh was
not run. Hosted checks are separate from these local results. The PR stays draft.

MW-33 remains In Progress for the broader researcher workflow and dependencies.
