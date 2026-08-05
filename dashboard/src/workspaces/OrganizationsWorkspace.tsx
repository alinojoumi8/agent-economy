import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  filterOrganizations,
  normalizeOrganizationsWorkspace,
} from "./organizationsWorkspaceModel.js";
import {
  validatedSelectedId,
  WorkspaceHeader,
  WorkspaceState,
  WorkspaceTable,
  workspaceUrl,
  useWorkspaceProjection,
} from "./workspaceShared";

type Organization = {
  id: number; name?: string; type?: string; status?: string; active?: boolean;
  sector?: string; region_id?: number; region_name?: string; currency_code?: string;
  employees?: number; balance_cents?: number; reserve_cents?: number; equity_cents?: number;
  founded_tick?: number; listed_tick?: number; bankrupt_tick?: number; mandate?: string;
  capacity?: number;
};
type OrganizationProjection = {
  organizations?: Organization[];
  firms?: Organization[];
  banks?: Organization[];
  institutions?: { legal_enabled?: boolean; politics_enabled?: boolean; agencies?: Organization[] };
  contracts?: Array<Record<string, unknown>>;
  disclosures?: Array<Record<string, unknown>>;
};

function label(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value).replaceAll("_", " ");
}

function money(cents: unknown, currency: unknown) {
  if (!Number.isFinite(cents)) return "—";
  return `${(Number(cents) / 100).toFixed(2)} ${label(currency, "currency not exposed")}`;
}

