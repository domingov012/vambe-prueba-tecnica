from beanie import PydanticObjectId
from pydantic import BaseModel

from app.ingestion.csv_loader import parse_csv
from app.ingestion.mappers import row_to_client_fields, row_to_meeting
from app.models import Client, MeetingTranscript


class IngestionSummary(BaseModel):
    rows_processed: int
    clients_created: int
    meetings_created: int


class IngestionResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    summary: IngestionSummary
    meetings: list[MeetingTranscript]


ClientKey = tuple[str, str, str]


def _client_key(fields: dict[str, str]) -> ClientKey:
    return (fields["name"], fields["email"], fields["phone_number"])


async def _get_or_create_client(
    row: dict[str, str], cache: dict[ClientKey, Client]
) -> tuple[Client, bool]:
    fields = row_to_client_fields(row)
    key = _client_key(fields)

    if key in cache:
        return cache[key], False

    existing = await Client.find_one(
        Client.name == fields["name"],
        Client.email == fields["email"],
        Client.phone_number == fields["phone_number"],
    )
    if existing is not None:
        cache[key] = existing
        return existing, False

    new_client = Client(**fields)
    await new_client.insert()
    cache[key] = new_client
    return new_client, True


async def ingest_csv(raw_bytes: bytes) -> IngestionResult:
    cache: dict[ClientKey, Client] = {}
    meetings: list[MeetingTranscript] = []
    rows_processed = 0
    clients_created = 0

    for row in parse_csv(raw_bytes):
        rows_processed += 1
        client, created = await _get_or_create_client(row, cache)
        if created:
            clients_created += 1
        meetings.append(row_to_meeting(row, client))

    if meetings:
        result = await MeetingTranscript.insert_many(meetings)
        # insert_many() doesn't populate ids on the passed-in documents — set them
        # from the result so callers (e.g. enrichment) can reference these meetings.
        for meeting, inserted_id in zip(meetings, result.inserted_ids):
            meeting.id = PydanticObjectId(inserted_id)

    return IngestionResult(
        summary=IngestionSummary(
            rows_processed=rows_processed,
            clients_created=clients_created,
            meetings_created=len(meetings),
        ),
        meetings=meetings,
    )
