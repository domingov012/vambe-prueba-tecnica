from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response

from app.aggregation.crosstab import available_dimensions, compute_crosstab
from app.aggregation.insights import get_cached_insights, recompute_insights
from app.aggregation.rows import get_transcript_rows

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _as_utc(dt: datetime) -> datetime:
    """Mongo returns datetimes naive; they were stored as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _iso_z(dt: datetime) -> str:
    return _as_utc(dt).isoformat().replace("+00:00", "Z")


@router.get("/insights")
async def get_insights(request: Request, response: Response):
    """Return the precomputed payload of all 10 chart datasets.

    Reads the cached blob directly — no live aggregation in the request path.
    The blob is (re)built whenever an enrichment job finishes; if none has yet,
    there is nothing to show.

    Sends an `ETag` derived from `computed_at`; a client that already holds the
    current payload gets a 304 (pairs with the frontend's skeleton-load — the
    single fetch is cheap to revalidate on every dashboard mount).
    """
    doc = await get_cached_insights()
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail="No insights computed yet — process at least one transcript batch first.",
        )

    etag = f'"{_as_utc(doc.computed_at).timestamp():.6f}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return {**doc.payload, "computed_at": _iso_z(doc.computed_at)}


@router.get("/crosstab")
async def crosstab(row: str, col: str) -> dict:
    """Cross two client attributes on demand — the one dashboard view too
    combinatorial to precompute (see `app/aggregation/crosstab.py`).

    `row` / `col` are each one of `available_dimensions()` and must differ.
    Reads the in-process row cache (refreshed after every enrichment job), so an
    interactive pivot costs no Mongo scan. 404s until a transcript is enriched.
    """
    dims = available_dimensions()
    if row not in dims or col not in dims:
        raise HTTPException(status_code=422, detail=f"row/col must each be one of {dims}")
    if row == col:
        raise HTTPException(status_code=422, detail="row and col must be different dimensions")

    rows = await get_transcript_rows()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No enriched transcripts yet — process at least one transcript batch first.",
        )
    return compute_crosstab(rows, row, col)


@router.post("/insights/recompute")
async def recompute() -> dict:
    """Force a rebuild of the cached payload (e.g. after re-running classification)."""
    doc = await recompute_insights()
    return {
        "status": "ok",
        "computed_at": _iso_z(doc.computed_at),
        "rows_aggregated": doc.payload.get("_meta", {}).get("rows_aggregated"),
    }


@router.get("/insights/status")
async def insights_status() -> dict:
    """Lightweight staleness check — when was the cached payload last built."""
    doc = await get_cached_insights()
    if doc is None:
        return {"computed_at": None, "meta": None, "stale_seconds": None}

    return {
        "computed_at": _iso_z(doc.computed_at),
        "meta": doc.payload.get("_meta"),
        "stale_seconds": (datetime.now(timezone.utc) - _as_utc(doc.computed_at)).total_seconds(),
    }
