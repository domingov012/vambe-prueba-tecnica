"""Fill `meeting_date` on `enhanced_transcripts` rows enriched before that field
existed, by copying it from the `MeetingTranscript` each one links to.

The field is denormalized onto the enhanced row so the dashboard aggregation
stays a single-collection scan (see `app/aggregation/rows.py`); rows written
before the field was added simply lack it, and the monthly conversion chart
skips them. This script closes that gap.

Idempotent: it only ever looks at documents where the field is missing, so a
re-run after a partial pass (or after a fresh enrichment job) is a no-op.

Run from the repo root as a module, so `app` is importable:

    python -m scripts.backfill_enhanced_meeting_date            # backfill + recompute
    python -m scripts.backfill_enhanced_meeting_date --dry-run  # report only
    python -m scripts.backfill_enhanced_meeting_date --no-recompute
"""

import argparse
import asyncio
import sys

from pymongo import UpdateOne

from app.aggregation.insights import recompute_insights
from app.config import get_settings
from app.db.session import close_db, get_client, init_db

BATCH_SIZE = 500


async def backfill(dry_run: bool) -> tuple[int, int]:
    """Returns (updated, orphaned) — orphaned means the linked meeting is gone,
    which the enrichment transaction is supposed to make impossible."""
    db = get_client()[get_settings().mongo_db_name]
    enhanced = db["enhanced_transcripts"]
    meetings = db["meeting_transcripts"]

    updated = 0
    orphaned = 0
    batch: list[dict] = []

    cursor = enhanced.find({"meeting_date": {"$exists": False}}, {"meeting": 1})
    async for doc in cursor:
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            done, missing = await _flush(batch, meetings, enhanced, dry_run)
            updated += done
            orphaned += missing
            batch = []

    if batch:
        done, missing = await _flush(batch, meetings, enhanced, dry_run)
        updated += done
        orphaned += missing

    return updated, orphaned


async def _flush(batch, meetings, enhanced, dry_run: bool) -> tuple[int, int]:
    # `meeting` is a Link, stored as a DBRef — the meeting's ObjectId is `.id`.
    by_meeting_id = {doc["meeting"].id: doc["_id"] for doc in batch if doc.get("meeting")}

    dates = {}
    async for meeting in meetings.find(
        {"_id": {"$in": list(by_meeting_id)}}, {"meeting_date": 1}
    ):
        dates[meeting["_id"]] = meeting["meeting_date"]

    writes = [
        # Stored as the midnight datetime beanie writes for a `date`, so copying
        # the raw value across keeps both collections byte-identical.
        UpdateOne({"_id": key}, {"$set": {"meeting_date": dates[meeting_id]}})
        for meeting_id, key in by_meeting_id.items()
        if meeting_id in dates
    ]
    orphaned = len(batch) - len(writes)

    if writes and not dry_run:
        result = await enhanced.bulk_write(writes, ordered=False)
        return result.modified_count, orphaned
    return len(writes), orphaned


async def main(dry_run: bool, recompute: bool) -> None:
    await init_db()
    try:
        settings = get_settings()
        print(f"Target: {settings.mongo_db_name} @ {settings.mongo_uri.split('@')[-1]}")

        updated, orphaned = await backfill(dry_run)
        verb = "would update" if dry_run else "updated"
        print(f"  enhanced_transcripts: {verb} {updated}")
        if orphaned:
            print(f"  WARNING: {orphaned} enhanced rows have no reachable meeting")

        if dry_run:
            print("Dry run — nothing written.")
            return

        remaining = await get_client()[settings.mongo_db_name]["enhanced_transcripts"].count_documents(
            {"meeting_date": {"$exists": False}}
        )
        print(f"  still missing meeting_date: {remaining}")

        if recompute:
            doc = await recompute_insights()
            meta = doc.payload.get("_meta", {})
            print(f"  insights recomputed: {meta.get('rows_aggregated')} rows aggregated")
    finally:
        await close_db()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument(
        "--no-recompute",
        action="store_true",
        help="skip rebuilding the cached dashboard payload afterwards",
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(args.dry_run, not args.no_recompute))
    except KeyboardInterrupt:
        sys.exit(1)
