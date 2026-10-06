"""
Auth business logic, kept separate from app/api/auth.py so the HTTP layer
stays thin. Routes call these functions and translate results/exceptions
into HTTP responses.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.models.revoked_token import RevokedToken
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
)
from app.schemas.auth import RegisterRequest
import jwt

logger = logging.getLogger("auth_service")


class EmailAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


def register_user(db: Session, payload: RegisterRequest) -> User:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise EmailAlreadyExistsError()

    user = User(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EmailAlreadyExistsError()
    db.refresh(user)

    logger.info("New user registered: user_id=%s", user.id)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not verify_password(password, user.password_hash):
        logger.info("Failed login attempt for email=%s", email)
        raise InvalidCredentialsError()

    if not user.is_active:
        raise InvalidCredentialsError()

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("Successful login: user_id=%s", user.id)
    return user


def issue_token_pair(db: Session, user: User) -> tuple[str, str]:
    """Issues a fresh access+refresh token pair. The refresh token's jti
    is NOT stored here — only revoked/used tokens get a row (an
    "allowlist" of every valid token would be a lot of unnecessary
    writes; a "blocklist" of revoked ones is far smaller in practice)."""
    access_token = create_access_token(user.email)
    refresh_token, _jti, _exp = create_refresh_token(user.email)
    return access_token, refresh_token


def is_token_revoked(db: Session, jti: str) -> bool:
    return db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is not None


def revoke_token(db: Session, jti: str, token_type: str, user_id: int | None, expires_at: datetime) -> None:
    # Idempotent — revoking an already-revoked jti is a no-op, not an error.
    if is_token_revoked(db, jti):
        return
    db.add(RevokedToken(jti=jti, token_type=token_type, user_id=user_id, expires_at=expires_at))
    db.commit()


def rotate_refresh_token(db: Session, refresh_token_str: str) -> tuple[str, str, User]:
    """Verifies a refresh token, revokes it (rotation — it can't be used
    again), and issues a brand-new access+refresh pair. Raises
    InvalidTokenError for anything wrong (expired, malformed, already
    revoked, user gone/inactive)."""
    try:
        decoded = decode_token(refresh_token_str, expected_type="refresh")
    except jwt.PyJWTError:
        raise InvalidTokenError("Invalid or expired refresh token.")

    if is_token_revoked(db, decoded.jti):
        # Reuse of an already-rotated-out refresh token — could be a
        # replay attempt (e.g. a stolen token used after the legitimate
        # client already rotated it). Logged for visibility.
        logger.warning("Attempted reuse of revoked refresh token: jti=%s", decoded.jti)
        raise InvalidTokenError("This refresh token is no longer valid. Please sign in again.")

    user = db.query(User).filter(User.email == decoded.subject).first()
    if not user or not user.is_active:
        raise InvalidTokenError("User not found or inactive.")

    revoke_token(db, decoded.jti, "refresh", user.id, decoded.expires_at)

    access_token = create_access_token(user.email)
    new_refresh_token, _jti, _exp = create_refresh_token(user.email)
    return access_token, new_refresh_token, user


def create_password_reset_token(db: Session, user: User) -> str:
    token, _jti, _exp = create_reset_token(user.email)
    return token


def reset_password_with_token(db: Session, token_str: str, new_password: str) -> User:
    try:
        decoded = decode_token(token_str, expected_type="reset")
    except jwt.PyJWTError:
        raise InvalidTokenError("This reset link is invalid or has expired.")

    if is_token_revoked(db, decoded.jti):
        raise InvalidTokenError("This reset link has already been used.")

    user = db.query(User).filter(User.email == decoded.subject).first()
    if not user or not user.is_active:
        raise InvalidTokenError("User not found or inactive.")

    user.password_hash = hash_password(new_password)
    revoke_token(db, decoded.jti, "reset", user.id, decoded.expires_at)
    db.commit()

    logger.info("Password reset completed: user_id=%s", user.id)
    return user
