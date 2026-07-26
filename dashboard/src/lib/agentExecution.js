const PRESENTATIONS = {
  live: {
    label: "Live AI",
    tone: "good",
    className: "live",
    summary: "A network LLM call is durably recorded for this citizen.",
  },
  awaiting_live: {
    label: "Awaiting live wake",
    tone: "warn",
    className: "awaiting",
    summary: "Live providers are configured, but this citizen has no call receipt yet.",
  },
  scripted: {
    label: "Scripted",
    tone: "neutral",
    className: "scripted",
    summary: "This citizen is using deterministic app-side policy.",
  },
  recorded_replay: {
    label: "Recorded replay",
    tone: "neutral",
    className: "replay",
    summary: "This citizen is replaying a previously recorded model decision.",
  },
  hermes_connected: {
    label: "Hermes connected",
    tone: "good",
    className: "hermes",
    summary: "An external Hermes citizen holds a current gateway lease.",
  },
  hermes_pending: {
    label: "Hermes pending",
    tone: "warn",
    className: "pending",
    summary: "The passport is admitted and its dedicated citizen is awaiting arrival.",
  },
  offline_fallback: {
    label: "Offline fallback",
    tone: "warn",
    className: "fallback",
    summary: "Hermes is offline; the deterministic safe policy controls this wake.",
  },
};

export function agentExecutionPresentation(execution) {
  const state = execution?.state || "scripted";
  const base = PRESENTATIONS[state] || PRESENTATIONS.scripted;
  const route = [execution?.provider, execution?.model].filter(Boolean).join(" · ");
  const receipt = execution?.latest_receipt;
  const proof = receipt
    ? `${receipt.kind === "llm_call" ? "LLM" : "Action"} receipt ${receipt.id} · ${receipt.status}`
    : "No receipt yet";
  return {
    ...base,
    state,
    route,
    proof,
    title: route ? `${base.summary} ${route}. ${proof}.` : `${base.summary} ${proof}.`,
  };
}
