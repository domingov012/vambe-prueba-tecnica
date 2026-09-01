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
        base_url=settings.google_base_url,
        headers={"x-goog-api-key": settings.google_api_key},
        timeout=httpx.Timeout(settings.llm_request_timeout_seconds),
    )
    _rate_limiter = RateLimiter(settings.llm_requests_per_minute)


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def _to_contents(messages: list[dict[str, str]]) -> list[dict]:
    """Translate OpenAI-style messages to the Gemini generateContent format.

    Gemma models on the Google API accept neither a `system` role nor a
    `systemInstruction` block, so system text is folded into the first user turn.
    """
    system_text = "\n\n".join(m["content"] for m in messages if m["role"] == "system")

    contents: list[dict] = []
    for message in messages:
        if message["role"] == "system":
            continue
        role = "model" if message["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message["content"]}]})

    if system_text:
        first_user = next((c for c in contents if c["role"] == "user"), None)
        if first_user is None:
            contents.insert(0, {"role": "user", "parts": [{"text": system_text}]})
        else:
            first_user["parts"][0]["text"] = f"{system_text}\n\n{first_user['parts'][0]['text']}"

    return contents


async def chat_completion(
    messages: list[dict[str, str]], *, thinking_level: ThinkingLevel | None = None
) -> str:
    """Send a generateContent request to the Google Developer API (Gemini/Gemma),
    retrying on rate limits/server errors — same contract as the OpenRouter caller."""
    if _http is None or _rate_limiter is None:
        raise RuntimeError("LLM client not initialized — call init_llm_client() first")

    settings = get_settings()
    payload: dict = {"contents": _to_contents(messages)}
    if thinking_level is not None:
        payload["generationConfig"] = {
            "thinkingConfig": {"thinkingLevel": thinking_level.value}
        }
    path = f"/models/{settings.google_model}:generateContent"

    response = await post_with_retries(_http, path, payload, _rate_limiter, "Google API")

    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError(
            f"Google API returned a 200 that is not JSON: {response.text[:500]!r}",
            kind="bad_response",
        ) from exc

    # A safety filter or a prompt-level block answers 200 with no candidates at
    # all; say so explicitly rather than surfacing a bare KeyError.
    blocked = (body.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise LLMError(f"Google API blocked the prompt: {blocked}", kind="bad_response")

    try:
        candidate = body["candidates"][0]
        parts = candidate["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            f"Google API returned no candidate content: {str(body)[:500]}",
            kind="bad_response",
        ) from exc

    finish_reason = candidate.get("finishReason")
    if finish_reason and finish_reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        logger.warning(
            "Google API finished with reason=%s — the response is probably incomplete "
            "(if MAX_TOKENS, lower LLM_BATCH_SIZE)",
            finish_reason,
        )

    # Gemma 4 emits reasoning as parts flagged `"thought": true` — keep only
    # the answer text.
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise LLMError(
            f"Google API returned an empty completion (finishReason={finish_reason})",
            kind="bad_response",
        )
    return text
