export type RunReportState = {
  pause_reason?: { reason?: string; active_tick?: number; phase?: string } | null;
};

export function RunReportNotice({ status }: { status?: RunReportState | null }) {
  const deferred = status?.pause_reason;
  if (deferred?.reason !== "report_deferred_partial_tick") return null;
  return <p role="status" className="world-os-policy-note">
    Run stopped during day {deferred.active_tick ?? "unknown"}
    {deferred.phase ? ` (${deferred.phase})` : ""}. No end-of-run report was generated
    because that day is incomplete. The saved checkpoint is preserved.
  </p>;
}
