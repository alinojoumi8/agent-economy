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
    const routeUnavailable = readiness.mode === "network";
    return {
      label: routeUnavailable ? "UNAVAILABLE · provider routing" : "AI unavailable",
      title: (readiness.errors || []).join("; ") || "Provider configuration is not ready.",
      tone: "bad",
      live: false,
    };
  }

  if (readiness.mode === "network") {
    const routeContract = readiness.route_contract;
    const routedProviders = Array.isArray(readiness.routed_providers)
      ? readiness.routed_providers.filter(Boolean)
      : null;
    if (routeContract?.enforced && routeContract.provider && routeContract.model) {
      return {
        label: `LIVE · ${routeContract.model}`,
        title: `All gateway routes are enforced through ${routeContract.provider}.`,
        tone: "good",
        live: true,
      };
    }
    if (routedProviders !== null) {
      if (!routedProviders.length) {
        return {
          label: "UNAVAILABLE · provider routing",
          title: "No network provider routes are active.",
          tone: "bad",
          live: false,
        };
      }
      return {
        label: `HYBRID · ${routedProviders.join(" + ")}`,
        title: "Agent decisions use more than one configured provider route.",
        tone: "warn",
        live: true,
      };
    }
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
