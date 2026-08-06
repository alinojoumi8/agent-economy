const FIELDS = {
  run: ["run_id", "parent_run_id", "fork_tick", "status"],
  checkpoints: ["id", "tick", "created_at"],
  shocks: ["id", "kind", "trigger_type", "duration_ticks", "label", "fired", "fired_tick", "active_until_tick"],
  predictions: ["id", "asked_tick", "question", "p", "confidence", "deadline_tick", "resolved_tick", "outcome", "brier", "status"],
  acceptance: ["id", "scheduled_tick", "question", "status", "prediction_id", "detail"],
  datasets: ["id", "dataset_key", "release_date", "vintage_date", "checksum_sha256", "transform_version", "usage_terms", "status"],
  scenarios: ["id", "scenario_key", "version", "title", "manifest_checksum", "limitations"],
  experiments: ["id", "experiment_key", "scenario_key", "created_at", "checkpoint_hash", "status"],
  results: ["id", "experiment_id", "arm", "seed", "run_id", "replay_hash", "metrics", "causal_trace"],
};

function records(value) {
  return Array.isArray(value) ? value.filter(row => row && typeof row === "object") : [];
}

function pick(row, fields) {
  return Object.fromEntries(fields.filter(field => row[field] !== undefined).map(field => [field, row[field]]));
}

function sorted(value, fields, tickField = "id") {
  return records(value).map(row => pick(row, fields)).filter(row => row.id !== undefined).sort((left, right) => (
    Number(left[tickField] ?? 0) - Number(right[tickField] ?? 0)
    || Number(left.id ?? 0) - Number(right.id ?? 0)
  ));
}

export function classifyEvidence(evidence = {}) {
  const source = evidence && typeof evidence === "object" ? evidence : {};
  const blocked = source.blocked === true
    || source.external_agent_contamination === true
    || source.participant_influence === true
    || source.stale_commit === true
    || source.dirty_tree === true
    || (Array.isArray(source.missing_artifacts) && source.missing_artifacts.length > 0);
  if (blocked || String(source.status).toLowerCase() === "blocked") return "blocked";
  const status = String(source.status ?? "").toLowerCase().replaceAll("_", "-");
  if (["running", "partial", "in-progress", "pending"].includes(status)) return "partial";
  if (source.passed === false || ["failed", "error"].includes(status)) return "failed";
  if (["not-run", "notrun", "skipped", ""].includes(status) && source.passed !== true) return "not-run";
  if (source.passed === true && source.exact_replay === true && source.eligible === true) return "eligible";
  if (source.passed === true && source.real_providers === false) return "mechanics-only";
  if (source.passed === true && source.real_providers === true) return "live-evidence";
  if (source.passed === true || status === "passed" || status === "complete" || status === "completed") return "passed";
  return "not-run";
}

export function experimentActionState(run = {}, observerTick = "live") {
  const paused = String(run?.status ?? "").toLowerCase() === "paused";
  const live = observerTick === "live";
  const allowed = paused && live;
  return {
    canPrepareFork: allowed,
    canPrepareShock: allowed,
    reason: allowed ? null : !live ? "Actions are unavailable in historical views." : "Pause the current run before preparing a fork or shock.",
  };
}

export function normalizeExperimentsWorkspace(data = {}) {
  const source = data && typeof data === "object" ? data : {};
  const acceptanceSource = records(source.acceptance);
  const acceptance = acceptanceSource.map(row => ({
    ...pick(row, FIELDS.acceptance),
    classification: classifyEvidence(row),
  })).filter(row => row.id !== undefined).sort((left, right) => (
    Number(left.scheduled_tick ?? 0) - Number(right.scheduled_tick ?? 0)
    || Number(left.id ?? 0) - Number(right.id ?? 0)
  ));
  return {
    run: pick(source.run && typeof source.run === "object" ? source.run : {}, FIELDS.run),
    checkpoints: sorted(source.checkpoints, FIELDS.checkpoints, "tick"),
    shocks: sorted(source.shocks, FIELDS.shocks, "fired_tick"),
    predictions: sorted(source.predictions, FIELDS.predictions, "asked_tick"),
    acceptance,
    datasets: sorted(source.datasets, FIELDS.datasets),
    scenarios: sorted(source.scenarios, FIELDS.scenarios),
    experiments: sorted(source.experiments, FIELDS.experiments),
    results: sorted(source.results, FIELDS.results),
    currentOnlyArtifactsOmitted: source.current_only_artifacts_omitted === true,
  };
}
