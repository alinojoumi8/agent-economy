const REDACTED = "[REDACTED]";
const SENSITIVE_KEY = /(api[_-]?key|authorization|credential|password|secret)/i;
function safeText(value) {
  let safe = value
    .replace(/\bBearer\s+\S+/gi, REDACTED)
    .replace(/\bsk-[A-Za-z0-9_-]{6,}/g, REDACTED)
    .replace(/(api[_-]?key|access[_-]?token|password|secret)=([^&\s]+)/gi,
      (_match, key) => `${key}=${REDACTED}`);
  return safe.length <= 500 ? safe : `${safe.slice(0, 497)}...`;
}

function safeValue(key, value) {
  if (SENSITIVE_KEY.test(key) || key.toLowerCase() === "token" || key.toLowerCase().endsWith("_token")) {
    return REDACTED;
  }
  if (value === null || ["boolean", "number"].includes(typeof value)) return value;
  if (typeof value === "string") return safeText(value);
  if (Array.isArray(value)) return value.map(item => safeValue(key, item));
  if (typeof value === "object") return safeFields(value);
  return safeText(String(value));
}

export function safeFields(fields = {}) {
  return Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, safeValue(key, value)]));
}

export function clientLog(event, fields = {}, level = "info") {
  const payload = {
    timestamp: new Date().toISOString(),
    level: level.toUpperCase(),
    logger: "agent_economy.dashboard",
    event,
    ...safeFields(fields),
  };
  const sink = typeof console[level] === "function" ? console[level] : console.log;
  sink(JSON.stringify(payload));
  return payload;
}
