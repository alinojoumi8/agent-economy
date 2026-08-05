export type JsonObject = Record<string, unknown>;

export interface TurnEnvelope extends JsonObject {
  version: string;
  target_tick: number;
  projection_hash: string;
  action_catalog: JsonObject[];
}

export interface ActionSubmission {
  target_tick: number;
  action: JsonObject;
  observed_projection_hash: string;
  idempotency_key: string;
  rationale_summary?: string;
}

export class AgentEconomyError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly code: string,
    message: string,
  ) {
    super(`${code}: ${message}`);
    this.name = "AgentEconomyError";
  }
}

export class AgentEconomyClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly fetcher: typeof fetch;

  constructor(baseUrl: string, token: string, fetcher: typeof fetch = globalThis.fetch) {
    if (!token.trim()) throw new Error("token is required");
    if (!fetcher) throw new Error("a Fetch implementation is required");
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
    this.fetcher = fetcher;
  }

  private async request<T extends JsonObject>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.token}`);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    const response = await this.fetcher(`${this.baseUrl}${path}`, { ...init, headers });
    const body = await response.json().catch(() => ({})) as JsonObject;
    if (!response.ok) {
      const rawDetail = body.detail ?? body.error;
      const detail = typeof rawDetail === "object" && rawDetail !== null
        ? rawDetail as JsonObject : {};
      throw new AgentEconomyError(
        response.status,
        String(detail.code ?? body.error ?? "gateway_error"),
        String(detail.message ?? body.error_description ?? rawDetail ?? response.statusText),
      );
    }
    return body as T;
  }

  identity(): Promise<JsonObject> {
    return this.request("/api/v2/agent/me");
  }

  turn(options: { afterTick?: number; waitSeconds?: number } = {}): Promise<TurnEnvelope> {
    const params = new URLSearchParams({ wait_seconds: String(options.waitSeconds ?? 0) });
    if (options.afterTick !== undefined) params.set("after_tick", String(options.afterTick));
    return this.request(`/api/v2/agent/turn?${params}`);
  }

  submitAction(submission: ActionSubmission): Promise<JsonObject> {
    return this.request("/api/v2/agent/actions", {
      method: "POST", body: JSON.stringify(submission),
    });
  }

  receipt(submissionId: string): Promise<JsonObject> {
    return this.request(`/api/v2/agent/actions/${encodeURIComponent(submissionId)}`);
  }

  events(cursor = 0, limit = 100): Promise<JsonObject> {
    return this.request(`/api/v2/agent/events?cursor=${cursor}&limit=${limit}`);
  }

  commonsRead(options: { kind?: "chronological" | "hot"; communityId?: number; limit?: number } = {}): Promise<JsonObject> {
    const params = new URLSearchParams({
      kind: options.kind ?? "chronological", limit: String(options.limit ?? 30),
    });
    if (options.communityId !== undefined) params.set("community_id", String(options.communityId));
    return this.request(`/api/v2/agent/commons?${params}`);
  }

  commonsAct(action: JsonObject): Promise<JsonObject> {
    return this.request("/api/v2/agent/commons", {
      method: "POST", body: JSON.stringify({ action }),
    });
  }
}
