import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import dashboard, ingestion, jobs
from app.config import get_settings
from app.db.session import close_db, init_db
from app.llm.client import close_llm_client, init_llm_client
from app.llm.jobs import fail_orphaned_jobs, start_worker, stop_worker
from app.logging_config import configure_logging

# At import for anything that loads the app without a server; again in the
# lifespan because uvicorn applies its own dictConfig after this module is
# imported, and that is the call that reliably wins.
configure_logging()

logger = logging.getLogger(__name__)


def _warn_on_inconsistent_timeouts(settings) -> None:
    """The four LLM ceilings are meant to nest. Say so out loud when they don't.

    An over-large `LLM_REQUEST_TIMEOUT_SECONDS` is the failure that is hardest to
    see from the outside: a single hung connection then holds a batch for as long
    as it likes, the retry loop never gets a turn, and the job just sits at
    `running` with no error. The outer ceilings now cut it off regardless, but
    the config is still wrong and worth flagging rather than silently clamping.
    """
    if settings.llm_request_timeout_seconds > settings.llm_batch_timeout_seconds:
        logger.warning(
            "LLM_REQUEST_TIMEOUT_SECONDS (%.0fs) exceeds LLM_BATCH_TIMEOUT_SECONDS (%.0fs): a "
            "single request can consume the whole batch budget, so LLM_MAX_RETRIES never gets "
            "to retry. Set the request timeout well below the batch ceiling.",
            settings.llm_request_timeout_seconds,
            settings.llm_batch_timeout_seconds,
        )
    if settings.llm_batch_timeout_seconds > settings.llm_batch_max_stall_seconds:
        logger.warning(
            "LLM_BATCH_TIMEOUT_SECONDS (%.0fs) exceeds LLM_BATCH_MAX_STALL_SECONDS (%.0fs): "
            "a batch gets only one attempt before its stall budget is gone.",
            settings.llm_batch_timeout_seconds,
            settings.llm_batch_max_stall_seconds,
        )
    if settings.llm_batch_max_stall_seconds > settings.llm_job_timeout_seconds:
        logger.warning(
            "LLM_BATCH_MAX_STALL_SECONDS (%.0fs) exceeds LLM_JOB_TIMEOUT_SECONDS (%.0fs): "
            "one stalled batch can consume the entire job deadline.",
            settings.llm_batch_max_stall_seconds,
            settings.llm_job_timeout_seconds,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    logger.info(
        "Starting up: db=%s, llm_provider=%s, batch_size=%d, cap=%d, "
        "timeouts(request/batch/stall/job)=%.0f/%.0f/%.0f/%.0fs",
        settings.mongo_db_name,
        settings.llm_provider,
        settings.llm_batch_size,
        settings.llm_max_transcripts_per_job,
        settings.llm_request_timeout_seconds,
        settings.llm_batch_timeout_seconds,
        settings.llm_batch_max_stall_seconds,
        settings.llm_job_timeout_seconds,
    )
    _warn_on_inconsistent_timeouts(settings)
    await init_db()
    # Jobs left `running` by the previous process can never resume — the queue
    # was in-memory. Close them out before the UI polls and shows them as live.
    await fail_orphaned_jobs()
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
