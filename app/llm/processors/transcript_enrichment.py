import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.llm.client import chat_completion
from app.models.enhanced_transcript import TranscriptClassification

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "system.md").read_text(encoding="utf-8")

# How much of a malformed response to put in the log / the job row. Enough to
# see whether the model emitted prose, a truncated object or a wrapper key.
_PREVIEW_CHARS = 800


@dataclass
class BatchOutcome:
    """What one LLM call produced, including *why* anything was dropped.

    `enrich_batch` used to return a bare list, so "the model answered with
    prose", "the JSON was truncated" and "every item failed validation" all
    reached the job as an indistinguishable empty list. The job row could then
    only say `failed_count: 10`. Carrying the reason up is what lets a stuck or
    empty job explain itself in the UI.
    """

    classified: list[tuple[str, TranscriptClassification]] = field(default_factory=list)
    # Set when the *whole* batch was discarded (unparseable response).
    error: str | None = None
    error_kind: str | None = None
    # Items the model returned that individually failed validation, plus items
    # we asked about that it never mentioned.
    invalid_count: int = 0
    missing_count: int = 0


async def enrich_batch(items: list[tuple[str, str]]) -> BatchOutcome:
    """Classify a batch of transcripts in a single LLM call.

    `items` is a list of `(enrichment_key, transcript_text)`. Returns a
    `BatchOutcome` whose `classified` holds the subset that validated; an
    invalid/missing item is skipped without discarding the rest of the batch.
    Only a batch-level failure (malformed JSON, empty/non-array response)
    discards the whole batch, and it sets `error`/`error_kind` when it does.

    Provider-level failures (`LLMError`) propagate — the caller's stall
    tolerance owns those.
    """
    if not items:
        return BatchOutcome()

    user_content = json.dumps(
        [{"id": idx, "transcript": transcript} for idx, (_key, transcript) in enumerate(items)],
        ensure_ascii=False,
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = await chat_completion(messages)
    logger.debug("Raw enrichment response (%d chars): %s", len(raw), raw)

    parsed, failure = _parse_response(raw)
    if failure is not None:
        return failure

    keys_by_id = {idx: key for idx, (key, _transcript) in enumerate(items)}
    results: list[tuple[str, TranscriptClassification]] = []
    invalid = 0
    seen_ids: set[int] = set()

    for position, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            invalid += 1
            logger.warning(
                "Skipping enrichment entry at position %d: expected an object, got %s",
                position,
                type(entry).__name__,
            )
            continue
        if "id" not in entry:
            invalid += 1
            logger.warning(
                "Skipping enrichment entry at position %d: no 'id' field (keys: %s)",
                position,
                sorted(entry)[:10],
            )
            continue

        key = keys_by_id.get(entry["id"])
        if key is None:
            invalid += 1
            logger.warning(
                "Skipping enrichment result for unknown id=%r (batch has ids 0..%d)",
                entry["id"],
                len(items) - 1,
            )
            continue

        seen_ids.add(entry["id"])
        try:
            results.append((key, TranscriptClassification.model_validate(entry)))
        except ValidationError as exc:
            invalid += 1
            logger.warning(
                "Skipping invalid enrichment result for id=%s: %s",
                entry.get("id"),
                _format_validation_error(exc),
            )

    missing = len(items) - len(seen_ids)
    if missing:
        logger.warning(
            "Model returned no result for %d/%d transcript(s) in the batch (ids: %s)",
            missing,
            len(items),
            sorted(set(keys_by_id) - seen_ids)[:20],
        )

    return BatchOutcome(classified=results, invalid_count=invalid, missing_count=missing)


def _parse_response(raw: str) -> tuple[list, BatchOutcome | None]:
    """Turn the raw completion into a list of entries, or a failed BatchOutcome.

    Returns `(entries, None)` on success and `([], outcome)` on failure, so the
    caller reads one branch instead of catching three exception types.
    """
    text = _strip_code_fence(raw)

    if not text:
        message = "model returned an empty response"
        logger.warning("Enrichment batch discarded: %s", message)
        return [], BatchOutcome(error=message, error_kind="empty_response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # Distinguish "hit the output-token cap mid-object" from "ignored the
        # format and wrote prose" — same exception, different fix. A response
        # that opened a container and never closed it is the truncated one;
        # `exc.pos` alone is not enough, since "Unterminated string" reports
        # where the string *started*, which can be far from the end.
        truncated = text.startswith(("[", "{")) and not text.rstrip().endswith(("]", "}"))
        message = (
            f"response was not valid JSON ({exc.msg} at char {exc.pos} of {len(text)})"
            + (" — looks truncated, lower LLM_BATCH_SIZE" if truncated else "")
        )
        logger.warning(
            "Enrichment batch discarded: %s. Response preview: %s",
            message,
            _preview(text),
        )
        return [], BatchOutcome(error=message, error_kind="invalid_json")

    # Models routinely wrap the array in a single-key object
    # (`{"results": [...]}`); unwrap that rather than throwing the batch away.
    if isinstance(parsed, dict):
        lists = [value for value in parsed.values() if isinstance(value, list)]
        if len(lists) == 1:
            logger.info("Unwrapped enrichment array from a single-key JSON object")
            parsed = lists[0]

    if not isinstance(parsed, list):
        message = f"response was not a JSON array (got {type(parsed).__name__})"
        logger.warning(
            "Enrichment batch discarded: %s. Response preview: %s", message, _preview(text)
        )
        return [], BatchOutcome(error=message, error_kind="invalid_json")

    return parsed, None


def _format_validation_error(exc: ValidationError) -> str:
    """Pydantic's default str() is multi-line and repeats the docs URL per error;
    collapse it to `field: message` pairs so one log line stays one log line."""
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors()[:5]
    )


def _preview(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _PREVIEW_CHARS:
        return repr(collapsed)
    half = _PREVIEW_CHARS // 2
    # Keep both ends: the head shows whether the shape is right at all, the tail
    # shows where a truncated response stopped.
    return f"{collapsed[:half]!r} … {collapsed[-half:]!r} ({len(collapsed)} chars)"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()
