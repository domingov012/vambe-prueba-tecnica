from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import ingestion
from app.db.session import close_db, init_db
from app.llm.client import close_llm_client, init_llm_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    init_llm_client()
    yield
    await close_llm_client()
    await close_db()


app = FastAPI(lifespan=lifespan)
app.include_router(ingestion.router)


@app.get("/")
def read_root():
    return {"status": "ok"}
