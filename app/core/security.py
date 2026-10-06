"""
Password hashing (bcrypt) and JWT issuing/verification.

Every token now carries a unique 'jti' (JWT ID) claim, which is what
makes refresh-token rotation and reset-token single-use enforcement
possible — app/services/auth_service.py checks jti against the
revoked_tokens table (see app/models/revoked_token.py) before honoring
a refresh or reset token. Access tokens are short-lived enough (default
30 min) that they aren't individually revocable — logging out doesn't
retroactively kill an in-flight access token, only the refresh token
that would have renewed it.
"""

import bcrypt
import jwt
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, NamedTuple

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


class DecodedToken(NamedTuple):
    subject: str  # user email
    jti: str
    expires_at: datetime


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> tuple[str, str, datetime]:
    """Returns (encoded_jwt, jti, expires_at) — callers that need to track
    the token (refresh, reset) use the jti/expires_at; access tokens
    discard them."""
    jti = uuid.uuid4().hex
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": subject, "exp": expire, "type": token_type, "jti": jti}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti, expire


def create_access_token(user_email: str) -> str:
    token, _, _ = _create_token(user_email, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access")
    return token


def create_refresh_token(user_email: str) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at) — the jti/expiry get stored if this
    token is ever revoked (rotation or logout)."""
    return _create_token(user_email, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def create_reset_token(user_email: str) -> tuple[str, str, datetime]:
    return _create_token(user_email, timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES), "reset")


def decode_token(token: str, expected_type: Literal["access", "refresh", "reset"] = "access") -> DecodedToken:
    """Raises jwt.PyJWTError subclasses on failure — callers catch these
    and turn them into HTTP 401s."""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected a {expected_type} token.")

    if not payload.get("sub") or not payload.get("jti") or not payload.get("exp"):
        raise jwt.InvalidTokenError("Token is missing required claims.")

    return DecodedToken(
        subject=payload["sub"],
        jti=payload["jti"],
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    )
