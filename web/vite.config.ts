/**
 * How the demo screen is built and served while someone is working on it.
 *
 * The one thing worth knowing here is the proxy. The screen and the claims service run
 * on two different ports, and a browser will not let a page on one port read from
 * another unless the service says it may. Rather than open the service up — it has no
 * sign-in, so opening it up to any page anywhere is not a small thing — the development
 * server forwards the claim addresses on to it. As far as the browser is concerned
 * there is only ever one address, and the service needs no change at all.
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
