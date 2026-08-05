import { Navigate, Route, Routes, useParams } from "react-router";
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
import { workspaceFallbackPath } from "../lib/routes";

function WorkspaceFallback() {
  const { runId } = useParams<{ runId?: string }>();
  return <Navigate to={workspaceFallbackPath(runId)} replace />;
}

export function WorldOSApp() {
  return <Routes>
    <Route element={<WorkspaceShell />}>
      <Route index element={<Navigate to="overview" replace />} />
      <Route path="overview" element={<OverviewWorkspace />} />
      <Route path="news-communications" element={<NewsCommunicationsWorkspace />} />
      <Route path="news-communications/:threadId" element={<NewsCommunicationsWorkspace />} />
      <Route path="investigations" element={<InvestigationsWorkspace />} />
      <Route path="investigations/:investigationId" element={<InvestigationsWorkspace />} />
      <Route path="commons" element={<CommonsWorkspace />} />
      <Route path="world" element={<WorldWorkspace />} />
      <Route path="people" element={<PeopleWorkspace />} />
      <Route path="people/:agentId" element={<PeopleWorkspace />} />
      <Route path="organizations" element={<OrganizationsWorkspace />} />
      <Route path="organizations/:organizationId" element={<OrganizationsWorkspace />} />
      <Route path="markets" element={<MarketsWorkspace />} />
      <Route path="politics-law" element={<PoliticsLawWorkspace />} />
      <Route path="experiments" element={<ExperimentsWorkspace />} />
      <Route path="experiments/:experimentId" element={<ExperimentsWorkspace />} />
      <Route path="*" element={<WorkspaceFallback />} />
    </Route>
  </Routes>;
}
