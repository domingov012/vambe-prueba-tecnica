from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ThinkingLevel(str, Enum):
    """How much internal reasoning the model is asked to spend before answering.

    Passed straight through to the Google API as
    `generationConfig.thinkingConfig.thinkingLevel` (Gemini 3 / thinking-capable
    Gemma). The OpenRouter provider maps it onto its own `reasoning` knob:
    `minimal` disables reasoning, the rest become `reasoning.effort`. Values
    match the Google API's documented set; anything the model doesn't support it
    clamps to its own minimum.
    """

    minimal = "minimal"
    low = "low"
    high = "high"


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

    # Default reasoning effort for enrichment calls; the CSV upload endpoint can
    # override it per job (`thinking_level` query param). None sends no
    # thinkingConfig at all, leaving the model on its own default.
    llm_thinking_level: ThinkingLevel | None = None

    llm_requests_per_minute: int = 20
    llm_max_retries: int = 5
    llm_batch_size: int = 10
    llm_max_transcripts_per_job: int = 100
    # Per-request HTTP timeout. Measured throughput for gemma-4-31b-it on the
    # Google free tier is ~22s per transcript (3 transcripts in 67s), so the
    # default batch of 10 needs ~220s — the old 120s default could not fit one
    # and every batch timed out, retried, and then stalled. Budget roughly
    # `LLM_BATCH_SIZE × 30s` and keep it under LLM_BATCH_TIMEOUT_SECONDS; drop
    # LLM_BATCH_SIZE rather than raising this without measuring.
    llm_request_timeout_seconds: float = 300.0

    # --- Wall-clock ceilings ---------------------------------------------
    # Three nested deadlines, each bounding the layer below it. They exist
    # because llm_request_timeout_seconds bounds only a *single* HTTP request:
    # post_with_retries multiplies it by llm_max_retries, and the job's stall
    # tolerance then multiplies *that* again, so without these a "120s timeout"
    # could keep one batch alive for hours — which is exactly how a job ends up
    # sitting at `running` with 0 processed and nothing to show for it.
    #
    # 1. One enrich_batch() call including its internal retries. ~2 requests.
    llm_batch_timeout_seconds: float = 660.0
    # 2. One batch including stall-tolerance re-attempts of enrich_batch().
    llm_batch_max_stall_seconds: float = 1500.0
    # 3. The whole job. On expiry the remaining batches are abandoned and the
    #    job is marked failed rather than left running indefinitely. 10 batches
    #    of 10 at measured speed is ~40min; this leaves room for a few retries.
    llm_job_timeout_seconds: float = 5400.0

    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
