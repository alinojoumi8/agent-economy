/** @param {any} frame @param {{runId: string, fork?: string | null, tick: number, agentId: number}} scope */
export function householdFinanceFrameMatches(frame, scope) {
  return Boolean(frame && frame.projection === "operator.household-finances"
    && frame.semantics_version >= 20 && frame.run_id === scope.runId
    && (frame.fork_id || null) === (scope.fork || null)
    && frame.tick === scope.tick && frame.data?.requested_tick === String(scope.tick)
    && frame.data?.contract_version === "household-finances-v1"
    && frame.data?.visibility === "local_operator"
    && frame.data?.selected_agent_id === scope.agentId);
}

/** @param {number | null | undefined} cents @param {string} currency */
export function financeMoney(cents, currency) {
  return typeof cents === "number" && Number.isFinite(cents)
    ? `${(cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`
    : "Unavailable";
}

/** @param {{gini: number, population_count: number, nonnegative_cash_cents: number} | undefined} observation */
export function cashGiniLabel(observation) {
  if (!observation || !Number.isFinite(observation.gini)) return "Unavailable";
  if (observation.population_count === 0) return "Empty cohort (0 by convention)";
  if (observation.nonnegative_cash_cents === 0) return "No positive cash (0 by convention)";
  return observation.gini.toFixed(3);
}
