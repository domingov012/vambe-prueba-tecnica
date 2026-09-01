import asyncio
import logging
import time
from collections import deque

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """An LLM provider call failed.

    `kind` classifies the failure so callers can react without string-matching
    and so the job row can tell the operator *which* of the three failure modes
    they hit. Values: `timeout`, `transport`, `rate_limit`, `server_error`,
    `client_error`, `bad_response`.
    """

    def __init__(self, message: str, *, kind: str = "unknown", status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


class LLMFatalError(LLMError):
    """A failure that retrying cannot fix — a rejected API key, an unknown model
    name, a malformed request (any non-429 4xx). Callers must fail the job
    immediately instead of stalling on it: waiting 30 minutes to re-send a
    request the server has already refused only hides the real problem.
    """


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
                wait = 60 - (now - self._timestamps[0])
                logger.info("Local rate limit reached (%d/min), waiting %.1fs", self._max_requests, wait)
                await asyncio.sleep(wait)


def retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return min(2**attempt, 60)


def _truncate(text: str, limit: int = 500) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}… ({len(text)} chars)"


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
    HTTP status. Gives up after `LLM_MAX_RETRIES` attempts, raising `LLMError` so
    the caller's stall-tolerance can decide whether to keep waiting.

    Non-429 4xx responses raise `LLMFatalError` on the first attempt: the server
    has understood the request and refused it, so neither the retry loop here nor
    the stall loop above should burn wall-clock re-sending it.

    Every attempt logs its outcome and duration — this is the only place that can
    tell "the model is slow" apart from "the model is refusing us", and a job
    stuck at 0 processed is unreadable without it.
    """
    settings = get_settings()
    attempt = 0
    while True:
        attempt += 1
        await rate_limiter.acquire()
        started = time.monotonic()
        try:
            response = await http.post(path, json=json_body)
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - started
            message = (
                f"{provider_label} request timed out after {elapsed:.1f}s "
                f"(LLM_REQUEST_TIMEOUT_SECONDS={settings.llm_request_timeout_seconds:.0f}) "
                f"on attempt {attempt}/{settings.llm_max_retries}: {type(exc).__name__}"
            )
            if attempt >= settings.llm_max_retries:
                logger.error("%s — giving up", message)
                raise LLMError(message, kind="timeout") from exc
            delay = min(2**attempt, 60)
            logger.warning("%s — retrying in %.0fs", message, delay)
            await asyncio.sleep(delay)
            continue
        except httpx.TransportError as exc:
            elapsed = time.monotonic() - started
            message = (
                f"{provider_label} request failed after {elapsed:.1f}s on attempt "
                f"{attempt}/{settings.llm_max_retries}: {type(exc).__name__}: {exc}"
            )
            if attempt >= settings.llm_max_retries:
                logger.error("%s — giving up", message)
                raise LLMError(message, kind="transport") from exc
            delay = min(2**attempt, 60)
            logger.warning("%s — retrying in %.0fs", message, delay)
            await asyncio.sleep(delay)
            continue

        elapsed = time.monotonic() - started
        status = response.status_code

        if status == 429 or status >= 500:
            kind = "rate_limit" if status == 429 else "server_error"
            message = (
                f"{provider_label} returned {status} after {elapsed:.1f}s on attempt "
                f"{attempt}/{settings.llm_max_retries}: {_truncate(response.text)}"
            )
            if attempt >= settings.llm_max_retries:
                logger.error("%s — giving up", message)
                raise LLMError(message, kind=kind, status_code=status)
            delay = retry_delay(response, attempt)
            logger.warning("%s — retrying in %.0fs", message, delay)
            await asyncio.sleep(delay)
            continue

        if status >= 400:
            message = (
                f"{provider_label} rejected the request with {status} "
                f"(not retryable): {_truncate(response.text)}"
            )
            logger.error(message)
            raise LLMFatalError(message, kind="client_error", status_code=status)

        logger.info(
            "%s responded %d in %.1fs (attempt %d, %d bytes)",
            provider_label,
            status,
            elapsed,
            attempt,
            len(response.content),
        )
        return response
