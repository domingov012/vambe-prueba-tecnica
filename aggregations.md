# Vambe Sales Insights Dashboard — Backend Implementation Prompt

## Context

Once we have more transcripts saved in the dsatabase, the idea is to show charts of the enhanced data in the frontend dashboard. For this, we need to work on a data aggregation endpoint to show every relevant metric on our frontend. The enhanced data schema provides the following information (crossing with original transcript data):

- `sector`, `sub_sector`, `business_model`, `business_size`, `inquiry_volume`
- `discovery_channel`, `current_channels` (multi), `client_needs` (multi)
- `regulatory_flag`, `pain_point_urgency`
- `closed` (0/1, from the original source data — not LLM-inferred)
- `vendedor_asignado` (sales rep, from the original source data)

The task: **design and implement the backend endpoint(s)** that compute and serve the aggregated data each chart needs — not the frontend rendering itself.

For each chart below: the insight it answers, the fields it depends on, the aggregation logic required, and a suggested response shape.

---

## 1. Classification vs. Conversion Outcome

**Insight:** Which business classifications (sector, size, business model, etc.) correlate with higher close rates.

**Depends on:** `sector`, `business_model`, `business_size`, `closed`

**Logic:** Group by each dimension independently, compute `close_rate = closed_count / total_count` per group.

**Suggested endpoint:** `GET /api/dashboard/close-rate-by-dimension?dimension=sector`

**Response shape:**
```json
[
  { "group": "health_medical", "total": 14, "closed": 9, "close_rate": 0.64 },
  { "group": "retail_ecommerce", "total": 11, "closed": 5, "close_rate": 0.45 }
]
```

---

## 2. Most Asked Client Needs

**Insight:** Which needs appear most frequently across all transcripts — signals what Vambe should prioritize building/marketing.

**Depends on:** `client_needs` (multi-select — needs flattening before counting)

**Logic:** Flatten the `client_needs` arrays across all transcripts, count frequency per unique value, sort descending.

**Suggested endpoint:** `GET /api/dashboard/needs-frequency`

**Response shape:**
```json
[
  { "need": "appointment_scheduling", "count": 38 },
  { "need": "crm_erp_pos_lms_integration", "count": 31 }
]
```

---

## 3. Most Used Discovery/Current Channels

**Insight:** Where leads come from (`discovery_channel`) and what channels clients currently use (`current_channels`) — two related but distinct counts.

**Depends on:** `discovery_channel` (single), `current_channels` (multi)

**Logic:** Simple frequency count per enum value, one query per field. Keep these as two separate result sets since they answer different questions.

**Suggested endpoint:** `GET /api/dashboard/channel-frequency?type=discovery` and `?type=current`

**Response shape:**
```json
[
  { "channel": "linkedin", "count": 22 },
  { "channel": "peer_referral", "count": 19 }
]
```

---

## 4. Sales Rep Performance and Specialization

**Insight:** Close rate per rep, and whether reps perform differently across sectors (specialization pattern).

**Depends on:** `vendedor_asignado`, `closed`, `sector`

**Logic:** Two-level aggregation — (a) close rate grouped by rep alone, (b) close rate grouped by rep × sector for the specialization cross-tab.

**Suggested endpoint:** `GET /api/dashboard/rep-performance` and `GET /api/dashboard/rep-performance-by-sector`

**Response shape:**
```json
[
  { "rep": "Toro", "total": 20, "closed": 13, "close_rate": 0.65 }
]
```
```json
[
  { "rep": "Toro", "sector": "health_medical", "total": 5, "closed": 4, "close_rate": 0.8 }
]
```

---

## 5. Pain Point Urgency vs. Close Rate

**Insight:** Does higher stated urgency actually predict closing, or do calmer/exploratory clients close just as often.

**Depends on:** `pain_point_urgency`, `closed`

**Logic:** Group by `pain_point_urgency` value, compute close rate per group.

