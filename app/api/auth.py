"""
POST /api/auth/register        (rate limited: 5/hour per IP)
POST /api/auth/login            (rate limited: 10/5min per IP)
POST /api/auth/refresh          (rotates the refresh token — old one is revoked)
POST /api/auth/logout           (revokes the refresh token so it can't be used again)
POST /api/auth/forgot-password  (rate limited: 3/15min per IP; sends a real email now)
POST /api/auth/reset-password   (one-time token, enforced via revoked_tokens)
"""

import logging
import jwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.config import settings
from app.core.security import decode_token
from app.utils.rate_limiter import rate_limit
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    LogoutRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.services import auth_service
from app.services.email_service import send_password_reset_email
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("auth_api")


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("register", max_requests=5, window_seconds=3600))],
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.register_user(db, payload)
    except auth_service.EmailAlreadyExistsError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    access_token, refresh_token = auth_service.issue_token_pair(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user=UserOut.model_validate(user))


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login", max_requests=10, window_seconds=300))],
)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.authenticate_user(db, payload.email, payload.password)
    except auth_service.InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    access_token, refresh_token = auth_service.issue_token_pair(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        access_token, new_refresh_token, user = auth_service.rotate_refresh_token(db, payload.refresh_token)
    except auth_service.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(
    payload: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Revoke the refresh token so it can't be used to mint new access
    # tokens after logout. The current access token itself stays valid
    # until it naturally expires (short-lived by design — see
    # ACCESS_TOKEN_EXPIRE_MINUTES) since access tokens aren't tracked
    # individually.
    if payload.refresh_token:
        try:
            decoded = decode_token(payload.refresh_token, expected_type="refresh")
            auth_service.revoke_token(db, decoded.jti, "refresh", current_user.id, decoded.expires_at)
        except jwt.PyJWTError:
            pass  # already invalid/expired — nothing to revoke

    logger.info("User logged out: user_id=%s", current_user.id)
    return None


@router.post(
    "/forgot-password",
    status_code=202,
    dependencies=[Depends(rate_limit("forgot-password", max_requests=3, window_seconds=900))],
)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()

    # Always return the same response whether or not the email exists —
    # never reveal which emails are registered.
    if user and user.is_active:
        reset_token = auth_service.create_password_reset_token(db, user)
        reset_link = f"{settings.FRONTEND_URL}?token={reset_token}"
        send_password_reset_email(user.email, reset_link)
        logger.info("Password reset requested: user_id=%s", user.id)
    else:
        logger.info("Password reset requested for unknown/inactive email=%s", payload.email)

    return {"message": "If an account exists for this email, a reset link has been sent."}


@router.post("/reset-password", status_code=200)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        auth_service.reset_password_with_token(db, payload.token, payload.new_password)
    except auth_service.InvalidTokenError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Your password has been reset. Please sign in with your new password."}
