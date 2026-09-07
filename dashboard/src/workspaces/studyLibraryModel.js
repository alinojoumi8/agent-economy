/** @param {any} frame
 * @param {{runId: string, fork: string|null, tick: string, studyId?: string, resultHash?: string, kind?: string}} scope */
export function studyFrameMatches(frame, { runId, fork, tick, studyId, resultHash, kind = "finalized" }) {
  if (!frame || tick !== "live" || frame.context?.tick !== "live"
    || frame.context?.run_id !== runId || (frame.context?.fork_id ?? null) !== (fork ?? null)) return false;
  if (studyId !== undefined && (frame.id !== studyId || frame.verification?.result_sha256 !== resultHash
    || frame.contract !== (kind === "working" ? "operator-working-study-v1" : "operator-study-comparison-v1"))) return false;
  if (studyId === undefined && frame.contract !== "operator-study-catalog-v1") return false;
  return true;
}

export function studyNumber(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(value) : "Unavailable";
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
