from datetime import date

from beanie import Document, Link

from app.models.client import Client


class MeetingTranscript(Document):
    client: Link[Client]
    meeting_date: date
    salesperson: str
    closed: bool
    transcript: str

    class Settings:
        name = "meeting_transcripts"
