"""Persistence for ingested rows.

Client dedup (match on name + email + phone_number) lives here and is mirrored by
the compound unique index on `Client`. Both helpers are bulk: one query + one
`insert_many`, never a round trip per row — a 10k-row file against a remote
cluster made the old per-row `find_one`/`insert` loop unusable.

Called from the enrichment job *after* the LLM step, so we only ever write
Client/MeetingTranscript rows for transcripts that were actually classified.
"""

from beanie import PydanticObjectId
from beanie.operators import In
from pymongo.asynchronous.client_session import AsyncClientSession

from app.ingestion.mappers import ClientKey, ParsedRow
from app.models import Client, MeetingTranscript


async def get_or_create_clients(
    rows: list[ParsedRow], *, session: AsyncClientSession | None = None
) -> dict[ClientKey, Client]:
    """Return a `client_key -> Client` map for every row, creating the ones that
    don't exist yet. Two DB calls total regardless of row count."""
    wanted: dict[ClientKey, ParsedRow] = {r.client_key: r for r in rows}
    if not wanted:
        return {}

    by_key: dict[ClientKey, Client] = {}
    emails = list({key[1] for key in wanted})
    for client in await Client.find(In(Client.email, emails), session=session).to_list():
        by_key[(client.name, client.email, client.phone_number)] = client

    to_create = [
        Client(
            id=PydanticObjectId(),
            name=row.name,
            email=row.email,
            phone_number=row.phone_number,
        )
        for key, row in wanted.items()
        if key not in by_key
    ]
    if to_create:
        await Client.insert_many(to_create, session=session)
        for client in to_create:
            by_key[(client.name, client.email, client.phone_number)] = client

    return by_key


async def insert_meetings(
    rows: list[tuple[str, ParsedRow]],
    clients: dict[ClientKey, Client],
    *,
    session: AsyncClientSession | None = None,
) -> dict[str, MeetingTranscript]:
    """Bulk-insert one MeetingTranscript per (enrichment_key, row) pair and return
    them keyed by enrichment_key so the caller can attach EnhancedTranscripts."""
    by_key: dict[str, MeetingTranscript] = {}
    for key, row in rows:
        by_key[key] = MeetingTranscript(
            id=PydanticObjectId(),
            client=clients[row.client_key],
            meeting_date=row.meeting_date,
            salesperson=row.salesperson,
            closed=row.closed,
            transcript=row.transcript,
        )
    if by_key:
        await MeetingTranscript.insert_many(list(by_key.values()), session=session)
    return by_key
