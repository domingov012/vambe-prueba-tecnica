# Prueba Tecnica Vambe - Domingo Venegas

FastAPI + MongoDB app that ingests client meeting transcripts from CSV, enriches
them with an LLM, and serves a dashboard of insights over the results.

## Run it locally

Requires Docker and a MongoDB connection string.

```bash
cp .env.example .env     # then fill in MONGO_URI and one LLM API key
docker compose up --build
```

Open **http://localhost:8080**.

Two containers: `web` (nginx) serves the built SPA and proxies `/api` to
`backend` (FastAPI + uvicorn), which is not published. Same-origin, so the
frontend's relative `/api/*` URLs work with no CORS configuration.

### MongoDB is not containerised

Deliberately. The enrichment pipeline writes `Client`, `MeetingTranscript` and
`EnhancedTranscript` in a single transaction, and MongoDB transactions require a
replica set — a standalone `mongod` cannot run them. Point `MONGO_URI` at Atlas;
the free M0 tier is a replica set and works.

If you do want a local server, it must be started as a single-node replica set,
and the URI from inside the container is `host.docker.internal`, not `localhost`.

## Deployment (Render)

The repo-root `Dockerfile` builds a **single self-contained image**: it compiles
the frontend in a Node stage and bakes `dist/` into `static/`, which
`app/main.py` mounts when present. So one image serves both the API and the UI,
with no nginx — that is what the deployed instance runs.

Under `docker compose` the same image is used, nginx fronts it, and the baked
copy simply goes unused. One build path, two topologies.

`render.yaml` is a Blueprint describing that service. Render injects `PORT` and
the Dockerfile's `CMD` already reads it, so nothing platform-specific is baked
into the image. Secrets (`MONGO_URI`, `LLM_PROVIDER`, and `GOOGLE_API_KEY` or
`OPENROUTER_API_KEY`) are declared `sync: false` — set in the Render dashboard,
never committed and never in the image.

**Atlas must allow `0.0.0.0/0`** under Network Access. Render's egress IPs on
the free plan are dynamic, so there is no address to allowlist; the database
password is the actual gate, so use a user scoped to the `vambe` database rather
than admin credentials.

### Known limits of the free plan

- **Sleeps after ~15 minutes idle.** First request afterwards cold-starts and
  takes roughly a minute. The dashboard itself is unaffected once up: insights
  are a precomputed blob in Mongo, so the deployed instance reads rather than
  recomputes.
- **A long enrichment job may not survive a spin-down.** Enrichment runs on an
  in-process `asyncio.Queue` worker (`app/llm/jobs.py`) that keeps working after
  the upload response returned, for up to 30 minutes on a stalled batch. The
  work is resumable — re-uploading the same CSV skips everything that already
  landed — but prefer running large ingests locally and letting the deployed
  instance read the results.
- **512 MB RAM.** A CSV is parsed and validated fully in memory before being
  enqueued, so very large uploads are another reason to ingest locally.

The service runs **one uvicorn worker and one instance**, deliberately: a second
process would get its own queue and its own worker loop.

## Layout

```
app/                 FastAPI backend — see app/CLAUDE.md
frontend/            Vite SPA (vanilla JS + Chart.js) — see frontend/CLAUDE.md
deploy/nginx.conf    static serving + /api proxy for the compose setup
render.yaml          Render Blueprint for the deployed single-image service
scripts/             one-off maintenance scripts
aggregations.md      dashboard insights payload contract
```
