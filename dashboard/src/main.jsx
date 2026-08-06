import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";
import App from "./App";
import "./index.css";
import "./civic-weather-room.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 1_000, retry: 1, refetchOnWindowFocus: false },
  },
});
const router = createBrowserRouter([{ path: "*", element: <App /> }]);

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
