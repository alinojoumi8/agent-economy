export const participantActionKey = item => `${item.type}:${item.variant || "default"}`;

export function initialParticipantValues(descriptor, queued) {
  const initial = {};
  for (const field of descriptor?.fields || []) {
    if (queued && queued.type === descriptor.type && queued[field.name] !== undefined) {
      initial[field.name] = queued[field.name];
    } else if (field.default !== undefined) {
      initial[field.name] = field.default;
    } else if (field.kind === "select" && field.options?.length) {
      initial[field.name] = field.options[0].value;
    } else {
      initial[field.name] = "";
    }
  }
  return initial;
}

export function buildParticipantAction(descriptor, values) {
  const action = { type: descriptor.type };
  if ((descriptor.variant || "default") !== "default") action.variant = descriptor.variant;
  for (const field of descriptor.fields || []) {
    const raw = field.kind === "hidden" ? field.default : values[field.name];
    action[field.name] = field.kind === "number" ? Number(raw) : raw;
  }
  return action;
}

export function appendParticipantHistory(current, page) {
  const seen = new Set();
  const items = [...(current?.items || []), ...(page?.items || [])].filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
  return { ...page, items };
}
