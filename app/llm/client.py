"""Public LLM client surface.

Dispatches `init_llm_client()` / `close_llm_client()` / `chat_completion()` to the
provider selected by `LLM_PROVIDER` (see `app/config.py`). Every provider in
`app/llm/providers/` implements the same three-function contract, so callers
(`llm/processors/*`, `llm/jobs.py`) never need to know which one is active.
"""

from app.config import get_settings
from app.llm.providers import google, openrouter
from app.llm.providers.base import LLMError, LLMFatalError

# Backwards-compatible alias — the error is provider-agnostic now.
OpenRouterError = LLMError

__all__ = [
    "LLMError",
    "LLMFatalError",
    "OpenRouterError",
    "chat_completion",
    "close_llm_client",
    "init_llm_client",
]

_PROVIDERS = {
    "openrouter": openrouter,
    "google": google,
}


def _provider():
    name = get_settings().llm_provider
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER {name!r} — expected one of {sorted(_PROVIDERS)}"
        ) from None


def init_llm_client() -> None:
    _provider().init()


async def close_llm_client() -> None:
    await _provider().close()


async def chat_completion(messages: list[dict[str, str]]) -> str:
    return await _provider().chat_completion(messages)
