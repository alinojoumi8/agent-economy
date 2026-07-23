import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { WorkspaceShell } from "./WorkspaceShell";
import { InvestigationsWorkspace } from "../workspaces/InvestigationsWorkspace";
import { NewsCommunicationsWorkspace } from "../workspaces/NewsCommunicationsWorkspace";
import { OverviewWorkspace } from "../workspaces/OverviewWorkspace";
import { CommonsWorkspace } from "../workspaces/CommonsWorkspace";
import { PeopleWorkspace } from "../workspaces/PeopleWorkspace";
import { workspaceFallbackPath } from "../lib/routes";

function WorkspaceFallback() {
  const { runId } = useParams<{ runId?: string }>();
  return <Navigate to={workspaceFallbackPath(runId)} replace />;
}

function LegacyWorkspace({ title }: { title: string }) {
  return <section className="world-os-empty">
    <p className="world-os-kicker">Canonical route established</p>
    <h2>{title}</h2>
    <p>This semantic lake preserves the current Observatory panel while deeper cross-domain projections follow the communications and causal gate.</p>
    <a className="button" href="/">Open the current panel</a>
  </section>;
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
      <Route path="world" element={<LegacyWorkspace title="World" />} />
      <Route path="people" element={<PeopleWorkspace />} />
      <Route path="people/:agentId" element={<PeopleWorkspace />} />
      <Route path="organizations" element={<LegacyWorkspace title="Organizations" />} />
      <Route path="organizations/:organizationId" element={<LegacyWorkspace title="Organizations" />} />
      <Route path="markets" element={<LegacyWorkspace title="Markets" />} />
      <Route path="politics-law" element={<LegacyWorkspace title="Politics & Law" />} />
      <Route path="experiments" element={<LegacyWorkspace title="Experiments" />} />
      <Route path="experiments/:experimentId" element={<LegacyWorkspace title="Experiments" />} />
      <Route path="*" element={<WorkspaceFallback />} />
    </Route>
  </Routes>;
}
