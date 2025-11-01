"""
Rate limiting utilities with IP whitelisting support
"""
import os
from functools import wraps
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request


def get_remote_address_with_whitelist(request: Request) -> str:
    """
    Custom key function that exempts whitelisted IPs from rate limiting.
    Whitelisted IPs will all get the same key, effectively removing limits.
    """
    # Get whitelisted IPs from environment variable
    whitelist_str = os.getenv("RATE_LIMIT_WHITELIST", "")
    whitelisted_ips = [ip.strip() for ip in whitelist_str.split(",") if ip.strip()]

    # Get the actual client IP
    client_ip = get_remote_address(request)

    # If IP is whitelisted, return a special key that has no limits
    if client_ip in whitelisted_ips:
        return f"whitelisted:{client_ip}"

    # Otherwise, return the normal IP for rate limiting
    return client_ip


def create_limiter() -> Limiter:
    """Create and configure the rate limiter"""
    return Limiter(key_func=get_remote_address_with_whitelist)


# Rate limit presets for different endpoint types
RATE_LIMITS = {
    "expensive": "30/hour",  # For AI analysis endpoints (POST /incidents)
    "write": "100/hour",  # For PUT/DELETE operations
    "read": "300/minute",  # For GET operations
    "logs": "60/minute",  # For audit log access
}
