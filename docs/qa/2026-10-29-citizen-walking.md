# Readable citizens and recorded walking

The 3D district now draws original articulated citizens with heads, clothing,
arms, legs and shoes. The dynamic body layer reuses instanced geometry and retains
poses across identical data polls. Walking direction and stride come from
distance along authorized morning/business/evening placements. Buildings and
ground are not rebuilt on animation frames.

Play/Pause, Restart and 0.5–4× speed operate on a presentation clock. Run, fork,
visibility or committed-frame changes reset playback. Hidden tabs pause;
reduced motion shows discrete anchor placements without limb animation.
Incomplete, private, malformed and out-of-roster itineraries do not create
journeys. Selection, follow and dossier links retain the existing observer scope.

Names appear for selected/hovered citizens. Default bodies target 28–40 CSS
pixels, with bounded enlargement on smaller screens and a closer focus camera.
Body scale, placement offsets and connecting segments are illustrative. These
segments are not recorded street routes; no economic or ledger code changed.

## Fresh live demonstration

- Run `e378003ad7`, created from `runs/city-research-acceptance.yaml` in a fresh
  temporary directory; loopback preview at `http://127.0.0.1:4184`.
- Observed day 0 → day 20, then automatic pause at the server's 20-day cap.
  25 citizens, 24 moving itineraries, scripted routes only, $0 recorded spend.
- The default desktop bodies measured about 32px tall, versus 11.7px in the
  reviewed baseline. The follow camera showed Editor B at about 51px.
- Captured a full daily cycle at 2×, then followed Editor B. His position,
  heading and submitted leg matrices changed while world day remained 20.
  Two recorded legs connect Residential District 2 and the Public Commons.
- Evidence, video and logs: task artifact directory
  `starnet-district/citizen-walking-20day`. This is a local scripted UI test,
  not a provider-quality or hosted acceptance claim.

## Verification

- Dashboard unit suite: 49 files passed; TypeScript and production build passed.
- Backend focused CI smoke: 170 passed. The initial sandboxed attempt stalled;
  the bounded retry with localhost access completed in 148 seconds.
- Critical browser suite plus new walking/district cases: 158 passed initially;
  the mobile layout and click/follow fixture failures were fixed. Final focused
  confirmation and CodeRabbit results are recorded below when complete.
- Dataset verification and Python dependency consistency passed. Compileall
  completed with warnings for inaccessible pre-existing report directories.
- The full Python suite did not finish in its 300-second local bound.
  Existing license notices are stale; the Python audit flags certifi; the
  TypeScript client lacks installed dependencies; pnpm audit cannot use the
  repository's npm lockfile. No dashboard lint script is configured. These
  broader gates are not represented as passing or repaired by this UI change.

## Remaining scope

Street navigation, collision avoidance, work/conversation poses and distant
aggregate rendering require further presentation decisions. MW-33 remains In
Progress for the broader researcher acceptance workflow and dependencies.
