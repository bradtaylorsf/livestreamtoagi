/// <reference types="vitest" />
import { defineConfig } from "vite";

const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:8010";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      // Forward audio files, API calls, and WebSocket to the FastAPI backend.
      // Keeps URLs relative in the browser so they work in production too.
      "/audio": BACKEND,
      "/api": BACKEND,
      "/ws": { target: BACKEND.replace("http", "ws"), ws: true },
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
