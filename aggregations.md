# Vambe Sales Insights Dashboard — Frontend Implementation Prompt

## Context

The backend exposes a single endpoint that returns all 10 dashboard chart datasets in one payload, precomputed and cached server-side (see backend implementation prompt for full details). The frontend's job is to fetch that one payload, render 10 charts from it, and handle loading/error/staleness states — not to orchestrate 10 separate fetches or compute any aggregation client-side.

## Data contract

`GET /api/dashboard/insights`

```json
{
  "close_rate_by_sector": [ { "group": "string", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "close_rate_by_business_model": [ /* same shape */ ],
  "close_rate_by_business_size": [ /* same shape */ ],
  "needs_frequency": [ { "need": "string", "count": 0 } ],
  "discovery_channel_frequency": [ { "channel": "string", "count": 0 } ],
  "current_channel_frequency": [ { "channel": "string", "count": 0 } ],
  "rep_performance": [ { "rep": "string", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "rep_performance_by_sector": [ { "rep": "string", "sector": "string", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "close_rate_by_urgency": [ /* same shape as close_rate_by_sector */ ],
  "close_rate_by_needs_complexity": [ { "needs_bucket": "string", "total": 0, "closed": 0, "close_rate": 0.0 } ],
  "close_rate_by_discovery_channel": [ /* same shape as close_rate_by_sector */ ],
  "sector_needs_matrix": [ { "sector": "string", "need": "string", "count": 0 } ],
  "close_rate_by_regulatory_flag": [ /* same shape as close_rate_by_sector */ ],
  "size_needs_matrix": [ { "business_size": "string", "need": "string", "count": 0 } ],
  "computed_at": "ISO-8601 timestamp"
}
```

Treat this contract as authoritative — don't reshape or re-aggregate any of these arrays client-side; they arrive pre-shaped for direct chart consumption.

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

## State/error handling specifics

- If the payload's `computed_at` is older than an agreed staleness threshold (e.g. 24h), consider a subtle visual indicator ("data may be outdated") rather than treating it as an error — the backend recomputes on its own schedule, not on dashboard load, so staleness is expected, not exceptional.
- If a specific dataset key is missing or empty from the response (e.g. `sector_needs_matrix: []` because no data qualified), render that individual chart's own empty state ("not enough data yet") rather than failing the whole dashboard — this is different from a fetch failure and shouldn't share the same error UI.
- Don't retry-poll automatically; a manual retry button on fetch failure is sufficient given this data doesn't change in real time.

## Explicitly out of scope for this implementation

- Per-chart filters (date range, sector, etc.) — not supported by the current single-blob contract; would require the backend changes noted in the backend prompt first.
- Client-side caching/revalidation beyond a single fetch per dashboard visit — the backend cache already serves this purpose; don't duplicate it with something like stale-while-revalidate unless the dashboard is later expected to auto-refresh.
- Real-time/live updates — this is a precomputed snapshot dashboard, not a live one.