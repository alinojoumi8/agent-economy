import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

// Dev API target. Defaults to the usual local server; override with AE_API to point the
// dev server at a different run (e.g. AE_API=http://127.0.0.1:8002 for a live-ticking run).
const apiTarget = process.env.AE_API || "http://127.0.0.1:8000";
const wsTarget = apiTarget.replace(/^http/, "ws");

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/" : "/",
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": apiTarget,
      "/ws": { target: wsTarget, ws: true },
      "/reports": apiTarget,
    },
  },
  build: {
    outDir: resolve(import.meta.dirname, "../server/static"),
    emptyOutDir: true,
  },
}));
