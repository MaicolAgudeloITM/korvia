"""sincronización de carpetas

Revision ID: cafa2f6fd877
Revises: b4d6e8f10a92
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "cafa2f6fd877"
down_revision: Union[str, Sequence[str], None] = "b4d6e8f10a92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_runs_space_id", "sync_runs", ["space_id"], unique=False)
    op.create_index("ix_sync_runs_tenant_id", "sync_runs", ["tenant_id"], unique=False)

    op.create_table(
        "synced_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("relative_path", sa.String(length=1000), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "space_id", "relative_path", name="uq_synced_file_path"),
    )
    op.create_index("ix_synced_files_document_id", "synced_files", ["document_id"], unique=False)
    op.create_index("ix_synced_files_space_id", "synced_files", ["space_id"], unique=False)
    op.create_index("ix_synced_files_tenant_id", "synced_files", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_synced_files_tenant_id", table_name="synced_files")
    op.drop_index("ix_synced_files_space_id", table_name="synced_files")
    op.drop_index("ix_synced_files_document_id", table_name="synced_files")
    op.drop_table("synced_files")
    op.drop_index("ix_sync_runs_tenant_id", table_name="sync_runs")
    op.drop_index("ix_sync_runs_space_id", table_name="sync_runs")
    op.drop_table("sync_runs")
