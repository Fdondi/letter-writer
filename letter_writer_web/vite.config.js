import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const EXTENSION_AND_LOCAL_ORIGIN =
  /^(https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?|moz-extension:\/\/[0-9a-fA-F-]+|chrome-extension:\/\/[a-z]+)$/;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // Allow external connections (needed for Docker)
    allowedHosts: ["frontend", "localhost", "127.0.0.1"],
    cors: {
      origin: EXTENSION_AND_LOCAL_ORIGIN,
      credentials: true,
    },
    proxy: {
      // Proxy API requests to the backend during development
      // In Docker, this will proxy to the backend service
      // For local dev, use http://localhost:8000
      "/api": {
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
        // Align with nginx long waits for slow local LLM responses (avoid dev proxy closing first).
        timeout: 1_800_000,
        proxyTimeout: 1_800_000,
      },
      "/accounts": {
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
}); 