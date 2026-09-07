import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { workspaceApi } from "../app/api";
import { useObserverViewState } from "../app/observerViewState";
import { StudyLibrary } from "./StudyLibrary";
import { StudyOrigin } from "./StudyOrigin";
import { StudyPolicyEvidence } from "./StudyPolicyEvidence";
import { operatorStudyFrameMatches, policyStudyRequest, priceStudyRequest, studyJobActive } from "./studyLauncherModel.js";
import { WorkspaceTable } from "./workspaceShared";
import { studyCost, studyPhaseLabel, studyPhasePosition } from "./studyLibraryModel.js";
import "./study-launcher.css";

const BASE = "/api/v2/operator/research";
const words = (value: unknown) => String(value ?? "Unavailable").replaceAll("_", " ");
const mib = (value: number) => `${(value / 1048576).toFixed(1)} MiB`;
type CheckpointChoice = { id: string; database_sha256: string; receipt_sha256: string };
type Form = { preset: string; origin: string; checkpoints: CheckpointChoice[]; warmup_ticks: number;
  seeds: string; horizon: number; intervention_tick: number; goods_firm_id: number;
  max_wall_seconds: number; max_disk_mib: number; pause_after_ticks: number | null; pause_after_phase: string | null;
  design: { id: string; sha256: string } | null; model_replicates: string;
  max_provider_calls: number; max_tokens: number; max_spend_usd: number };
const initialForm: Form = { preset: "G2", origin: "fresh_genesis", checkpoints: [], warmup_ticks: 0,
  seeds: "1, 2", horizon: 8, intervention_tick: 3, goods_firm_id: 2, max_wall_seconds: 180, max_disk_mib: 128, pause_after_ticks: null, pause_after_phase: null,
  design: null, model_replicates: "draw1, draw2", max_provider_calls: 500, max_tokens: 1000000, max_spend_usd: 1 };

export function PriceStudyWorkbench() {
  const [params, setParams] = useSearchParams();
  const creating = params.get("study_mode") === "create";
  const choose = (create: boolean) => setParams(previous => {
    const next = new URLSearchParams(previous);
    if (create) next.set("study_mode", "create"); else next.delete("study_mode");
    return next;
  });
  return <>
    <div className="world-os-view-switch" role="group" aria-label="Price study workflow">
      <button type="button" aria-pressed={!creating} onClick={() => choose(false)}>Compare saved studies</button>
      <button type="button" aria-pressed={creating} onClick={() => choose(true)}>Create a study</button>
    </div>
    {creating ? <StudyLauncher /> : <StudyLibrary />}
  </>;
}

