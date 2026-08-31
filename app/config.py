from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "vambe"

    # "openrouter" or "google" (Google Developer API — Gemini/Gemma direct)
    llm_provider: str = "openrouter"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"

    google_api_key: str = ""
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    google_model: str = "gemma-4-31b-it"

    llm_requests_per_minute: int = 20
    llm_max_retries: int = 5
    llm_batch_size: int = 10
    llm_max_transcripts_per_job: int = 100
    # Per-request HTTP timeout. A batch that the model can't answer within this
    # window raises a transport error (retried by post_with_retries). Keep it
    # comfortably above a slow generation; shrink LLM_BATCH_SIZE if batches of
    # this size routinely time out rather than bumping this much higher.
    llm_request_timeout_seconds: float = 120.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
