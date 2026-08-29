from datetime import date

from pydantic import BaseModel, EmailStr


class Client(BaseModel):
    name: str
    email: EmailStr
    phone_number: str


class MeetingTranscript(BaseModel):
    client_email: EmailStr
    meeting_date: date
    salesperson: str
    closed: bool
    transcript: str
