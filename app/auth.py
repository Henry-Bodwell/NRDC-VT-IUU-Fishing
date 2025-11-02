"""
Authentication utilities for NextAuth JWT token validation
"""

import os
import json
import logging
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.users import User

logger = logging.getLogger(__name__)

# NextAuth secret from environment
NEXTAUTH_SECRET = os.getenv("NEXTAUTH_SECRET")
if not NEXTAUTH_SECRET:
    raise ValueError("NEXTAUTH_SECRET environment variable must be set")

# HTTP Bearer token security
security = HTTPBearer()


def decode_nextauth_token(token: str) -> dict:
    """
    Decode NextAuth session token (JWE encrypted token).

    Uses HKDF key derivation with jose.jwe for decryption.

    Args:
        token: The JWE token string from the session cookie or Authorization header

    Returns:
        dict: The decoded token payload containing 'sub' (user ID), 'email', etc.

    Raises:
        ValueError: If token cannot be decrypted or is invalid
    """
    try:
        from hkdf import Hkdf
        from jose.jwe import decrypt

        # Derive encryption key using HKDF (same as NextAuth)
        secret_bytes = bytes(NEXTAUTH_SECRET, "utf-8")  # type: ignore
        encryption_key = Hkdf("", secret_bytes).expand(
            b"NextAuth.js Generated Encryption Key", 32
        )

        # Decrypt JWE token
        decrypted = decrypt(token, encryption_key)

        if decrypted:
            payload = json.loads(bytes.decode(decrypted, "utf-8"))
            logger.debug(
                f"Successfully decoded NextAuth token for user: {payload.get('sub')}"
            )
            return payload
        else:
            raise ValueError("Decryption returned None")

    except Exception as e:
        logger.error(f"Failed to decode NextAuth token: {e}")
        raise ValueError(f"Invalid token: {e}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Dependency to get the current authenticated user from NextAuth token.

    Extracts the user ID from the token's 'sub' claim and looks up the user
    in the database.

    Args:
        credentials: HTTP Bearer credentials containing the token

    Returns:
        User: The authenticated user object

    Raises:
        HTTPException: 401 if token is invalid or user not found
        HTTPException: 403 if user account is inactive
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Decode the NextAuth token
        payload = decode_nextauth_token(credentials.credentials)

        # Extract user ID from 'sub' claim
        user_id = payload.get("sub")
        if not user_id or not isinstance(user_id, str):
            logger.warning("Token missing 'sub' claim or invalid type")
            raise credentials_exception

    except ValueError as e:
        logger.warning(f"Token validation failed: {e}")
        raise credentials_exception

    # Look up user in database
    user = await User.get(user_id)
    if user is None:
        logger.warning(f"User not found: {user_id}")
        raise credentials_exception

    # Check if user is active
    if not user.is_active:
        logger.warning(f"Inactive user attempted access: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to ensure user is active (explicit version of get_current_user).
    """
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to ensure user has admin privileges.

    Raises:
        HTTPException: 403 if user is not an admin
    """
    if current_user.role != "admin":
        logger.warning(f"Non-admin user attempted admin access: {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )
    return current_user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> Optional[User]:
    """
    Dependency to optionally get the current user (doesn't require auth).

    Returns None if no valid token is provided instead of raising an exception.
    Useful for endpoints that have different behavior for authenticated vs
    unauthenticated users.

    Args:
        credentials: Optional HTTP Bearer credentials

    Returns:
        User or None: The authenticated user if valid token provided, else None
    """
    if not credentials:
        return None

    try:
        payload = decode_nextauth_token(credentials.credentials)
        user_id = payload.get("sub")

        if not user_id or not isinstance(user_id, str):
            return None

        user = await User.get(user_id)
        if user and user.is_active:
            return user

    except ValueError:
        # Invalid token, return None instead of raising
        pass

    return None
