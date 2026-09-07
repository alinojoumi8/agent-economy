import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { workspaceApi } from "../app/api";
import { useObserverViewState } from "../app/observerViewState";
import { WorkspaceTable } from "./workspaceShared";
import { studyFrameMatches, studyNumber, studyOutcomeRows, studyPhasePosition } from "./studyLibraryModel.js";
import { operatorStudyFrameMatches } from "./studyLauncherModel.js";
import { StudyOrigin, type OriginDetails } from "./StudyOrigin";
import "./price-lab.css";
import "./study-library.css";

type CatalogItem = { id: string; title: string; domains: string[]; result_sha256: string; kind?: "working" | "finalized" };
type MeasurementRow = { id: number; arm: string; seed: number; value: number | null; status: string; age_ticks: number | null };
type Catalog = { context: any; contract: string; items: CatalogItem[]; truncated: boolean; omitted: number; scope: string };
type Comparison = { context: any; contract: "operator-study-comparison-v1"; id: string; title: string; hypothesis: string; limitations: string[];
  arms: Array<{ key: string; label: string; role: string }>; measurement_window: number[]; outcomes: any[];
  summary: { baseline_arm: string; coverage: Record<string, any>; metrics: any; exclusions: any[] };
  attempts: any[]; verification: any; verification_sha256: string; manifest_sha256: string; source_identity: any; origin_details?: OriginDetails };
type Working = Omit<Comparison, "contract" | "outcomes" | "summary"> & {
  contract: "operator-working-study-v1"; state: string; comparison_available: false; export_available: boolean;
  budget: { max_wall_seconds: number; active_wall_seconds: number | null; max_disk_bytes: number }; operator_job?: any };

const words = (value: unknown) => String(value ?? "Unavailable").replaceAll("_", " ");
const isWorking = (value: Comparison | Working): value is Working => value.contract === "operator-working-study-v1";
const isComparison = (value: Comparison | Working): value is Comparison => value.contract === "operator-study-comparison-v1";

function DomainComparison({ study, domain, treatment }: { study: Comparison; domain: string; treatment: string }) {
  const rows = studyOutcomeRows(study, domain, treatment);
  const label = domain === "goods" ? "Goods" : "Equities";
  return <article className="world-os-workspace-card" aria-label={`${label} study comparison`}>
    <header><div><p className="world-os-kicker">{domain === "goods" ? "Real economy" : "Financial markets"}</p><h3>{label}</h3></div></header>
    {!rows.length && <p className="price-lab__note">No outcome for this domain was declared in this study.</p>}
    {rows.map((row: any) => <section key={row.key} className="study-library__outcome" aria-label={row.label}>
      <h4>{row.label} <span>{row.purpose === "primary" ? "Primary outcome" : "Exploratory"}</span></h4>
      <p>{row.currency && `${row.currency} · `}{words(row.unit)} · {words(row.aggregation)}</p>
      <dl className="price-lab__measurements">
        <div><dt>Baseline mean</dt><dd>{studyNumber(row.baseline)}</dd></div>
        <div><dt>Treatment mean</dt><dd>{studyNumber(row.treatment)}</dd></div>
        <div><dt>Mean paired difference</dt><dd><strong>{studyNumber(row.difference)}</strong></dd></div>
        <div><dt>{study.origin_details?.kind === "verified_checkpoints" ? "Usable saved-world pairs" : "Usable seed pairs"}</dt><dd>{row.pairs} / {row.assignedPairs}</dd></div>
      </dl>
      <p>95% paired bootstrap interval: {row.interval ? `${studyNumber(row.interval[0])} to ${studyNumber(row.interval[1])}` : "Unavailable"}.</p>
      {row.exclusions.length > 0 && <details><summary>{row.exclusions.length} excluded pair{row.exclusions.length === 1 ? "" : "s"}</summary>
        <ul>{row.exclusions.map((item: any, index: number) => <li key={index}>Seed {item.seed}: {words(item.reason || item.reasons?.join(", "))}</li>)}</ul></details>}
      <details><summary>Values and execution age by seed</summary>
        <WorkspaceTable<MeasurementRow> caption={`Outcome evidence for ${row.label}`} rows={row.measurements.map((item: any, index: number) => ({ ...item, id: index }))}
          columns={[
            { key: "arm", label: "Arm", render: item => words(item.arm) },
            { key: "seed", label: "Seed", render: item => item.seed },
            { key: "value", label: "Value", render: item => studyNumber(item.value) },
            { key: "status", label: "Evidence", render: item => words(item.status) },
            { key: "age", label: "Execution age (ticks)", render: item => item.age_ticks == null ? "Not recorded for this measure" : item.age_ticks },
          ]} />
      </details>
      <details><summary>Measurement definition</summary><p>{row.formula}</p><p>{row.missingness}</p><code>{row.metric_version}</code></details>
    </section>)}
  </article>;
}

