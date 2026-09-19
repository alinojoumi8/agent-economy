import { Navigate, Route, Routes, useLocation, useParams } from "react-router";
import { WorkspaceShell } from "./WorkspaceShell";
import { InvestigationsWorkspace } from "../workspaces/InvestigationsWorkspace";
import { CityInformationPanel } from "../workspaces/CityInformationPanel";
import { CommonsWorkspace } from "../workspaces/CommonsWorkspace";
import { PeopleWorkspace } from "../workspaces/PeopleWorkspace";
import { WorldWorkspace } from "../workspaces/WorldWorkspace";
import { OrganizationsWorkspace } from "../workspaces/OrganizationsWorkspace";
import { MarketsWorkspace } from "../workspaces/MarketsWorkspace";
import { PoliticsLawWorkspace } from "../workspaces/PoliticsLawWorkspace";
import { ExperimentsWorkspace } from "../workspaces/ExperimentsWorkspace";
import { CityOperationsWorkspace } from "../workspaces/CityOperationsWorkspace";
import { legacyCityRedirectPath, recordedCityRedirectPath, workspaceFallbackPath } from "../lib/routes";
import { worldOSIndexWorkspace } from "./worldOSRouting.js";

function OverviewRoute() {
  const { runId } = useParams<{ runId?: string }>();
  const location = useLocation();
  const cityPath = legacyCityRedirectPath(runId, location.search, location.hash);
  return <Navigate to={cityPath || `/runs/${encodeURIComponent(runId || '')}/world${location.search}${location.hash}`} replace />;
}

function WorkspaceFallback() {
  const { runId } = useParams<{ runId?: string }>();
  return <Navigate to={`/runs/${encodeURIComponent(runId || '')}/world`} replace />;
}

function RecordedCityRedirect() {
  const { runId = "run" } = useParams();
  const location = useLocation();
  return <Navigate to={recordedCityRedirectPath(runId, location.search, location.hash)} replace />;
}

export function WorldOSApp() {
  const location = useLocation();
  if (worldOSIndexWorkspace(location.pathname) === "commons") {
    return <Routes><Route element={<WorkspaceShell />}>
      <Route path="*" element={<WorldWorkspace panel="Public commons"><CommonsWorkspace /></WorldWorkspace>} />
    </Route></Routes>;
  }
  return <Routes>
    <Route path="live-city" element={<RecordedCityRedirect />} />
    <Route element={<WorkspaceShell />}>
      <Route index element={<OverviewRoute />} />
      <Route path="overview" element={<OverviewRoute />} />
      <Route path="news-communications" element={<WorldWorkspace panel="Conversations & news"><CityInformationPanel /></WorldWorkspace>} />
      <Route path="news-communications/:threadId" element={<WorldWorkspace panel="Conversations & news"><CityInformationPanel /></WorldWorkspace>} />
      <Route path="investigations" element={<WorldWorkspace panel="Evidence"><InvestigationsWorkspace /></WorldWorkspace>} />
      <Route path="investigations/:investigationId" element={<WorldWorkspace panel="Evidence"><InvestigationsWorkspace /></WorldWorkspace>} />
      <Route path="commons" element={<WorldWorkspace panel="Public commons"><CommonsWorkspace /></WorldWorkspace>} />
      <Route path="world" element={<WorldWorkspace />} />
      <Route path="economy" element={<WorldWorkspace panel="Economy"><CityOperationsWorkspace kind="economy" /></WorldWorkspace>} />
      <Route path="operations" element={<WorldWorkspace panel="Operator tools"><CityOperationsWorkspace /></WorldWorkspace>} />
      <Route path="people" element={<WorldWorkspace panel="People"><PeopleWorkspace /></WorldWorkspace>} />
      <Route path="people/:agentId" element={<WorldWorkspace panel="People"><PeopleWorkspace /></WorldWorkspace>} />
      <Route path="organizations" element={<WorldWorkspace panel="Businesses & banks"><OrganizationsWorkspace /></WorldWorkspace>} />
      <Route path="organizations/:organizationType/:organizationId" element={<WorldWorkspace panel="Businesses & banks"><OrganizationsWorkspace /></WorldWorkspace>} />
      <Route path="organizations/:organizationId" element={<WorldWorkspace panel="Businesses & banks"><OrganizationsWorkspace /></WorldWorkspace>} />
      <Route path="markets" element={<WorldWorkspace panel="Markets"><MarketsWorkspace /></WorldWorkspace>} />
      <Route path="politics-law" element={<WorldWorkspace panel="Law & civic life"><PoliticsLawWorkspace /></WorldWorkspace>} />
      <Route path="experiments" element={<WorldWorkspace panel="Research tools"><ExperimentsWorkspace /></WorldWorkspace>} />
      <Route path="experiments/:experimentId" element={<WorldWorkspace panel="Research tools"><ExperimentsWorkspace /></WorldWorkspace>} />
      <Route path="*" element={<WorkspaceFallback />} />
    </Route>
  </Routes>;
}
