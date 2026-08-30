from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import ingestion
from app.db.session import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(lifespan=lifespan)
app.include_router(ingestion.router)


@app.get("/")
def read_root():
    return {"status": "ok"}
