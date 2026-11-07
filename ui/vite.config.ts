import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// /api -> FastAPI on :8001. SSE (/api/stream) must not be buffered or compressed by the dev proxy.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { chunkSizeWarningLimit: 900 }, // cytoscape is ~450 kB; one chunk is fine for a localhost tool
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            if (req.url?.startsWith("/api/stream")) proxyReq.setHeader("Accept-Encoding", "identity");
          });
          proxy.on("proxyRes", (proxyRes, req, res) => {
            if (req.url?.startsWith("/api/stream")) {
              proxyRes.headers["cache-control"] = "no-cache, no-transform";
              proxyRes.headers["x-accel-buffering"] = "no";
              // Node holds response headers until the first body write; an idle SSE stream would never
              // reach the browser's onopen. Flush as soon as the proxy has copied the headers over.
              setImmediate(() => res.flushHeaders());
            }
          });
        },
      },
    },
  },
});
