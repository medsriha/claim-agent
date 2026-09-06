import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const CLAIMS_SERVICE = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/cases": { target: CLAIMS_SERVICE, changeOrigin: true },
      "/admin": { target: CLAIMS_SERVICE, changeOrigin: true },
      "/precedent": { target: CLAIMS_SERVICE, changeOrigin: true },
      "/reports": { target: CLAIMS_SERVICE, changeOrigin: true },
      "/health": { target: CLAIMS_SERVICE, changeOrigin: true },
    },
  },
});
