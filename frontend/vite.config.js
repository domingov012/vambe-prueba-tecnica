import { defineConfig } from 'vite';

// Dev server for the Vambe frontend SPA.
// The frontend always talks to the backend over relative `/api/*` URLs.
// In dev, this proxy forwards them to the local FastAPI instance; in prod,
// nginx (see deploy/) serves the built assets and proxies `/api` to the
// backend container. `VITE_API_TARGET` overrides the dev target if the
// backend runs somewhere other than localhost:8000.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
