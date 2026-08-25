import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 15174,
    proxy: { "/api": { target: "http://localhost:18000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  preview: { host: true, port: 15174 },
});
