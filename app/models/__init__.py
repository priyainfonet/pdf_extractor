# Import every model here so Base.metadata sees all tables — Alembic's
# autogenerate and Base.metadata.create_all() both rely on this.
from app.models.user import User
from app.models.file import File
from app.models.conversion import ConversionJob, JobStatus
from app.models.revoked_token import RevokedToken

__all__ = ["User", "File", "ConversionJob", "JobStatus", "RevokedToken"]
