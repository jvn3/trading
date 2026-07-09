/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The frontend talks to the backend via /api, proxied to the FastAPI dev server in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.ALPHADASH_WEB_PORT ?? 5173),
    proxy: {
      "/api": {
        target: process.env.ALPHADASH_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/setupTests.ts",
    exclude: ["node_modules/**", "e2e/**"], // e2e/ belongs to Playwright, not vitest
  },
});
