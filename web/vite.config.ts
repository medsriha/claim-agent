/**
 * How the demo screen is built and served.
 *
 * The proxy is the part worth knowing. The screen and the service run on different ports,
 * and a browser will not read across them unless the service allows it. Rather than open
 * up a service that has no sign-in, the dev server forwards the claim addresses on to it,
 * so the browser sees one address and the service needs no change.
 */
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** Where the claims service is listening. `make run` serves it here. */
const CLAIMS_SERVICE = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/cases": { target: CLAIMS_SERVICE, changeOrigin: true },
      "/health": { target: CLAIMS_SERVICE, changeOrigin: true },
    },
  },
});
