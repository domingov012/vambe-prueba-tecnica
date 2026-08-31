"""Wipe every app collection on the configured MongoDB (MONGO_URI / MONGO_DB_NAME
from .env). For a clean slate before re-ingesting.

    python scripts/reset_db.py           # prompts for confirmation
    python scripts/reset_db.py --yes     # skip the prompt
"""

import argparse
import asyncio
import sys

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import get_settings

COLLECTIONS = [
    "clients",
    "meeting_transcripts",
    "enhanced_transcripts",
    "enrichment_jobs",
    "dashboard_insights",
]


async def main(assume_yes: bool) -> None:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]

    counts = {name: await db[name].estimated_document_count() for name in COLLECTIONS}
    print(f"Target: {settings.mongo_db_name} @ {settings.mongo_uri.split('@')[-1]}")
    for name, count in counts.items():
        print(f"  {name}: {count}")

    if not assume_yes:
        if input("\nDelete all of the above? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return

    for name in COLLECTIONS:
        result = await db[name].delete_many({})
        print(f"  {name}: deleted {result.deleted_count}")

    client.close()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.yes))
    except KeyboardInterrupt:
        sys.exit(1)
