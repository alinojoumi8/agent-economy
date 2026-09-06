/** @param {string} value */
export function parseStudySeeds(value) {
  const tokens = value.trim().split(/[\s,]+/);
  const seeds = tokens.map(Number);
  if (!value.trim() || tokens.some(token => !/^\d+$/.test(token))
    || seeds.length > 5 || seeds.some(seed => !Number.isSafeInteger(seed) || seed > 2147483647)
    || new Set(seeds).size !== seeds.length) {
    throw new Error("Enter one to five unique whole-number seeds, separated by commas (0–2147483647).");
  }
  return seeds;
}

/** @param {any} frame
 * @param {{runId: string, fork: string|null, tick: string}} scope
 * @param {string} contract
 * @param {string|undefined} [identity] */
export function operatorStudyFrameMatches(frame, scope, contract, identity) {
  return Boolean(frame && scope.tick === "live" && frame.contract === contract
    && frame.context?.run_id === scope.runId && frame.context?.tick === "live"
    && (frame.context?.fork_id ?? null) === (scope.fork ?? null)
    && (identity === undefined || frame.id === identity));
}

export const studyJobActive = (status) => ["starting", "running", "interrupted_worker_active"].includes(status);
