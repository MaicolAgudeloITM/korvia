"""embeddings para búsqueda por similitud

Revision ID: b4d6e8f10a92
Revises: 7c1e9a4b2d30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b4d6e8f10a92"
down_revision: Union[str, Sequence[str], None] = "7c1e9a4b2d30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 384
INDEX_NAME = "ix_document_chunks_embedding"


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from pgvector.sqlalchemy import Vector

        column_type = Vector(EMBEDDING_DIM)
    else:
        column_type = sa.JSON()

    with op.batch_alter_table("document_chunks") as batch_op:
        batch_op.add_column(sa.Column("embedding", column_type, nullable=True))

    if is_postgres:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    with op.batch_alter_table("document_chunks") as batch_op:
        batch_op.drop_column("embedding")
