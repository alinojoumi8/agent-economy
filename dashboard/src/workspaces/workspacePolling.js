export function terminalWorkspaceStatus(data) {
  if (!data || typeof data !== "object") return false;
  const status = data.status || data.summary?.status || data.run?.status;
  return ["halted", "completed", "failed", "stopped"].includes(
    String(status || "").toLowerCase(),
  );
}
