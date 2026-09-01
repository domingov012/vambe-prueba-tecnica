# Vambe Prueba Tecnica

FastAPI + MongoDB (Beanie ODM) app: ingest client meeting transcripts from CSV, persist them, enrich with an LLM, and expose read endpoints over the results.

## Structure

```
app/
├── main.py              # FastAPI instance, lifespan (Mongo connect/disconnect), router includes,
│                        #   /health, and an optional SPA mount (../static, only when built)
├── config.py             # Settings (env vars via pydantic-settings)
├── models/                # Beanie Documents — the only place schemas are defined
│   ├── client.py           # Client
│   └── meeting.py           # MeetingTranscript (Link[Client])
├── db/
│   ├── session.py           # init_db()/close_db(), Motor client + init_beanie()
│   └── repositories/         # data-access helpers, as query logic grows past simple find/insert
├── ingestion/               # CSV → validated ParsedRows; bulk Client/MeetingTranscript writes
│   ├── csv_loader.py          # bytes → dict rows + header validation
│   ├── mappers.py             # dict row → ParsedRow (normalized, frozen)
│   └── service.py             # get_or_create_clients() / insert_meetings() — bulk, no per-row round trips
├── llm/
│   ├── client.py             # public surface: init_llm_client()/close_llm_client() + chat_completion(messages) -> str; dispatches to a provider
│   ├── providers/            # one module per backend (openrouter.py, google.py), same init()/close()/chat_completion() contract + shared base.py
│   └── processors/           # transcript enrichment logic (prompt + parsing), isolated from the LLM client itself
├── aggregation/               # dashboard aggregation logic (precomputed insights payload)
│   ├── rows.py                 # EnhancedTranscript -> flat TranscriptRow list (single-collection scan)
│   └── insights.py             # 22 chart datasets, recompute_insights() upserts the cached blob
└── api/routes/                 # thin FastAPI routers — parse request, call a service/aggregator, return response
```

## Dashboard insights

- **One precomputed endpoint, not one per chart.** `GET /api/dashboard/insights` returns all 22 chart
  datasets + `_meta` + `computed_at` from a single cached blob (`DashboardInsights`, `_id="latest"`). No
  live aggregation in the request path; sends an `ETag` (from `computed_at`) so an unchanged payload is
  a 304. Contract in `aggregations.md`.
- **Recompute triggers:** automatically at the end of every enrichment job (`llm/jobs.py`), and manually
  via `POST /api/dashboard/insights/recompute`. `GET /api/dashboard/insights/status` reports staleness.
  Recompute is `_id`-upsert (`save()`) + guarded by an `asyncio.Lock`, so concurrent triggers coalesce.
- **`closed` / `salesperson` / `meeting_date` are denormalized onto `EnhancedTranscript`** at enrichment
  time — immutable source fields, never LLM-inferred — so the aggregation reads a single collection with
  no join. `meeting_date` is nullable *only* because rows predate the field; back it with
  `python -m scripts.backfill_enhanced_meeting_date` and `_meta.rows_without_date` drops to 0.
- **Duplicates need no runtime filtering.** Reworded near-duplicates share the tuple
  `(name, email, phone_number, meeting_date)`, which *is* `EnhancedTranscript._id` (`enrichment_key()`);
  the primary key guarantees one enhanced row per duplicate group. Multi-selects (`client_needs`,
  `current_channels`) are flattened in application code (`rows.py` docstring explains the app- vs.
  query-layer choice and when to revisit).
- Three generic functions back most charts: `close_rate_by_dimension()` (single-select cuts),
  `close_rate_by_membership()` (multi-select cuts) and `needs_matrix()` (cross-tabs).
- **Partitioning vs. overlapping is the distinction to hold onto.** Single-select groups partition the
  population; multi-select ones (needs, channels-in-use) overlap, so their totals sum past `N` and no
  baseline can be recovered by summing them. Those datasets carry `lift` precomputed, and
  `_meta.base_rate` / `_meta.min_sample` publish the one baseline and one small-sample gate the whole
  dashboard uses — `min_sample()` scales it with the population instead of hardcoding a threshold.
- `signal_board` re-derives from the same row list rather than reading the other datasets, so it costs
  no extra scan and can't drift from the charts it summarises. `salesperson` is deliberately excluded
  from it — see the comment on `_SINGLE_SELECT_FIELDS`.

## Enrichment pipeline

`POST /api/ingestion/csv` does **not** persist anything itself. It parses + validates the whole
file into `ParsedRow`s (a bad row → 422) and hands them to `enqueue_enrichment_job()`; the rows
ride the in-memory queue. `llm/jobs.py::_run_job` then, in order:

