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
    ├── components/
    │   └── nav.js           # persistent top nav, rendered once outside the router outlet
    └── pages/
        ├── upload.js        # Data Upload page
        └── dashboard.js     # Dashboard page (scaffold, placeholder data)
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

**Data Upload is wired; Dashboard is still placeholder.**

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

- **`src/api.js`** — `uploadCsv(file)`, `listJobs()`, `getJob(id)`. The only
  place that knows URL paths and response shapes; add `getDashboardStats()` here
  when wiring the dashboard.

Still to do — **Dashboard page** (`src/pages/dashboard.js`):
   - Replace the `PLACEHOLDER` object with one `getDashboardStats()` call in
     `renderDashboardPage`, then feed the response into the existing `CHARTS`
     specs (each spec's `build(data)` already isolates the data-shape mapping —
     adjust those functions to the real aggregation response keys).
   - Remove the "Scaffold — placeholder data" `.empty-note` banner.
   - Add a loading state and an error/empty state (e.g. "no processed
     transcripts yet") — the aggregation endpoints return nothing until at least
     one enhancement job has completed.

**Backend endpoints:**
   - `POST /api/ingestion/csv` — multipart CSV upload →
     `{ summary, enrichment_job_id }` (job id is null when nothing to enrich)
   - `GET  /api/jobs` — list enrichment jobs, newest first; each has
     `_id` (Beanie serializes the id under its `_id` alias), `filename`,
     `status`, `total_candidates`, `processed_count`, `failed_count`,
     `error`, `created_at`
   - `GET  /api/jobs/{id}` — single job detail
   - `GET  /api/dashboard/...` — *(not built yet)* aggregation results backing
     the charts (see `app/aggregation/` in the backend)

## Notes for future changes

- If routing needs real URLs (history API) or nested layouts, `router.js` is
  ~40 lines — rewrite it rather than bolting on. Don't add a router dependency
  for two pages.
- New page = new file in `src/pages/`, one `registerRoute` line in `main.js`,
  one link in `components/nav.js`.
