import asyncio
import time
from collections import deque

import httpx

from app.config import get_settings


class LLMError(Exception):
    """Raised when an LLM provider returns an unrecoverable error."""


class RateLimiter:
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


def retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return min(2**attempt, 60)


async def post_with_retries(
    http: httpx.AsyncClient,
    path: str,
    json_body: dict,
    rate_limiter: RateLimiter,
    provider_label: str,
) -> httpx.Response:
    """POST `json_body` to `path`, retrying transient failures with backoff.

    Retries both HTTP-level (429 / 5xx) and transport-level failures — a read
    timeout, dropped connection or DNS blip raises `httpx.TransportError`, not an
    HTTP status, and used to fall straight through to the caller and kill the job.
    Gives up after `LLM_MAX_RETRIES` attempts, raising `LLMError` so the caller's
    stall-tolerance can decide whether to keep waiting.
    """
    settings = get_settings()
    attempt = 0
    while True:
        attempt += 1
        await rate_limiter.acquire()
        try:
            response = await http.post(path, json=json_body)
        except httpx.TransportError as exc:
            if attempt >= settings.llm_max_retries:
                raise LLMError(
                    f"{provider_label} request failed after {attempt} attempts: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            await asyncio.sleep(min(2**attempt, 60))
            continue

        if response.status_code == 429 or response.status_code >= 500:
            if attempt >= settings.llm_max_retries:
                raise LLMError(
                    f"{provider_label} request failed after {attempt} attempts: "
                    f"{response.status_code} {response.text}"
                )
            await asyncio.sleep(retry_delay(response, attempt))
            continue

        response.raise_for_status()
        return response
