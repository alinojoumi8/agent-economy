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
  const { checkpoints, design, model_replicates, max_provider_calls, max_tokens, max_spend_usd, ...parameters } = form;
  if (form.origin !== "verified_checkpoints") {
    return { ...parameters, origin: "fresh_genesis", seeds: parseStudySeeds(form.seeds), warmup_ticks: 0, equity_firm_id: 1 };
  }
  const selected = selectedCheckpoints(checkpoints, catalog);
  if (form.intervention_tick <= selected[0].tick + form.warmup_ticks) {
    throw new Error("The intervention must follow the saved day and additional warmup.");
  }
  return { ...parameters, seeds: null, equity_firm_id: 1,
    checkpoints: selected.map(({ id, database_sha256, receipt_sha256 }) => ({ id, database_sha256, receipt_sha256 })) };
}

function selectedCheckpoints(checkpoints, catalog) {
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
  return selected;
}

export function parseModelDraws(value) {
  const draws = value.trim().split(/[\s,]+/);
  if (!value.trim() || draws.length > 3 || new Set(draws).size !== draws.length
    || draws.some(draw => !/^[a-z0-9][a-z0-9_-]{0,31}$/.test(draw))) {
    throw new Error("Enter one to three distinct model draw labels using lowercase letters, digits, underscores or hyphens.");
  }
  return draws;
}

export function policyStudyRequest(form, checkpoints, catalog) {
  const design = catalog?.items.find(item => item.id === form.design?.id && item.sha256 === form.design?.sha256);
  if (!design) throw new Error("Choose a reviewed policy design from the current catalog. Refresh if it changed.");
  const request = { preset: "POLICY", origin: form.origin, design: { id: design.id, sha256: design.sha256 },
    model_replicates: parseModelDraws(form.model_replicates), horizon: form.horizon,
    max_wall_seconds: form.max_wall_seconds, max_disk_mib: form.max_disk_mib,
    max_provider_calls: form.max_provider_calls, max_tokens: form.max_tokens, max_spend_usd: form.max_spend_usd,
    pause_after_ticks: form.pause_after_ticks, pause_after_phase: form.pause_after_phase };
  if (form.origin === "fresh_genesis") return { ...request, seeds: parseStudySeeds(form.seeds) };
  if (form.origin !== "verified_checkpoints") throw new Error("Choose fresh or saved worlds.");
  const selected = selectedCheckpoints(form.checkpoints, checkpoints);
  if (form.horizon < selected[0].tick + 3) throw new Error("Policy studies require at least three new days after the saved day.");
  return { ...request, seeds: null,
    checkpoints: selected.map(({ id, database_sha256, receipt_sha256 }) => ({ id, database_sha256, receipt_sha256 })) };
}
