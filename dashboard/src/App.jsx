import { HostedShell } from "./components/HostedShell";
import { Observatory } from "./components/Observatory";
import { useHostedMode } from "./hooks/useHostedMode";

export default function App() {
  const mode = useHostedMode();
  if (mode.loading) {
    return <div className="min-h-screen bg-ink-950" aria-label="Loading Agent Economy" />;
  }
  return mode.hosted
    ? <HostedShell config={mode.config} />
    : <Observatory />;
}
