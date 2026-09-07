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

/** Bind deliberate saved-world choices to the currently admitted catalog.
 * @param {any} form
 * @param {any} catalog */
export function priceStudyRequest(form, catalog) {
  const { checkpoints, ...parameters } = form;
  if (form.origin !== "verified_checkpoints") {
    return { ...parameters, origin: "fresh_genesis", seeds: parseStudySeeds(form.seeds), warmup_ticks: 0, equity_firm_id: 1 };
  }
  if (!catalog || !checkpoints?.length || checkpoints.length > 5) {
    throw new Error("Choose one to five saved worlds from the current catalog.");
  }
  const selected = checkpoints.map(choice => {
    const item = catalog.items.find(row => row.id === choice.id && row.database_sha256 === choice.database_sha256
      && row.receipt_sha256 === choice.receipt_sha256);
    if (!item) throw new Error("A selected saved world changed. Refresh saved worlds and select it again.");
    return item;
  });
  if (new Set(selected.map(item => item.tick)).size !== 1
    || new Set(selected.map(item => item.seed)).size !== selected.length
    || new Set(selected.map(item => item.run_id)).size !== selected.length) {
    throw new Error("Choose the same saved day from worlds with distinct seeds and run identities.");
  }
  if (form.intervention_tick <= selected[0].tick + form.warmup_ticks) {
    throw new Error("The intervention must follow the saved day and additional warmup.");
  }
  return { ...parameters, seeds: null, equity_firm_id: 1,
    checkpoints: selected.map(({ id, database_sha256, receipt_sha256 }) => ({ id, database_sha256, receipt_sha256 })) };
}
