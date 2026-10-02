from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import Field, EmailStr


class User(Document):
    """User account for authentication and authorization - Compatible with NextAuth"""

    email: EmailStr = Field(..., unique=True, index=True)
    name: Optional[str] = None  # NextAuth uses 'name' instead of 'full_name'
    hashedPassword: str = Field(
        ..., description="Bcrypt hashed password"
    )  # NextAuth uses camelCase
    role: str = Field(default="user")  # NextAuth uses 'role' instead of is_admin
    can_validate: bool = Field(
        default=False,
        description="Grants access to the protected validation workspace",
    )
    username: Optional[str] = Field(
        None, unique=True, index=True
    )  # Optional for NextAuth compatibility
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None

    class Settings:
        name = "users"

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "johndoe",
                "name": "John Doe",
                "role": "user",
                "can_validate": False,
                "is_active": True,
            }
        }
