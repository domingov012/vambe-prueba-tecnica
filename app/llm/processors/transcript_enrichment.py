import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.llm.client import chat_completion
from app.models.enhanced_transcript import TranscriptClassification

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "system.md").read_text(encoding="utf-8")


async def enrich_batch(items: list[tuple[str, str]]) -> list[tuple[str, TranscriptClassification]]:
    """Classify a batch of transcripts in a single LLM call.

    `items` is a list of `(enrichment_key, transcript_text)`. Returns the subset
    that classified successfully as `(enrichment_key, TranscriptClassification)`;
    an invalid/missing item is skipped without discarding the rest of the batch.
    Only a batch-level failure (malformed JSON, empty/non-array response) discards
    the whole batch.
    """
    if not items:
        return []

    user_content = json.dumps(
        [{"id": idx, "transcript": transcript} for idx, (_key, transcript) in enumerate(items)],
        ensure_ascii=False,
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = await chat_completion(messages)

    try:
        parsed = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        logger.warning("Enrichment batch discarded: response was not valid JSON")
        return []

    if not isinstance(parsed, list):
        logger.warning("Enrichment batch discarded: response was not a JSON array")
        return []

    keys_by_id = {idx: key for idx, (key, _transcript) in enumerate(items)}
    results: list[tuple[str, TranscriptClassification]] = []

    for entry in parsed:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        key = keys_by_id.get(entry["id"])
        if key is None:
            continue
        try:
            results.append((key, TranscriptClassification.model_validate(entry)))
        except ValidationError as exc:
            logger.warning("Skipping invalid enrichment result for id=%s: %s", entry.get("id"), exc)

    return results


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()
