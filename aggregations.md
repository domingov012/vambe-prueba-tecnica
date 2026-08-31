# Vambe Sales Insights Dashboard — Frontend Implementation Prompt

## Context

The backend exposes a single endpoint that returns every dashboard chart dataset in one payload, precomputed and cached server-side (see backend implementation prompt for full details). The frontend's job is to fetch that one payload, render the charts from it, and handle loading/error/staleness states — not to orchestrate a fetch per chart or compute any aggregation client-side.

## Data contract

`GET /api/dashboard/insights`

```json
{
  "close_rate_by_sector": [ { "group": "string", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "close_rate_by_business_model": [ /* same shape */ ],
  "close_rate_by_business_size": [ /* same shape */ ],
  "close_rate_by_inquiry_volume": [ /* same shape */ ],
  "needs_frequency": [ { "need": "string", "count": 0 } ],
  "discovery_channel_frequency": [ { "channel": "string", "count": 0 } ],
  "current_channel_frequency": [ { "channel": "string", "count": 0 } ],
  "rep_performance": [ { "rep": "string", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "rep_performance_by_sector": [ { "rep": "string", "sector": "string", "total": 0, "closed": 0, "close_rate": 0.0, "segment_close_rate": 0.0, "lift": 0.0 } ],
  "rep_performance_by_business_model": [ /* same, with "business_model" */ ],
  "close_rate_by_urgency": [ /* same shape as close_rate_by_sector */ ],
  "close_rate_by_needs_complexity": [ { "needs_bucket": "string", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "close_rate_by_discovery_channel": [ /* same shape as close_rate_by_sector */ ],
  "sector_needs_matrix": [ { "sector": "string", "need": "string", "count": 0 } ],
  "close_rate_by_regulatory_flag": [ /* same shape as close_rate_by_sector */ ],
  "size_needs_matrix": [ { "business_size": "string", "need": "string", "count": 0 } ],
  "close_rate_by_need": [ { "value": "string", "total": 0, "closed": 0, "close_rate": 0.0, "lift": 0.0 } ],
  "close_rate_by_current_channel": [ /* same shape */ ],
  "signal_board": [ { "dimension": "string", "value": "string", "total": 0, "closed": 0, "close_rate": 0.0, "lift": 0.0 } ],
  "close_rate_by_month": [ { "month": "2024-02", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "rep_performance_by_month": [ { "rep": "string", "month": "2024-02", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "_meta": { "rows_aggregated": 0, "base_rate": 0.0, "min_sample": 0, "rows_without_date": 0 },
  "computed_at": "ISO-8601 timestamp"
}
```

Treat this contract as authoritative — don't reshape or re-aggregate any of these arrays client-side; they arrive pre-shaped for direct chart consumption.

### Partitioning vs. overlapping datasets

Two kinds of close-rate dataset live in this payload and they are **not** interchangeable:

- **Partitioning** (`close_rate_by_*` over a single-select field, `rep_performance`): every meeting
  lands in exactly one group, so `sum(total) == rows_aggregated` and a volume-weighted mean over the
  groups reproduces the population close rate.
- **Overlapping** (`close_rate_by_need`, `close_rate_by_current_channel`): a meeting that lists four
  needs is counted in four groups, so `sum(total)` exceeds the population and **a weighted mean over
  these groups is not the house average** — it over-weights busy meetings. These rows therefore ship
  with `lift` precomputed, and any baseline drawn against them must come from `_meta.base_rate`.

`_meta.min_sample` is the one small-sample gate for the whole page (`max(5, rows/100)`): the
`signal_board` is filtered by it server-side, and the client dims rows below it wherever a chart is
sorted by rate.

`close_rate_by_month` covers only rows that have a `meeting_date`; `_meta.rows_without_date` counts
the rest (rows enriched before that field was denormalized — see
`scripts/backfill_enhanced_meeting_date.py`).

## Loading pattern

This dashboard uses **one fetch, one loading state, ten charts** — not per-chart lazy loading. The backend already precomputes and caches the full payload, so there's nothing to gain from staggering the fetches; the only latency is one network round trip.

