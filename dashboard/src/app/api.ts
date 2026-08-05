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
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Workspace request failed (${response.status})`);
  }
  return response.json();
}
