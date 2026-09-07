import { WorkspaceTable } from "./workspaceShared";
import { studyCost, studyNumber } from "./studyLibraryModel.js";

export type PolicyDesign = {
  independent_worlds: number; model_replicates: string[]; assigned_cells: number; aggregation: string;
  policies: Array<{ key: string; family: string; provider: string | null; model: string | null;
    temperature: number | null; repair_temperature: number; preflight_temperature: number; prompt_sha256: string | null }>;
  tariffs?: Array<{ provider: string; model: string; max_input_tokens: number; max_output_tokens: number;
    input_usd_per_million_tokens: number; output_usd_per_million_tokens: number }>;
};
export type ProviderAllowance = {
  limits: { max_provider_calls: number; max_tokens: number; max_spend_usd: number; max_wall_seconds: number; max_disk_bytes: number };
  usage: { provider_calls: number | null; reported_tokens: number | null; encumbered_tokens: number | null;
    reported_cost_usd: number | null; encumbered_usd: number | null; unknown_usage_calls: number | null;
    unresolved_calls: number | null; breached_calls: number | null; sealed: boolean | null };
  verified: boolean; preflight_ready: boolean | null;
};

export function StudyPolicyEvidence({ design, allowance }: { design: PolicyDesign; allowance: ProviderAllowance }) {
  const { limits, usage } = allowance;
  return <section className="study-library__verdict study-library__policies" aria-label="Decision policies and original allowance">
    <h4>Decision policies and model draws</h4>
    <p>{design.independent_worlds} independent worlds · {design.model_replicates.length} model draw{design.model_replicates.length === 1 ? "" : "s"} per world and policy · {design.assigned_cells} assigned executions.</p>
    <p>Complete model draws are averaged within each world. Paired effects compare independent worlds; extra draws do not increase the independent-world count.</p>
    <WorkspaceTable caption="Declared decision policies" rows={design.policies.map(policy => ({ ...policy, id: policy.key }))} columns={[
      { key: "policy", label: "Policy", render: row => row.key },
      { key: "model", label: "Model", render: row => row.family === "scripted" ? "Scripted policy" : `${row.provider} · ${row.model}` },
      { key: "sampling", label: "Primary sampling temperature", render: row => row.family === "scripted" ? "Not applicable" : studyNumber(row.temperature) },
      { key: "repair", label: "Repair temperature", render: row => row.family === "scripted" ? "Not applicable" : studyNumber(row.repair_temperature) },
    ]} />
    {design.tariffs && <details><summary>Declared token prices and per-call ceilings</summary>
      <p>Prices are supplied by the operator and are used for reservations and accounting; they are not verified invoices.</p>
      <WorkspaceTable caption="Declared provider tariffs" rows={design.tariffs.map(row => ({ ...row, id: `${row.provider}/${row.model}` }))} columns={[
        { key: "model", label: "Model", render: row => `${row.provider} · ${row.model}` },
        { key: "input", label: "Input USD / million tokens", render: row => studyCost(row.input_usd_per_million_tokens) },
        { key: "output", label: "Output USD / million tokens", render: row => studyCost(row.output_usd_per_million_tokens) },
        { key: "ceilings", label: "Input / output ceiling per call", render: row => `${studyNumber(row.max_input_tokens)} / ${studyNumber(row.max_output_tokens)}` },
      ]} />
    </details>}
    <h4>Original provider allowance</h4>
    <p>{allowance.verified ? (usage.sealed ? "Final accounting is sealed." : "Verified accounting from the saved pause; the original allowance remains open.") : "Usage has not been verified. Declared limits are shown below."}</p>
    <dl className="study-library__metadata">
      <div><dt>Physical calls / original limit</dt><dd>{studyNumber(usage.provider_calls)} / {studyNumber(limits.max_provider_calls)}</dd></div>
      <div><dt>Encumbered tokens / original limit</dt><dd>{studyNumber(usage.encumbered_tokens)} / {studyNumber(limits.max_tokens)}</dd></div>
      <div><dt>Reported tokens</dt><dd>{studyNumber(usage.reported_tokens)}</dd></div>
      <div><dt>Reported usage cost</dt><dd>{studyCost(usage.reported_cost_usd)}</dd></div>
      <div><dt>Encumbered amount / original limit</dt><dd>{studyCost(usage.encumbered_usd)} / {studyCost(limits.max_spend_usd)}</dd></div>
      <div><dt>Calls with unknown usage</dt><dd>{studyNumber(usage.unknown_usage_calls)}</dd></div>
      <div><dt>Unresolved reserved calls</dt><dd>{studyNumber(usage.unresolved_calls)}</dd></div>
      <div><dt>Usage contract breaches</dt><dd>{studyNumber(usage.breached_calls)}</dd></div>
      <div><dt>Recorded preflight</dt><dd>{allowance.preflight_ready === true ? "Verified" : allowance.preflight_ready === false ? "Did not pass" : "Not verified"}</dd></div>
    </dl>
    <p>Readiness checks consume the same allowance as execution. Unknown usage keeps its reservation. Inherited source costs are separate; recorded preflight does not establish current provider availability.</p>
  </section>;
}
