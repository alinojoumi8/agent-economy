import { Link, useSearchParams } from "react-router";
import { normalizePoliticsLawWorkspace } from "./politicsLawWorkspaceModel.js";
import { organizationWorkspaceUrl } from "./workspaceRouteState.js";
import {
  WorkspaceHeader,
  WorkspaceState,
  WorkspaceTable,
  useWorkspaceProjection,
} from "./workspaceShared";

type EvidenceRow = { id: number; [key: string]: unknown };
type PoliticsLawProjection = {
  politics?: { enabled?: boolean; institutional_actions_enabled?: boolean };
  legal?: { enabled?: boolean };
  bills?: EvidenceRow[]; bill_versions?: EvidenceRow[]; votes?: EvidenceRow[];
  rules?: EvidenceRow[]; lobbying?: EvidenceRow[]; contracts?: EvidenceRow[];
  obligations?: EvidenceRow[]; matters?: EvidenceRow[]; mergers?: EvidenceRow[];
  merger_reviews?: EvidenceRow[];
};
type View = "legislation" | "lobbying" | "legal" | "mergers";

function text(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value).replaceAll("_", " ");
}

function tick(value: unknown) {
  return Number.isFinite(value) ? `Tick ${value}` : "—";
}

function amount(cents: unknown, currency: unknown) {
  return Number.isFinite(cents) ? `${(Number(cents) / 100).toFixed(2)} ${text(currency, "currency not exposed")}` : "—";
}