1. On mount, render all 10 chart containers as skeleton placeholders (matching each chart's approximate final size/shape, e.g. a rectangular block for bar charts, a grid for the matrix charts) so the layout doesn't shift when data arrives.
2. Fire a single request to `GET /api/dashboard/insights`.
3. On success, populate all 10 charts from their respective keys in the response in one state update — don't stagger chart rendering after fetch completes, since the data's already there.
4. On error, show a single dashboard-level error state with a retry action (retry re-fires the same single request) — not 10 independent per-chart error states.
5. Display `computed_at` somewhere unobtrusive (e.g. "Data as of {relative time}") so users know this is precomputed, not live.

Do not implement per-chart fetching, per-chart loading spinners, or client-side polling unless a future requirement (e.g. per-chart filters) explicitly calls for it — see the backend prompt's note on when the single-endpoint design would need to change.

## Chart-by-chart rendering guide

| # | Dataset key | Suggested chart type | Notes |
|---|---|---|---|
| 1 | `close_rate_by_sector`, `close_rate_by_business_model`, `close_rate_by_business_size` | Horizontal bar, sorted descending by `close_rate` | Three separate charts from the same shape; consider one reusable `<CloseRateBarChart data={...} />` component |
| 2 | `needs_frequency` | Horizontal bar, sorted descending by `count` | Likely the longest list (14+ enum values) — consider truncating to top N with an "show all" toggle |
| 3 | `discovery_channel_frequency`, `current_channel_frequency` | Bar or donut, two separate charts | Keep visually distinct since they answer different questions — don't combine into one chart |
| 4 | `rep_performance` | Bar, one bar per rep | `rep_performance_by_sector` — heatmap or grouped/stacked bar (rep × sector) |
| 5 | `close_rate_by_urgency` | Bar, ordered `low → medium → high` (not alphabetical) — ordinal, not categorical | Reuse the same `<CloseRateBarChart />` component as #1 |
| 6 | `close_rate_by_needs_complexity` | Bar, ordered by bucket (`1-2 → 3-4 → 5+`) | Also ordinal — preserve bucket order, don't sort by value |
| 7 | `close_rate_by_discovery_channel` | Scatter or combo chart: `total` (volume, x-axis) vs. `close_rate` (quality, y-axis) | This is the one chart in the set that benefits from a non-bar type, since the insight is the volume/quality relationship, not either value alone |
| 8 | `sector_needs_matrix` | Heatmap: sector (rows) × need (columns), cell = `count` | Likely needs a wider layout or horizontal scroll given ~14 need columns |
| 9 | `close_rate_by_regulatory_flag` | Bar | Reuse `<CloseRateBarChart />` |
| 10 | `size_needs_matrix` | Heatmap: business_size (rows) × need (columns), cell = `count` | Same component as #8, different data key |

Building one reusable `<CloseRateBarChart />` component (for #1×3, #5, #7's bar-if-not-using-scatter, #9) and one reusable `<NeedsMatrix />` heatmap component (for #8, #10) mirrors the backend's own consolidation into shared aggregation functions — the frontend component boundaries should match the backend's data-shape boundaries.

### Added after the first pass

| # | Dataset key | Rendering | Notes |
|---|---|---|---|
| 11 | `close_rate_by_inquiry_volume` | Same bar list as #1, ordinal order `low → very_high` | Was classified but never charted |
| 12 | `close_rate_by_need` | Bar list, second measure on the `needs_frequency` section | Overlapping groups — baseline from `_meta.base_rate`, `lift` shown as points |
| 13 | `close_rate_by_current_channel` | Same, on the current-channels section | Same overlap caveat; association, not causation |
| 14 | `signal_board` | One ranked bar list, sorted by `abs(lift)` | Pre-gated by `min_sample`; both tails matter |
| 15 | `close_rate_by_month` | SVG line — dot radius = volume, hollow under `min_sample` | Needs ≥ 2 months to draw a trend |
| 16 | `rep_performance_by_business_model` | Feeds the rep section's segment dropdown, alongside `_by_sector` | Both carry `segment_close_rate` + `lift` |
| 17 | `rep_performance_by_month` | Second line on #15, picked by a rep dropdown | Months a rep took no meetings are **absent, not zero** — the line breaks over them |

## State/error handling specifics

- If the payload's `computed_at` is older than an agreed staleness threshold (e.g. 24h), consider a subtle visual indicator ("data may be outdated") rather than treating it as an error — the backend recomputes on its own schedule, not on dashboard load, so staleness is expected, not exceptional.
- If a specific dataset key is missing or empty from the response (e.g. `sector_needs_matrix: []` because no data qualified), render that individual chart's own empty state ("not enough data yet") rather than failing the whole dashboard — this is different from a fetch failure and shouldn't share the same error UI.
- Don't retry-poll automatically; a manual retry button on fetch failure is sufficient given this data doesn't change in real time.

## Explicitly out of scope for this implementation

- **Server-side per-chart filters** (date range × sector × rep, freely combined) — still unsupported,
  and still the thing that would break this contract. What *was* added instead: the cross-tabs the UI
  actually needs (`rep_performance_by_sector` / `_by_business_model`) are precomputed, and the client
  filters those arrays in memory. That keeps one request and one cache, and it scales as long as each
  new filter is one pre-baked dimension. The day a filter needs two free dimensions at once, the
  cross-product stops being precomputable — that's when the endpoint takes query params (or the
  payload becomes a fact table the client slices), not before.
- Client-side caching/revalidation beyond a single fetch per dashboard visit — the backend cache already serves this purpose; don't duplicate it with something like stale-while-revalidate unless the dashboard is later expected to auto-refresh.
- Real-time/live updates — this is a precomputed snapshot dashboard, not a live one.