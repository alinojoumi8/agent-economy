import { Link, useParams, useSearchParams } from "react-router";
import {
  experimentActionState,
  normalizeExperimentsWorkspace,
} from "./experimentsWorkspaceModel.js";
import {
  validatedSelectedId,
  WorkspaceHeader,
  WorkspaceState,
  WorkspaceTable,
  workspaceUrl,
  useWorkspaceProjection,
} from "./workspaceShared";

type EvidenceRow = { id: number; [key: string]: unknown };
type ExperimentsProjection = {
  run?: Record<string, unknown>; checkpoints?: EvidenceRow[]; shocks?: EvidenceRow[];
  predictions?: EvidenceRow[]; acceptance?: EvidenceRow[]; datasets?: EvidenceRow[];
  scenarios?: EvidenceRow[]; experiments?: EvidenceRow[]; results?: EvidenceRow[];
  current_only_artifacts_omitted?: boolean;
};
type View = "evidence" | "rehearsals" | "forecasts" | "campaigns" | "inputs";

function text(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value).replaceAll("_", " ");
}

function classificationCopy(value: unknown) {
  const labels: Record<string, string> = {
    "eligible": "All supplied eligibility gates passed",
    "live-evidence": "Real-provider evidence; release eligibility is not inferred",
    "mechanics-only": "Scripted or non-real-provider mechanics evidence",
    "partial": "Execution is incomplete",
    "blocked": "A fail-closed evidence gate is blocking promotion",
    "failed": "The evidence record reports failure",
    "passed": "The record passed its own scope; release eligibility is not inferred",
    "not-run": "No qualifying execution receipt is present",
  };
  return labels[String(value)] || labels["not-run"];
}