export function StudyLibrary() {
  const { runId = "run" } = useParams();
  const [observer] = useObserverViewState();
  const [params, setParams] = useSearchParams();
  const studyId = params.get("study") || "";
  const scope = { runId, fork: observer.fork, tick: observer.tick };
  const live = observer.tick === "live";
  const query = new URLSearchParams({ run_id: runId, tick: "live" });
  if (observer.fork) query.set("fork_id", observer.fork);
  const session = useQuery({ queryKey: ["world-os", runId, "study-operator-session"],
    queryFn: ({ signal }) => workspaceApi<{ csrf_token: string }>("/api/v2/operator/session", { signal }),
    enabled: live, retry: false, refetchOnWindowFocus: false });
  const token = session.data?.csrf_token;
  const headers = { "X-CSRF-Token": token || "" };
  const catalog = useQuery({ queryKey: ["study-catalog", runId, observer.fork, observer.tick],
    queryFn: ({ signal }) => workspaceApi<Catalog>(`/api/v2/operator/research/studies?${query}`, { headers, signal }),
    enabled: live && Boolean(token), retry: false, refetchOnWindowFocus: false });
  const currentCatalog = studyFrameMatches(catalog.data, scope) && !catalog.isFetching ? catalog.data : undefined;
  const selected = currentCatalog?.items.find(item => item.id === studyId);
  const detailQuery = new URLSearchParams(query);
  if (selected) detailQuery.set("result_sha256", selected.result_sha256);
  const detail = useQuery({ queryKey: ["study-comparison", runId, observer.fork, observer.tick, studyId, selected?.result_sha256],
    queryFn: ({ signal }) => workspaceApi<Comparison | Working>(`/api/v2/operator/research/studies/${encodeURIComponent(studyId)}?${detailQuery}`, { headers, signal }),
    enabled: Boolean(live && token && selected), retry: false, refetchOnWindowFocus: false });
  const study = selected && !detail.isFetching && studyFrameMatches(detail.data,
    { ...scope, studyId, resultHash: selected.result_sha256, kind: selected.kind }) ? detail.data : undefined;
  const comparison = study && isComparison(study) ? study : undefined;
  const working = study && isWorking(study) ? study : undefined;
  const operatorJob = working?.operator_job?.study_id === studyId && operatorStudyFrameMatches(working.operator_job,
    scope, "operator-study-job-status-v1", working.operator_job.id) ? working.operator_job : undefined;
  const treatment = study?.arms.find(arm => arm.key === params.get("study_arm") && arm.role === "treatment")?.key
    || study?.arms.find(arm => arm.role === "treatment")?.key || "";
  const [exportState, setExportState] = useState<{ identity: string; pending?: boolean; error?: string; sha256?: string } | null>(null);
  const identity = `${runId}:${observer.fork}:${observer.tick}:${studyId}:${study?.verification_sha256}`;
  const active = useRef(identity);
  active.current = identity;
  useEffect(() => () => { if (active.current === identity) active.current = ""; }, [identity]);
  const choose = (key: string, value: string) => setParams(previous => {
    const next = new URLSearchParams(previous);
    if (value) next.set(key, value); else next.delete(key);
    if (key === "study") next.delete("study_arm");
    return next;
  });
  const download = async () => {
    if (!study || !token || (working && !working.export_available) || (exportState?.identity === identity && exportState.pending)) return;
    const exportIdentity = identity;
    setExportState({ identity, pending: true });
    try {
      const receipt = await workspaceApi<{ token: string; sha256: string }>(`/api/v2/operator/research/studies/${study.id}/export?${query}`,
        { method: "POST", headers, body: JSON.stringify({ result_sha256: study.verification.result_sha256,
          verification_sha256: study.verification_sha256 }) });
      if (active.current !== exportIdentity) return;
      const response = await fetch(`/api/v2/operator/research/exports/${encodeURIComponent(receipt.token)}?${query}`,
        { credentials: "same-origin", headers });
      if (!response.ok) throw new Error("The saved evidence bundle could not be downloaded.");
      const blob = await response.blob();
      if (active.current !== exportIdentity) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `study-${study.id}.zip`;
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
      setExportState({ identity: exportIdentity, sha256: receipt.sha256 });
    } catch (error) {
      if (active.current === exportIdentity) setExportState({ identity: exportIdentity,
        error: error instanceof Error ? error.message : "Evidence export failed." });
    } finally {
      setExportState(current => current?.identity === exportIdentity && current.pending
        ? { identity: exportIdentity } : current);
    }
  };
  const mismatch = (catalog.data && !catalog.isFetching && !studyFrameMatches(catalog.data, scope))
    || (selected && detail.data && !detail.isFetching && !studyFrameMatches(detail.data,
      { ...scope, studyId, resultHash: selected.result_sha256, kind: selected.kind }));
  const error = session.error || catalog.error || detail.error
    || (mismatch ? new Error("Study evidence does not match the selected run, fork, study or result identity.") : null);
  const shownExport = exportState?.identity === identity ? exportState : null;

  if (!live) return <div className="world-os-empty"><h3>Saved studies use the current operator workspace</h3>
    <p>Return the observer cursor to Live to open the local study library. Historical world evidence stays at the selected tick.</p></div>;

  return <section className="study-library price-lab" aria-label="Saved price studies">
    <header className="price-lab__intro"><div><p className="world-os-kicker">Local operator · Price Discovery Lab</p><h3>Compare saved studies</h3>
      <p>Inspect paired worlds, missing observations and preserved evidence. These studies are independent of the world currently open.</p></div></header>
    <div className="price-lab__controls">
      <label>Saved study <select aria-label="Saved study" value={selected?.id || ""} onChange={event => choose("study", event.target.value)}>
        <option value="">Choose a study to verify</option>{currentCatalog?.items.map(item => <option key={item.id} value={item.id}>{item.title} · {item.kind === "working" ? "Working · " : ""}{item.id.slice(0, 6)}</option>)}
      </select></label>
      <button type="button" disabled={!token || catalog.isFetching} onClick={() => { void catalog.refetch(); }}>Refresh library</button>
      {comparison && <label>Treatment arm <select aria-label="Treatment arm" value={treatment} onChange={event => choose("study_arm", event.target.value)}>
        {comparison.arms.filter(arm => arm.role === "treatment").map(arm => <option key={arm.key} value={arm.key}>{arm.label}</option>)}
      </select></label>}
      {study && <button type="button" onClick={() => { void detail.refetch(); }}>Verify again</button>}
    </div>
    {(session.isFetching || catalog.isFetching || detail.isFetching) && <p role="status">Checking saved study evidence…</p>}
    {error && <p className="world-os-form-error" role="alert">{error instanceof Error ? error.message : "Study library is unavailable."}</p>}
    {currentCatalog?.truncated && <p>The catalog is limited to 100 studies and a bounded directory scan. Use the local research commands for older batches.</p>}
    {Boolean(currentCatalog?.omitted) && <p>{currentCatalog?.omitted} malformed catalog record(s) could not be listed.</p>}
    {currentCatalog && !currentCatalog.items.length && <div className="world-os-empty"><h3>No saved price studies</h3><p>Choose Create a study to prepare a G2 or F2 pilot, or use the local research commands.</p></div>}
    {studyId && currentCatalog && !selected && <p role="alert">This study is not in the current local catalog.</p>}
    {study && <StudyOrigin origin={study.origin_details} />}
    {working && <section className="study-library__verdict" aria-label="Working study progress">
      <h4>Working study · {words(working.state)}</h4>
      <p>{working.verification.status === "verified" ? "Saved checkpoint verified. Study eligibility is pending." : "This checkpoint has not been verified. Refresh after execution stops or inspect the job status."}</p>
      <p>Price-effect comparisons become available after finalization and replay checks. Earlier completed cells and unfinished assignments are preserved below.</p>
      <WorkspaceTable caption="Saved study days" rows={working.attempts.map((row, index) => ({ ...row, id: index }))} columns={[
        { key: "arm", label: "Arm", render: row => words(row.arm) }, { key: "seed", label: "Seed", render: row => row.seed },
        { key: "ticks", label: "Saved day / horizon", render: row => `${row.ticks ?? "Unavailable"} / ${row.expected_ticks}` },
        { key: "position", label: "Next step", render: row => studyPhasePosition(row, working.verification.status === "verified") },
        { key: "execution", label: "Execution", render: row => words(row.execution_status) },
        { key: "eligibility", label: "Eligibility", render: row => words(row.eligibility.status) },
      ]} />
      <p>Active wall time: {studyNumber(working.budget.active_wall_seconds)} / {working.budget.max_wall_seconds} seconds. Original disk budget: {studyNumber(working.budget.max_disk_bytes / 1048576)} MiB.</p>
      {operatorJob ? <button type="button" onClick={() => setParams(previous => {
        const next = new URLSearchParams(previous); next.set("study_mode", "create");
        next.set("study_job", operatorJob.id); next.set("study_draft", operatorJob.draft_id); return next;
      })}>Open study controls</button> : <p>Resume controls are available in the local operator workspace that launched this study. Command-line studies retain their original configuration and controls.</p>}
    </section>}
    {comparison && <>
      <div className="study-library__verdict" aria-live="polite"><strong>{comparison.verification.status === "verified" ? "Evidence verified" : "Evidence needs attention"}</strong>
        <span>Measurement ticks {comparison.measurement_window.join("–")} · exploratory paired worlds</span>
        <p>{comparison.hypothesis}</p><p>Small samples and narrow intervals do not establish real-economy fit. A zero response and an unavailable observation are different results.</p>
        <p>Arm means use each arm's available eligible observations. Paired differences use matching eligible seeds.</p>
      </div>
      <WorkspaceTable caption="Study attempt coverage" rows={comparison.arms.map(arm => ({ ...arm, ...comparison.summary.coverage[arm.key], id: arm.key }))}
        columns={[
          { key: "arm", label: "Arm", render: row => row.label },
          { key: "assigned", label: "Assigned", render: row => row.assigned },
          { key: "started", label: "Started", render: row => row.started },
          { key: "completed", label: "Completed", render: row => row.completed },
          { key: "eligible", label: "Eligible", render: row => row.eligible },
        ]} />
      <div className="price-lab__domains"><DomainComparison study={comparison} domain="goods" treatment={treatment} />
        <DomainComparison study={comparison} domain="equities" treatment={treatment} /></div>
    </>}
    {study && <>
      <details><summary>Attempt and exclusion evidence</summary>
        <WorkspaceTable caption="Preserved study attempts" rows={study.attempts.map((row, index) => ({ ...row, id: index }))} columns={[
          { key: "arm", label: "Arm", render: row => words(row.arm) }, { key: "seed", label: "Seed", render: row => row.seed },
          { key: "execution", label: "Execution", render: row => words(row.execution_status) },
          { key: "ticks", label: "Ticks", render: row => `${row.ticks} / ${row.expected_ticks}` },
          { key: "eligible", label: "Eligibility", render: row => words(row.eligibility.status) },
          { key: "reasons", label: "Reasons", render: row => row.eligibility.reasons.length ? words(row.eligibility.reasons.join(", ")) : "None" },
        ]} />
        {study.verification.issues?.map((issue: any, index: number) => <p key={index}>{words(issue.reason)}</p>)}
      </details>
      <details><summary>Protocol, costs and limitations</summary>
        <dl className="study-library__metadata">
          <div><dt>Provider calls</dt><dd>{studyNumber(study.verification.operations?.provider_calls)}</dd></div>
          <div><dt>Provider spend (USD)</dt><dd>{studyNumber(study.verification.operations?.provider_spend_usd)}</dd></div>
          <div><dt>Cost evidence</dt><dd>{words(study.verification.operations?.status)}</dd></div>
          <div><dt>Model and input snapshots</dt><dd>{words(study.verification.declared_context)}</dd></div>
          <div><dt>Manifest SHA-256</dt><dd><code>{study.manifest_sha256}</code></dd></div>
          <div><dt>Source commit</dt><dd><code>{study.source_identity.git_commit}</code></dd></div>
        </dl><ul>{study.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </details>
      <aside className="study-library__export"><h4>Private evidence bundle</h4>
        <p>Includes original run databases, recorded communications, local paths and receipts. Keep this archive within your research workspace.</p>
        {working && <p>This archive preserves a working checkpoint with pending eligibility. Importing it verifies evidence; it does not grant resume compatibility.</p>}
        <button type="button" onClick={() => { void download(); }} disabled={shownExport?.pending || (working && !working.export_available)}>{shownExport?.pending ? "Verifying and packaging…" : "Download private evidence"}</button>
        <p>UI export supports up to 128 MiB of source evidence. The local bundle command supports larger studies.</p>
        {shownExport?.error && <p role="alert">{shownExport.error}</p>}
        {shownExport?.sha256 && <p role="status">Download ready. SHA-256: <code>{shownExport.sha256}</code></p>}
      </aside>
    </>}
  </section>;
}
