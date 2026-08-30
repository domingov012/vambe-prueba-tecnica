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
