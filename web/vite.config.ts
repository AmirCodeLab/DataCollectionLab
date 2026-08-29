import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Override when the backend is not on the default port — another uvicorn, or
// a container. Development only; a deployed console is same-origin.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      // The health endpoint sits outside /api/v1 (app/main.py) and the header
      // badge reads it, so it needs its own proxy entry.
      "/health": { target: apiTarget, changeOrigin: true },
    },
  },
});
