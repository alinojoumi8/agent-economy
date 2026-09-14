import { useCallback, useEffect, useState } from "react";

/**
 * Theme lives on the document element as data-theme, which is exactly what
 * src/design/tokens.css keys its light variant on. Dark is the default because
 * the token ladder is dark-first.
 */
export type Theme = "dark" | "light";

const STORAGE_KEY = "ae-theme";

function readTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  const attribute = document.documentElement.getAttribute("data-theme");
  if (attribute === "light" || attribute === "dark") return attribute;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* storage is unavailable; fall through to the dark default */
  }
  return "dark";
}

/**
 * Apply the stored preference before the first render.
 *
 * The hook below only runs where a component calls it (today, Overview), so on
 * every other route a saved light theme was ignored until that workspace
 * mounted. main.jsx calls this once, ahead of createRoot, so the attribute the
 * token ladder keys on is present for the very first paint. The hosted CSP
 * forbids inline scripts, so this cannot live in index.html.
 */
export function applyStoredTheme(root: HTMLElement | null = typeof document === "undefined" ? null : document.documentElement): Theme {
  const theme = readTheme();
  root?.setAttribute("data-theme", theme);
  return theme;
}

export function useTheme(): { theme: Theme; toggleTheme(): void } {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* storage is unavailable; the attribute is still applied for this session */
    }
  }, [theme]);

  const toggleTheme = useCallback(
    () => setTheme(current => (current === "dark" ? "light" : "dark")),
    [],
  );

  return { theme, toggleTheme };
}
