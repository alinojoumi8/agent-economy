export function mergeRunPayload(current, payload) {
  if (!current || !["tick", "run_status"].includes(payload?.type)) return current;

  const has = key => Object.prototype.hasOwnProperty.call(payload, key);
  const tick = has("tick") ? payload.tick : current.tick;
  const targetTick = has("target_tick") ? payload.target_tick : current.target_tick;
  const remainingTicks = has("remaining_ticks")
    ? payload.remaining_ticks
    : (has("tick") || has("target_tick"))
      ? (targetTick == null || tick == null ? null : Math.max(0, targetTick - tick))
      : current.remaining_ticks;

  return {
    ...current,
    tick,
    status: has("status") ? payload.status : current.status,
    running: has("running") ? payload.running : current.running,
    target_tick: targetTick,
    remaining_ticks: remainingTicks,
    governor: has("governor") ? payload.governor : current.governor,
    pause_reason: has("pause_reason") ? payload.pause_reason : current.pause_reason,
    report_path: has("report_path") ? payload.report_path : current.report_path,
  };
}
