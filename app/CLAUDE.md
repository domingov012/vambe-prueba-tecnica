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
│   ├── rows.py                 # EnhancedTranscript -> flat TranscriptRow list (single-collection scan);
│   │                           #   process-caches the list, refreshed by every recompute
│   ├── insights.py             # 22 chart datasets, recompute_insights() upserts the cached blob
│   └── crosstab.py             # on-demand cross-tab of 2 client dimensions — the one view too
│                               #   combinatorial to precompute; runs on the request path over the cache
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
- **`GET /api/dashboard/crosstab?row=&col=`** is the deliberate exception to "one precomputed blob".
  Any 2 of 5 client dimensions (`sector`, `business_model`, `business_size`, `inquiry_volume`,
  `client_needs`) × 2 measures is too many combinations to bake, so `crosstab.py` computes it live
  over `rows.get_transcript_rows()` (the process-cached scan — no Mongo hit on an interactive pivot).
  Each cell ships `total` + `closed` + `close_rate` so the client renders either measure without a
  refetch. `client_needs` on an axis makes cells overlap → `overlapping: true` in the response.
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

## LLM calling

- Two providers, selected by `LLM_PROVIDER` (`openrouter` default, or `google` for the Google Developer API — Gemini/Gemma direct). Same `chat_completion(messages, *, thinking_level=None, response_schema=None) -> str` contract either way; callers don't branch on provider.
  - `openrouter`: `OPENROUTER_MODEL` (default `google/gemma-4-31b-it:free`), `OPENROUTER_API_KEY`.
  - `google`: `GOOGLE_MODEL` (default `gemma-4-31b-it`), `GOOGLE_API_KEY`. Switch here when OpenRouter's shared free pool throttles too hard. Gemma on the Google API takes no `system` role, so `providers/google.py` folds system text into the first user turn; it also drops `"thought": true` reasoning parts, returning only the answer text.
