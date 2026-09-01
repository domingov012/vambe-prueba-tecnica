import logging

import httpx

from app.config import ThinkingLevel, get_settings
from app.llm.providers.base import LLMError, RateLimiter, post_with_retries

logger = logging.getLogger(__name__)

_http: httpx.AsyncClient | None = None
_rate_limiter: RateLimiter | None = None


def init() -> None:
    global _http, _rate_limiter
    settings = get_settings()
    _http = httpx.AsyncClient(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=httpx.Timeout(settings.llm_request_timeout_seconds),
    )
    _rate_limiter = RateLimiter(settings.llm_requests_per_minute)


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


async def chat_completion(
    messages: list[dict[str, str]], *, thinking_level: ThinkingLevel | None = None
) -> str:
    """Send a chat completion request to OpenRouter, retrying on rate limits/server errors."""
    if _http is None or _rate_limiter is None:
        raise RuntimeError("LLM client not initialized — call init_llm_client() first")

    settings = get_settings()
    payload: dict = {"model": settings.openrouter_model, "messages": messages}
    if thinking_level is not None:
        # OpenRouter has no `thinkingLevel`; map onto its `reasoning` knob —
        # `minimal` turns reasoning off, `low`/`high` become `effort`. Ignored by
        # models with no reasoning mode.
        payload["reasoning"] = (
            {"enabled": False}
            if thinking_level is ThinkingLevel.minimal
            else {"effort": thinking_level.value}
        )

    response = await post_with_retries(
        _http, "/chat/completions", payload, _rate_limiter, "OpenRouter"
    )

    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError(
            f"OpenRouter returned a 200 that is not JSON: {response.text[:500]!r}",
            kind="bad_response",
        ) from exc

    # OpenRouter reports some upstream failures as a 200 carrying an `error`
    # object and no `choices` — an unguarded ["choices"][0] turned that into a
    # bare KeyError that told the operator nothing.
    if body.get("error"):
        raise LLMError(f"OpenRouter returned an error body: {body['error']}", kind="bad_response")

    try:
        choice = body["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            f"OpenRouter returned no completion content: {str(body)[:500]}",
            kind="bad_response",
        ) from exc

    # finish_reason="length" means the JSON the caller is about to parse is
    # truncated mid-object — the fix is a smaller LLM_BATCH_SIZE, not a retry.
    if choice.get("finish_reason") == "length":
        logger.warning(
            "OpenRouter truncated the completion (finish_reason=length) — the response is "
            "incomplete; lower LLM_BATCH_SIZE"
        )

    if not (content or "").strip():
        raise LLMError(
            f"OpenRouter returned an empty completion "
            f"(finish_reason={choice.get('finish_reason')})",
            kind="bad_response",
        )
    return content
