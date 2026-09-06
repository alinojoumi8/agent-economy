export const DEFAULT_CITY_CAMERA = Object.freeze({ x: 50, y: 50, zoom: 3.05 });

/** Validate bookmark values without admitting arbitrary renderer properties. */
export function parseCityCamera(raw) {
  if (typeof raw !== "string" || raw.length > 80) return null;
  const parts = raw.split(",");
  if (parts.length !== 3 || parts.some(part => !/^-?\d+(?:\.\d+)?$/.test(part))) return null;
  const [x, y, zoom] = parts.map(Number);
  if (![x, y, zoom].every(Number.isFinite) || x < 0 || x > 100 || y < 0 || y > 100 || zoom < 1.8 || zoom > 5.4) return null;
  return { x, y, zoom };
}

/** Bound pointer movements to the public city plane and a usable zoom. */
export function normalizeCityCamera(camera) {
  const bounded = (value, fallback, min, max) => Number.isFinite(value)
    ? Math.round(Math.max(min, Math.min(max, value)) * 1000) / 1000 : fallback;
  return { x: bounded(camera?.x, 50, 0, 100), y: bounded(camera?.y, 50, 0, 100),
    zoom: bounded(camera?.zoom, 3.05, 1.8, 5.4) };
}

export function serializeCityCamera(camera) {
  if (!camera) return "";
  const { x, y, zoom } = normalizeCityCamera(camera);
  return x === 50 && y === 50 && zoom === 3.05 ? "" : `${x},${y},${zoom}`;
}
