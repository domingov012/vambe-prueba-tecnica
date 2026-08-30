import asyncio
import time
from collections import deque

import httpx

from app.config import get_settings


class OpenRouterError(Exception):
    """Raised when OpenRouter returns an unrecoverable error."""


class _RateLimiter:
    """Sliding-window limiter capping requests to N per rolling 60s window."""

    def __init__(self, requests_per_minute: int) -> None:
        self._max_requests = requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= 60:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return
                await asyncio.sleep(60 - (now - self._timestamps[0]))


_http: httpx.AsyncClient | None = None
_rate_limiter: _RateLimiter | None = None


def init_llm_client() -> None:
    global _http, _rate_limiter
    settings = get_settings()
    _http = httpx.AsyncClient(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=httpx.Timeout(120.0),
    )
    _rate_limiter = _RateLimiter(settings.llm_requests_per_minute)


async def close_llm_client() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return min(2**attempt, 60)


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
                raise OpenRouterError(
                    f"OpenRouter request failed after {attempt} attempts: "
                    f"{response.status_code} {response.text}"
                )
            await asyncio.sleep(_retry_delay(response, attempt))
            continue

        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]
