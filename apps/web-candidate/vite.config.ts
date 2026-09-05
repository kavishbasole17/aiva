import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Overridable for dev setups where the frontend and API don't share a
// loopback interface (e.g. the frontend running inside WSL against an API
// bound on the Windows host) -- defaults to the same-host assumption
// everyone else uses.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:18000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 15174,
    proxy: { "/api": { target: apiProxyTarget, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  preview: { host: true, port: 15174 },
});
