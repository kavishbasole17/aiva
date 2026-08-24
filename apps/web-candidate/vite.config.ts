import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 15174 },
  preview: { host: true, port: 15174 },
});
