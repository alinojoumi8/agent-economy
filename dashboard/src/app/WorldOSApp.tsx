import { Navigate, Route, Routes } from "react-router-dom";
import { WorkspaceShell } from "./WorkspaceShell";
import { InvestigationsWorkspace } from "../workspaces/InvestigationsWorkspace";
import { NewsCommunicationsWorkspace } from "../workspaces/NewsCommunicationsWorkspace";
import { OverviewWorkspace } from "../workspaces/OverviewWorkspace";

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
      <Route path="world" element={<LegacyWorkspace title="World" />} />
      <Route path="people" element={<LegacyWorkspace title="People" />} />
      <Route path="people/:agentId" element={<LegacyWorkspace title="People" />} />
      <Route path="organizations" element={<LegacyWorkspace title="Organizations" />} />
      <Route path="organizations/:organizationId" element={<LegacyWorkspace title="Organizations" />} />
      <Route path="markets" element={<LegacyWorkspace title="Markets" />} />
      <Route path="politics-law" element={<LegacyWorkspace title="Politics & Law" />} />
      <Route path="experiments" element={<LegacyWorkspace title="Experiments" />} />
      <Route path="experiments/:experimentId" element={<LegacyWorkspace title="Experiments" />} />
      <Route path="*" element={<Navigate to="overview" replace />} />
    </Route>
  </Routes>;
}
