/** Elapsed presentation time; never a simulation tick or a world command. */
export function playbackElapsed(clock, now) {
  return clock.elapsed + (clock.startedAt === null ? 0 : Math.max(0, now - clock.startedAt) * clock.speed);
}

/** Accumulate with the OLD speed before changing it, so the day cannot jump. */
export function updatePlayback(clock, { playing, speed }, now) {
  return { elapsed: playbackElapsed(clock, now), startedAt: playing ? now : null,
    speed: [0.5, 1, 2, 4].includes(speed) ? speed : 1 };
}
