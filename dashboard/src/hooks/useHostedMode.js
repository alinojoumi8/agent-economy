import { useEffect, useState } from "react";
import {
  configureHostedRouting,
  HOSTED_MODE_PATH,
  isSafeCsrfCookieName,
  resetApiRouting,
} from "../hostedRouting.js";
import { presumedDeploymentMode } from "../lib/deploymentMode.js";

function validModeConfig(value) {
  return Boolean(
    value && value.hosted === true && value.mode === "hosted"
    && value.api_base === "/api/v2"
    && isSafeCsrfCookieName(value.csrf_cookie_name)
    && typeof value.csrf_header_name === "string"
    && Array.isArray(value.profiles),
  );
}

/** Total `/api/v2/mode` attempts before the probe is declared failed. */
export const MODE_PROBE_ATTEMPTS = 3;
const MODE_PROBE_RETRY_BASE_MS = 500;
const MODE_PROBE_RETRY_MAX_MS = 4_000;

export function modeProbeRetryDelay(attempt) {
  const safeAttempt = Math.max(0, Math.min(Number(attempt) || 0, 10));
  return Math.min(MODE_PROBE_RETRY_BASE_MS * (2 ** safeAttempt), MODE_PROBE_RETRY_MAX_MS);
}

/**
 * Classify one `/api/v2/mode` answer.
 *
 * Only a 200 carrying a valid hosted config selects hosted, and only a 200 that
 * says `hosted: false` selects local. Everything else — a network error, a 5xx,
 * a 404, a body that is not the mode document — is inconclusive: it proves
 * nothing about which deployment served the page, so it must not be read as
 * "the server says local" and mount the local observatory on a hosted origin.
 *
 * @param {{ ok: boolean, status?: number, body?: unknown }} answer
 * @returns {{ kind: "hosted", config: object }
 *   | { kind: "local" }
 *   | { kind: "inconclusive", error: string }}
 */
export function classifyModeProbe({ ok, status = 0, body = null }) {
  if (!ok) {
    return { kind: "inconclusive", error: `HTTP ${status || "error"} from ${HOSTED_MODE_PATH}` };
  }
  const value = body;
  const config = validModeConfig(value) ? value : null;
  if (config) return { kind: "hosted", config };
  if (value && typeof value === "object" && value.hosted === false) return { kind: "local" };
  return { kind: "inconclusive", error: `unrecognised document from ${HOSTED_MODE_PATH}` };
}

/**
 * Resolve the deployment mode without blocking first paint.
 *
 * `presumed` is derived synchronously from the document URL (see
 * `lib/deploymentMode.js`) and is available on the very first render, so a
 * caller that lands on a local-only route can mount the real shell immediately.
 * `/api/v2/mode` still runs on every load and remains authoritative: hosted mode
 * is only ever entered once the probe has returned a valid hosted config, local
 * mode only once it has returned `hosted: false`, and a presumption that
 * disagrees with the probe is corrected when it lands. An inconclusive answer is
 * retried with bounded backoff; after the last attempt `error` names the cause
 * and `loading` clears without either mode being selected.
 *
 * @param {string} [pathname] document path; defaults to the live location.
 */
export function useHostedMode(pathname) {
  const [state, setState] = useState(() => ({
    loading: true,
    hosted: false,
    config: null,
    error: "",
    presumed: presumedDeploymentMode(pathname),
  }));

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const probe = async attempt => {
      let verdict;
      try {
        const response = await fetch(HOSTED_MODE_PATH, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const body = await response.json().catch(() => null);
        verdict = classifyModeProbe({ ok: response.ok, status: response.status, body });
      } catch (reason) {
        verdict = {
          kind: "inconclusive",
          error: reason instanceof Error ? reason.message : String(reason),
        };
      }
      if (cancelled) return;
      if (verdict.kind === "hosted") {
        configureHostedRouting({
          csrfCookieName: verdict.config.csrf_cookie_name,
          csrfHeaderName: verdict.config.csrf_header_name,
        });
        setState(current => ({
          ...current, loading: false, hosted: true, config: verdict.config, error: "",
        }));
      } else if (verdict.kind === "local") {
        resetApiRouting();
        setState(current => ({
          ...current, loading: false, hosted: false, config: null, error: "",
        }));
      } else if (attempt + 1 < MODE_PROBE_ATTEMPTS) {
        timer = window.setTimeout(() => probe(attempt + 1), modeProbeRetryDelay(attempt));
      } else {
        setState(current => ({
          ...current, loading: false, hosted: false, config: null, error: verdict.error,
        }));
      }
    };
    probe(0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  return state;
}

export { validModeConfig };
