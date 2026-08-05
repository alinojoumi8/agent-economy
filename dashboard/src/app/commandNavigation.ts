import { commonObserverSearchParams } from "./observerViewStateCore.js";

export type SearchResultKind = "agent" | "firm" | "event" | "communication_thread";

export type SearchResultItem = {
  kind: SearchResultKind;
  id: number;
  label: string;
  sublabel: string;
};

function withSearch(path: string, params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function workspacePath(
  runId: string,
  workspace: string,
  currentSearch: URLSearchParams,
): string {
  return withSearch(
    `/runs/${encodeURIComponent(runId)}/${workspace}`,
    commonObserverSearchParams(currentSearch),
  );
}

export function searchResultPath(
  runId: string,
  result: SearchResultItem,
  currentSearch: URLSearchParams,
): string {
  const common = commonObserverSearchParams(currentSearch);
  let workspace: string;
  switch (result.kind) {
    case "agent":
      workspace = `people/${result.id}`;
      break;
    case "firm":
      workspace = `organizations/${result.id}`;
      break;
    case "event":
      workspace = "investigations";
      common.set("event", String(result.id));
      break;
    case "communication_thread":
      workspace = `news-communications/${result.id}`;
      break;
  }
  return withSearch(
    `/runs/${encodeURIComponent(runId)}/${workspace}`,
    common,
  );
}
