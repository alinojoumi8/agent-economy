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