export function OrganizationsWorkspace() {
  const projection = useWorkspaceProjection<OrganizationProjection>("workspace.organizations", "/api/v2/workspaces/organizations");
  const { organizationId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const model = normalizeOrganizationsWorkspace(projection.data || {});
  const filters = {
    q: searchParams.get("q") || "",
    type: searchParams.get("type") || "",
    sector: searchParams.get("sector") || "",
    region: searchParams.get("region") || "",
    status: searchParams.get("status") || "",
    activeOnly: searchParams.get("active") === "1",
  };
  const filtered = filterOrganizations(model.organizations, filters) as Organization[];
  const selectedId = validatedSelectedId(organizationId);
  const selected = model.organizations.find(item => Number(item.id) === selectedId) as Organization | undefined;
  const disclosures = selected?.type === "firm"
    ? model.disclosures.filter(item => Number(item.firm_id) === Number(selected.id))
    : [];
  const unique = (key: keyof Organization) => [...new Set(model.organizations.map(item => item[key]).filter(Boolean).map(String))].sort();
  const patchFilter = (key: string, value: string | boolean) => {
    const next = new URLSearchParams(searchParams);
    if (value === "" || value === false) next.delete(key);
    else next.set(key, value === true ? "1" : String(value));
    setSearchParams(next, { replace: true });
  };
  const detailUrl = (organization: Organization) => workspaceUrl(
    projection.runId,
    `organizations/${organization.id}`,
    projection.observerState,
  );

  return <section className="world-os-organizations-workspace">
    <WorkspaceHeader title="Organizations" kicker="Authorized organization directory"
      sourceLabel="Organizations workspace committed projection" envelope={projection.envelope} />
    <WorkspaceState loading={projection.loading} error={projection.error}>
      <dl className="world-os-summary-strip" aria-label="Organization summary">
        <div><dt>Organizations</dt><dd>{model.organizations.length}</dd></div>
        <div><dt>Active</dt><dd>{model.organizations.filter(item => item.active === true).length}</dd></div>
        <div><dt>Firms</dt><dd>{model.firms.length}</dd></div>
        <div><dt>Banks</dt><dd>{model.banks.length}</dd></div>
        <div><dt>Agencies</dt><dd>{model.agencies.length}</dd></div>
      </dl>
      <div className="world-os-institution-state" aria-label="Institution configuration">
        {!model.institutions.legalEnabled && <p className="world-os-disabled-callout">Legal institutions are disabled for this run.</p>}
        {!model.institutions.politicsEnabled && <p className="world-os-disabled-callout">Political institutions are disabled for this run.</p>}
      </div>
      <div className="world-os-filters" aria-label="Organization filters">
        <label>Search <input type="search" value={filters.q} onChange={event => patchFilter("q", event.target.value)} /></label>
        <label>Type <select value={filters.type} onChange={event => patchFilter("type", event.target.value)}><option value="">All</option>{unique("type").map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Sector <select value={filters.sector} onChange={event => patchFilter("sector", event.target.value)}><option value="">All</option>{unique("sector").map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Region <select value={filters.region} onChange={event => patchFilter("region", event.target.value)}><option value="">All</option>{unique("region_name").map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Status <select value={filters.status} onChange={event => patchFilter("status", event.target.value)}><option value="">All</option>{unique("status").map(value => <option key={value}>{value}</option>)}</select></label>
        <label><input type="checkbox" checked={filters.activeOnly} onChange={event => patchFilter("active", event.target.checked)} /> Active only</label>
      </div>
      <div className="world-os-organization-grid">
        <article className="world-os-workspace-card">
          <header><div><p className="world-os-kicker">Directory</p><h3>{filtered.length} matching organizations</h3></div></header>
          <WorkspaceTable caption="Organization directory" rows={filtered} selectedId={selected?.id}
            onSelect={organization => navigate(detailUrl(organization))}
            columns={[
              { key: "name", label: "Organization", render: row => <Link to={detailUrl(row)}>{label(row.name, `Organization ${row.id}`)}</Link> },
              { key: "type", label: "Type", render: row => label(row.type) },
              { key: "sector", label: "Sector / mandate", render: row => label(row.sector || row.mandate) },
              { key: "region", label: "Region", render: row => label(row.region_name, row.region_id == null ? "—" : `Region ${row.region_id}`) },
              { key: "status", label: "Status", render: row => label(row.status) },
              { key: "employees", label: "Employment", render: row => label(row.employees) },
            ]} />
        </article>
        <aside className="world-os-workspace-card world-os-organization-detail" aria-live="polite">
          <header><div><p className="world-os-kicker">Authoritative detail</p><h3>{selected ? label(selected.name) : selectedId ? "Organization unavailable" : "Select an organization"}</h3></div></header>
          {selected ? <>
            <dl>
              <div><dt>Type</dt><dd>{label(selected.type)}</dd></div>
              <div><dt>Status</dt><dd>{label(selected.status)}</dd></div>
              <div><dt>Region</dt><dd>{label(selected.region_name)}</dd></div>
              <div><dt>Sector</dt><dd>{label(selected.sector)}</dd></div>
              <div><dt>Employment</dt><dd>{label(selected.employees)}</dd></div>
              <div><dt>Public balance</dt><dd>{money(selected.balance_cents, selected.currency_code)}</dd></div>
              <div><dt>Reserves</dt><dd>{money(selected.reserve_cents, selected.currency_code)}</dd></div>
              <div><dt>Equity</dt><dd>{money(selected.equity_cents, selected.currency_code)}</dd></div>
              <div><dt>Founded</dt><dd>{selected.founded_tick == null ? "—" : `Tick ${selected.founded_tick}`}</dd></div>
              <div><dt>Terminal tick</dt><dd>{selected.bankrupt_tick == null ? "—" : `Tick ${selected.bankrupt_tick}`}</dd></div>
            </dl>
            {disclosures.length > 0 && <section><h4>Public disclosures</h4><ul>{disclosures.map(item => <li key={String(item.id)}>Tick {label(item.tick)} · {label(item.disclosure_type)}</li>)}</ul></section>}
          </> : <p>{selectedId ? "The requested ID is not present in this authorized projection." : "Choose a validated directory row to inspect public fields."}</p>}
        </aside>
      </div>
      {model.contracts.length > 0 && <article className="world-os-workspace-card world-os-organization-contracts">
        <header><div><p className="world-os-kicker">Public contract registry</p><h3>Contracts</h3></div></header>
        <WorkspaceTable caption="Public contracts" rows={model.contracts}
          columns={[
            { key: "title", label: "Contract", render: row => label(row.title, `Contract ${row.id}`) },
            { key: "type", label: "Type", render: row => label(row.contract_type) },
            { key: "jurisdiction", label: "Jurisdiction", render: row => label(row.jurisdiction) },
            { key: "status", label: "Status", render: row => label(row.status) },
            { key: "tick", label: "Offered", render: row => row.offered_tick == null ? "—" : `Tick ${row.offered_tick}` },
          ]} />
      </article>}
    </WorkspaceState>
  </section>;
}