**Suggested endpoint:** `GET /api/dashboard/close-rate-by-dimension?dimension=pain_point_urgency` (reuse the generic endpoint from #1)

**Response shape:** same shape as #1.

---

## 6. Needs Complexity vs. Close Rate

**Insight:** Does the number of distinct needs a client lists correlate with closing (more pain/more willingness to buy) or the opposite (too complex a deal to close quickly).

**Depends on:** `client_needs` (multi), `closed`

**Logic:** Compute `needs_count = length(client_needs)` per transcript, bucket into ranges (e.g. 1–2, 3–4, 5+), compute close rate per bucket.

**Suggested endpoint:** `GET /api/dashboard/close-rate-by-needs-complexity`

**Response shape:**
```json
[
  { "needs_bucket": "1-2", "total": 12, "closed": 5, "close_rate": 0.42 },
  { "needs_bucket": "3-4", "total": 40, "closed": 24, "close_rate": 0.60 },
  { "needs_bucket": "5+", "total": 18, "closed": 6, "close_rate": 0.33 }
]
```

---

## 7. Discovery Channel: Volume vs. Quality

**Insight:** A channel can drive many meetings but few closes (bad lead quality), or few meetings but a high close rate (efficient channel) — distinct from raw volume in #3.

**Depends on:** `discovery_channel`, `closed`

**Logic:** Group by `discovery_channel`, return both `total` (volume) and `close_rate` (quality) so the frontend can plot them together (e.g. bar + line combo, or scatter volume vs. rate).

**Suggested endpoint:** `GET /api/dashboard/close-rate-by-dimension?dimension=discovery_channel` (reuse #1's endpoint again)

**Response shape:** same shape as #1 — the frontend chart is what differs (scatter/combo instead of simple bar).

---

## 8. Sector × Needs Cross-Tab

**Insight:** Which needs cluster with which sectors — informs vertical-specific product packaging or sales messaging.

**Depends on:** `sector`, `client_needs` (multi)

**Logic:** For each sector, flatten and count `client_needs` occurrences within that sector's subset of transcripts. Output as a matrix (sector × need → count) for a heatmap.

**Suggested endpoint:** `GET /api/dashboard/sector-needs-matrix`

**Response shape:**
```json
[
  { "sector": "health_medical", "need": "appointment_scheduling", "count": 11 },
  { "sector": "health_medical", "need": "data_privacy_compliance", "count": 9 },
  { "sector": "retail_ecommerce", "need": "order_shipment_inventory_tracking", "count": 8 }
]
```

---

## 9. Regulatory Sensitivity vs. Close Rate

**Insight:** Do clients with health/financial/student data close at a different rate than clients with no flagged sensitive data — signals whether compliance messaging needs to happen earlier in the sales process.

**Depends on:** `regulatory_flag`, `closed`

**Logic:** Group by `regulatory_flag`, compute close rate per group.

**Suggested endpoint:** `GET /api/dashboard/close-rate-by-dimension?dimension=regulatory_flag` (reuse #1's endpoint)

**Response shape:** same shape as #1.

---

## 10. Business Size vs. Needs Profile

**Insight:** Do larger businesses ask for fundamentally different needs (e.g. more integration-heavy) than solo/micro businesses (e.g. more simplicity-focused) — could justify segmented product tiers.

**Depends on:** `business_size`, `client_needs` (multi)

**Logic:** Same cross-tab pattern as #8, but keyed on `business_size` instead of `sector`.

**Suggested endpoint:** `GET /api/dashboard/size-needs-matrix`

**Response shape:**
```json
[
  { "business_size": "large", "need": "crm_erp_pos_lms_integration", "count": 10 },
  { "business_size": "solo_micro", "need": "brand_tone_alignment", "count": 4 }
]
```

---

## Implementation notes

- Charts #1, #5, #7, #9 all share the same "close rate grouped by one dimension" shape — implement this as a single generic endpoint (`/api/dashboard/close-rate-by-dimension?dimension=<field>`) rather than four separate ones, with the `dimension` param whitelisted to valid single-select fields.
- Charts #8 and #10 share the same "cross-tab a dimension against multi-select needs" shape — consider a single generic endpoint (`/api/dashboard/needs-matrix?dimension=sector`) instead of two separate ones, for the same reason.
- All multi-select fields (`client_needs`, `current_channels`) require flattening (one row per value) before aggregation — decide once whether this happens in the query layer (e.g. `UNNEST` in SQL, `$unwind` in Mongo) or in application code, and reuse that approach across every chart that touches a multi-select field.
- Before wiring these up, run a duplicate-detection pass on the source transcripts (several share phone numbers/dates with reworded content) — decide whether duplicates should be excluded from these aggregates or kept, and make that a documented, consistent choice across all endpoints rather than a per-chart decision.

# Vambe Sales Insights Dashboard — Backend Implementation Prompt

## Context

Once we have more transcripts saved in the dsatabase, the idea is to show charts of the enhanced data in the frontend dashboard. For this, we need to work on a data aggregation endpoint to show every relevant metric on our frontend. The enhanced data schema provides the following information (crossing with original transcript data):

- `sector`, `sub_sector`, `business_model`, `business_size`, `inquiry_volume`
- `discovery_channel`, `current_channels` (multi), `client_needs` (multi)
- `regulatory_flag`, `pain_point_urgency`
- `closed` (0/1, from the original source data — not LLM-inferred)
- `vendedor_asignado` (sales rep, from the original source data)

This classified data will be persisted (e.g. one row/document per transcript) and needs to power a dashboard of 10 charts.

## Design decision: single precomputed endpoint, not one endpoint per chart

- **One endpoint** returns all 10 chart datasets in a single JSON payload, rather than 10 separate round-trips.
- **Precompute and cache** the aggregations whenever the underlying classified data changes (new transcripts classified/re-classified) — do not recompute all 10 aggregations live on every dashboard page load.
- **Skeleton-load the frontend**, not the data fetch — render chart placeholders immediately, fire the single request, populate all charts once the response arrives.

This avoids the coordination overhead of managing 10 separate loading states, and since none of these aggregations are individually expensive, splitting them into lazily-loaded separate endpoints would add complexity without a real performance payoff. Move to per-chart endpoints only if a genuine need emerges later — e.g. per-chart filters, a "refresh this chart only" action, or one aggregation becoming expensive at much larger data volumes.

---

## Endpoint: `GET /api/dashboard/insights`

Returns all 10 chart datasets as named keys in one response object.

**Response shape:**
```json
{
  "close_rate_by_sector": [ /* see #1 */ ],
  "close_rate_by_business_model": [ /* see #1 */ ],
  "close_rate_by_business_size": [ /* see #1 */ ],
  "needs_frequency": [ /* see #2 */ ],
  "discovery_channel_frequency": [ /* see #3 */ ],
  "current_channel_frequency": [ /* see #3 */ ],
  "rep_performance": [ /* see #4 */ ],
  "rep_performance_by_sector": [ /* see #4 */ ],
  "close_rate_by_urgency": [ /* see #5 */ ],
  "close_rate_by_needs_complexity": [ /* see #6 */ ],
  "close_rate_by_discovery_channel": [ /* see #7 */ ],
  "sector_needs_matrix": [ /* see #8 */ ],
  "close_rate_by_regulatory_flag": [ /* see #9 */ ],
  "size_needs_matrix": [ /* see #10 */ ],
  "computed_at": "2026-08-30T14:00:00Z"
}
```

Include `computed_at` so the frontend can show "data as of X" and so you can debug staleness issues in caching.

### Caching / precompute strategy

- Compute the full payload above as a batch job whenever new transcripts are classified (on-write trigger) or on a schedule (e.g. nightly), not on-request.
- Store the computed payload as a single blob (JSON column, cache key in Redis/similar, or a static file) keyed by something like `dashboard:insights:latest`.
- `GET /api/dashboard/insights` reads and returns the stored blob directly — no live aggregation in the request path.
- If a "force refresh" action is needed (e.g. an admin re-running classification), expose a separate internal trigger (`POST /api/dashboard/insights/recompute`) rather than making the read endpoint do the computation.
- Given the current data volume, live computation on each request would likely be fast enough too — but precomputing removes any coupling between dashboard load time and classification-store query performance as the dataset grows, and makes the "single endpoint" contract trivial to serve.

### Frontend skeleton-loading notes (for context, even though this prompt is backend-focused)

- Render all 10 chart containers with skeleton/placeholder states immediately on page mount.
- Fire the single `GET /api/dashboard/insights` request once.
- On response, populate all charts from their respective keys in the payload — no per-chart fetch orchestration needed.
- Only the single request needs a loading/error state, not ten independent ones.

---

## Chart-by-chart breakdown

### 1. Close Rate by Dimension (sector / business_model / business_size)

**Insight:** Which classifications correlate with higher close rates.

**Depends on:** `sector` | `business_model` | `business_size`, `closed`

**Logic:** Group by each dimension independently, compute `close_rate = closed_count / total_count` per group. Produces three payload keys (`close_rate_by_sector`, `close_rate_by_business_model`, `close_rate_by_business_size`) from one shared aggregation function parameterized by field name.

**Shape:**
```json
[
  { "group": "health_medical", "total": 14, "closed": 9, "close_rate": 0.64 },
  { "group": "retail_ecommerce", "total": 11, "closed": 5, "close_rate": 0.45 }
]
```

### 2. Most Asked Client Needs

**Insight:** Which needs appear most frequently — signals what to prioritize building/marketing.

**Depends on:** `client_needs` (multi — flatten before counting)

**Logic:** Flatten `client_needs` arrays across all transcripts, count frequency per unique value, sort descending.

**Shape:**
```json
[
  { "need": "appointment_scheduling", "count": 38 },
  { "need": "crm_erp_pos_lms_integration", "count": 31 }
]
```

### 3. Most Used Channels (discovery / current)

**Insight:** Where leads come from vs. what channels clients already use — two distinct questions.

**Depends on:** `discovery_channel` (single), `current_channels` (multi)

**Logic:** Frequency count per enum value, one aggregation per field, kept as separate payload keys.

**Shape:**
```json
[
  { "channel": "linkedin", "count": 22 },
  { "channel": "peer_referral", "count": 19 }
]
```

### 4. Sales Rep Performance and Specialization

**Insight:** Close rate per rep, and whether reps perform differently across sectors.

**Depends on:** `vendedor_asignado`, `closed`, `sector`

**Logic:** (a) close rate grouped by rep alone, (b) close rate grouped by rep × sector.

**Shape:**
```json
[{ "rep": "Toro", "total": 20, "closed": 13, "close_rate": 0.65 }]
```
```json
[{ "rep": "Toro", "sector": "health_medical", "total": 5, "closed": 4, "close_rate": 0.8 }]
```

### 5. Pain Point Urgency vs. Close Rate

**Insight:** Does stated urgency predict closing, or do calmer clients close just as often.

**Depends on:** `pain_point_urgency`, `closed`

**Logic:** Same generic close-rate-by-dimension aggregation as #1, keyed on `pain_point_urgency`.

**Shape:** same as #1.

### 6. Needs Complexity vs. Close Rate

**Insight:** Does the number of distinct needs listed correlate with closing.

**Depends on:** `client_needs` (multi), `closed`

**Logic:** Compute `needs_count = length(client_needs)` per transcript, bucket into ranges (1–2, 3–4, 5+), compute close rate per bucket.

**Shape:**
```json
[
  { "needs_bucket": "1-2", "total": 12, "closed": 5, "close_rate": 0.42 },
  { "needs_bucket": "3-4", "total": 40, "closed": 24, "close_rate": 0.60 },
  { "needs_bucket": "5+", "total": 18, "closed": 6, "close_rate": 0.33 }
]
```

### 7. Discovery Channel: Volume vs. Quality

**Insight:** A channel can drive many meetings but few closes, or few meetings but a high close rate.

**Depends on:** `discovery_channel`, `closed`

**Logic:** Same generic close-rate-by-dimension aggregation as #1, keyed on `discovery_channel` — return both `total` and `close_rate` so the frontend can plot volume against quality together.

**Shape:** same as #1.

### 8. Sector × Needs Cross-Tab

**Insight:** Which needs cluster with which sectors — informs vertical-specific packaging/messaging.

**Depends on:** `sector`, `client_needs` (multi)

**Logic:** For each sector, flatten and count `client_needs` occurrences within that sector's subset. Output as a flat list of `(sector, need, count)` rows for a heatmap.

**Shape:**
```json
[
  { "sector": "health_medical", "need": "appointment_scheduling", "count": 11 },
  { "sector": "health_medical", "need": "data_privacy_compliance", "count": 9 }
]
```

### 9. Regulatory Sensitivity vs. Close Rate

**Insight:** Do clients with flagged sensitive data close at a different rate — signals whether compliance messaging needs to move earlier in the sales process.

**Depends on:** `regulatory_flag`, `closed`

**Logic:** Same generic close-rate-by-dimension aggregation as #1, keyed on `regulatory_flag`.

**Shape:** same as #1.

### 10. Business Size vs. Needs Profile

**Insight:** Do larger businesses ask for fundamentally different needs than solo/micro businesses — could justify segmented product tiers.

**Depends on:** `business_size`, `client_needs` (multi)

**Logic:** Same cross-tab pattern as #8, keyed on `business_size` instead of `sector`.

**Shape:**
```json
[
  { "business_size": "large", "need": "crm_erp_pos_lms_integration", "count": 10 },
  { "business_size": "solo_micro", "need": "brand_tone_alignment", "count": 4 }
]
```

---

## Implementation notes

- Build **one generic "close rate by dimension" aggregation function** and reuse it for #1 (×3 dimensions), #5, #7, and #9 — six of the ten datasets share this exact shape, so this should be a single parameterized function, not six copies.
- Build **one generic "dimension × needs cross-tab" function** and reuse it for #8 and #10.
- All multi-select fields (`client_needs`, `current_channels`) require flattening (one row per value) before aggregation — decide once whether this happens in the query layer (e.g. `$unwind` in Mongo) or in application code, and reuse that approach across every aggregation that touches a multi-select field.
- Run a duplicate-detection pass on the source transcripts before the first precompute (several share phone numbers/dates with reworded content) — decide whether duplicates should be excluded from these aggregates, and make that a documented, consistent choice applied once at the data layer rather than per-chart.
- Since the whole payload is precomputed and cached, invalidate/recompute it as part of whatever process writes new classification results — don't let the cache silently go stale relative to the underlying data.