"""Compute the full dashboard payload — every chart dataset in one object.

Design (per `aggregations.md`): a single precomputed blob, not one endpoint per
chart. `recompute_insights()` builds the whole payload and stores it as one
`DashboardInsights` document keyed `latest`; `GET /api/dashboard/insights` just
reads that blob back. Recompute is triggered whenever an enrichment job finishes
(see `app/llm/jobs.py`) and via `POST /api/dashboard/insights/recompute`.

Three generic aggregation functions cover most of the payload:
  * `close_rate_by_dimension`  — single-select fields (sector, size, urgency, …)
  * `close_rate_by_membership` — multi-select fields (client_needs, current_channels)
  * `needs_matrix`             — a single-select × needs cross-tab

The distinction between the first two is not cosmetic: single-select groups
partition the population (`sum(total) == len(rows)`), multi-select groups overlap
(a meeting listing four needs lands in four of them). Anything derived from the
group totals — a volume-weighted baseline above all — is only valid for the
first kind, which is why the membership datasets carry `lift` precomputed.
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


def population_rate(rows: list[TranscriptRow]) -> float:
    """The dataset's own close rate — the only baseline valid for every chart.

    Charts over single-select dimensions can recover this by summing their group
    totals; charts over overlapping (multi-select) groups cannot, so it is
    computed once here and published in `_meta`.
    """
    return _round_rate(sum(1 for row in rows if row.closed), len(rows))


def min_sample(population: int) -> int:
    """Smallest group we're willing to draw a conclusion from.

    A 100% close rate over two meetings is noise, and ranking by rate puts
    exactly that noise on top. Scales with the dataset rather than hardcoding a
    threshold that means opposite things at 100 and 10 000 rows: 5 up to 500
    rows, 1% of the population above it.
    """
    return max(5, population // 100)


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


def close_rate_by_membership(rows: list[TranscriptRow], field: str) -> list[dict]:
    """Close rate per value of a **multi-select** field (`client_needs`,
    `current_channels`): "do clients who already run WhatsApp convert better?"

    Every meeting is counted once per value it lists, so the groups overlap and
    `sum(total)` exceeds `len(rows)`. Two consequences the callers depend on:

    * The volume-weighted mean of these groups is *not* the population close
      rate — it over-weights meetings that listed many values. Each row therefore
      carries `lift` (its close rate minus the population's, as a fraction),
      computed here against the real denominator so no caller has to reconstruct
      a baseline it cannot see.
    * The comparison is associational and confounded — `whatsapp` may lead
      because retail leads, not because of the channel. The UI says so; this
      function only reports the split.
    """
    base = population_rate(rows)
    totals: Counter = Counter()
    closed: Counter = Counter()
    for row in rows:
        for value in getattr(row, field):
            totals[value] += 1
            if row.closed:
                closed[value] += 1

    result = [
        {
            "value": value,
            "total": total,
            "closed": closed[value],
            "close_rate": _round_rate(closed[value], total),
            "lift": round(_round_rate(closed[value], total) - base, 4),
        }
        for value, total in totals.items()
    ]
    result.sort(key=lambda r: (-r["close_rate"], -r["total"], r["value"]))
    return result


# Every classified field that partitions the population, plus the two that don't.
# `salesperson` is deliberately absent: it is a person rather than an attribute
# of the lead, it already has its own section, and ranking reps inside a board
# titled "what predicts a close" invites reading a book of business as a skill
# gap. The rep section makes that comparison properly, against each segment.
_SINGLE_SELECT_FIELDS = (
    "sector",
    "business_model",
    "business_size",
    "inquiry_volume",
    "discovery_channel",
    "regulatory_flag",
    "pain_point_urgency",
)
_MULTI_SELECT_FIELDS = ("client_needs", "current_channels")


def signal_board(rows: list[TranscriptRow]) -> list[dict]:
    """Every attribute value in the dataset, ranked by how far its close rate
    sits from the population's.

    Re-derives from the same row list rather than reading the other datasets, so
    it costs no extra scan and can't drift from them. Groups below `min_sample`
    are dropped outright — this chart is a ranking, and an ungated ranking is
    just a list of the smallest groups.
    """
    base = population_rate(rows)
    floor = min_sample(len(rows))

    entries: list[dict] = []
    for field in _SINGLE_SELECT_FIELDS:
        for row in close_rate_by_dimension(rows, field):
            entries.append({"dimension": field, "value": row["group"], **row})
    for field in _MULTI_SELECT_FIELDS:
        entries.extend({"dimension": field, **row} for row in close_rate_by_membership(rows, field))

    board = [
        {
            "dimension": entry["dimension"],
            "value": entry["value"],
            "total": entry["total"],
            "closed": entry["closed"],
            "close_rate": entry["close_rate"],
            "lift": round(entry["close_rate"] - base, 4),
        }
        for entry in entries
        if entry["total"] >= floor
    ]
    # Both tails are the story: the segments to chase and the ones bleeding time.
    board.sort(key=lambda r: (-abs(r["lift"]), -r["total"], r["dimension"], r["value"]))
    return board


def close_rate_by_month(rows: list[TranscriptRow], *, per_rep: bool = False) -> list[dict]:
    """Monthly conversion trend, oldest first — for the whole team, or split per
    rep when `per_rep` is set (same rows, one series each).

    Rows with no `meeting_date` (enriched before the field existed and not yet
    backfilled) are skipped here and counted into `_meta.rows_without_date` — a
    half-backfilled collection should show as a gap in the metadata, not as a
    silently short timeline.

    Months a rep took no meetings in are *absent*, not zero: a rep who sold
    nothing in March and a rep who wasn't working in March are different claims,
    and the chart breaks its line rather than drawing a plunge to 0%.
    """
    totals: Counter = Counter()
    closed: Counter = Counter()
    for row in rows:
        if row.meeting_date is None:
            continue
        month = row.meeting_date.strftime("%Y-%m")
        key = (row.salesperson, month) if per_rep else month
        totals[key] += 1
        if row.closed:
            closed[key] += 1

    result = [
        {
            **({"rep": key[0], "month": key[1]} if per_rep else {"month": key}),
            "total": total,
            "closed": closed[key],
            "close_rate": _round_rate(closed[key], total),
        }
        for key, total in totals.items()
    ]
    result.sort(key=lambda r: (r.get("rep", ""), r["month"]))
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
    """Close rate per rep, optionally split by one single-select segment.

    When `extra_key` is given, each row also carries the segment's own close rate
    across all reps (`segment_close_rate`) and the rep's distance from it
    (`lift`). Rep-vs-segment is the comparison that means something: a 30% rate
    is strong in a segment that closes at 18% and weak in one that closes at 55%,
    and the rep who owns the hard segment shouldn't read as the worst on the
    team. Computing it here keeps the dataset self-describing — the client would
    otherwise have to join this against `close_rate_by_<segment>`.
    """
    totals: Counter = Counter()
    closed: Counter = Counter()
    segment_totals: Counter = Counter()
    segment_closed: Counter = Counter()
    for row in rows:
        key = row.salesperson if extra_key is None else (row.salesperson, getattr(row, extra_key))
        totals[key] += 1
        if row.closed:
            closed[key] += 1
        if extra_key is not None:
            segment = getattr(row, extra_key)
            segment_totals[segment] += 1
            if row.closed:
                segment_closed[segment] += 1

    result = []
    for key, total in totals.items():
        entry = {"rep": key} if extra_key is None else {"rep": key[0], extra_key: key[1]}
        rate = _round_rate(closed[key], total)
        entry.update(total=total, closed=closed[key], close_rate=rate)
        if extra_key is not None:
            segment_rate = _round_rate(segment_closed[key[1]], segment_totals[key[1]])
            entry.update(segment_close_rate=segment_rate, lift=round(rate - segment_rate, 4))
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
        "rep_performance_by_business_model": _rep_group(rows, "business_model"),
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
        # 11. Inquiry volume vs. close rate — the closest thing the taxonomy has
        #     to a deal-size proxy, and the cheapest ICP signal in the set.
        "close_rate_by_inquiry_volume": close_rate_by_dimension(rows, "inquiry_volume"),
        # 12. Do the needs a client raises predict the close? (overlapping groups)
        "close_rate_by_need": close_rate_by_membership(rows, "client_needs"),
        # 13. Same question for the channels they already operate.
        "close_rate_by_current_channel": close_rate_by_membership(rows, "current_channels"),
        # 14. Everything above, ranked by distance from the house average.
        "signal_board": signal_board(rows),
        # 15. Conversion over time — needs `meeting_date` on the enhanced row.
        "close_rate_by_month": close_rate_by_month(rows),
        # 16. The same trend per rep, for the timeline's rep selector.
        "rep_performance_by_month": close_rate_by_month(rows, per_rep=True),
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
        payload["_meta"] = {
            "rows_aggregated": len(rows),
            # Published so every chart labels the same baseline and the same
            # small-sample gate, instead of each one re-deriving its own.
            "base_rate": population_rate(rows),
            "min_sample": min_sample(len(rows)),
            "rows_without_date": sum(1 for row in rows if row.meeting_date is None),
        }
        doc = DashboardInsights(
            id=LATEST_KEY,
            payload=payload,
            computed_at=datetime.now(timezone.utc),
        )
        await doc.save()
        return doc


async def get_cached_insights() -> DashboardInsights | None:
    return await DashboardInsights.get(LATEST_KEY)
