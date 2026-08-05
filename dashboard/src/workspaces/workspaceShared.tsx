import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useParams } from "react-router";
import { projectionApi } from "../app/api";
import { projectionScopeParams, useObserverViewState } from "../app/observerViewState";
import { FreshnessBadge, useWorkspaceOutletContext } from "../components/FreshnessBadge";
import type { ProjectionEnvelope } from "../generated/worldOs";
import { terminalWorkspaceStatus } from "./workspacePolling.js";
export {
  normalizeWorkspaceFilters, validatedSelectedId, workspaceRouteUrl, workspaceUrl,
} from "./workspaceRouteState";

export function useWorkspaceProjection<T>(projection: string, path: string) {
  const { runId = "run" } = useParams();
  const [observerState, setObserverState] = useObserverViewState();
  const { transport } = useWorkspaceOutletContext();
  const query = useQuery({
    queryKey: ["world-os", runId, observerState.fork, projection, observerState.tick],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      return projectionApi<T>(`${path}?${params}`, signal);
    },
    retry: false,
    refetchInterval: queryState => (
      observerState.tick === "live"
      && !terminalWorkspaceStatus(queryState.state.data?.data) ? 3000 : false
    ),
  });
  return {
    runId, observerState, setObserverState, transport,
    loading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    envelope: query.data as ProjectionEnvelope<T> | undefined,
    data: query.data?.data,
  };
}

export function WorkspaceState({
  loading, error, children,
}: { loading: boolean; error: Error | null; children: ReactNode }) {
  if (loading) return <div className="world-os-loading" aria-label="Loading workspace projection" />;
  if (error) return <div className="world-os-error" role="alert">{error.message}</div>;
  return <>{children}</>;
}

export function WorkspaceHeader({
  title, kicker, sourceLabel, envelope, actions,
}: {
  title: string; kicker: string; sourceLabel: string;
  envelope?: ProjectionEnvelope<unknown>; actions?: ReactNode;
}) {
  const { tick, transport } = useWorkspaceOutletContext();
  return <header className="world-os-heading">
    <div><p className="world-os-kicker">{kicker}</p><h2>{title}</h2></div>
    <div className="world-os-heading-actions">
      <FreshnessBadge transport={transport} tick={tick} envelope={envelope}
        sourceLabel={sourceLabel} />
      {actions}
    </div>
  </header>;
}

export function WorkspaceEmpty({ title = "No records", children }: {
  title?: string; children?: ReactNode;
}) {
  return <div className="world-os-empty"><h3>{title}</h3>{children && <p>{children}</p>}</div>;
}

type WorkspaceColumn<T> = {
  key: string;
  label: string;
  render(row: T): ReactNode;
};

export function WorkspaceTable<T extends { id?: string | number }>({
  caption, columns, rows, empty = "No authorized records at this tick.", selectedId,
  onSelect,
}: {
  caption: string; columns: WorkspaceColumn<T>[]; rows: T[]; empty?: string;
  selectedId?: string | number | null; onSelect?(row: T): void;
}) {
  return <div className="world-os-workspace-table-wrap">
    <table className="world-os-workspace-table">
      <caption className="sr-only">{caption}</caption>
      <thead><tr>{columns.map(column => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
      <tbody>{rows.length ? rows.map((row, index) => {
        const key = row.id ?? index;
        const selectable = Boolean(onSelect);
        return <tr key={key} className={selectedId != null && String(row.id) === String(selectedId) ? "selected" : ""}
          tabIndex={selectable ? 0 : undefined} aria-selected={selectable ? String(row.id) === String(selectedId) : undefined}
          onClick={selectable ? () => onSelect?.(row) : undefined}
          onKeyDown={selectable ? event => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onSelect?.(row);
            }
          } : undefined}>
          {columns.map(column => <td key={column.key}>{column.render(row)}</td>)}
        </tr>;
      }) : <tr><td colSpan={columns.length} className="world-os-workspace-table-empty">{empty}</td></tr>}</tbody>
    </table>
  </div>;
}