export function StudyLauncher() {
  const { runId = "run" } = useParams();
  const [observer] = useObserverViewState();
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const scope = { runId, fork: observer.fork, tick: observer.tick };
  const live = observer.tick === "live";
  const selectedDraft = params.get("study_draft") || "";
  const jobId = params.get("study_job") || "";
  const identity = JSON.stringify([runId, observer.fork, observer.tick, selectedDraft, jobId]);
  const active = useRef(identity);
  active.current = identity;
  useEffect(() => () => { if (active.current === identity) active.current = ""; }, [identity]);
  const [form, setForm] = useState<Form>(initialForm);
  const [approvedDraft, setApprovedDraft] = useState("");
  useEffect(() => { setForm(initialForm); }, [runId, observer.fork, observer.tick]);
  const [operation, setOperation] = useState<{ identity: string; key: object; pending?: boolean; error?: string } | null>(null);
  const currentOperation = operation?.identity === identity ? operation : null;
  const synchronousPending = useRef(false);
  const query = new URLSearchParams({ run_id: runId, tick: "live" });
  if (observer.fork) query.set("fork_id", observer.fork);
  const session = useQuery({ queryKey: ["world-os", runId, "study-operator-session"],
    queryFn: ({ signal }) => workspaceApi<{ csrf_token: string }>("/api/v2/operator/session", { signal }),
    enabled: live, retry: false, refetchOnWindowFocus: false });
  const token = session.data?.csrf_token;
  const headers = { "X-CSRF-Token": token || "", "Content-Type": "application/json" };
  const read = (path: string, signal: AbortSignal) => workspaceApi<any>(`${BASE}${path}?${query}`, { headers, signal });
  const matches = (frame: any, contract: string, id?: string) => operatorStudyFrameMatches(frame, scope, contract, id);
  const capabilities = useQuery({ queryKey: ["study-capabilities", runId, observer.fork, observer.tick],
    queryFn: ({ signal }) => read("/capabilities", signal), enabled: live && Boolean(token), retry: false, refetchOnWindowFocus: false });
  const caps = matches(capabilities.data, "operator-study-launch-capabilities-v1") ? capabilities.data : undefined;
  const jobQuery = useQuery({ queryKey: ["study-job", runId, observer.fork, observer.tick, jobId],
    queryFn: ({ signal }) => read(`/jobs/${encodeURIComponent(jobId)}`, signal),
    enabled: live && Boolean(token && jobId), retry: false, refetchOnWindowFocus: false,
    refetchInterval: query => !query.state.error && matches(query.state.data, "operator-study-job-status-v1", jobId)
      && studyJobActive(query.state.data?.status) ? 1000 : false });
  const job = matches(jobQuery.data, "operator-study-job-status-v1", jobId) ? jobQuery.data : undefined;
  const draftId = job?.draft_id || selectedDraft;
  const draftQuery = useQuery({ queryKey: ["study-draft", runId, observer.fork, observer.tick, draftId],
    queryFn: ({ signal }) => read(`/drafts/${encodeURIComponent(draftId)}`, signal),
    enabled: live && Boolean(token && draftId), retry: false, refetchOnWindowFocus: false });
  const draft = matches(draftQuery.data, "operator-study-draft-v1", draftId) ? draftQuery.data : undefined;
  const policy = Boolean(draft ? draft.policy_design : form.preset === "POLICY");
  const policyCatalog = caps?.policy_designs?.contract === "operator-policy-design-catalog-v1" ? caps.policy_designs : undefined;
  const policyLimits = policyCatalog?.limits;
  const approvalIdentity = draft ? `${identity}:${draft.draft_sha256}` : "";
  const approved = Boolean(approvalIdentity && approvedDraft === approvalIdentity);
  const choosingSaved = form.origin === "verified_checkpoints" && !draftId && !jobId;
  const checkpointQuery = useQuery({ queryKey: ["study-checkpoints", runId, observer.fork, observer.tick],
    queryFn: ({ signal }) => read("/checkpoints", signal), enabled: live && Boolean(token && caps?.checkpoint_fork && choosingSaved),
    retry: false, refetchOnWindowFocus: false });
  const checkpoints = matches(checkpointQuery.data, "operator-checkpoint-catalog-v1") && !checkpointQuery.isFetching && !checkpointQuery.error
    ? checkpointQuery.data : undefined;
  const firstSaved = checkpoints?.items.find((item: any) => item.id === form.checkpoints[0]?.id);
  const mismatch = (capabilities.data && !caps) || (jobQuery.data && !job) || (draftQuery.data && !draft)
    || (choosingSaved && checkpointQuery.data && !matches(checkpointQuery.data, "operator-checkpoint-catalog-v1"));
  const error = currentOperation?.error || session.error?.message || capabilities.error?.message
    || (choosingSaved && checkpointQuery.error?.message)
    || jobQuery.error?.message || draftQuery.error?.message || (mismatch ? "Study response does not match the selected run, fork or artifact. Refresh this workspace." : null);
  const pending = Boolean(currentOperation?.pending);
  const navigate = (values: Record<string, string | null>) => setParams(previous => {
    const next = new URLSearchParams(previous);
    for (const [key, value] of Object.entries(values)) { if (value) next.set(key, value); else next.delete(key); }
    return next;
  });

  const mutate = async (kind: "validate" | "launch" | "recover" | "resume") => {
    if (!live || !token || !caps || mismatch || synchronousPending.current) return;
    if (kind === "resume" && (!job?.resumable || !job.progress_sha256 || !job.resume_check_sha256)) return;
    if (kind === "launch" && policy && !approved) return;
    synchronousPending.current = true;
    const requestIdentity = identity, key = {};
    setOperation({ identity, key, pending: true });
    try {
      const path = kind === "validate" ? "/drafts/validate"
        : kind === "launch" ? `/drafts/${draft.id}/launch` : `/jobs/${job.id}/${kind}`;
      const body = kind === "validate" ? (form.preset === "POLICY" ? policyStudyRequest(form, checkpoints, policyCatalog) : priceStudyRequest(form, checkpoints))
        : kind === "launch" ? { draft_sha256: draft.draft_sha256, idempotency_key: draft.id, ...(policy ? { approve_live_inference: true } : {}) }
        : kind === "resume" ? { progress_sha256: job.progress_sha256, resume_check_sha256: job.resume_check_sha256, idempotency_key: job.id } : undefined;
      const result = await workspaceApi<any>(`${BASE}${path}?${query}`, { headers, method: "POST", body: body ? JSON.stringify(body) : undefined });
      if (active.current !== requestIdentity) return;
      const contract = kind === "validate" ? "operator-study-draft-v1" : "operator-study-job-status-v1";
      if (!matches(result, contract, kind === "recover" ? job.id : undefined)
        || (kind === "launch" && (result.draft_id !== draft.id || result.draft_sha256 !== draft.draft_sha256))
        || (kind === "resume" && (result.parent_job_id !== job.id || result.draft_id !== job.draft_id || result.draft_sha256 !== job.draft_sha256))) {
        throw new Error("Study response does not match the reviewed draft or run context.");
      }
      if (kind === "validate") navigate({ study_draft: result.id, study_job: null });
      else {
        queryClient.setQueryData(["study-job", runId, observer.fork, observer.tick, result.id], result);
        navigate({ study_job: result.id, study_draft: result.draft_id });
        void capabilities.refetch();
      }
    } catch (cause) {
      if (active.current === requestIdentity) setOperation({ identity, key, error: cause instanceof Error ? cause.message : "Study operation failed." });
    } finally {
      synchronousPending.current = false;
      setOperation(previous => previous?.key === key && previous.pending ? null : previous);
    }
  };
  const edit = () => {
    if (draft) setForm({ ...initialForm, ...draft.request, checkpoints: draft.request.checkpoints ?? [],
      model_replicates: (draft.request.model_replicates ?? ["draw1", "draw2"]).join(", "),
      seeds: (draft.request.seeds ?? []).join(", ") });
    void capabilities.refetch();
    navigate({ study_draft: null, study_job: null });
  };
  const compare = () => {
    void queryClient.invalidateQueries({ queryKey: ["study-catalog", runId, observer.fork, observer.tick] });
    navigate({ study: job.study_id, study_mode: null, study_arm: null, study_draft: null, study_job: null });
  };
  if (!live) return <div className="world-os-empty"><h3>Study creation needs the Live workspace</h3>
    <p>Return the observer cursor to Live to use local operator controls. Historical navigation does not start or fetch studies.</p></div>;

  return <section className="study-launcher" aria-label="Create a price study">
    <header><p className="world-os-kicker">Local operator · Independent worlds</p><h3>{job ? "Study execution" : draft ? "Review the validated study" : "Draft a price study"}</h3>
      <p>Compare a baseline with a declared intervention or decision policy. Both goods and equities are measured in every study.</p></header>
    <p className="study-launcher__scope">{policy ? "Policy pilots use small research worlds and owner-configured models. Validation makes no provider calls. Launch requires explicit approval of the original inference allowance." : "These pilots use small research worlds and scripted decisions. Choose fresh worlds or compatible saved worlds explicitly. New external provider calls and spend are zero."}</p>
    {(session.isFetching || capabilities.isFetching || draftQuery.isFetching || (jobQuery.isFetching && !job)) && <p role="status">Loading the local study workspace…</p>}
    {error && <p role="alert" className="world-os-form-error">{error}</p>}
    {caps?.launch_blocked && !job && <aside className="study-launcher__callout"><p>{caps.reason || "A study already owns the local execution slot. You can still prepare a draft."}</p>
      {caps.active_job && <button type="button" onClick={() => navigate({ study_job: caps.active_job.id, study_draft: caps.active_job.draft_id })}>Open active study</button>}
      <button type="button" disabled={capabilities.isFetching} onClick={() => { void capabilities.refetch(); }}>Refresh launch availability</button></aside>}
    {!draftId && !jobId && <form onSubmit={event => { event.preventDefault(); void mutate("validate"); }}>
      <fieldset disabled={!caps || pending}><legend>Study parameters</legend><div className="study-launcher__fields">
        <label>Initial conditions<select value={form.origin} onChange={event => setForm({ ...form, origin: event.target.value, checkpoints: [] })}>
          <option value="fresh_genesis">Fresh worlds</option><option value="verified_checkpoints" disabled={!caps?.checkpoint_fork}>Saved worlds</option></select></label>
        <label>Research question<select value={form.preset} onChange={event => setForm({ ...form, preset: event.target.value,
          max_wall_seconds: event.target.value === "POLICY" ? 300 : Math.min(form.max_wall_seconds, 300),
          max_disk_mib: event.target.value === "POLICY" ? 256 : Math.min(form.max_disk_mib, 128) })}>
          <option value="G2">Goods: input-cost increase (G2)</option><option value="F2">Equities: public firm information (F2)</option>
          <option value="POLICY" disabled={!caps?.live_models}>Goods and equities: decision policies</option></select></label>
        {policy && <>
          <label>Configured policy design<select required value={form.design?.id ?? ""} onChange={event => {
            const selected = policyCatalog?.items.find((item: any) => item.id === event.target.value);
            setForm({ ...form, design: selected ? { id: selected.id, sha256: selected.sha256 } : null });
          }}><option value="">Choose policies</option>{policyCatalog?.items.map((item: any) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          <label>Model draw labels<input required value={form.model_replicates} onChange={event => setForm({ ...form, model_replicates: event.target.value })} aria-describedby="study-draw-help" /></label>
          <label>Original physical-call limit<input type="number" min={1} max={policyLimits?.max_provider_calls} required value={form.max_provider_calls} onChange={event => setForm({ ...form, max_provider_calls: Number(event.target.value) })} /></label>
          <label>Original token limit<input type="number" min={1} max={policyLimits?.max_tokens} required value={form.max_tokens} onChange={event => setForm({ ...form, max_tokens: Number(event.target.value) })} /></label>
          <label>Original spend limit (USD)<input type="number" min={0.000001} max={policyLimits?.max_spend_usd} step="any" required value={form.max_spend_usd} onChange={event => setForm({ ...form, max_spend_usd: Number(event.target.value) })} /></label>
        </>}
        {form.origin === "fresh_genesis" ? <label>World seeds<input value={form.seeds} onChange={event => setForm({ ...form, seeds: event.target.value })} aria-describedby="study-seed-help" /></label>
          : !policy && <label>Additional warmup (days)<input type="number" min={0} max={29} required value={form.warmup_ticks}
            onChange={event => setForm({ ...form, warmup_ticks: Number(event.target.value) })} /></label>}
        <label>Horizon (days)<input type="number" min={3} max={30} required value={form.horizon} onChange={event => setForm({ ...form, horizon: Number(event.target.value) })} /></label>
        {!policy && <><label>Intervention day<input type="number" min={1} max={form.horizon} required value={form.intervention_tick} onChange={event => setForm({ ...form, intervention_tick: Number(event.target.value) })} /></label>
          <label>Goods firm<select value={form.goods_firm_id} onChange={event => setForm({ ...form, goods_firm_id: Number(event.target.value) })}><option value={2}>Firm 2</option><option value={3}>Firm 3</option></select></label></>}
        <label>Wall-time limit (seconds)<input type="number" min={10} max={policy ? policyLimits?.max_wall_seconds : 300} required value={form.max_wall_seconds} onChange={event => setForm({ ...form, max_wall_seconds: Number(event.target.value) })} /></label>
        <label>Evidence disk budget (MiB)<input type="number" min={32} max={policy ? policyLimits?.max_disk_mib : 128} required value={form.max_disk_mib} onChange={event => setForm({ ...form, max_disk_mib: Number(event.target.value) })} /></label>
        {caps?.resume && <label>Pause after saved days (optional)<input type="number" min={1} max={form.horizon - 1} value={form.pause_after_ticks ?? ""}
          onChange={event => setForm({ ...form, pause_after_ticks: event.target.value ? Number(event.target.value) : null, pause_after_phase: null })} aria-describedby="study-pause-help" /></label>}
        {Array.isArray(caps?.pause_phases) && <label>Pause after a step (optional)<select value={form.pause_after_phase ?? ""}
          onChange={event => setForm({ ...form, pause_after_phase: event.target.value || null, pause_after_ticks: null })} aria-describedby="study-pause-help">
          <option value="">No step pause</option>{caps.pause_phases.map((phase: string) => <option key={phase} value={phase}>{studyPhaseLabel(phase)}</option>)}
        </select></label>}
      </div><p id="study-seed-help">Use one to five unique seeds. At least two usable pairs are required for a bootstrap interval. Equity target: listed firm 1; currency: USD.</p>
      {policy && <p id="study-draw-help">Use one to three distinct labels, such as draw1, draw2. These are repeated decisions within each source world, not additional independent worlds. Readiness checks and retries consume the same original allowance.</p>}
      {policy && <button type="button" disabled={capabilities.isFetching} onClick={() => {
        setForm({ ...form, design: null }); void capabilities.refetch();
      }}>Refresh policy designs</button>}
      {!caps?.live_models && policyCatalog && <p>No valid policy designs are configured. The server owner can add a private design to the configured policy directory to enable model comparisons.</p>}
      {choosingSaved && <section className="study-launcher__sources" aria-label="Choose saved worlds">
        <h4>Choose saved worlds</h4><p>Choose the same completed day from one to five independent worlds. Their seeds are retained. {policy ? "The horizon is an absolute simulation day, with at least three new days after the saved day. Each policy begins at the same saved state." : "Horizon and intervention are absolute simulation days; warmup starts after the saved day."}</p>
        <button type="button" disabled={checkpointQuery.isFetching} onClick={() => { setForm({ ...form, checkpoints: [] }); void checkpointQuery.refetch(); }}>Refresh saved worlds</button>
        {checkpointQuery.isFetching && <p role="status">Checking compatible saved states…</p>}
        {checkpoints?.items.length === 0 && <p>No compatible closed snapshots were found. The local catalog accepts the scripted pilot profile and snapshots up to {caps?.checkpoint_source_mib ?? 16} MiB. The checkpoint directory is configured on the server.</p>}
        {checkpoints && <>
          <div className="study-launcher__source-list">{checkpoints.items.map((item: any) => {
            const checked = form.checkpoints.some(choice => choice.id === item.id);
            const conflict = !checked && (form.checkpoints.length >= 5 || (firstSaved && (item.tick !== firstSaved.tick
              || checkpoints.items.some((other: any) => form.checkpoints.some(choice => choice.id === other.id)
                && (item.seed === other.seed || item.run_id === other.run_id)))));
            return <label key={item.id}><input type="checkbox" checked={checked} disabled={Boolean(conflict)}
              onChange={event => setForm(previous => ({ ...previous, checkpoints: event.target.checked
                ? [...previous.checkpoints, { id: item.id, database_sha256: item.database_sha256, receipt_sha256: item.receipt_sha256 }]
                : previous.checkpoints.filter(choice => choice.id !== item.id) }))} />
              <span>Seed {item.seed} · saved day {item.tick}<small>Run {item.run_id} · {mib(item.bytes)}</small></span></label>;
          })}</div>
          <p>{form.checkpoints.length} selected{firstSaved ? ` · new execution starts on day ${firstSaved.tick + 1}` : ""}. Refreshing clears the selection.</p>
          {checkpoints.truncated && <p>This is a bounded catalog. Use the local research commands for sources beyond the catalog limits.</p>}
          {Object.values(checkpoints.omitted ?? {}).some(value => Number(value) > 0) && <p>Omitted: {checkpoints.omitted.oversized ?? 0} oversized and {checkpoints.omitted.unavailable_or_incompatible ?? 0} unavailable or incompatible snapshots.</p>}
        </>}
      </section>}
      {caps?.resume && <p id="study-pause-help">Leave blank to run to completion. Choose a saved-day limit or a step in the first unfinished world. An unfinished day remains pending and has no price comparison. Resume uses the remaining original budget.</p>}
      <button type="submit" disabled={(choosingSaved && (!checkpoints || !form.checkpoints.length)) || (policy && !form.design)}>{pending ? "Validating…" : "Validate draft"}</button></fieldset>
      <p>Validation preserves an immutable protocol and estimates storage. It creates no simulated worlds.</p>
    </form>}
    {draft && <section aria-label="Validated study protocol" className="study-launcher__review">
      <h4>{draft.spec.title}</h4><p>{draft.spec.hypothesis}</p>
      <StudyOrigin origin={draft.origin_details} />
      <dl className="study-launcher__facts">
        <div><dt>Worlds</dt><dd>{draft.estimate.worlds} · seeds {(draft.spec.randomness?.seeds ?? draft.request.seeds ?? []).join(", ")}</dd></div>
        <div><dt>Measurement days</dt><dd>{draft.spec.time.measurement_start}–{draft.spec.time.measurement_end}</dd></div>
        <div><dt>Source + replay ticks</dt><dd>{draft.estimate.source_and_replay_ticks}</dd></div>
        <div><dt>Storage planning allowance</dt><dd>{mib(draft.estimate.disk_bytes)} / {mib(draft.estimate.disk_bytes_limit)} budget</dd></div>
        <div><dt>Wall-time limit</dt><dd>{draft.estimate.wall_seconds_limit} seconds</dd></div>
        <div><dt>Provider calls / spend during validation</dt><dd>0 / $0</dd></div>
        {draft.request.pause_after_ticks != null && <div><dt>Planned pause</dt><dd>After {draft.request.pause_after_ticks} saved days in the first world</dd></div>}
        {draft.request.pause_after_phase != null && <div><dt>Planned pause</dt><dd>After {studyPhaseLabel(draft.request.pause_after_phase)} in the first world</dd></div>}
      </dl>
      {draft.policy_design && !jobId && <StudyPolicyEvidence design={draft.policy_design} allowance={draft.provider_allowance} />}
      <p>{draft.estimate.method}. Actual disk use is checked every 200 ms; a write or final report can exceed the threshold.</p>
      <div className="study-launcher__arms">{draft.spec.arms.map((arm: any) => <article key={arm.key}><h4>{arm.role === "baseline" ? "Baseline" : "Treatment"}</h4><p>{arm.label}</p>
        {arm.changes?.shocks?.length ? arm.changes.shocks.map((shock: any, index: number) => <p key={index}>Day {shock.tick}: {shock.kind === "oil" ? `input commodity cost × ${shock.multiplier}` : `public adverse information about firm ${shock.firm_id}`}</p>) : <p>{policy ? `Decision policy: ${arm.policy}. Common economic conditions.` : "No intervention."}</p>}</article>)}</div>
      <p>{policy ? "Goods and equity prices are equally primary outcomes. Policy comparisons use common observations, feasible actions and economic parameters." : `Goods target: firm ${draft.request.goods_firm_id}; equity target: firm ${draft.request.equity_firm_id}. The preset's primary outcome is declared before execution; the other outcomes remain exploratory.`}</p>
      <details><summary>Frozen protocol and limitations</summary><p>Draft SHA-256: <code>{draft.draft_sha256}</code></p><p>Source tree: <code>{draft.source_identity.source_tree_sha256}</code></p>
        <ul>{draft.spec.limitations.map((item: string) => <li key={item}>{item}</li>)}</ul>
        <pre>{JSON.stringify(draft.spec, null, 2)}</pre></details>
      {!jobId && <div className="study-launcher__actions">
        {policy && !draft.job_id && <label className="study-launcher__approval"><input type="checkbox" checked={approved} onChange={event => setApprovedDraft(event.target.checked ? approvalIdentity : "")} />
          <span>I approve live inference for this reviewed draft, within {draft.request.max_provider_calls} physical calls, {draft.request.max_tokens} tokens and {studyCost(draft.request.max_spend_usd)} total. Readiness checks and any resume share these limits.</span></label>}
        {draft.job_id ? <button type="button" onClick={() => navigate({ study_job: draft.job_id })}>Open this draft's existing job</button>
          : <button type="button" disabled={!caps || caps.launch_blocked || pending || Boolean(mismatch) || (policy && !approved)} onClick={() => { void mutate("launch"); }}>{pending ? "Starting…" : policy ? "Run reviewed policy study" : draft.origin === "verified_checkpoints" ? "Run saved-world study" : "Run independent study"}</button>}
        <button type="button" onClick={edit} disabled={pending}>Edit as a new draft</button>
      </div>}
    </section>}
    {job && <section className="study-launcher__job" aria-label="Study job status">
      <h4>{words(job.status)}</h4><p role="status">{job.finished_cells} / {job.expected_cells} world attempts reported as finished. Eligibility requires the full horizon and verified replay.</p>
      {job.reason && <p>{words(job.reason)}</p>}
      {job.policy_design && <StudyPolicyEvidence design={job.policy_design} allowance={job.provider_allowance} />}
      <WorkspaceTable<any> caption="Study execution progress" rows={job.cells.map((row: any, index: number) => ({ ...row, id: row.cell_key ?? index }))} empty="Waiting for the first world attempt to report."
        columns={[{ key: "arm", label: "Arm", render: row => words(row.arm) }, { key: "seed", label: "Seed", render: row => row.seed },
          ...(job.policy_design ? [{ key: "model_replicate", label: "Model draw", render: (row: any) => row.model_replicate }] : []),
          { key: "execution_status", label: "Execution", render: row => words(row.execution_status) },
          { key: "ticks", label: "Saved day", render: row => row.ticks ?? "Unavailable" },
          { key: "position", label: "Next step", render: row => studyPhasePosition(row, job.resumable || job.status === "completed") },
          { key: "eligibility", label: "Evidence", render: row => words(row.eligibility.status) },
          { key: "reasons", label: "Exclusions", render: row => row.eligibility.reasons.map(words).join(", ") || "None reported" }]} />
      <div className="study-launcher__actions"><button type="button" disabled={jobQuery.isFetching} onClick={() => { void jobQuery.refetch(); }}>Refresh job status</button>
        {job.study_id && <button type="button" onClick={compare}>{job.status === "paused" ? "Inspect saved progress" : "Open verified comparison"}</button>}
        {job.resumable && <button type="button" className="study-launcher__primary" disabled={pending || !caps || Boolean(mismatch)} onClick={() => { void mutate("resume"); }}>{pending ? "Resuming…" : "Resume saved study"}</button>}
        {job.continuation_job_id && <button type="button" onClick={() => navigate({ study_job: job.continuation_job_id })}>Open continuation job</button>}
        {job.recoverable && <button type="button" disabled={pending} onClick={() => { void mutate("recover"); }}>Release interrupted job slot</button>}
        {!studyJobActive(job.status) && <button type="button" onClick={edit}>Prepare another draft</button>}</div>
      {job.recoverable && <p>The supervisor is no longer active. Releasing its slot preserves all evidence; it does not resume or rerun the study.</p>}
      {job.resumable && <p>{Number(job.remaining_wall_seconds).toFixed(1)} seconds remain in the original wall-time budget. Resume continues the same worlds and preserves earlier receipts. Idle time is excluded.</p>}
      {job.resume_unavailable_reason && <p role="status">Resume unavailable: {words(job.resume_unavailable_reason)}. Saved evidence remains available for inspection.</p>}
      <p>Leaving this page does not stop the independent supervisor. Run starts a new study; Resume continues an existing pause. Repeating either request opens its existing job.</p>
    </section>}
  </section>;
}
