from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import dashboard, ingestion, jobs
from app.db.session import close_db, init_db
from app.llm.client import close_llm_client, init_llm_client
from app.llm.jobs import start_worker, stop_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    init_llm_client()
    start_worker()
    yield
    await stop_worker()
    await close_llm_client()
    await close_db()


app = FastAPI(lifespan=lifespan)
app.include_router(ingestion.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.get("/health")
def health():
    """Liveness probe. Lives at /health rather than / because the SPA mount
    below owns /; also what the container HEALTHCHECK hits."""
    return {"status": "ok"}


# Serve the built frontend when it is present. The Docker image bakes it into
# ./static so one container can serve the whole app (that is how the deployed
# Space runs). Under docker-compose nginx serves the same assets instead and
# this mount is never reached; running from source without a build, the
# directory simply does not exist and the API still works on its own.
#
# Mounted last: Starlette matches routes in registration order, so every /api
# route and /health above win before anything falls through to the SPA.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    # html=True serves index.html for "/". The router is hash-based
    # (frontend/src/router.js), so no history-fallback handling is needed.
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="frontend")
