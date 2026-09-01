# Vambe Frontend

Vanilla-JS Vite SPA for the Vambe transcript-insights app. No framework and no
chart library — plain DOM APIs, ES modules, a hand-rolled hash router. Two
pages: **Data Upload** and **Dashboard**.

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
├── index.html            # mount point (#app) + Google Fonts link, loads src/main.js
├── vite.config.js         # dev server + commented-out /api proxy stub
├── package.json           # vite ^6 (no runtime deps)
└── src/
    ├── main.js             # bootstrap: renders nav, creates router outlet, registers routes
    ├── router.js           # minimal hash router: registerRoute / startRouter / navigate
    ├── style.css           # design tokens + all component styles (no CSS modules)
    ├── format.js            # humanize / percent / count / relativeTime / isStale helpers
    ├── components/
    │   ├── nav.js           # persistent top nav, rendered once outside the router outlet
    │   ├── barList.js       # the dashboard's chart mark: createProportionList / createCountList
    │   ├── segmented.js     # tablist selector used by every dashboard section
    │   ├── dropdown.js      # native <select>, for the one selector too long to be a tab strip
    │   ├── timeSeries.js    # SVG line chart for the monthly trend (team + one rep)
    │   └── heatmap.js       # HTML cross-tab heatmap (sector×need, size×need)
    └── pages/
        ├── upload.js        # Data Upload page
        ├── dashboard.js     # Dashboard page (wired to /api/dashboard/insights)
        └── dashboard.sample.js  # synthetic insights payload for the "sample data" mode
