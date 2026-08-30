import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.llm.client import chat_completion
from app.models.enhanced_transcript import EnhancedTranscript
from app.models.meeting import MeetingTranscript

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "system.md").read_text(encoding="utf-8")

_ENHANCED_FIELDS = [
    "sector",
    "sub_sector",
    "business_model",
    "business_size",
    "inquiry_volume",
    "discovery_channel",
    "current_channels",
    "client_needs",
    "regulatory_flag",
    "pain_point_urgency",
]


async def enrich_batch(items: list[tuple[str, MeetingTranscript]]) -> list[EnhancedTranscript]:
    """Classify a batch of transcripts in a single LLM call.

    Each item's schema is validated independently — an invalid/missing item is
    skipped without discarding the rest of the batch. Only a batch-level failure
    (malformed JSON, empty/non-array response) discards the whole batch.
    """
    if not items:
        return []

    user_content = json.dumps(
        [{"id": idx, "transcript": meeting.transcript} for idx, (_key, meeting) in enumerate(items)],
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

    by_id = {idx: (key, meeting) for idx, (key, meeting) in enumerate(items)}
    results: list[EnhancedTranscript] = []

    for entry in parsed:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        matched = by_id.get(entry["id"])
        if matched is None:
            continue
        key, meeting = matched
        try:
            fields = {name: entry[name] for name in _ENHANCED_FIELDS}
            results.append(
                EnhancedTranscript(
                    id=key,
                    meeting=meeting,
                    closed=meeting.closed,
                    salesperson=meeting.salesperson,
                    **fields,
                )
            )
        except (KeyError, ValidationError) as exc:
            logger.warning("Skipping invalid enrichment result for id=%s: %s", entry.get("id"), exc)

    return results


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()
