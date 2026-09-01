"""Build the flat rows every dashboard aggregation runs against.

One `TranscriptRow` per `EnhancedTranscript`. `closed`, `salesperson` and
`meeting_date` are denormalized onto `EnhancedTranscript` at enrichment time
(immutable source fields), so this is a **single-collection read with no join** —
we don't touch `meeting_transcripts` or `clients` here at all.

## Duplicate handling

Reworded near-duplicate transcripts share the exact tuple
`(name, email, phone_number, meeting_date)`. That tuple *is* the
`EnhancedTranscript` `_id` (see `enrichment_key()`), so the collection can hold
at most one enhanced row per duplicate group by construction — de-duplication is
already guaranteed at write time by the primary key and needs no filtering here.

## Query-layer vs. app-layer aggregation

Counting happens in Python, not a `$group`/`$unwind` pipeline. Justified for the
current scale (≤ ~10k transcripts): the whole payload is precomputed off the
request path, one full scan of a small projected collection is a few ms, the
multi-select flattening + bucketing logic stays in one testable place, and the
repo already avoids Motor's `aggregate()` (broken for this beanie/motor pair —
see `app/llm/jobs.py`). Revisit if the enhanced collection passes ~100k rows or
`recompute_insights()` starts taking more than a couple of seconds — at that
point move `close_rate_by_dimension` / `needs_matrix` to `$group` pipelines and
add indexes on the grouped fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel

from app.models.enhanced_transcript import (
    BusinessModel,
    BusinessSize,
    Channel,
    ClientNeed,
    DiscoveryChannel,
    EnhancedTranscript,
    IndustryBucket,
    InquiryVolume,
    PainPointUrgency,
    RegulatoryFlag,
)


class _EnhancedProjection(BaseModel):
    """Only the fields the charts depend on — skips sub_sector (free text, not a
    chartable domain), the meeting link and the id, keeping the scan payload
    minimal."""

    sector: IndustryBucket
    business_model: BusinessModel
    business_size: BusinessSize
    inquiry_volume: InquiryVolume
    discovery_channel: DiscoveryChannel
    regulatory_flag: RegulatoryFlag
    pain_point_urgency: PainPointUrgency
    current_channels: list[Channel]
    client_needs: list[ClientNeed]
    closed: bool
    salesperson: str
    # Stored as a midnight datetime (beanie encodes `date` that way) and coerced
    # back on read. `None` for rows enriched before the field existed — see the
    # model and `scripts/backfill_enhanced_meeting_date.py`.
    meeting_date: date | None = None


@dataclass(frozen=True)
class TranscriptRow:
    sector: str
    business_model: str
    business_size: str
    inquiry_volume: str
    discovery_channel: str
    regulatory_flag: str
    pain_point_urgency: str
    current_channels: tuple[str, ...]
    client_needs: tuple[str, ...]
    closed: bool
    salesperson: str
    meeting_date: date | None


# Process cache of the projected rows. They only change when an enrichment job
# writes new `EnhancedTranscript`s, and that path always ends in
# `recompute_insights()` → `load_transcript_rows()`, which refreshes this. The
# custom-crosstab endpoint reads it through `get_transcript_rows()` so an
# interactive pivot (any 2 of 5 dimensions × 2 measures — too many combinations
# to precompute) never re-scans Mongo.
_ROWS_CACHE: list[TranscriptRow] | None = None


async def load_transcript_rows() -> list[TranscriptRow]:
    """Scan the enhanced collection and rebuild the flat row list. Also refreshes
    the process cache that `get_transcript_rows()` serves."""
    global _ROWS_CACHE
    projected = await EnhancedTranscript.find_all().project(_EnhancedProjection).to_list()
    _ROWS_CACHE = [
        TranscriptRow(
            sector=p.sector.value,
            business_model=p.business_model.value,
            business_size=p.business_size.value,
            inquiry_volume=p.inquiry_volume.value,
            discovery_channel=p.discovery_channel.value,
            regulatory_flag=p.regulatory_flag.value,
            pain_point_urgency=p.pain_point_urgency.value,
            current_channels=tuple(c.value for c in p.current_channels),
            client_needs=tuple(n.value for n in p.client_needs),
            closed=p.closed,
            salesperson=p.salesperson.strip(),
            meeting_date=p.meeting_date,
        )
        for p in projected
    ]
    return _ROWS_CACHE


async def get_transcript_rows() -> list[TranscriptRow]:
    """Cached view of `load_transcript_rows()` for the request path. Falls back to
    a live scan on a cold process (no enrichment job has completed this boot).

    Callers must treat the list as read-only — it is the shared cached reference.
    """
    if _ROWS_CACHE is not None:
        return _ROWS_CACHE
    return await load_transcript_rows()
