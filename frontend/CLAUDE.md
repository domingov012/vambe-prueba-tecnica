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

## Backend wiring (not done yet)

Everything is client-side placeholder right now. To connect to the FastAPI
backend:

1. **Dev proxy** — uncomment the `server.proxy` block in `vite.config.js` so
   `/api/*` forwards to `http://localhost:8000`. Then all frontend fetches use
   relative `/api/...` URLs (no CORS config needed in dev).

2. **API module** — add `src/api.js` with thin `fetch` wrappers, e.g.
   `uploadCsv(file)`, `listJobs()`, `getJob(id)`, `getDashboardStats()`. Keep it
   the only place that knows URL paths and response shapes. This is the "second
   concrete use" that justifies the module — don't inline `fetch` in pages.

3. **Data Upload page** (`src/pages/upload.js`):
   - Replace the `startBtn` click handler: `POST /api/ingestion` (or the real
     ingestion route) with `FormData` containing the CSV file. On success, the
     backend returns a job id — refresh the jobs list.
   - Replace `MOCK_JOBS` + the `setInterval` simulation with a poll of
     `GET /api/jobs` (every ~2–3s while any job is `running`/`queued`; stop when
     all terminal). Map the backend job status enum to the `.badge--*` classes.
   - Keep the client-side `.csv` extension check as a fast pre-validation; the
     backend still does the authoritative column/format validation.

4. **Dashboard page** (`src/pages/dashboard.js`):
   - Replace the `PLACEHOLDER` object with one `getDashboardStats()` call in
     `renderDashboardPage`, then feed the response into the existing `CHARTS`
     specs (each spec's `build(data)` already isolates the data-shape mapping —
     adjust those functions to the real aggregation response keys).
   - Remove the "Scaffold — placeholder data" `.empty-note` banner.
   - Add a loading state and an error/empty state (e.g. "no processed
     transcripts yet") — the aggregation endpoints return nothing until at least
     one enhancement job has completed.

5. **Backend endpoints expected** (align names with `app/api/routes/` as they
   land):
   - `POST /api/ingestion` — multipart CSV upload → `{ job_id }`
   - `GET  /api/jobs` — list enhancement jobs with progress
   - `GET  /api/jobs/{id}` — single job detail
   - `GET  /api/dashboard/...` — aggregation results backing the charts
     (see `app/aggregation/` in the backend)

## Notes for future changes

- If routing needs real URLs (history API) or nested layouts, `router.js` is
  ~40 lines — rewrite it rather than bolting on. Don't add a router dependency
  for two pages.
- New page = new file in `src/pages/`, one `registerRoute` line in `main.js`,
  one link in `components/nav.js`.
