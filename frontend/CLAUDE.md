# Vambe Frontend

Vanilla-JS Vite SPA for the Vambe transcript-insights app. No framework — plain
DOM APIs, ES modules, a hand-rolled hash router. Two pages: **Data Upload** and
**Dashboard** (Chart.js).

## Run

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # -> dist/
```

Requires Node 20.19+ (Vite 6).

## Structure

```
frontend/
├── index.html            # single mount point (#app), loads src/main.js
├── vite.config.js         # dev server + commented-out /api proxy stub
├── package.json           # vite ^6, chart.js ^4
└── src/
    ├── main.js             # bootstrap: renders nav, creates router outlet, registers routes
    ├── router.js           # minimal hash router: registerRoute / startRouter / navigate
    ├── style.css           # global dark theme + all component styles (no CSS modules)
    ├── format.js            # humanize / percent / relativeTime / isStale helpers (dashboard)
    ├── components/
    │   ├── nav.js           # persistent top nav, rendered once outside the router outlet
    │   ├── closeRateBarChart.js  # reusable "close rate by <dimension>" bar chart
    │   └── heatmap.js       # reusable HTML cross-tab heatmap (sector×need, size×need, rep×sector)
    └── pages/
        ├── upload.js        # Data Upload page
        ├── dashboard.js     # Dashboard page (wired to /api/dashboard/insights)
        └── dashboard.sample.js  # synthetic insights payload for the "sample data" mode
```

## Conventions

- **One module per page**, exporting `renderXPage(mountEl)`. The function builds
  DOM into `mountEl` and **returns an optional cleanup callback** — the router
  calls it on navigation away (used to `clearInterval`, `chart.destroy()`, etc.).
- **Router owns the outlet only.** The nav is rendered once in `main.js` and
  persists across route changes. Routes are hash paths (`/`, `/dashboard`).
- **No build-time templating.** Pages assemble markup with template strings +
  `innerHTML` for static scaffolding, then wire listeners against queried nodes.
- **Styling is global.** All classes live in `src/style.css` keyed by BEM-ish
  names (`.card`, `.chart-card`, `.badge--running`). No inline styles except
  one-off layout nudges.
- **Chart.js is tree-shaken.** `dashboard.js` imports and `Chart.register()`s
  only the controllers/elements/scales it uses. Add registrations when adding
  chart types.
- **No premature abstraction.** No state library, no API client layer, no
  component framework until a second real use needs it.

## Backend wiring

**Data Upload and Dashboard are both wired.**

- **Transport** — relative `/api/*` URLs everywhere (`src/api.js`). The vite dev
  server proxies `/api` → `http://localhost:8000` (`VITE_API_TARGET` overrides);
  in prod nginx serves the static build and proxies `/api` to the backend
  container. Backend routers are mounted under `/api` (see `app/main.py`). No
  CORS config in either environment.

- **Progress updates use polling, not websockets** — `upload.js` polls
  `GET /api/jobs` every 2s while any job is `queued`/`running`, stops on
  all-terminal, restarts after an upload. Job progress only advances once per
  LLM batch, so a 2s poll is visually indistinguishable from pushed events and
  needs no connection/reconnect machinery. Revisit only if we add token
  streaming or many concurrent viewers.

- **`src/api.js`** — `uploadCsv(file)`, `listJobs()`, `getJob(id)`,
  `getDashboardInsights()`. The only place that knows URL paths and response
  shapes. `request()` attaches `err.status` so callers can tell a 404 (no data
  computed yet) from a real failure.

- **Dashboard** (`src/pages/dashboard.js`) — one fetch of
  `GET /api/dashboard/insights`, one loading state, ~14 chart sections rendered
  from the precomputed payload (no per-chart fetching, no client-side
  aggregation — see `aggregations.md`). `SPECS` lists each chart: payload key,
  title, whether it spans the full grid width, and a `render(container, data)`
  fn returning a cleanup. Shared chart shapes live in
  `components/closeRateBarChart.js` and `components/heatmap.js`, mirroring the
  backend's `close_rate_by_dimension` / `needs_matrix` aggregation boundaries.
  - **States**: skeleton placeholders on mount → charts on success (with
    "Data as of {relative}" + a staleness note past 24h); a single
    dashboard-level error with Retry on fetch failure; a per-chart
    "Not enough data yet." note when an individual payload key is empty.
  - **Sample mode**: the DB is empty and the endpoint 404s, so the page starts
    in "sample data" mode — every chart rendered against the synthetic payload
    in `dashboard.sample.js` (shapes/sort match the backend exactly). "Try live
    data" switches to the real endpoint; the error/empty states also offer
    "Preview with sample data". Delete the `load({ sample: true })` default (drop
    to `load({ sample: false })`) once real data flows.

**Backend endpoints:**
   - `POST /api/ingestion/csv` — multipart CSV upload →
     `{ summary, enrichment_job_id }` (job id is null when nothing to enrich)
   - `GET  /api/jobs` — list enrichment jobs, newest first; each has
     `_id` (Beanie serializes the id under its `_id` alias), `filename`,
     `status`, `total_candidates`, `processed_count`, `failed_count`,
     `error`, `created_at`
   - `GET  /api/jobs/{id}` — single job detail
   - `GET  /api/dashboard/insights` — all chart datasets in one precomputed blob
     (`{ <14 dataset keys>, computed_at }`); 404 until an enrichment job has
     completed. Shape documented in `aggregations.md`.

## Notes for future changes

- If routing needs real URLs (history API) or nested layouts, `router.js` is
  ~40 lines — rewrite it rather than bolting on. Don't add a router dependency
  for two pages.
- New page = new file in `src/pages/`, one `registerRoute` line in `main.js`,
  one link in `components/nav.js`.
