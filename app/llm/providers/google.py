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
        base_url=settings.google_base_url,
        headers={"x-goog-api-key": settings.google_api_key},
        timeout=httpx.Timeout(120.0),
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


async def chat_completion(messages: list[dict[str, str]]) -> str:
    """Send a generateContent request to the Google Developer API (Gemini/Gemma),
    retrying on rate limits/server errors — same contract as the OpenRouter caller."""
    if _http is None or _rate_limiter is None:
        raise RuntimeError("LLM client not initialized — call init_llm_client() first")

    settings = get_settings()
    payload = {"contents": _to_contents(messages)}
    path = f"/models/{settings.google_model}:generateContent"

    attempt = 0
    while True:
        attempt += 1
        await _rate_limiter.acquire()
        response = await _http.post(path, json=payload)

        if response.status_code == 429 or response.status_code >= 500:
            if attempt >= settings.llm_max_retries:
                raise LLMError(
                    f"Google API request failed after {attempt} attempts: "
                    f"{response.status_code} {response.text}"
                )
            await asyncio.sleep(retry_delay(response, attempt))
            continue

        response.raise_for_status()
        body = response.json()
        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Google API returned no candidate content: {body}") from exc
        return "".join(part.get("text", "") for part in parts)
