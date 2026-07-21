export const participantActionKey = item => `${item.type}:${item.variant || "default"}`;

const actionPath = field => field.action_path || [field.name];

function nestedValue(source, path) {
  let value = source;
  for (const part of path) {
    if (value === null || typeof value !== "object" || !(part in value)) return undefined;
    value = value[part];
  }
  return value;
}

function assignNested(target, path, value) {
  let cursor = target;
  for (const part of path.slice(0, -1)) {
    if (cursor[part] === null || typeof cursor[part] !== "object") cursor[part] = {};
    cursor = cursor[part];
  }
  cursor[path.at(-1)] = value;
}

export function initialParticipantValues(descriptor, queued) {
  const initial = {};
  for (const field of descriptor?.fields || []) {
    const queuedValue = queued && queued.type === descriptor.type
      ? nestedValue(queued, actionPath(field))
      : undefined;
    if (queuedValue !== undefined) {
      initial[field.name] = queuedValue;
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
    assignNested(action, actionPath(field), field.kind === "number" ? Number(raw) : raw);
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
