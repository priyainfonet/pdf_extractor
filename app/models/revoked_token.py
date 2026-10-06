from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey

from app.core.database import Base


class RevokedToken(Base):
    """Tracks JWTs that must no longer be honored, by their unique 'jti'
    claim — used for refresh-token rotation (old refresh tokens are
    revoked when a new pair is issued) and one-time password-reset
    tokens (revoked immediately after use so they can't be replayed).

    JWTs are otherwise stateless (see app/core/security.py), so this is
    the one place the app tracks token state server-side."""

    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), unique=True, index=True, nullable=False)
    token_type = Column(String(20), nullable=False)  # "refresh" | "reset"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    expires_at = Column(DateTime, nullable=False)  # mirrors the JWT's own exp, for cleanup
    revoked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