- **`thinking_level`** (`minimal` / `low` / `high`, a `ThinkingLevel` in `config.py`) sets how much the model reasons before answering. Default `LLM_THINKING_LEVEL` (unset ⇒ no `thinkingConfig` sent), overridable per job via `?thinking_level=` on `POST /api/ingestion/csv`; it's stored on `EnrichmentJob` and threaded job → `enrich_batch` → `chat_completion`. Google sends it verbatim as `generationConfig.thinkingConfig.thinkingLevel`; OpenRouter maps it (`minimal` ⇒ `reasoning.enabled=false`, else `reasoning.effort`).
- **Structured output** (`LLM_STRUCTURED_OUTPUT`, on by default). `enrich_batch` builds `_BATCH_SCHEMA` from `TranscriptClassification` (`$ref`s inlined — the Google validator won't resolve them) and passes it as `response_schema`. Google → `generationConfig.responseJsonSchema` + `responseMimeType: application/json`; OpenRouter → `response_format: json_schema`. The schema is `{"results": [ …one object per transcript… ]}` **wrapped in an object on purpose**: given a bare array schema, Gemma stops after one or two elements with `finishReason: STOP` (reads as a complete response, not a truncation); wrapped, it fills the array. `_parse_response` unwraps the single `results` key. This is a strong constraint on gemma-4 (right field names, enum-only values, no code fence) but not hard constrained decoding — per-item Pydantic validation and the truncation check still run. Flip the flag off if a model rejects the schema.
- Each provider rate-limits (`LLM_REQUESTS_PER_MINUTE`, 20/min default) and, via the shared
  `base.post_with_retries`, retries **429, 5xx *and* transport errors** (read timeout, dropped
  connection) with backoff up to `LLM_MAX_RETRIES`, then raises `LLMError`. A **non-429 4xx** raises
  `LLMFatalError` on the first attempt instead — a refused key or unknown model won't fix itself, and
  stalling on it only hides the cause. `LLMError.kind` (`timeout`, `rate_limit`, `server_error`,
  `client_error`, `transport`, `bad_response`) is what the job row reports.
- **Four nested wall-clock ceilings.** `LLM_REQUEST_TIMEOUT_SECONDS` bounds one HTTP request only;
  `post_with_retries` multiplies it by `LLM_MAX_RETRIES` and the stall loop multiplies *that* again.
  So each layer has its own deadline, checked against `time.monotonic()`:
  `LLM_REQUEST_TIMEOUT_SECONDS` (300) < `LLM_BATCH_TIMEOUT_SECONDS` (660, one `enrich_batch` incl.
  retries, enforced with `asyncio.timeout`) < `LLM_BATCH_MAX_STALL_SECONDS` (1500, one batch incl.
  stall re-attempts) < `LLM_JOB_TIMEOUT_SECONDS` (5400, the whole job). `main._warn_on_inconsistent_timeouts`
  logs a warning at startup when they stop nesting. **Never sum the sleeps to measure elapsed time** —
  that was the original bug: the stall loop counted only its own `asyncio.sleep` calls and ignored the
  hours it spent inside `enrich_batch`, so its "30 minute cap" allowed several hours per batch and a
  job sat at `running / 0 processed` indefinitely.
- **Sizing.** Measured: ~22s per transcript (3 in 67s on gemma-4-31b-it, Google free tier). So
  `LLM_BATCH_SIZE` 10 needs ~220s and the old 120s request timeout could not fit a single batch.
  Budget ~30s × `LLM_BATCH_SIZE` for the request timeout. `Transcripcion` rows average ~130 tokens, so
  token/context limits are a non-issue; **request count** is the free-tier constraint, which is why
  batching exists at all — prefer a bigger request timeout to a smaller batch until batches get slow
  enough to risk the job deadline.
- The free Gemma pool can 429 at an **upstream shared-pool** level (all OpenRouter free users, not just our account) — seen intermittently in testing, unrelated to our own rate limit. And `generateContent` is non-streaming, so a slow batch can outlast the HTTP timeout and surface as `httpx.ReadTimeout`. `jobs._enrich_with_stall_tolerance` absorbs both: it retries an `LLMError` batch with escalating backoff until the batch stall budget (or the job deadline) runs out, then gives up — that batch's transcripts stay unenriched (`failed_count`, `failed_batches`) and the job still completes; a later re-upload retries just them.
- **Parsing failures never cost more than their batch.** `enrich_batch` returns a `BatchOutcome`
  (`classified` / `error` / `error_kind` / `invalid_count` / `missing_count`), not a bare list, so
  "the model wrote prose", "the JSON was truncated" and "every item failed validation" reach the job
  as distinct reasons instead of an indistinguishable empty list. A truncated response (opened a
  container, never closed it) is reported as such, because its fix is a smaller `LLM_BATCH_SIZE`.
  A single-key object wrapping the array (`{"results": [...]}` — the structured-output schema's own
  shape, or a wrapper a schemaless model volunteered) is unwrapped rather than discarded.
  `_strip_code_fence` strips a leading and a trailing ``` independently — in JSON mode Gemma still
  sometimes appends a bare closing fence. Per-item validation errors skip that item only.

## Observability

- **`app/logging_config.py` must run.** Uvicorn's dictConfig only touches the `uvicorn*` loggers and
  leaves root bare, so without `configure_logging()` every `app.*` record falls through to
  `logging.lastResort` — WARNING and up, no timestamps, INFO silently dropped. It is called at import
  of `app.main` and again in the lifespan (which runs after uvicorn's own config, and is the call that
  wins). `LOG_LEVEL=DEBUG` additionally dumps every raw LLM response.
- **A job explains itself from `GET /api/jobs`.** `error` is the fatal reason (set only when `failed`);
  `last_error` / `last_error_kind` / `last_error_at` are the most recent *non-fatal* problem, written
  while the job is still running — that is what a job sitting at 0 processed shows instead of nothing.
  `failed_batches` counts abandoned batches (`failed_count` counts transcripts).
- **A job that classified nothing fails.** It used to end `completed` with 0 processed, which reads as
  "there was nothing to do" — the opposite of what happened.
- **Orphans are reconciled at startup.** `jobs.fail_orphaned_jobs()` runs in the lifespan and marks any
  job left `queued`/`running` by a previous process as failed. The queue is an in-process
  `asyncio.Queue` and the rows only ever live in memory, so nothing can resume — but the job document
  survives, and on a free host that idles the container mid-job, a permanently-`running` row is the
  likeliest reason a job looks stuck.
