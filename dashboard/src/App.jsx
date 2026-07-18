import { HostedShell } from "./components/HostedShell";
import { Observatory } from "./components/Observatory";
import { useHostedMode } from "./hooks/useHostedMode";
import { Route, Routes } from "react-router-dom";
import { WorldOSApp } from "./app/WorldOSApp";

export default function App() {
  const mode = useHostedMode();
  if (mode.loading) {
    return <div className="min-h-screen bg-ink-950" aria-label="Loading Agent Economy" />;
  }
  if (mode.hosted) return <HostedShell config={mode.config} />;
  return <Routes>
    <Route path="/runs/:runId/*" element={<WorldOSApp />} />
    <Route path="*" element={<Observatory />} />
  </Routes>;
}
