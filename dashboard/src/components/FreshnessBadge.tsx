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
  /*
   * Set when the workspace under this badge already names the transport state in
   * its own chrome. The badge then stops repeating the state word and presents
   * itself as the provenance disclosure it actually is, so one screen states one
   * condition once. Nothing is lost: the plain-English explanation and the raw
   * reason code both live inside the disclosure.
   */
  statusShownElsewhere?: boolean;
};

/*
 * Transport reason tokens, written out for people.
 *
 * The token set has two sources and this map covers both. The server emits
 * `backfill_truncated` on a projection_invalidated frame (server/projections/
 * transport.py). The client's cursor reducer (src/app/cursorReducer.js) emits
 * `cursor_ahead`, `cursor_gap`, `lineage_mismatch`, `socket_closed`, and falls
 * back to `invalidated` for an invalidation that carries no reason of its own.
 *
 * SHORT is the one line the badge can show inline; SENTENCE is the full
 * explanation inside the disclosure. The token itself is never dropped — it is
 * demoted to the "Reason code" row so an operator can still quote it.
 */
export const REASON_SHORT: Record<string, string> = {
  backfill_truncated: "reloading; live feed fell behind",
  cursor_ahead: "resyncing to the server",
  cursor_gap: "updates arrived out of order",
  invalidated: "this view was retired; reloading",
  lineage_mismatch: "the run changed; reloading",
  socket_closed: "connection dropped; reconnecting",
};

export const REASON_SENTENCE: Record<string, string> = {
  backfill_truncated:
    "The live feed fell too far behind to replay update by update, so the workspace is reloading the whole picture from the server.",
  cursor_ahead:
    "The workspace asked for updates the server has not published yet, so it is resyncing to the server's position.",
  cursor_gap:
    "Some updates arrived out of order, so the workspace is reloading from the server rather than showing a gap.",
  invalidated:
    "The server retired this view, so the workspace is reloading it.",
  lineage_mismatch:
    "The run or fork behind this view changed, so the workspace is reloading from the new source.",
  socket_closed:
    "The live connection dropped. The workspace is reconnecting and will catch up on its own.",
};

const UNKNOWN_SHORT = "reloading from the server";
const UNKNOWN_SENTENCE =
  "Live updates stopped arriving cleanly, so the workspace is reloading from the server.";

export function reasonShort(staleReason: string | null): string {
  if (!staleReason) return "";
  return REASON_SHORT[staleReason] || UNKNOWN_SHORT;
}

export function reasonSentence(staleReason: string | null): string {
  if (!staleReason) return "";
  return REASON_SENTENCE[staleReason] || UNKNOWN_SENTENCE;
}

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
  statusShownElsewhere = false,
}: FreshnessBadgeProps) {
  const historical = tick !== "live";
  const currentRoster = sourceMode === "current-roster";
  const ownStatus = currentRoster ? "Current roster" : displayStatus(transport.status, historical);
  const ownDetail = currentRoster
    ? historical ? `current data; tick ${tick} selected` : "polling current data"
    : historical
      ? `as of tick ${tick}`
      : transport.status === "live"
        ? `cursor ${transport.cursor}`
        : reasonShort(transport.staleReason) || "reconnecting";
  const display = statusShownElsewhere ? "Provenance" : ownStatus;
  const detail = statusShownElsewhere
    ? historical ? `as of tick ${tick}` : sourceLabel.toLowerCase()
    : ownDetail;
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
      {!statusShownElsewhere
        && <span className={`world-os-health world-os-health--${statusClass}`} aria-hidden="true" />}
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
        {transport.staleReason
          && <div><dt>Reason code</dt><dd>{transport.staleReason}</dd></div>}
      </dl>
      {transport.staleReason && <p role="status">
        {statusShownElsewhere ? `${ownStatus}. ` : ""}{reasonSentence(transport.staleReason)}
      </p>}
    </div>
  </details>;
}
