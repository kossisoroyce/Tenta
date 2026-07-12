import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The runtime serves the built assets under the `/dashboard/` prefix (and also
// serves index.html at `/`), so every emitted asset URL must be prefixed to
// match. Build output lands in `dashboard/dist`, which the runtime points at.
export default defineConfig({
  base: "/dashboard/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    // `pnpm dev` proxies API calls to a locally running runtime.
    proxy: {
      "/v1": "http://127.0.0.1:8080",
    },
  },
});