1. collapses rows sharing an `enrichment_key` (`(name,email,phone,meeting_date)` hash);
2. drops keys already in `enhanced_transcripts` (one projected `$in` lookup);
3. caps to `max_transcripts` (`LLM_MAX_TRANSCRIPTS_PER_JOB`, default 100) — free-tier request
   count is the binding constraint;
4. per `batch_size` chunk: one LLM call, then **for the transcripts the model returned**,
   bulk-writes `Client` (get-or-create), `MeetingTranscript`, `EnhancedTranscript` together in a
   **single MongoDB transaction** (`_persist_classified`) — all three land or none do.

So `clients` / `meeting_transcripts` only ever gain rows that were actually classified, and never
a `MeetingTranscript` without its `EnhancedTranscript`. A restart mid-job loses in-flight progress;
re-uploading the same file resumes cleanly because step 2 skips whatever already landed (and the
transaction guarantees a key is either fully present or fully absent, never half-written). The
transaction spans only the local writes — the LLM call is already done — so it stays well inside
the commit window. Needs a replica set (Atlas is one); a standalone `mongod` can't do transactions.

## Conventions

- **One responsibility per subpackage.** `ingestion`, `db`, `llm`, `aggregation`, `api` don't reach into each other's internals — they compose through plain function calls (e.g. a route calls `ingestion.service.ingest_csv`, never touches CSV parsing directly).
- **Routes stay thin.** No business logic in `api/routes/*` — validate input, call a service/aggregator, map errors to HTTP responses.
- **Models are Beanie `Document`s in `models/`.** These are the only schema definitions — no separate DTO/schema duplication unless an endpoint genuinely needs a different shape than the stored document.
- **No premature abstraction.** Don't add a repository/service layer, config option, or interface until there's a second concrete use that needs it. Empty stub directories (`db/repositories`, `llm/processors`) exist because the structure was agreed on, not because they need content yet — fill them when a real need shows up.
- **Business rules belong next to the logic they govern**, not in routes. E.g. client dedup (match on `name` + `email` + `phone_number`) lives in `ingestion/service.py::get_or_create_clients` and is mirrored by a compound unique index on `Client`, not re-implemented per caller. Dedup is **bulk** — one `$in` read + one `insert_many` per batch, never a query per row (a per-row loop against a remote cluster is what made 10k-row uploads crash).

## LLM calling (for the upcoming enrichment step)

- Two providers, selected by `LLM_PROVIDER` (`openrouter` default, or `google` for the Google Developer API — Gemini/Gemma direct). Same `chat_completion(messages) -> str` contract either way; callers don't branch on provider.
  - `openrouter`: `OPENROUTER_MODEL` (default `google/gemma-4-31b-it:free`), `OPENROUTER_API_KEY`.
  - `google`: `GOOGLE_MODEL` (default `gemma-4-31b-it`), `GOOGLE_API_KEY`. Switch here when OpenRouter's shared free pool throttles too hard. Gemma on the Google API takes no `system` role, so `providers/google.py` folds system text into the first user turn; it also drops `"thought": true` reasoning parts, returning only the answer text.
- Each provider rate-limits (`LLM_REQUESTS_PER_MINUTE`, 20/min default) and, via the shared
  `base.post_with_retries`, retries **429, 5xx *and* transport errors** (read timeout, dropped
  connection) with backoff up to `LLM_MAX_RETRIES`, then raises `LLMError`. Per-request HTTP
  timeout is `LLM_REQUEST_TIMEOUT_SECONDS` (120s). Callers just await `chat_completion(messages)`.
- The free Gemma pool can 429 at an **upstream shared-pool** level (all OpenRouter free users, not just our account) — seen intermittently in testing, unrelated to our own rate limit. And `generateContent` is non-streaming, so a slow batch can outlast the HTTP timeout and surface as `httpx.ReadTimeout`. `jobs._enrich_with_stall_tolerance` absorbs both: it retries an `LLMError` batch with escalating backoff for up to `_STALL_MAX_ELAPSED` (30 min), then gives up — that batch's transcripts stay unenriched (`failed_count`) and the job still completes; a later re-upload retries just them.
- `Transcripcion` rows average ~130 tokens — token/context limits are a non-issue; **request count** is the real constraint on the free tier. Batch multiple transcripts per request (`LLM_BATCH_SIZE`, 10) to cut request count — but too large a batch makes each `generateContent` slow enough to time out, so that's the knob to turn down first if batches start timing out.
