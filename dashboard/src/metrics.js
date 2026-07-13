export function rollingSumSeries(series, windowTicks = 30) {
  if (!Array.isArray(series) || series.length === 0) return [];

  const width = Math.max(1, Math.trunc(Number(windowTicks) || 1));
  const window = [];
  let total = 0;

  return series.map((point, index) => {
    const numericTick = Number(point?.tick);
    const tick = Number.isFinite(numericTick) ? numericTick : index;
    const numericValue = Number(point?.value);
    const value = Number.isFinite(numericValue) ? numericValue : 0;

    window.push({ tick, value });
    total += value;
    const firstIncludedTick = tick - width + 1;
    while (window.length && window[0].tick < firstIncludedTick) {
      total -= window.shift().value;
    }

    return { ...point, value: total };
  });
}
