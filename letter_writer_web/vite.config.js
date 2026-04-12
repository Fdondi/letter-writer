import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // Allow external connections (needed for Docker)
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