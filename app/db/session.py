from motor.motor_asyncio import AsyncIOMotorClient

from beanie import init_beanie

from app.config import get_settings
from app.models import Client, MeetingTranscript

_client: AsyncIOMotorClient | None = None


async def init_db() -> None:
    global _client
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongo_uri)
    await init_beanie(
        database=_client[settings.mongo_db_name],
        document_models=[Client, MeetingTranscript],
        allow_index_dropping=True,
    )


async def close_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
