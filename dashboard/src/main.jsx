import { StrictMode, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider, useLocation } from "react-router";
import "./design/tokens.css";
import App from "./App";
import "./index.css";
import "./civic-weather-room.css";
import "./ui/ui.css";
import { applyStoredTheme } from "./ui/useTheme";

// The saved theme must be on <html> before the first paint on every route, not
// only once a workspace that toggles it has mounted.
applyStoredTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 1_000, retry: 1, refetchOnWindowFocus: false },
  },
});
function RouteScrollReset() {
  const { pathname } = useLocation();
  // Only changing pages resets the viewport. Query-only city selections own
  // their focus/scroll behavior and must not be overwritten by restoration.
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [pathname]);
  return null;
}

const router = createBrowserRouter([{ path: "*", element: <>
  <App />
  <RouteScrollReset />
</> }]);

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
