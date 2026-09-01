"""Live cross-tab of two client-describing attributes — the one dashboard view
that can't be precomputed.

The insights blob (`app/aggregation/insights.py`) bakes every chart it serves.
This one can't be baked: the user picks any 2 of 5 client dimensions for the
axes and either measure (frequency or close rate), which is far more
combinations than belong in a cached document. So it runs on the request path
instead, over the same `TranscriptRow` scan the blob uses — cached in-process
between enrichment jobs by `get_transcript_rows()`.

Only attributes that describe the **client** are offered: sector, business
model, size, inquiry volume and the (multi-select) client needs. `salesperson`
is a person not a lead attribute and has its own section; the channel/urgency/
regulatory cuts already live in the precomputed sections.

`client_needs` is multi-select, so a cell crossing it counts one meeting in
several cells — `sum(total)` then exceeds the population and no marginal
partitions it. The response flags this as `overlapping` and the UI says so; the
per-cell close rate is still a valid `closed / total` within the cell.
"""

from __future__ import annotations

from collections import Counter

from app.aggregation.insights import min_sample, population_rate
from app.aggregation.rows import TranscriptRow

# name -> "single" (partitions the population) | "multi" (overlapping groups)
_DIMENSIONS: dict[str, str] = {
    "sector": "single",
    "business_model": "single",
    "business_size": "single",
    "inquiry_volume": "single",
    "client_needs": "multi",
}

# Ordinal domains render in their own sequence; everything else sorts by volume.
_ORDINAL_ORDER: dict[str, list[str]] = {
    "business_size": ["solo_micro", "small", "medium", "large", "unclear"],
    "inquiry_volume": ["low", "medium", "high", "very_high", "unclear"],
}


def available_dimensions() -> list[str]:
    return list(_DIMENSIONS)


def _values(row: TranscriptRow, dim: str) -> tuple[str, ...]:
    value = getattr(row, dim)
    return tuple(value) if _DIMENSIONS[dim] == "multi" else (value,)


def _axis_values(dim: str, present: set[str], volume: Counter) -> list[str]:
    if dim in _ORDINAL_ORDER:
        return [v for v in _ORDINAL_ORDER[dim] if v in present]
    return sorted(present, key=lambda v: (-volume[v], v))


def compute_crosstab(rows: list[TranscriptRow], row_dim: str, col_dim: str) -> dict:
    """Cross `row_dim` × `col_dim` over `rows`, one cell per value pair.

    Each cell carries `total`, `closed` and `close_rate` so the client can render
    either measure from one response without a refetch.
    """
    totals: Counter = Counter()
    closed: Counter = Counter()
    row_volume: Counter = Counter()
    col_volume: Counter = Counter()

    for row in rows:
        row_vals = _values(row, row_dim)
        col_vals = _values(row, col_dim)
        for rv in row_vals:
            row_volume[rv] += 1
            for cv in col_vals:
                col_volume[cv] += 1
                totals[(rv, cv)] += 1
                if row.closed:
                    closed[(rv, cv)] += 1

    cells = [
        {
            "row": rv,
            "col": cv,
            "total": total,
            "closed": closed[(rv, cv)],
            "close_rate": round(closed[(rv, cv)] / total, 4),
        }
        for (rv, cv), total in totals.items()
    ]
    cells.sort(key=lambda c: (c["row"], -c["total"], c["col"]))

    return {
        "row_dim": row_dim,
        "col_dim": col_dim,
        "row_values": _axis_values(row_dim, set(row_volume), row_volume),
        "col_values": _axis_values(col_dim, set(col_volume), col_volume),
        "cells": cells,
        "overlapping": "multi" in (_DIMENSIONS[row_dim], _DIMENSIONS[col_dim]),
        "_meta": {
            "rows_aggregated": len(rows),
            "base_rate": population_rate(rows),
            "min_sample": min_sample(len(rows)),
        },
    }
