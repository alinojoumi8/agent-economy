export function inferenceMode(readiness) {
  if (!readiness) {
    return {
      label: "AI status loading",
      title: "Provider readiness has not loaded yet.",
      tone: "warn",
      live: false,
    };
  }

  if (!readiness.ready) {
    return {
      label: "AI unavailable",
      title: (readiness.errors || []).join("; ") || "Provider configuration is not ready.",
      tone: "bad",
      live: false,
    };
  }

  if (readiness.mode === "network") {
    const providers = (readiness.providers || [])
      .map(provider => provider.name)
      .filter(Boolean)
      .join(" + ");
    return {
      label: `Live AI${providers ? ` · ${providers}` : ""}`,
      title: "Native agent decisions are routed to network LLM providers.",
      tone: "good",
      live: true,
    };
  }

  return {
    label: "Scripted AI · no LLM calls",
    title: "Native agent decisions use the deterministic local scripted adapter.",
    tone: "warn",
    live: false,
  };
}