export function ExperimentsWorkspace() {
  const projection = useWorkspaceProjection<ExperimentsProjection>("workspace.experiments", "/api/v2/workspaces/experiments");
  const { experimentId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const model = normalizeExperimentsWorkspace(projection.data || {});
  const requested = searchParams.get("view");
  const view: View = ["evidence", "rehearsals", "forecasts", "campaigns", "inputs"].includes(String(requested)) ? requested as View : "evidence";
  const selectedId = validatedSelectedId(experimentId);
  const selected = model.experiments.find(item => Number(item.id) === selectedId) as EvidenceRow | undefined;
  const selectedResults = selected ? model.results.filter(item => Number(item.experiment_id) === Number(selected.id)) : [];
  const actions = experimentActionState(model.run, projection.observerState.tick);
  const choose = (nextView: View) => {
    const next = new URLSearchParams(searchParams);
    if (nextView === "evidence") next.delete("view");
    else next.set("view", nextView);
    setSearchParams(next, { replace: true });
  };
  const experimentUrl = (id: number) => workspaceUrl(projection.runId, `experiments/${id}`, projection.observerState);
  const operatorUrl = workspaceUrl(projection.runId, "overview", projection.observerState);

  return <section className="world-os-experiments-workspace">
    <WorkspaceHeader title="Experiments" kicker="Evidence scope and counterfactual lab"
      sourceLabel="Experiments workspace committed projection" envelope={projection.envelope} />
    <WorkspaceState loading={projection.loading} error={projection.error}>
      <dl className="world-os-summary-strip" aria-label="Experiment summary">
        <div><dt>Acceptance records</dt><dd>{model.acceptance.length}</dd></div>
        <div><dt>Checkpoints</dt><dd>{model.checkpoints.length}</dd></div>
        <div><dt>Predictions</dt><dd>{model.predictions.length}</dd></div>
        <div><dt>Campaigns</dt><dd>{model.experiments.length}</dd></div>
        <div><dt>Results</dt><dd>{model.results.length}</dd></div>
      </dl>
      {model.currentOnlyArtifactsOmitted && <p className="world-os-stale-callout">Current-only campaign artifacts are intentionally omitted from this historical view.</p>}
      <aside className="world-os-experiment-boundary" aria-label="Experiment action boundary">
        <div><p className="world-os-kicker">Operator boundary</p><strong>Observer routes never start provider spend or mutate the run.</strong></div>
        <p>{actions.reason || "The run is paused at the live boundary; authorized operator controls may prepare a fork or shock."}</p>
        <Link to={operatorUrl}>Review authorized run controls <span>↗</span></Link>
      </aside>
      <div className="world-os-view-switch world-os-experiment-tabs" role="group" aria-label="Experiment evidence view">
        {(["evidence", "rehearsals", "forecasts", "campaigns", "inputs"] as View[]).map(item => <button type="button" key={item} aria-pressed={view === item} onClick={() => choose(item)}>{text(item)}</button>)}
      </div>

      {view === "evidence" && <section className="world-os-evidence-cards" aria-label="Acceptance and release evidence">
        {(model.acceptance as unknown as EvidenceRow[]).map(item => <article key={item.id} className={`world-os-evidence-card world-os-evidence-card--${item.classification}`}>
          <header><span>{text(item.classification)}</span><small>{item.scheduled_tick == null ? "Unscheduled" : `Tick ${item.scheduled_tick}`}</small></header>
          <h3>{text(item.question, `Evidence record ${item.id}`)}</h3>
          <p>{classificationCopy(item.classification)}</p>
          {item.detail != null && item.detail !== "" && <small>{text(item.detail)}</small>}
        </article>)}
        {!model.acceptance.length && <div className="world-os-empty"><h3>No acceptance evidence</h3><p>A green release label is never inferred without an explicit qualifying record.</p></div>}
      </section>}

      {view === "rehearsals" && <div className="world-os-experiment-grid">
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Replay anchors</p><h3>Checkpoints</h3></div></header>
          <WorkspaceTable caption="Checkpoints" rows={model.checkpoints as EvidenceRow[]} empty="No checkpoint is committed at this tick." columns={[
            { key: "id", label: "Checkpoint", render: row => `#${row.id}` }, { key: "tick", label: "Tick", render: row => text(row.tick) },
            { key: "created", label: "Created", render: row => text(row.created_at) },
          ]} />
        </article>
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Scripted interventions</p><h3>Shocks</h3></div></header>
          <WorkspaceTable caption="Shocks" rows={model.shocks as EvidenceRow[]} empty="No shocks are configured at this tick." columns={[
            { key: "label", label: "Shock", render: row => text(row.label, text(row.kind, `Shock ${row.id}`)) },
            { key: "trigger", label: "Trigger", render: row => text(row.trigger_type) }, { key: "fired", label: "Fired", render: row => row.fired ? text(row.fired_tick, "yes") : "No" },
          ]} />
        </article>
      </div>}

      {view === "forecasts" && <article className="world-os-workspace-card">
        <header><div><p className="world-os-kicker">Resolution-bound forecasts</p><h3>Predictions</h3></div></header>
        <WorkspaceTable caption="Predictions" rows={model.predictions as EvidenceRow[]} empty="No predictions are recorded at this tick." columns={[
          { key: "question", label: "Question", render: row => text(row.question, `Prediction ${row.id}`) },
          { key: "p", label: "Probability", render: row => Number.isFinite(row.p) ? `${(Number(row.p) * 100).toFixed(1)}%` : "—" },
          { key: "confidence", label: "Confidence", render: row => text(row.confidence) },
          { key: "status", label: "Status", render: row => text(row.status) }, { key: "deadline", label: "Deadline", render: row => text(row.deadline_tick) },
        ]} />
      </article>}

      {view === "campaigns" && <div className="world-os-experiment-grid">
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Counterfactual campaigns</p><h3>Experiments</h3></div></header>
          <WorkspaceTable caption="Counterfactual experiments" rows={model.experiments as EvidenceRow[]} selectedId={selected?.id}
            empty={model.currentOnlyArtifactsOmitted ? "Campaigns are omitted outside the current tick." : "No campaign artifacts are present."}
            columns={[
              { key: "name", label: "Experiment", render: row => <Link to={experimentUrl(row.id)}>{text(row.experiment_key, `Experiment ${row.id}`)}</Link> },
              { key: "scenario", label: "Scenario", render: row => text(row.scenario_key) }, { key: "status", label: "Status", render: row => text(row.status) },
            ]} />
        </article>
        <aside className="world-os-workspace-card world-os-experiment-detail" aria-live="polite">
          <header><div><p className="world-os-kicker">Campaign detail</p><h3>{selected ? text(selected.experiment_key) : selectedId ? "Experiment unavailable" : "Select an experiment"}</h3></div></header>
          {selected ? <><dl>
            <div><dt>Status</dt><dd>{text(selected.status)}</dd></div><div><dt>Scenario</dt><dd>{text(selected.scenario_key)}</dd></div>
            <div><dt>Checkpoint hash</dt><dd>{text(selected.checkpoint_hash)}</dd></div><div><dt>Results</dt><dd>{selectedResults.length}</dd></div>
          </dl>{selectedResults.length > 0 && <ul>{selectedResults.map(result => <li key={result.id}>{text(result.arm)} · seed {text(result.seed)} · run {text(result.run_id)}</li>)}</ul>}</> : <p>{selectedId ? "This ID is not present in the authorized current projection." : "Select a validated campaign row."}</p>}
        </aside>
      </div>}

      {view === "inputs" && <div className="world-os-experiment-grid">
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Pinned sources</p><h3>Datasets</h3></div></header>
          <WorkspaceTable caption="Datasets" rows={model.datasets as EvidenceRow[]} empty="No dataset manifests are registered." columns={[
            { key: "dataset", label: "Dataset", render: row => text(row.dataset_key) }, { key: "vintage", label: "Vintage", render: row => text(row.vintage_date) },
            { key: "transform", label: "Transform", render: row => text(row.transform_version) }, { key: "status", label: "Status", render: row => text(row.status) },
          ]} />
        </article>
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Scenario definitions</p><h3>Scenarios</h3></div></header>
          <WorkspaceTable caption="Scenario packs" rows={model.scenarios as EvidenceRow[]} empty="No scenario packs are registered." columns={[
            { key: "scenario", label: "Scenario", render: row => text(row.title, text(row.scenario_key)) }, { key: "version", label: "Version", render: row => text(row.version) },
            { key: "limitations", label: "Limitations", render: row => text(row.limitations) },
          ]} />
        </article>
      </div>}
    </WorkspaceState>
  </section>;
}
