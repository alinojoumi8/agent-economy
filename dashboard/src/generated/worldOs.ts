export type StableReference = {
  kind: string;
  id: string | number;
  tick?: number;
  order_key?: string;
};

export type ProjectionEnvelope<T> = {
  run_id: string;
  fork_id: string | null;
  tick: number;
  semantics_version: number;
  projection_version: number;
  policy_version: number;
  view_key: string;
  snapshot_version: string;
  event_cursor: number;
  projection: string;
  data: T;
};

export type CommunicationMessage = {
  id: number;
  thread_id: number;
  parent_message_id: number | null;
  forwarded_from_id: number | null;
  sender_agent_id: number;
  created_tick: number;
  deliver_at_tick: number;
  visibility: string;
  status: string;
  subject: string;
  body_text?: string;
  access_basis: string;
  sender?: { id: number; name: string; role: string };
  audience: Array<Record<string, unknown>>;
  deliveries: Array<Record<string, unknown>>;
  disclosures: Array<Record<string, unknown>>;
};

export type CommunicationThread = {
  thread_id: number;
  created_tick: number;
  status: string;
  subject: string;
  authorized_message_count: number;
  messages: CommunicationMessage[];
};

export type CausalNode = StableReference & { tick: number; order_key: string };
export type CausalEdge = {
  id: number;
  source: StableReference;
  target: StableReference;
  relation: string;
  authority: string;
  confidence: number;
  method?: string | null;
  provenance: Record<string, unknown>;
  evidence: Record<string, unknown>;
};
