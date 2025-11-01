"""
Authentication routes for user registration and login
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field
from app.models.users import User
from app.auth import (
    create_access_token,
    get_password_hash,
    verify_password,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Request/Response Models
class RegisterRequest(BaseModel):
    """User registration request"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=72)
    full_name: str | None = None


class LoginRequest(BaseModel):
    """User login request"""
    username_or_email: str
    password: str


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    """User information response (without password)"""
    id: str
    email: str
    username: str
    full_name: str | None
    is_active: bool
    is_admin: bool
    created_at: datetime


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest):
    """
    Register a new user account

    Returns JWT token immediately after registration
    """
    # Check if email already exists
    existing_email = await User.find_one(User.email == request.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check if username already exists
    existing_username = await User.find_one(User.username == request.username)
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )

    # Create new user
    user = User(
        email=request.email,
        username=request.username,
        hashed_password=get_password_hash(request.password),
        full_name=request.full_name,
        is_active=True,
        is_admin=False,  # First user can be made admin manually in database
    )

    await user.insert()

    # Generate access token
    access_token = create_access_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
        }
    }


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    Login with username/email and password

    Returns JWT token on successful authentication
    """
    # Try to find user by email or username
    user = await User.find_one(
        {"$or": [
            {"email": request.username_or_email},
            {"username": request.username_or_email}
        ]}
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password"
        )

    # Verify password
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password"
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    # Update last login time
    user.last_login = datetime.utcnow()
    await user.save()

    # Generate access token
    access_token = create_access_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
        }
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current authenticated user information

    Requires: Bearer token in Authorization header
    """
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
        "is_admin": current_user.is_admin,
        "created_at": current_user.created_at,
    }
