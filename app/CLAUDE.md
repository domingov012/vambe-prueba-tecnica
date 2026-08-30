# Vambe Prueba Tecnica

FastAPI + MongoDB (Beanie ODM) app: ingest client meeting transcripts from CSV, persist them, enrich with an LLM, and expose read endpoints over the results.

## Structure

```
app/
├── main.py              # FastAPI instance, lifespan (Mongo connect/disconnect), router includes
├── config.py             # Settings (env vars via pydantic-settings)
├── models/                # Beanie Documents — the only place schemas are defined
│   ├── client.py           # Client
│   └── meeting.py           # MeetingTranscript (Link[Client])
├── db/
│   ├── session.py           # init_db()/close_db(), Motor client + init_beanie()
│   └── repositories/         # data-access helpers, as query logic grows past simple find/insert
├── ingestion/               # CSV → validated rows → Client/MeetingTranscript instances
│   ├── csv_loader.py
│   ├── mappers.py
│   └── service.py
├── llm/
│   ├── client.py             # public surface: init_llm_client()/close_llm_client() + chat_completion(messages) -> str; dispatches to a provider
│   ├── providers/            # one module per backend (openrouter.py, google.py), same init()/close()/chat_completion() contract + shared base.py
│   └── processors/           # transcript enrichment logic (prompt + parsing), isolated from the LLM client itself
├── aggregation/               # query/aggregation logic backing the GET endpoints
└── api/routes/                 # thin FastAPI routers — parse request, call a service/aggregator, return response
```

## Conventions

- **One responsibility per subpackage.** `ingestion`, `db`, `llm`, `aggregation`, `api` don't reach into each other's internals — they compose through plain function calls (e.g. a route calls `ingestion.service.ingest_csv`, never touches CSV parsing directly).
- **Routes stay thin.** No business logic in `api/routes/*` — validate input, call a service/aggregator, map errors to HTTP responses.
- **Models are Beanie `Document`s in `models/`.** These are the only schema definitions — no separate DTO/schema duplication unless an endpoint genuinely needs a different shape than the stored document.
- **No premature abstraction.** Don't add a repository/service layer, config option, or interface until there's a second concrete use that needs it. Empty stub directories (`db/repositories`, `llm/processors`) exist because the structure was agreed on, not because they need content yet — fill them when a real need shows up.
- **Business rules belong next to the logic they govern**, not in routes. E.g. client dedup (match on `name` + `email` + `phone_number`) lives in `ingestion/service.py` and is mirrored by a compound unique index on `Client`, not re-implemented per caller.

## LLM calling (for the upcoming enrichment step)

- Two providers, selected by `LLM_PROVIDER` (`openrouter` default, or `google` for the Google Developer API — Gemini/Gemma direct). Same `chat_completion(messages) -> str` contract either way; callers don't branch on provider.
  - `openrouter`: `OPENROUTER_MODEL` (default `google/gemma-4-31b-it:free`), `OPENROUTER_API_KEY`.
  - `google`: `GOOGLE_MODEL` (default `gemma-3-27b-it`), `GOOGLE_API_KEY`. Switch here when OpenRouter's shared free pool throttles too hard. Gemma on the Google API takes no `system` role, so `providers/google.py` folds system text into the first user turn.
- Each provider rate-limits (`LLM_REQUESTS_PER_MINUTE`, 20/min default) and retries 429/5xx with backoff. Callers just await `chat_completion(messages)`.
- The free Gemma pool can 429 at an **upstream shared-pool** level (all OpenRouter free users, not just our account) — seen intermittently in testing, unrelated to our own rate limit. A long batch job (10k rows) should tolerate extended stalls beyond the built-in retries, not just treat a failure as fatal.
- `Transcripcion` rows average ~130 tokens — token/context limits are a non-issue; **request count** is the real constraint on the free tier. Batch multiple transcripts per request to cut request count, rather than one call per transcript.
