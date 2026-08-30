import asyncio

import httpx

from app.config import get_settings
from app.llm.providers.base import LLMError, RateLimiter, retry_delay

_http: httpx.AsyncClient | None = None
_rate_limiter: RateLimiter | None = None


def init() -> None:
    global _http, _rate_limiter
    settings = get_settings()
    _http = httpx.AsyncClient(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=httpx.Timeout(120.0),
    )
    _rate_limiter = RateLimiter(settings.llm_requests_per_minute)


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


async def chat_completion(messages: list[dict[str, str]]) -> str:
    """Send a chat completion request to OpenRouter, retrying on rate limits/server errors."""
    if _http is None or _rate_limiter is None:
        raise RuntimeError("LLM client not initialized — call init_llm_client() first")

    settings = get_settings()
    payload = {"model": settings.openrouter_model, "messages": messages}

    attempt = 0
    while True:
        attempt += 1
        await _rate_limiter.acquire()
        response = await _http.post("/chat/completions", json=payload)

        if response.status_code == 429 or response.status_code >= 500:
            if attempt >= settings.llm_max_retries:
                raise LLMError(
                    f"OpenRouter request failed after {attempt} attempts: "
                    f"{response.status_code} {response.text}"
                )
            await asyncio.sleep(retry_delay(response, attempt))
            continue

        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]
