from beanie import Document, Indexed
from pydantic import EmailStr
from typing_extensions import Annotated


class Client(Document):
    name: str
    email: Annotated[EmailStr, Indexed(unique=True)]
    phone_number: str

    class Settings:
        name = "clients"
