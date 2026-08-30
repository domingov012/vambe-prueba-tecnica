from beanie import Document, Indexed
from pydantic import EmailStr
from pymongo import ASCENDING, IndexModel
from typing_extensions import Annotated


class Client(Document):
    name: str
    email: Annotated[EmailStr, Indexed()]
    phone_number: str

    class Settings:
        name = "clients"
        indexes = [
            IndexModel(
                [("name", ASCENDING), ("email", ASCENDING), ("phone_number", ASCENDING)],
                unique=True,
                name="uniq_name_email_phone",
            ),
        ]
