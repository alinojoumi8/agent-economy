export function priceLabSelection(params) {
  const rawFirm = params.get("price_firm");
  const rawWindow = params.get("price_window");
  const validFirm = rawFirm === null || /^[1-9]\d*$/.test(rawFirm) && Number.isSafeInteger(Number(rawFirm));
  const validWindow = rawWindow === null || ["7", "30", "90"].includes(rawWindow);
  return { firmId: rawFirm && validFirm ? Number(rawFirm) : undefined,
    window: validWindow && rawWindow ? Number(rawWindow) : 30, invalid: !validFirm || !validWindow };
}

export function priceLabFrameMatches(envelope, context) {
  if (!envelope || envelope.run_id !== context.runId
      || (envelope.fork_id ?? null) !== (context.fork ?? null)
      || envelope.projection !== "workspace.price_lab"
      || !Number.isSafeInteger(envelope.tick) || envelope.tick < 0
      || context.tick !== "live" && (!/^\d+$/.test(String(context.tick))
        || envelope.tick !== Number(context.tick))) return false;
  const data = envelope.data;
  if (!data || data.contract !== "price-lab-projection-v1" || data.tick !== envelope.tick
      || data.window_ticks !== context.window) return false;
  const selected = data.selected_firm;
  if (context.firmId !== undefined && selected?.id !== context.firmId) return false;
  if (!selected) return data.observation === null;
  return data.observation?.firm_id === selected.id && data.observation.tick === envelope.tick
    && data.observation.start_tick === data.start_tick
    && data.observation.currency === selected.currency_code;
}

export function priceNumber(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "Unavailable";
}
