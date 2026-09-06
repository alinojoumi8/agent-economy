import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

/**
 * One source = one endpoint = one panel.
 *
 * Panels on this surface never share a loading gate. Measured round trips on the
 * live run range from 2 ms (/api/run/status) to more than 30 s (/api/commons),
 * and the ranking is not stable — a projection endpoint contends with the tick
 * loop, so today's fast source is tomorrow's slow one. So nothing here is
 * hard-coded: every panel owns its own query, reports its own measured latency,
 * and renders its own skeleton. A panel that has not received a number renders
 * "pending", never a zero.
 */

export type SourceStatus = "pending" | "resolved" | "error";

export type Source<T> = {
  /** The endpoint path, shown verbatim in the panel header as provenance. */
  label: string;
  status: SourceStatus;
  /** No payload has ever arrived. Skeleton, not zeroes. */
  pending: boolean;
  /** Pending because the request has not been released yet — not yet in flight. */
  queued: boolean;
  data: T | undefined;
  error: Error | null;
  /** Round trip of the last completed fetch, in milliseconds. Measured, not assumed. */
  latencyMs: number | null;
  receivedAt: number | null;
  /** A payload is on screen and a newer one is in flight (stale-while-revalidate). */
  refetching: boolean;
  refetch(): void;
};

type Envelope<T> = { payload: T; latencyMs: number; receivedAt: number };

export async function fetchSource<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => ({}));
    const detail = body && typeof body === "object" && "detail" in body
      ? (body as { detail?: unknown }).detail
      : undefined;
    throw new Error(
      typeof detail === "string" && detail.trim()
        ? detail
        : `${path} failed (${response.status})`,
    );
  }
  return response.json() as Promise<T>;
}

export function useSource<T>(options: {
  key: ReadonlyArray<unknown>;
  path: string;
  /** Provenance label; defaults to the path with its query string trimmed. */
  label?: string;
  enabled?: boolean;
  refetchInterval?: number | false;
  /** Disable across run/fork/tick changes where old payloads would be misleading. */
  retainPreviousData?: boolean;
}): Source<T> {
  const { key, path, enabled = true, refetchInterval = false } = options;
  const label = options.label ?? path.split("?")[0];

  const query = useQuery<Envelope<T>, Error>({
    queryKey: ["ae-source", ...key],
    enabled,
    refetchInterval,
    retry: false,
    placeholderData: options.retainPreviousData === false ? undefined : keepPreviousData,
    queryFn: async ({ signal }) => {
      const started = performance.now();
      const payload = await fetchSource<T>(path, signal);
      return {
        payload,
        latencyMs: Math.round(performance.now() - started),
        receivedAt: Date.now(),
      };
    },
  });

  const envelope = query.data;
  const status: SourceStatus = envelope
    ? "resolved"
    : query.error
      ? "error"
      : "pending";

  return {
    label,
    status,
    pending: status === "pending",
    queued: !enabled && !envelope && !query.error,
    data: envelope?.payload,
    error: query.error ?? null,
    latencyMs: envelope?.latencyMs ?? null,
    receivedAt: envelope?.receivedAt ?? null,
    refetching: Boolean(envelope) && query.isFetching,
    refetch: () => void query.refetch(),
  };
}

/**
 * True once `delayMs` has passed since mount. Used as a release valve so a
 * deferred tier still starts even if the tier it waits on never settles.
 */
export function useAfter(delayMs: number): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setReady(true), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs]);
  return ready;
}

/**
 * Milliseconds since `active` last became true. Drives the honest "resolving,
 * 4.1 s so far" readout, so a slow panel tells the reader how long it has
 * actually been waiting instead of implying a duration it cannot know.
 */
export function useElapsed(active: boolean, stepMs = 100): number {
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      startedAt.current = null;
      setElapsed(0);
      return;
    }
    startedAt.current = performance.now();
    setElapsed(0);
    const timer = window.setInterval(() => {
      if (startedAt.current === null) return;
      setElapsed(performance.now() - startedAt.current);
    }, stepMs);
    return () => window.clearInterval(timer);
  }, [active, stepMs]);

  return elapsed;
}
