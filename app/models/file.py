from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship

from app.core.database import Base


class File(Base):
    """Metadata only — the actual PDF bytes live in storage (filesystem or
    S3, via StorageService), never in the database. storage_key is the
    path/key StorageService needs to fetch it back."""

    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = Column(String(500), nullable=False)
    storage_key = Column(String(1000), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(String(100), nullable=False)
    page_count = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="files")
    conversion_jobs = relationship("ConversionJob", back_populates="source_file")
