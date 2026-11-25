"""versiones, metadata y borrado lógico

Revision ID: 7c1e9a4b2d30
Revises: acf878be84ce
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "7c1e9a4b2d30"
down_revision: Union[str, Sequence[str], None] = "acf878be84ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    # En modo --sql no hay filas que copiar; la copia se hace solo en modo online.
    offline = context.is_offline_mode()

    # El documento pasa a ser la entidad lógica; el hash deja de ser único por espacio.
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.drop_constraint("uq_document_content_per_space", type_="unique")

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("file_extension", sa.String(length=10), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("extraction_method", sa.String(length=30), nullable=False),
        sa.Column("warning_messages", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
            name="fk_version_document_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_version_tenant_id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_version_document_number"),
        sa.UniqueConstraint("document_id", "content_sha256", name="uq_version_document_hash"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_tenant_id", "document_versions", ["tenant_id"])

    # Los documentos que ya existían se convierten en su versión 1.
    if offline:
        op.execute("-- NOTA: la copia de documentos antiguos se ejecuta solo en modo online.")
    else:
        old_documents = connection.execute(
            sa.text(
                "SELECT id, tenant_id, filename, file_extension, content_sha256, storage_key, "
                "extraction_method, warning_messages, created_at FROM documents"
            )
        ).mappings().all()
        for document in old_documents:
            connection.execute(
                sa.text(
                    "INSERT INTO document_versions (id, tenant_id, document_id, version_number, "
                    "filename, file_extension, content_sha256, storage_key, extraction_method, "
                    "warning_messages, created_at) VALUES (:id, :tenant_id, :document_id, 1, "
                    ":filename, :file_extension, :content_sha256, :storage_key, :extraction_method, "
                    ":warning_messages, :created_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": document["tenant_id"],
                    "document_id": document["id"],
                    "filename": document["filename"],
                    "file_extension": document["file_extension"],
                    "content_sha256": document["content_sha256"],
                    "storage_key": document["storage_key"],
                    "extraction_method": document["extraction_method"],
                    "warning_messages": document["warning_messages"],
                    "created_at": document["created_at"],
                },
            )

    with op.batch_alter_table("document_chunks") as batch_op:
        batch_op.add_column(sa.Column("version_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_document_chunks_version_id", ["version_id"])
        batch_op.drop_constraint("uq_chunk_document_position", type_="unique")
        batch_op.create_unique_constraint("uq_chunk_version_position", ["version_id", "position"])

    if not offline:
        connection.execute(
            sa.text(
                "UPDATE document_chunks SET version_id = ("
                "SELECT version.id FROM document_versions AS version "
                "WHERE version.document_id = document_chunks.document_id)"
            )
        )

    with op.batch_alter_table("document_chunks") as batch_op:
        batch_op.alter_column("version_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_foreign_key(
            "fk_chunk_version_tenant",
            "document_versions",
            ["tenant_id", "version_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )

    if not offline:
        metadata_column = sa.column("metadata_json", sa.JSON())
        connection.execute(
            sa.update(sa.table("documents", metadata_column))
            .where(metadata_column.is_(None))
            .values(metadata_json={})
        )
        connection.execute(sa.text("UPDATE documents SET updated_at = created_at WHERE updated_at IS NULL"))

    with op.batch_alter_table("documents") as batch_op:
        batch_op.alter_column("metadata_json", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column(
            "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("document_chunks") as batch_op:
        batch_op.drop_index("ix_document_chunks_version_id")
        batch_op.drop_constraint("fk_chunk_version_tenant", type_="foreignkey")
        batch_op.drop_constraint("uq_chunk_version_position", type_="unique")
        batch_op.drop_column("version_id")
        batch_op.create_unique_constraint("uq_chunk_document_position", ["document_id", "position"])

    op.drop_index("ix_document_versions_tenant_id", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")

    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("metadata_json")
        batch_op.create_unique_constraint(
            "uq_document_content_per_space", ["tenant_id", "space_id", "content_sha256"]
        )
