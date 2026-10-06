"""store source PDF page counts

Revision ID: 0003_page_counts
Revises: 0002_revoked_tokens
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_page_counts"
down_revision: Union[str, None] = "0002_revoked_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("files", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("conversion_jobs", sa.Column("page_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversion_jobs", "page_count")
    op.drop_column("files", "page_count")
