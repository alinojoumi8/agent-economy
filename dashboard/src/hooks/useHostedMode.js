import { useEffect, useState } from "react";
import {
  configureHostedRouting,
  HOSTED_MODE_PATH,
  isSafeCsrfCookieName,
  resetApiRouting,
} from "../hostedRouting.js";

function validModeConfig(value) {
  return Boolean(
    value && value.hosted === true && value.mode === "hosted"
    && value.api_base === "/api/v2"
    && isSafeCsrfCookieName(value.csrf_cookie_name)
    && typeof value.csrf_header_name === "string"
    && Array.isArray(value.profiles),
  );
}

export function useHostedMode() {
  const [state, setState] = useState({ loading: true, hosted: false, config: null });

  useEffect(() => {
    let cancelled = false;
    fetch(HOSTED_MODE_PATH, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    }).then(async response => {
      if (!response.ok) return null;
      const value = await response.json();
      return validModeConfig(value) ? value : null;
    }).catch(() => null).then(config => {
      if (cancelled) return;
      if (config) {
        configureHostedRouting({
          csrfCookieName: config.csrf_cookie_name,
          csrfHeaderName: config.csrf_header_name,
        });
        setState({ loading: false, hosted: true, config });
      } else {
        resetApiRouting();
        setState({ loading: false, hosted: false, config: null });
      }
    });
    return () => { cancelled = true; };
  }, []);

  return state;
}

export { validModeConfig };
