import jwt
from typing import Optional
from fastapi import Request


def validate_token(token: str) -> Optional[str]:
    """Validate JWT token and return user_id"""
    try:
        payload = jwt.decode(token, "your-secret", algorithms=["HS256"])
        return payload.get("user_id")
    except jwt.InvalidTokenError:
        return None


async def extract_user_from_request(request: Request) -> Optional[str]:
    """Extract user from request headers or query params"""
    # From Authorization header
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        user_id = validate_token(token)
        if user_id:
            return user_id

    # From query params (if needed for your use case)
    return request.query_params.get("user_id")
