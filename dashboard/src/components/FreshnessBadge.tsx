import { useOutletContext } from "react-router";
import type { ProjectionEnvelope } from "../generated/worldOs";

export type TransportStatus = "connecting" | "live" | "reconnecting" | "stale";

export type ProjectionTransport = {
  runId: string | null;
  forkId: string | null;
  semanticsVersion: number | null;
  projectionVersion: number | null;
  policyVersion: number | null;
  viewKey: string | null;
  cursor: number;
  status: TransportStatus;
  staleReason: string | null;
};

export type WorkspaceOutletContext = {
  tick: string;
  forkId: string | null;
  transport: ProjectionTransport;
};

type FreshnessBadgeProps = {
  transport: ProjectionTransport;
  tick: string;
  envelope?: ProjectionEnvelope<unknown> | null;
  sourceLabel?: string;
  sourceMode?: "projection" | "current-roster";
  placement?: "global" | "workspace";
};

const REASON_LABELS: Record<string, string> = {
  cursor_ahead: "cursor ahead; canonical refetch requested",
  cursor_gap: "cursor gap; canonical refetch requested",
  invalidated: "projection invalidated",
  lineage_mismatch: "lineage mismatch; authoritative hello requested",
  socket_closed: "connection closed; retrying",
};

function displayStatus(status: TransportStatus, historical: boolean) {
  if (historical) return "Historical";
  if (status === "live") return "Live";
  if (status === "reconnecting") return "Reconnecting";
  if (status === "stale") return "Stale";
  return "Connecting";
}

function value(value: unknown, fallback = "not available") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

export function useWorkspaceOutletContext() {
  return useOutletContext<WorkspaceOutletContext>();
}

export function FreshnessBadge({
  transport,
  tick,
  envelope = null,
  sourceLabel = "Committed projection",
  sourceMode = "projection",
  placement = "workspace",
}: FreshnessBadgeProps) {
  const historical = tick !== "live";
  const currentRoster = sourceMode === "current-roster";
  const display = currentRoster ? "Current roster" : displayStatus(transport.status, historical);
  const detail = currentRoster
    ? historical ? `current data; tick ${tick} selected` : "polling current data"
    : historical
      ? `as of tick ${tick}`
      : transport.status === "live"
        ? `cursor ${transport.cursor}`
        : REASON_LABELS[transport.staleReason || ""] || transport.status;
  const statusClass = historical ? "historical" : transport.status;
  const runId = envelope?.run_id ?? transport.runId;
  const forkId = envelope?.fork_id ?? transport.forkId;
  const eventCursor = envelope?.event_cursor ?? transport.cursor;
  const semanticsVersion = envelope?.semantics_version ?? transport.semanticsVersion;
  const projectionVersion = envelope?.projection_version ?? transport.projectionVersion;
  const policyVersion = envelope?.policy_version ?? transport.policyVersion;
  const viewKey = envelope?.view_key ?? transport.viewKey;

  return <details className={`world-os-freshness world-os-freshness--${placement}`}>
    <summary aria-label={`${display}: ${detail}`}>
      <span className={`world-os-health world-os-health--${statusClass}`} aria-hidden="true" />
      <span className="world-os-freshness-copy" aria-live="polite">
        <strong>{display}</strong>
        <small>{detail}</small>
      </span>
      <span className="world-os-freshness-chevron" aria-hidden="true">⌄</span>
    </summary>
    <div className="world-os-freshness-details">
      <p>{sourceMode === "current-roster"
        ? "Polling current-roster data. This is not a reconstructed historical projection."
        : sourceLabel}</p>
      <dl>
        <div><dt>Run</dt><dd>{value(runId)}</dd></div>
        <div><dt>Fork</dt><dd>{value(forkId, "canonical")}</dd></div>
        <div><dt>As of</dt><dd>{envelope ? `tick ${envelope.tick}` : historical ? `tick ${tick}` : "live"}</dd></div>
        <div><dt>Transport</dt><dd>{transport.status}</dd></div>
        {sourceMode === "projection" && <>
          <div><dt>Dataset</dt><dd>{value(envelope?.projection)}</dd></div>
          <div><dt>Event cursor</dt><dd>{value(eventCursor)}</dd></div>
          <div><dt>Snapshot</dt><dd>{value(envelope?.snapshot_version)}</dd></div>
          <div><dt>Semantics</dt><dd>{value(semanticsVersion)}</dd></div>
          <div><dt>Projection</dt><dd>{value(projectionVersion)}</dd></div>
          <div><dt>Policy</dt><dd>{value(policyVersion)}</dd></div>
          <div><dt>View</dt><dd>{value(viewKey)}</dd></div>
        </>}
      </dl>
      {transport.staleReason && <p role="status">
        {REASON_LABELS[transport.staleReason] || transport.staleReason}
      </p>}
    </div>
  </details>;
}
