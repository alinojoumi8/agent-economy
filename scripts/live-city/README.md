# The running-world probe

Rounds 1–3 of the Live City were all captured against a world **paused at tick 349**. This probe exists
because the requirement was *"whenever we run the backend the front end looks live"*, and a paused world
cannot test it. The first time it was run it found that the city renders one tick in six while holding a
steady 60 fps — a failure invisible to every paused measurement that preceded it.

Keep it. A city that animates smoothly off stale data looks identical to one that works, so this is not a
thing that can be checked by eye.

## Run it

Needs the simulation on `:8000` and the vite dev server on `:4174`, and Playwright from
`dashboard/node_modules` (resolved by absolute path, so run from anywhere).

```bash
node scripts/live-city/runworld.mjs /tmp/live-city-run
```

**It starts the world.** 20 s paused baseline, then `POST /api/run/start?max_ticks=6` — roughly four and a
half minutes of real ticking — then pauses again. The run advances by up to six ticks and that is
irreversible; on the scripted `civic-city-300.yaml` profile it costs `$0.00`.

Then:

```bash
node scripts/live-city/analyse.mjs /tmp/live-city-run
node scripts/live-city/film.mjs /tmp/live-city-run
```

## What it measures, and why each one needed a running world

| | |
|---|---|
| Every `fetch` timed to **body**, not just headers | a starved server returns headers long before the body |
| Every WebSocket frame with `event_cursor` / `previous_event_cursor` | the cursor rule is re-derived exactly as `cursorReducer.js` applies it, so `cursor_gap` is counted rather than assumed |
| `requestAnimationFrame` sampling the day clock and eight chip transforms | the only way to catch a single-frame teleport |
| `.live-city__pulse` on every change | what the reader was actually told, with timestamps |
| Frame gaps, with screenshot-adjacent frames set aside | the camera itself costs frames; they are excluded rather than blamed |

Two traps worth keeping in mind if you extend it:

- **Do not key the day-clock reset off the map landing.** `dayOrigin` resets in an effect that runs *after*
  the frame carrying the new data, so measuring at the map frame understates the jump by ~80×. Use a
  backwards step in `dayProgress` instead, and separate a natural wrap (starts near 100%) from a forced
  reset (starts anywhere else) — they differ by three orders of magnitude in what they do to the screen.
- **Do not edit anything under `dashboard/` while a capture is running.** Vite will hot-reload the page and
  silently destroy the run.
