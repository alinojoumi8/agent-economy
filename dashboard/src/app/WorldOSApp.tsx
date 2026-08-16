import { Navigate, Route, Routes, useLocation, useParams } from "react-router";
import { LiveCity } from "../components/LiveCity";
import { WorkspaceShell } from "./WorkspaceShell";
import { InvestigationsWorkspace } from "../workspaces/InvestigationsWorkspace";
import { NewsCommunicationsWorkspace } from "../workspaces/NewsCommunicationsWorkspace";
import { OverviewWorkspace } from "../workspaces/OverviewWorkspace";
import { CommonsWorkspace } from "../workspaces/CommonsWorkspace";
import { PeopleWorkspace } from "../workspaces/PeopleWorkspace";
import { WorldWorkspace } from "../workspaces/WorldWorkspace";
import { OrganizationsWorkspace } from "../workspaces/OrganizationsWorkspace";
import { MarketsWorkspace } from "../workspaces/MarketsWorkspace";
import { PoliticsLawWorkspace } from "../workspaces/PoliticsLawWorkspace";
import { ExperimentsWorkspace } from "../workspaces/ExperimentsWorkspace";
import { legacyCityRedirectPath, workspaceFallbackPath } from "../lib/routes";
import { worldOSIndexWorkspace } from "./worldOSRouting.js";

function OverviewRoute() {
  const { runId } = useParams<{ runId?: string }>();
  const location = useLocation();
  const cityPath = legacyCityRedirectPath(runId, location.search, location.hash);
  return cityPath ? <Navigate to={cityPath} replace /> : <OverviewWorkspace />;
}

function WorkspaceFallback() {
  const { runId } = useParams<{ runId?: string }>();
  return <Navigate to={workspaceFallbackPath(runId)} replace />;
}

export function WorldOSApp() {
  const location = useLocation();
  if (worldOSIndexWorkspace(location.pathname) === "commons") {
    return <Routes><Route element={<WorkspaceShell />}>
      <Route path="*" element={<CommonsWorkspace />} />
    </Route></Routes>;
  }
  return <Routes>
    {/*
      * Live City sits OUTSIDE the workspace shell on purpose. The shell's rail
      * and topbar are the right frame for a workspace and the wrong one for a
      * map: this route's whole claim is that the city is the screen, so it owns
      * the viewport and floats its own chrome over the geography. It links back
      * to the shell rather than living inside it.
      */}
    <Route path="live-city" element={<LiveCity />} />
    <Route element={<WorkspaceShell />}>
      <Route index element={<Navigate to="overview" replace />} />
      <Route path="overview" element={<OverviewRoute />} />
      <Route path="news-communications" element={<NewsCommunicationsWorkspace />} />
      <Route path="news-communications/:threadId" element={<NewsCommunicationsWorkspace />} />
      <Route path="investigations" element={<InvestigationsWorkspace />} />
      <Route path="investigations/:investigationId" element={<InvestigationsWorkspace />} />
      <Route path="commons" element={<CommonsWorkspace />} />
      <Route path="world" element={<WorldWorkspace />} />
      <Route path="people" element={<PeopleWorkspace />} />
      <Route path="people/:agentId" element={<PeopleWorkspace />} />
      <Route path="organizations" element={<OrganizationsWorkspace />} />
      <Route path="organizations/:organizationType/:organizationId" element={<OrganizationsWorkspace />} />
      <Route path="organizations/:organizationId" element={<OrganizationsWorkspace />} />
      <Route path="markets" element={<MarketsWorkspace />} />
      <Route path="politics-law" element={<PoliticsLawWorkspace />} />
      <Route path="experiments" element={<ExperimentsWorkspace />} />
      <Route path="experiments/:experimentId" element={<ExperimentsWorkspace />} />
      <Route path="*" element={<WorkspaceFallback />} />
    </Route>
  </Routes>;
}
