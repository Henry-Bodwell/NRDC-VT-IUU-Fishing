from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import Field, EmailStr


class User(Document):
    """User account for authentication and authorization"""

    email: EmailStr = Field(..., unique=True, index=True)
    username: str = Field(..., unique=True, index=True)
    hashed_password: str = Field(..., description="Bcrypt hashed password")
    full_name: Optional[str] = None
    is_active: bool = Field(default=True)
    is_admin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None

    class Settings:
        name = "users"

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "johndoe",
                "full_name": "John Doe",
                "is_active": True,
                "is_admin": False
            }
        }
