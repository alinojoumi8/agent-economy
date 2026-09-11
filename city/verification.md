# City integration verification

Branch: `simcity`. Implementation uses original Blender assets, an optional 3D dashboard, and semantics-13 construction. This report distinguishes economic verification from synthetic renderer testing.

## Verified boundaries

| Boundary | Evidence |
|---|---|
| Blender asset contract | Blender 5.2.1 LTS reimported all 14 GLBs; 7 families; 223,924 bytes total; grounded hierarchy, finite bounds, material and triangle checks passed. Source exporter/catalog SHA-256 checked. |
| Public city projection | Legacy and civic fixtures; deterministic identity/grid mapping; missing/unknown/closed data; actual public bank identities; historical arrival/death/failure; hidden peripheral/appointment locations; source hash and SQLite change count remain unchanged on reads. |
| Construction | Fixed server quotes, escrow/settlement/full pending refund, no demolition salvage, zoning/authority/funds rejection, competing firms, receipt retries, founder death, bankruptcy, blocked completion and additive migration rollback. |
| Receipt retry effects | Start/cancel/demolish exact retries leave ledger, accounts, skills/history, events, causal links, places, leases, projects, receipts and projections unchanged; only the accepted audit proposal is added. |
| Recorded replay | Focused construction run resumes with escrow pending, completes deterministically, and passes exact replay without changing source hash. Frozen v1/v2 golden replay tests pass. |
| Browser | 300-agent/100-place synthetic fixture; keyboard/camera/entity evidence; banks; historical controls; 2D fallback; repeated mount/unmount; asset and WebGL failure; context loss; construction request identity/price boundary; backend disconnect/recovery; malformed projection clearing; participant daily-action clock. |
| Live browser construction | Provider-free 300-citizen run accepted a browser proposal at tick13, completed at tick16, created place53 and displayed the committed completion event. No JavaScript errors; ledger remained balanced. |

The first live replay diagnostic preserved every financial/construction table and the source artifact, but exposed preexisting participant-menu memory access writes and physical event IDs in attention fingerprints. These were discovered by testing actual browser reads between decisions, rather than only calling the engine. The fixes make catalog reads side-effect-free in every semantics version and give semantics13 attention content stable identities while independently validating logical event references. A fresh browser-driven 300-citizen run now passes exact replay across all compared tables with source bytes unchanged. The old diagnostic source remains untouched; it is not retroactively claimed as exact. See [the clean live-run proof](verification/live-construction-replay.json).

## Test commands and results

- `npm --prefix dashboard test`: **143 passed**.
- Full existing Playwright suite including initial city tests: **57 passed**.
- Expanded city Playwright suite: **9 passed**, including disconnected-backend recovery, invalid source clearing and participant clock gating. The final bank lifecycle assertion (failed live, open historically) also passed.
- `pytest` city assets, public projection, urban lifecycle and v1/v2 golden subset: **38 passed** (final follow-up changes rerun separately).
- Browser-path replay correction: **46** urban/external-gateway tests and **15** legacy catalog/participant/v1/v2 checks passed. Independent review passed **7** targeted tests and rejected wrong, dangling and boolean event pointers.
- Backend implementer focused regression: **121 passed**; retry fix follow-ups: **47** urban/migration/replay and **19** cognition/hook tests passed.
- TypeScript, production build, license notices, dependency checks and dataset verification passed. `uv pip check --python .venv/bin/python` substitutes for `python -m pip check` because this environment has no pip module; all 76 installed Python packages were compatible.
- `uvx pip-audit -r requirements.lock`: no known vulnerabilities. `npm audit --audit-level=high`: zero vulnerabilities.
- Staged secret scan passed (Gitleaks8.30.1, no leaks). Full Python suite and final renderer endurance result: pending completion. Linux was exercised locally; no Windows/macOS execution is claimed.

## Renderer measurements

Host: AMD Ryzen Threadripper 2990WX (32 cores/64 threads), NVIDIA GeForce GTX1080Ti, Linux. Chromium's test renderer is **ANGLE Vulkan SwiftShader (Subzero)**, software rendering. No integrated GPU is available on this host.

The fixture contains 300 citizens, 100 places, one firm sharing place geometry, and one bank. The browser viewport is 1920×1080; the city canvas is the available panel within that viewport, with a 0.75 drawing-buffer scale. HTML text is native-resolution. Continuous camera rotation stresses redraw; ordinary paused rendering is on demand. Samples record actual rendered frames, requested animation frames, post-GC JavaScript heap, canvas count and Three.js draw/geometry/texture counters every ten seconds. Other local tests may contend for CPU resources.

A 30-second production diagnostic reached its first usable city in **0.83s** and averaged **27.1 camera-animation FPS** on software rendering. The 30-minute test additionally measures actual render frames; its final values will replace the pending endurance entry below. These measurements do not certify the planned 30FPS integrated-GPU target, and the software result is below that target.

A separate hardware run using `CITY_TEST_GPU=hardware` measured **59.89 actual rendered FPS**, **1.74s** startup and no JavaScript errors on the NVIDIA GTX1080Ti. GPU identification confirmed hardware OpenGL rather than fallback. See [raw hardware measurement](verification/hardware-benchmark.json). This meets the numeric FPS/startup targets on the tested discrete GPU, not the untested integrated-GPU target.

Endurance: **running**. Renderer source and built bundle are frozen under a temporary test server to avoid Vite hot reloads. Later HTML/clock changes and a secure-context error guard do not change the renderer exercised by this test; its renderer source hash and final output are retained with the result.

## Limits

- Historical presence, lifetimes and construction are tick-resolved; some names, roles, region metadata and population tiers are current records and are labeled as such.
- Derived coordinates, roads, silhouettes and marker offsets do not establish wealth, transport, ownership or private location.
- Integrity checks require HTTPS or localhost; WebGL failure falls back to the existing 2D atlas.
- No integrated-GPU or cross-platform performance certification, remote deployment, traffic, utility network, pollution or disaster mechanics are claimed.
