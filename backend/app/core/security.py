"""Security utilities for Argon2 password hashing and JWT lifecycle management."""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Dict, Optional, Tuple
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
import jwt

from app.core.config import settings

# Initialize Argon2 password hasher with enterprise parameters
ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MiB
    parallelism=1,
    hash_len=32,
)


def hash_password(plain_password: str) -> str:
    """Generate a secure Argon2id password hash."""
    return ph.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an Argon2 hash in constant time."""
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_refresh_token(raw_token: str) -> str:
    """Compute SHA-256 hash of high-entropy refresh token for safe storage."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def create_access_token(
    user_id: UUID,
    extra_claims: Optional[Dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a cryptographically signed, short-lived JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate claims of an incoming JWT access token.

    Raises:
        jwt.PyJWTError: If signature, format, or expiration checks fail.
        ValueError: If essential claims or token type are invalid.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat", "jti", "type"]},
    )

    if payload.get("type") != "access":
        raise ValueError("Invalid token type. Access token expected.")

    return payload


def create_refresh_token(
    expires_delta: Optional[timedelta] = None,
) -> Tuple[str, str, datetime]:
    """Generate a secure opaque refresh token.

    Returns:
        Tuple of (raw_token, token_hash, expires_at_utc)
    """
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw_token)
    expires_at = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    return raw_token, token_hash, expires_at
