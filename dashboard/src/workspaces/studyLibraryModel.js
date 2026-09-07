/** @param {any} frame
 * @param {{runId: string, fork: string|null, tick: string, studyId?: string, resultHash?: string, kind?: string, protocol?: string}} scope */
export function studyFrameMatches(frame, { runId, fork, tick, studyId, resultHash, kind = "finalized", protocol }) {
  if (!frame || tick !== "live" || frame.context?.tick !== "live"
    || frame.context?.run_id !== runId || (frame.context?.fork_id ?? null) !== (fork ?? null)) return false;
  const policy = protocol === "research-study-v3";
  const contract = kind === "working" ? (policy ? "operator-policy-working-study-v1" : "operator-working-study-v1")
    : policy ? "operator-policy-study-comparison-v1" : "operator-study-comparison-v1";
  if (studyId !== undefined && (frame.id !== studyId || frame.verification?.result_sha256 !== resultHash
    || frame.contract !== contract)) return false;
  if (studyId === undefined && frame.contract !== "operator-study-catalog-v1") return false;
  return true;
}

export function studyNumber(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(value) : "Unavailable";
}

export function studyCost(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "Unavailable";
  if (value > 0 && value < .000001) return "<$0.000001";
  return new Intl.NumberFormat("en", { style: "currency", currency: "USD", maximumFractionDigits: 6 }).format(value);
}

const PHASE_LABELS = { NIGHT_CLOSE: "Start of day", INBOX_DELIVERY: "Inbox delivery", MORNING: "Morning decisions",
  EXECUTION: "Action execution", MARKET: "Market settlement", NEWSROOM: "News publication",
  EVENING: "Conversations", MEMORY: "Memory", FINALIZE: "Day finalization" };

export function studyPhaseLabel(phase) {
  return Object.hasOwn(PHASE_LABELS, phase) ? PHASE_LABELS[phase] : "Unavailable";
}

export function studyPhasePosition(row, verified) {
  if (!verified) return "Not verified";
  if (row.execution_status === "planned") return "Not started";
  const position = row.position;
  if (!position) return ["paused", "completed"].includes(row.execution_status) && Number.isInteger(row.ticks)
    && row.ticks >= 0 ? "Between days" : "Unavailable";
  if (!Number.isInteger(position.completed_tick) || position.completed_tick !== row.ticks
      || position.completed_tick < 0 || !Object.hasOwn(PHASE_LABELS, position.next_phase)) return "Unavailable";
  if (position.active_tick === null) return position.next_phase === "NIGHT_CLOSE" ? "Between days" : "Unavailable";
  if (position.active_tick !== row.ticks + 1 || (row.expected_ticks != null && position.active_tick > row.expected_ticks)) return "Unavailable";
  return `Day ${position.active_tick} · next: ${studyPhaseLabel(position.next_phase)}`;
}

export function studyOutcomeRows(study, domain, treatment) {
  const baseline = study?.summary?.baseline_arm;
  return (study?.outcomes || []).filter(outcome => outcome.domain === domain).map(outcome => {
    const measured = study.summary?.metrics?.[outcome.key] || {};
    const effect = measured[treatment]?.paired_effect || {};
    return {
      ...outcome, baseline: measured[baseline]?.mean ?? null, treatment: measured[treatment]?.mean ?? null,
      difference: effect.mean_difference ?? null, interval: effect.ci95_bootstrap ?? null,
      pairs: effect.n_pairs ?? 0, assignedPairs: effect.assigned_pairs ?? 0,
      exclusions: effect.pair_exclusions || [],
      measurements: study.measurements?.[outcome.key] || [],
    };
  });
}