export function PoliticsLawWorkspace() {
  const projection = useWorkspaceProjection<PoliticsLawProjection>("workspace.politics-law", "/api/v2/workspaces/politics-law");
  const [searchParams, setSearchParams] = useSearchParams();
  const model = normalizePoliticsLawWorkspace(projection.data || {});
  const requested = searchParams.get("view");
  const fallback: View = model.configuration.politicsEnabled ? "legislation" : model.configuration.legalEnabled ? "legal" : "legislation";
  const view: View = ["legislation", "lobbying", "legal", "mergers"].includes(String(requested)) ? requested as View : fallback;
  const choose = (nextView: View) => {
    const next = new URLSearchParams(searchParams);
    if (nextView === fallback) next.delete("view");
    else next.set("view", nextView);
    setSearchParams(next, { replace: true });
  };
  const organizationUrl = (id: unknown) => organizationWorkspaceUrl(
    projection.runId, id, projection.observerState,
  );

  return <section className="world-os-politics-law-workspace">
    <WorkspaceHeader title="Politics & Law" kicker="Institutional record spine"
      sourceLabel="Politics and law committed projection" envelope={projection.envelope} />
    <WorkspaceState loading={projection.loading} error={projection.error}>
      <dl className="world-os-summary-strip" aria-label="Politics and law summary">
        <div><dt>Bills</dt><dd>{model.bills.length}</dd></div>
        <div><dt>Rules</dt><dd>{model.rules.length}</dd></div>
        <div><dt>Contracts</dt><dd>{model.contracts.length}</dd></div>
        <div><dt>Legal matters</dt><dd>{model.matters.length}</dd></div>
        <div><dt>Mergers</dt><dd>{model.mergers.length}</dd></div>
      </dl>
      <div className="world-os-institution-state">
        {!model.configuration.politicsEnabled && <p className="world-os-disabled-callout">Politics is configured disabled; retained political rows are not shown.</p>}
        {model.configuration.politicsEnabled && !model.configuration.institutionalActionsEnabled && <p className="world-os-disabled-callout">Institutional political actions are configured disabled.</p>}
        {!model.configuration.legalEnabled && <p className="world-os-disabled-callout">Legal systems are configured disabled; retained legal rows are not shown.</p>}
      </div>
      <div className="world-os-view-switch world-os-politics-tabs" role="group" aria-label="Institutional evidence view">
        {(["legislation", "lobbying", "legal", "mergers"] as View[]).map(item => <button type="button" key={item} aria-pressed={view === item} onClick={() => choose(item)}>{item === "mergers" ? "M&A" : text(item)}</button>)}
      </div>

      {view === "legislation" && <div className="world-os-politics-stack">
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Legislative lifecycle</p><h3>Bills</h3></div></header>
          <WorkspaceTable caption="Bills" rows={model.bills as EvidenceRow[]} empty={model.configuration.politicsEnabled ? "No bills are committed at this tick." : "Politics is disabled for this run."} columns={[
            { key: "title", label: "Bill", render: row => text(row.title, `Bill ${row.id}`) },
            { key: "chamber", label: "Origin", render: row => text(row.origin_chamber) },
            { key: "version", label: "Version", render: row => text(row.current_version) },
            { key: "status", label: "Status", render: row => text(row.status) },
            { key: "tick", label: "Introduced", render: row => tick(row.introduced_tick) },
          ]} />
        </article>
        <div className="world-os-politics-grid">
          <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Recorded choices</p><h3>Votes</h3></div></header>
            <WorkspaceTable caption="Legislative votes" rows={model.votes as EvidenceRow[]} empty="No votes are committed at this tick." columns={[
              { key: "tick", label: "Tick", render: row => text(row.tick) }, { key: "bill", label: "Bill", render: row => text(row.bill_id) },
              { key: "stage", label: "Stage", render: row => text(row.stage) }, { key: "vote", label: "Vote", render: row => text(row.vote) },
            ]} />
          </article>
          <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Effective policy</p><h3>Rules</h3></div></header>
            <WorkspaceTable caption="Policy rules" rows={model.rules as EvidenceRow[]} empty="No rules are enacted at this tick." columns={[
              { key: "rule", label: "Rule", render: row => text(row.rule_key) }, { key: "status", label: "Status", render: row => text(row.status) },
              { key: "enacted", label: "Enacted", render: row => tick(row.enacted_tick) }, { key: "effective", label: "Effective", render: row => tick(row.effective_tick) },
            ]} />
          </article>
        </div>
      </div>}

      {view === "lobbying" && <article className="world-os-workspace-card">
        <header><div><p className="world-os-kicker">Influence disclosures</p><h3>Lobbying</h3></div></header>
        <WorkspaceTable caption="Lobbying records" rows={model.lobbying as unknown as EvidenceRow[]} empty={model.configuration.politicsEnabled ? "No lobbying is committed at this tick." : "Politics is disabled for this run."} columns={[
          { key: "tick", label: "Tick", render: row => text(row.tick) }, { key: "bill", label: "Bill", render: row => text(row.bill_id) },
          { key: "sponsor", label: "Sponsor", render: row => `${text(row.sponsor_type)} ${text(row.sponsor_id)}` },
          { key: "position", label: "Position", render: row => text(row.position) },
          { key: "amount", label: "Amount (cents)", render: row => Number.isFinite(row.amount_cents) ? `${row.amount_cents} cents` : "—" },
          { key: "disclosure", label: "Disclosure", render: row => text(row.disclosure_state) },
        ]} />
      </article>}

      {view === "legal" && <div className="world-os-politics-stack">
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Public agreements</p><h3>Contracts</h3></div></header>
          <WorkspaceTable caption="Contracts" rows={model.contracts as EvidenceRow[]} empty={model.configuration.legalEnabled ? "No contracts are offered at this tick." : "Legal systems are disabled for this run."} columns={[
            { key: "title", label: "Contract", render: row => text(row.title, `Contract ${row.id}`) }, { key: "type", label: "Type", render: row => text(row.contract_type) },
            { key: "jurisdiction", label: "Jurisdiction", render: row => text(row.jurisdiction) }, { key: "status", label: "Status", render: row => text(row.status) },
          ]} />
        </article>
        <div className="world-os-politics-grid">
          <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Duties</p><h3>Obligations</h3></div></header>
            <WorkspaceTable caption="Obligations" rows={model.obligations as EvidenceRow[]} empty="No obligations are present at this tick." columns={[
              { key: "contract", label: "Contract", render: row => text(row.contract_id) }, { key: "type", label: "Type", render: row => text(row.obligation_type) },
              { key: "due", label: "Due", render: row => tick(row.due_tick) }, { key: "amount", label: "Amount", render: row => amount(row.amount_cents, row.currency_code) },
              { key: "status", label: "Status", render: row => text(row.status) },
            ]} />
          </article>
          <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Cases</p><h3>Legal matters</h3></div></header>
            <WorkspaceTable caption="Legal matters" rows={model.matters as EvidenceRow[]} empty="No matters are filed at this tick." columns={[
              { key: "type", label: "Matter", render: row => text(row.matter_type) }, { key: "claim", label: "Claim", render: row => text(row.claim_type) },
              { key: "venue", label: "Venue", render: row => text(row.venue) }, { key: "status", label: "Status", render: row => text(row.status) },
              { key: "filed", label: "Filed", render: row => tick(row.filed_tick) },
            ]} />
          </article>
        </div>
      </div>}

      {view === "mergers" && <div className="world-os-politics-grid">
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Transactions</p><h3>Mergers & acquisitions</h3></div></header>
          <WorkspaceTable caption="Mergers" rows={model.mergers as EvidenceRow[]} empty={model.configuration.legalEnabled ? "No mergers are proposed at this tick." : "Legal systems are disabled for this run."} columns={[
            { key: "acquirer", label: "Acquirer", render: row => { const href = organizationUrl(row.acquirer_firm_id); return href ? <Link to={href}>Organization {text(row.acquirer_firm_id)}</Link> : "—"; } },
            { key: "target", label: "Target", render: row => { const href = organizationUrl(row.target_firm_id); return href ? <Link to={href}>Organization {text(row.target_firm_id)}</Link> : "—"; } },
            { key: "price", label: "Consideration", render: row => amount(row.price_cents, row.currency_code) },
            { key: "status", label: "Status", render: row => text(row.status) }, { key: "tick", label: "Proposed", render: row => tick(row.proposed_tick) },
          ]} />
        </article>
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">Competition review</p><h3>M&A reviews</h3></div></header>
          <WorkspaceTable caption="Merger reviews" rows={model.mergerReviews as EvidenceRow[]} empty="No competition reviews are committed at this tick." columns={[
            { key: "tick", label: "Tick", render: row => text(row.tick) }, { key: "merger", label: "Merger", render: row => text(row.merger_id) },
            { key: "pre", label: "Pre HHI", render: row => text(row.pre_hhi) }, { key: "post", label: "Post HHI", render: row => text(row.post_hhi) },
            { key: "outcome", label: "Outcome", render: row => text(row.outcome) },
          ]} />
        </article>
      </div>}
    </WorkspaceState>
  </section>;
}
