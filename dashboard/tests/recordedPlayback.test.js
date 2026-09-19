import test from "node:test";
import assert from "node:assert/strict";
import { playbackElapsed, updatePlayback } from "../src/lib/recordedPlayback.js";

test("play, pause, resume and speed changes preserve a continuous presentation clock", () => {
  let clock = { elapsed: 0, startedAt: null, speed: 1 };
  assert.equal(playbackElapsed(clock, 1000), 0);
  clock = updatePlayback(clock, { playing: true, speed: 1 }, 1000);
  assert.equal(playbackElapsed(clock, 2000), 1000);
  clock = updatePlayback(clock, { playing: true, speed: 4 }, 2000);
  assert.equal(playbackElapsed(clock, 2000), 1000);
  assert.equal(playbackElapsed(clock, 2500), 3000);
  clock = updatePlayback(clock, { playing: false, speed: 0.5 }, 2500);
  assert.equal(playbackElapsed(clock, 9000), 3000);
  clock = updatePlayback(clock, { playing: true, speed: 0.5 }, 9000);
  assert.equal(playbackElapsed(clock, 10000), 3500);
});
