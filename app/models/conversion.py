import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ConversionJob(Base):
    __tablename__ = "conversion_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True, index=True)

    input_format = Column(String(20), default="pdf", nullable=False)
    output_format = Column(String(20), nullable=False)  # xlsx | docx | pptx
    page_count = Column(Integer, nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)

    output_filename = Column(String(500), nullable=True)
    output_storage_key = Column(String(1000), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="conversion_jobs")
    source_file = relationship("File", back_populates="conversion_jobs")
