"""
Test script to decode NextAuth tokens
Run this with: python test_auth.py "YOUR_TOKEN_HERE"
"""

import sys
import os
import json
from dotenv import load_dotenv

load_dotenv()


def decode_nextauth_token(token: str):
    """Decode a NextAuth JWE token using hkdf library"""
    from hkdf import Hkdf
    from jose.jwe import decrypt

    secret = os.getenv("NEXTAUTH_SECRET")
    if not secret:
        print("ERROR: NEXTAUTH_SECRET not set in environment")
        return None

    try:
        print("\n Decoding token with HKDF + jose.jwe...")

        # Derive encryption key using HKDF (same as NextAuth)
        secret_bytes = bytes(secret, "utf-8")
        encryption_key = Hkdf("", secret_bytes).expand(
            b"NextAuth.js Generated Encryption Key", 32
        )

        # Decrypt JWE token
        decrypted = decrypt(token, encryption_key)

        if decrypted:
            payload = json.loads(bytes.decode(decrypted, "utf-8"))
            print(" Successfully decoded token!")
            return payload
        else:
            print(" Decryption returned None")
            return None

    except Exception as e:
        print(f" Failed to decode token: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_auth.py <token>")
        sys.exit(1)

    token = sys.argv[1]
    print(f"Attempting to decode token...")
    print(f"Token starts with: {token[:50]}...")
    print(f"NEXTAUTH_SECRET: {os.getenv('NEXTAUTH_SECRET')[:10]}...")  # type: ignore

    payload = decode_nextauth_token(token)

    if payload:
        print("\n Successfully decoded token!")
        print(f"\nPayload:")
        print(json.dumps(payload, indent=2))
        print(f"\nUser ID (sub): {payload.get('sub')}")
        print(f"Email: {payload.get('email')}")
    else:
        print("\n Failed to decode token")
