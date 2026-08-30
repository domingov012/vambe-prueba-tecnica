"""Compute the full dashboard payload — all 10 chart datasets in one object.

Design (per `aggregations.md`): a single precomputed blob, not one endpoint per
chart. `recompute_insights()` builds the whole payload and stores it as one
`DashboardInsights` document keyed `latest`; `GET /api/dashboard/insights` just
reads that blob back. Recompute is triggered whenever an enrichment job finishes
(see `app/llm/jobs.py`) and via `POST /api/dashboard/insights/recompute`.

Two generic aggregation functions cover most of the payload:
  * `close_rate_by_dimension` — charts #1 (×3), #5, #7, #9
  * `needs_matrix`            — charts #8, #10
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone

from app.aggregation.rows import TranscriptRow, load_transcript_rows
from app.models.dashboard import LATEST_KEY, DashboardInsights

# Serializes recomputes: two near-simultaneous triggers (e.g. two enrichment jobs
# finishing, or a job completion racing a manual POST) would otherwise each run a
# full scan to produce the same result. The loser just waits and returns the
# fresh blob.
_recompute_lock = asyncio.Lock()


def _round_rate(closed: int, total: int) -> float:
    return round(closed / total, 4) if total else 0.0


def close_rate_by_dimension(rows: list[TranscriptRow], field: str) -> list[dict]:
    """Group by one single-select field, compute close_rate per group.

    `total` is kept alongside `close_rate` so chart #7 (volume vs. quality) can
    plot both from the same dataset.
    """
    totals: Counter = Counter()
    closed: Counter = Counter()
    for row in rows:
        group = getattr(row, field)
        totals[group] += 1
        if row.closed:
            closed[group] += 1

    result = [
        {
            "group": group,
            "total": total,
            "closed": closed[group],
            "close_rate": _round_rate(closed[group], total),
        }
        for group, total in totals.items()
    ]
    result.sort(key=lambda r: (-r["close_rate"], -r["total"], r["group"]))
    return result


def _frequency(values: list[str], key_name: str) -> list[dict]:
    counts = Counter(values)
    result = [{key_name: value, "count": count} for value, count in counts.items()]
    result.sort(key=lambda r: (-r["count"], r[key_name]))
    return result


def needs_frequency(rows: list[TranscriptRow]) -> list[dict]:
    flat = [need for row in rows for need in row.client_needs]
    return _frequency(flat, "need")


def channel_frequency(rows: list[TranscriptRow], *, current: bool) -> list[dict]:
    if current:
        values = [ch for row in rows for ch in row.current_channels]
    else:
        values = [row.discovery_channel for row in rows]
    return _frequency(values, "channel")


def _rep_group(rows: list[TranscriptRow], extra_key: str | None) -> list[dict]:
    totals: Counter = Counter()
    closed: Counter = Counter()
    for row in rows:
        key = row.salesperson if extra_key is None else (row.salesperson, getattr(row, extra_key))
        totals[key] += 1
        if row.closed:
            closed[key] += 1

    result = []
    for key, total in totals.items():
        entry = {"rep": key} if extra_key is None else {"rep": key[0], extra_key: key[1]}
        entry.update(
            total=total,
            closed=closed[key],
            close_rate=_round_rate(closed[key], total),
        )
        result.append(entry)

    if extra_key is None:
        result.sort(key=lambda r: (-r["close_rate"], -r["total"], r["rep"]))
    else:
        result.sort(key=lambda r: (r["rep"], -r["total"], r[extra_key]))
    return result


_NEEDS_BUCKETS = ["0", "1-2", "3-4", "5+"]


def _needs_bucket(n: int) -> str:
    if n == 0:
        return "0"
    if n <= 2:
        return "1-2"
    if n <= 4:
        return "3-4"
    return "5+"


def close_rate_by_needs_complexity(rows: list[TranscriptRow]) -> list[dict]:
    totals: Counter = Counter()
    closed: Counter = Counter()
    for row in rows:
        bucket = _needs_bucket(len(row.client_needs))
        totals[bucket] += 1
        if row.closed:
            closed[bucket] += 1

    return [
        {
            "needs_bucket": bucket,
            "total": totals[bucket],
            "closed": closed[bucket],
            "close_rate": _round_rate(closed[bucket], totals[bucket]),
        }
        for bucket in _NEEDS_BUCKETS
        if totals[bucket]
    ]


def needs_matrix(rows: list[TranscriptRow], dimension: str) -> list[dict]:
    """Cross-tab a single-select `dimension` against flattened `client_needs`.

    Returns a flat list of `(<dimension>, need, count)` rows for a heatmap.
    Covers chart #8 (`dimension="sector"`) and #10 (`dimension="business_size"`).
    """
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        dim_value = getattr(row, dimension)
        for need in row.client_needs:
            counts[(dim_value, need)] += 1

    result = [
        {dimension: dim_value, "need": need, "count": count}
        for (dim_value, need), count in counts.items()
    ]
    result.sort(key=lambda r: (r[dimension], -r["count"], r["need"]))
    return result


def build_payload(rows: list[TranscriptRow]) -> dict:
    return {
        # 1. Classification vs. conversion outcome
        "close_rate_by_sector": close_rate_by_dimension(rows, "sector"),
        "close_rate_by_business_model": close_rate_by_dimension(rows, "business_model"),
        "close_rate_by_business_size": close_rate_by_dimension(rows, "business_size"),
        # 2. Most asked client needs
        "needs_frequency": needs_frequency(rows),
        # 3. Most used channels
        "discovery_channel_frequency": channel_frequency(rows, current=False),
        "current_channel_frequency": channel_frequency(rows, current=True),
        # 4. Sales rep performance and specialization
        "rep_performance": _rep_group(rows, None),
        "rep_performance_by_sector": _rep_group(rows, "sector"),
        # 5. Pain point urgency vs. close rate
        "close_rate_by_urgency": close_rate_by_dimension(rows, "pain_point_urgency"),
        # 6. Needs complexity vs. close rate
        "close_rate_by_needs_complexity": close_rate_by_needs_complexity(rows),
        # 7. Discovery channel: volume vs. quality
        "close_rate_by_discovery_channel": close_rate_by_dimension(rows, "discovery_channel"),
        # 8. Sector × needs cross-tab
        "sector_needs_matrix": needs_matrix(rows, "sector"),
        # 9. Regulatory sensitivity vs. close rate
        "close_rate_by_regulatory_flag": close_rate_by_dimension(rows, "regulatory_flag"),
        # 10. Business size vs. needs profile
        "size_needs_matrix": needs_matrix(rows, "business_size"),
    }


async def recompute_insights() -> DashboardInsights:
    """Rebuild the full payload from current data and upsert the `latest` blob.

    `save()` is an atomic `_id`-filtered upsert, so concurrent callers can't
    create a duplicate; `_recompute_lock` additionally coalesces concurrent
    triggers so the expensive scan runs once.
    """
    async with _recompute_lock:
        rows = await load_transcript_rows()
        payload = build_payload(rows)
        payload["_meta"] = {"rows_aggregated": len(rows)}
        doc = DashboardInsights(
            id=LATEST_KEY,
            payload=payload,
            computed_at=datetime.now(timezone.utc),
        )
        await doc.save()
        return doc


async def get_cached_insights() -> DashboardInsights | None:
    return await DashboardInsights.get(LATEST_KEY)
