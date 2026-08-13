import { BootShell } from "./components/BootShell";
import { HostedShell } from "./components/HostedShell";
import { Observatory } from "./components/Observatory";
import { useHostedMode } from "./hooks/useHostedMode";
import { Route, Routes } from "react-router";
import { WorldOSApp } from "./app/WorldOSApp";

export default function App() {
  const mode = useHostedMode();
  // Hosted mode is only ever entered on a confirmed, valid hosted config, so its
  // shell and API routing can never be reached by presumption alone.
  if (mode.hosted) return <HostedShell config={mode.config} />;
  // `/runs/*` and `/commons/*` documents are only served by the local server, so
  // the local shell is correct before the probe answers. `"/"` is ambiguous and
  // waits behind real chrome rather than a blank page.
  if (mode.loading && mode.presumed !== "local") return <BootShell />;
  return <Routes>
    <Route path="/runs/:runId/*" element={<WorldOSApp />} />
    <Route path="/commons/*" element={<WorldOSApp />} />
    <Route path="*" element={<Observatory />} />
  </Routes>;
}
