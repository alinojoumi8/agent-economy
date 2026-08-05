import type { ProjectionEnvelope } from "../generated/worldOs";

export async function projectionApi<T>(path: string, signal?: AbortSignal): Promise<ProjectionEnvelope<T>> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Projection request failed (${response.status})`);
  }
  return response.json();
}

export function workspaceErrorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return `Workspace request failed (${status})`;
}

export class WorkspaceApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = "WorkspaceApiError";
    this.status = status;
    this.detail = detail;
  }
}

export async function workspaceApi<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : undefined;
    throw new WorkspaceApiError(
      response.status, detail, workspaceErrorMessage(payload, response.status),
    );
  }
  return payload as T;
}