```

## Design language

- **Palette** — deep pine ground (`--pine`), chalk text, **amber `--signal` for
  close rates** and **mint `--tide` for counts**. The two colours are semantic,
  not decorative: amber charts are proportions, mint ones are frequencies.
- **Type** — Archivo (width 125, "expanded") for display, IBM Plex Sans for
  body, IBM Plex Mono for eyebrows and every numeric readout. Loaded from Google
  Fonts in `index.html`; every stack has a system fallback.
- **The mark** — one bar shape carries the whole dashboard: **length = close
  rate, thickness = sample size**, dashed rule = the dataset's volume-weighted
  average. The thickness encoding is the point — it makes "100% of 2 deals"
  read as small without a tooltip. The hero draws that same mark at full scale
  (the entire dataset as one bar) so the grammar is established before it's
  decomposed. The monthly trend is the exception — a **line**, because the
  question there is the slope between months, not the height of any one of
  them. A line has no thickness to spend, so sample size moves to the point:
  dot radius = meetings that month, hollow under `min_sample`. Missing months
  break the path rather than dropping to 0% (a rep who took no meetings and a
  rep who closed nothing are different claims). Drawn in real pixels against a
  `ResizeObserver` — a scaled `viewBox` would stretch the dots into ellipses.
- **Small samples lose contrast, not just thickness.** Any list sorted by rate
  floats the thinnest bars to the top — exactly the rows nobody should act on —
  so rows under `_meta.min_sample` also render at 42% opacity (`.bar--faint`),
  with the reason in their tooltip. Where every row in a view is under the gate,
  the section says so in words: an entirely dimmed chart reads as disabled.
- **Layout** — no card grid. Full-bleed sections split by hairlines, each an
  asymmetric rail (eyebrow / question / controls) beside its chart body.

## Conventions

- **One module per page**, exporting `renderXPage(mountEl)`. The function builds
  DOM into `mountEl` and **returns an optional cleanup callback** — the router
  calls it on navigation away (used to `clearInterval`, `chart.destroy()`, etc.).
- **Router owns the outlet only.** The nav is rendered once in `main.js` and
  persists across route changes. Routes are hash paths (`/`, `/dashboard`).
- **No build-time templating.** Pages assemble markup with template strings +
  `innerHTML` for static scaffolding, then wire listeners against queried nodes.
- **Styling is global.** All classes live in `src/style.css` keyed by BEM-ish
  names (`.card`, `.bar__fill`, `.badge--running`). No inline styles except
  one-off layout nudges; per-instance values (bar width, thickness, label
  column) are passed as CSS custom properties.
- **Charts are HTML/CSS, not a library.** Every dashboard chart is either a
  `barList` (a `<ul>` of grid rows) or the heatmap `<table>`. This was a
  deliberate swap away from Chart.js: it makes rows keyable for in-place
  diffing, clickable as real `<button>`s for the rep drill-down, and animatable
  with CSS transitions — and it dropped the bundle from ~230 kB to ~27 kB.
  Reach for a library only if a genuinely non-cartesian chart is needed.
- **No premature abstraction.** No state library, no API client layer, no
  component framework until a second real use needs it.
- **Language: Spanish UI, English data.** This is an internal tool for the
  Vambe team, so every label, heading, button, status line and tooltip is in
  Spanish. What comes *from* the data stays in the language it arrives in —
  enum values (`retail_ecommerce`, `whatsapp`), rep names, job statuses — as do
  the selector options that name those dimensions (`SECTOR`, `BY VOLUME`,
  `BY SIZE`). Numbers and dates format through `LOCALE` (`es-CL`) in
  `format.js`; `relativeTime()` returns "hace 3 horas". Code, comments and docs
  stay in English.

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
  `GET /api/dashboard/insights`, one loading state, **eight sections** rendered
  from the precomputed payload (no per-chart fetching, no client-side
  aggregation — see `aggregations.md`). The datasets collapse into eight
  sections because several answer the same question along a different axis;
  every selector below re-slices arrays **already in memory**, never refetches:

  | Section | Datasets | Interaction |
  |---|---|---|
  | Conversión mes a mes | `close_rate_by_month` + `rep_performance_by_month` | rep dropdown (team line stays behind as context) |
  | Tasa de conversión por vendedor | `rep_performance` + `_by_sector` + `_by_business_model` | segment cut tabs + value dropdown; click a rep to expand |
  | Tasa de conversión por segmento | the 7 `close_rate_by_*` | dimension tabs + rate/volume sort |
  | Tasa de conversión por número de necesidades | `close_rate_by_needs_complexity` | static (ordinal) |
  | Necesidades más mencionadas | `needs_frequency` + `close_rate_by_need` | measure toggle, top 8 / show all |
  | Canales de descubrimiento | `discovery_channel_frequency` | static |
  | Canales de atención en uso | `current_channel_frequency` + `close_rate_by_current_channel` | measure toggle |
  | Necesidades por segmento | `sector_` + `size_needs_matrix` | two-way axis toggle |

  - **The two rep sections are adjacent on purpose** (trend, then standings).
    "How is each rep doing" and "how has that moved" are one question asked
    twice; read apart, the first invites judging a rep on a snapshot.

  - **Sections may return a cleanup function**, collected into `disposeSections`
    and run on re-render and on navigation away. Only the timeline needs one so
    far (its `ResizeObserver`); anything else holding a listener or observer
    should do the same rather than leaking one per visit.

  - **Enum values that are really thresholds get their range on the label.**
    `inquiry_volume` renders as `High (500–1500/sem)` from `VOLUME_RANGES`,
    which mirrors §5 of `app/llm/prompts/system.md` — without it "high" vs
    "very_high" is a guess, and a note under the chart makes the reader hold a
    legend in their head while comparing bars. If the prompt's thresholds
    change, that map has to change with them.

  - **Baselines come from `_meta.base_rate`, never from summing group totals.**
    The needs and channels-in-use datasets are multi-select: their groups
    overlap, so `weightedRate()` over them would divide by a denominator that
    counts busy meetings several times. `weightedRate()` is only for datasets
    that partition the population. Same for `_meta.min_sample` — one gate,
    published by the backend, applied identically everywhere.

  - **Two measures beat two sections** where the categories are the same. The
    needs and current-channels sections toggle between "how often is this
    asked for" and "does asking for it predict a close" rather than repeating
    fifteen labels twice down the page. Both lists are built once and toggled
    with `hidden` — they're different components, and rebuilding one on every
    switch would throw away the row diffing that makes the bars tween.

  - **The rep section compares against the segment, not the house.** Picking a
    sector or model rebases the dashed line onto that segment's own rate and
    switches the readout to signed points, because 30% is strong where the
    segment closes at 18% and weak where it closes at 55% — a leaderboard that
    ignores this just ranks who was handed the easy book.

  - **The two channel charts stay separate on purpose.** `discovery_channel` is
    the marketing touchpoint that brought the client in; `current_channel` is
    the support channel they already operate. They share a word, not a
    question — a toggle between them reads as two views of one metric and
    invites misreading. Amber vs. mint reinforces the split.

  - **Ordinal vs categorical**: `urgency`, `business_size` and the complexity
    buckets keep their natural order and hide the sort toggle — their sequence
    carries meaning. The other four dimensions sort by value.
  - **Selector state** is local to each section (`activeDimension`, `measure`,
    `activeMatrixDimension`, `activeCut`/`activeValue`, selected rep). Nothing
    is persisted or reflected in the URL; add search params only if sharing a
    specific view becomes a real need.
  - **States**: skeleton placeholders on mount → sections on success (with
    "Datos de {relative}" + a staleness note past 24h); a single
    dashboard-level error with Retry on fetch failure; a per-section
    "Not enough data yet." note when the active slice is empty (`emptySlot`
    toggles a note beside the chart rather than overwriting it, so chart nodes
    survive a switch through an empty dimension).
  - **Sample mode**: the page loads live data by default. When the endpoint 404s
    (no enrichment job has completed) or fails, the error state offers "Ver datos
    de ejemplo" — every section rendered against the synthetic payload in
    `dashboard.sample.js`, whose shapes, sort order and internal consistency
    (`lift` derived from the same `base_rate`, `signal_board` assembled from the
    other datasets) match the backend exactly. Keep it that way: a sample payload
    that contradicts the real contract is worse than none.

**Backend endpoints:**
   - `POST /api/ingestion/csv` — multipart CSV upload →
     `{ summary: { rows_received }, enrichment_job_id }`. The endpoint only
     validates + queues; de-dup, the cap and all DB writes happen in the job.
   - `GET  /api/jobs` — list enrichment jobs, newest first; each has
     `_id` (Beanie serializes the id under its `_id` alias), `filename`,
     `status`, `rows_in_file`, `skipped_existing`, `total_candidates`
     (0 until the job starts running — rows sent to the LLM after de-dup + cap),
     `processed_count`, `failed_count`, `failed_batches`, `error`, `created_at`.
     Two error fields, deliberately: `error` is the fatal reason and is only set
     when `status` is `failed`; **`last_error` (+ `last_error_kind`,
     `last_error_at`) is the most recent non-fatal problem and is written while
     the job is still `running`** — a job stalled on LLM timeouts shows its
     reason there rather than sitting at "0 / 100" with nothing to go on. The
     jobs table renders whichever is present.
   - `GET  /api/jobs/{id}` — single job detail
   - `GET  /api/dashboard/insights` — all chart datasets in one precomputed blob
     (`{ <20 dataset keys>, _meta, computed_at }`); 404 until an enrichment job
     has completed. Shape documented in `aggregations.md`.

## Notes for future changes

- If routing needs real URLs (history API) or nested layouts, `router.js` is
  ~40 lines — rewrite it rather than bolting on. Don't add a router dependency
  for two pages.
- New page = new file in `src/pages/`, one `registerRoute` line in `main.js`,
  one link in `components/nav.js`.
