export function calibrationView(value) {
  const calibration = value && !value.error ? value : {};
  const bins = Array.isArray(calibration.bins) ? calibration.bins : [];
  return {
    empty: !Number(calibration.n),
    n: Number(calibration.n || 0),
    runs: calibration.runs === undefined ? null : Number(calibration.runs || 0),
    brier: calibration.brier ?? null,
    naiveBrier: calibration.naive_brier ?? null,
    reliability: calibration.reliability ?? null,
    resolution: calibration.resolution ?? null,
    uncertainty: calibration.uncertainty ?? null,
    baseRate: calibration.base_rate ?? null,
    beatsNaive: calibration.beats_naive ?? null,
    points: bins.map(bin => ({
      label: bin.bin,
      n: Number(bin.n || 0),
      forecast: Math.max(0, Math.min(1, Number(bin.mean_forecast || 0))),
      observed: Math.max(0, Math.min(1, Number(bin.observed || 0))),
    })),
  };
}
