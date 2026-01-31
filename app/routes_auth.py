"""
Authentication routes - NextAuth handles login/register
FastAPI provides user info endpoints for authenticated sessions
"""

from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.models.users import User
from app.auth import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Response Models
class UserResponse(BaseModel):
    """User information response (without password)"""

    id: str
    email: str
    username: str | None
    name: str | None
    role: str
    is_active: bool
    created_at: datetime


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current authenticated user information

    Requires: NextAuth JWT token in Authorization header (Bearer token)
    The token must be signed with the same secret as NEXTAUTH_SECRET
    """
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "name": current_user.name,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
    }
