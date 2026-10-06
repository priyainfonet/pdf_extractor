"""initial schema - users, files, conversion_jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_files_id", "files", ["id"])
    op.create_index("ix_files_user_id", "files", ["user_id"])

    op.create_table(
        "conversion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("input_format", sa.String(length=20), nullable=False, server_default="pdf"),
        sa.Column("output_format", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "UPLOADING", "PROCESSING", "COMPLETED", "FAILED", name="jobstatus"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("output_filename", sa.String(length=500), nullable=True),
        sa.Column("output_storage_key", sa.String(length=1000), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversion_jobs_id", "conversion_jobs", ["id"])
    op.create_index("ix_conversion_jobs_user_id", "conversion_jobs", ["user_id"])
    op.create_index("ix_conversion_jobs_file_id", "conversion_jobs", ["file_id"])
    op.create_index("ix_conversion_jobs_status", "conversion_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("conversion_jobs")
    op.drop_table("files")
    op.drop_table("users")
