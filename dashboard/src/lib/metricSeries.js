/** Missing points must not become zero-valued changes through Number(null). */
export function metricDelta(points) {
  const latest = points.at(-1)?.value;
  const previous = points.at(-2)?.value;
  return [latest, previous].every(value => typeof value === "number" && Number.isFinite(value))
    ? latest - previous : null;
}

export function metricAvailabilityText(point) {
  if (!point || point.status !== "unavailable") return null;
  const reasons = {
    empty_resident_labor_force: "No eligible resident workers on this day.",
    no_resident_sentiment_observations: "No resident sentiment observations on this day.",
  };
  return reasons[point.reason] || "No valid observation is recorded for this day.";
}
