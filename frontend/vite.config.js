import { defineConfig } from 'vite';

// Dev server for the Vambe frontend SPA.
// `server.proxy` is left ready for when the FastAPI backend is wired in
// (e.g. proxy `/api` -> http://localhost:8000).
export default defineConfig({
  server: {
    port: 5173,
    // proxy: {
    //   '/api': { target: 'http://localhost:8000', changeOrigin: true },
    // },
  },
});
