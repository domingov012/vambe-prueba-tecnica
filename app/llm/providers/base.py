import asyncio
import time
from collections import deque

import httpx


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
