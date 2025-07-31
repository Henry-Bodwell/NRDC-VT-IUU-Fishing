from beanie import Document
from pydantic import Field


class User(Document):
    name: str = Field(...)
    email: str = Field(...)
    is_active: bool = Field(...)
    password: str = Field(..., description="Hashed Password")

    class Settings:
        name = "users"
