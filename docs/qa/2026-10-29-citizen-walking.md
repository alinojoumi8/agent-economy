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
  Read-only DB checks: 523 scripted call records, zero provider attempts and
  zero external action submissions.
- The default desktop bodies measured about 32px tall, versus 11.7px in the
  reviewed baseline. The follow camera showed Editor B at about 51px.
- Captured full daily playback at 2× and checked Editor B and Governor Vale,
  including camera follow. Their positions, headings and submitted leg matrices
  changed while world day remained 20. Editor B's recorded legs connect
  Residential District 2 and the Public Commons. The final video made zero API
  writes and covers the application code at `3097774`.
- In a 237-interval desktop sample, frame interval p50 was 16.7ms and p95
  33.4ms; renderer submission p50 was 1.6ms and p95 2.4ms. These are local
  browser measurements, not a general device performance guarantee.
- Evidence, video and logs: task artifact directory
  `starnet-district/citizen-walking-20day`. This is a local scripted UI test,
  not a provider-quality or hosted acceptance claim.

## Verification

- Dashboard unit suite: 49 files passed; TypeScript and production build passed.
- Backend focused CI smoke: 170 passed. The initial sandboxed attempt stalled;
  the bounded retry with localhost access completed in 148 seconds.
- All 147 critical browser cases passed. The initial combined run also found
  a mobile layout regression and a click/follow fixture failure; both were
  corrected. Final walking/district confirmation: 15 passed, including scope
  reset, withheld locations and the moving 300-person fixture.
- Actual 20-day world inspected at 390/768/1440px in both themes. No horizontal
  overflow; minimum body height was 28px on the phone and 32.2px on larger views.
- CodeRabbit completed the review of `5abc12a`: four minor findings. Three
  concern playback copy/casing and this evidence document; those are corrected.
  The fourth concerns signed zero in vendored WGSL inside the generated
  CivicDiorama bundle. Both flagged function bodies are byte-identical to the
  pre-walking `9eb7966` bundle; it is left standing outside this UI task.
  Follow-up review of `3097774` completed with one major finding in the same
  vendored WGSL: a potentially unsupported decoder guard combination involving
  `LUMA_FP64_F32_INPUT_ONLY`. The flagged guard/body spans also match `9eb7966`.
  Its reachability is not established by this UI test. Both dependency findings
  remain open outside this task; no generated shader was hand-edited. No
  walking-source findings remained in the follow-up review.
- The branch includes the new walking regression file in the critical Chromium
  CI job. Hosted CI was still pending when inspected; the PR remains a draft.
- Dataset verification and Python dependency consistency passed. Compileall
  completed with warnings for inaccessible pre-existing report directories.
- The full Python suite did not finish in its 300-second local bound.
  Existing license notices are stale; the Python audit flags certifi; the
  TypeScript client lacks installed dependencies; pnpm audit cannot use the
  repository's npm lockfile. No dashboard lint script is configured. These
  broader gates are not represented as passing or repaired by this UI change.

## Remaining scope

Street navigation and building avoidance were subsequently requested and
implemented in the [road-following increment](2026-10-29-road-walking.md).
Work/conversation poses and distant aggregate rendering still require further
presentation decisions. MW-33 remains In Progress for the broader researcher
acceptance workflow and dependencies.
