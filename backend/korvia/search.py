"""Búsqueda por similitud sobre los fragmentos de la versión vigente."""

from __future__ import annotations

import math
from typing import Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from korvia.models import Document, DocumentChunk, DocumentVersion, USING_PGVECTOR


def current_version_number():
    """Número de la versión vigente de cada documento (subconsulta correlacionada).

    ``correlate(Document)`` es importante: sin él SQLAlchemy quita también la
    tabla ``document_versions`` de la subconsulta y la consulta queda vacía.
    """
    return (
        select(func.max(DocumentVersion.version_number))
        .where(DocumentVersion.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )


def find_similar_chunks(
    db: Session,
    tenant_id: str,
    query_vector: Sequence[float],
    top_k: int,
    *,
    space_id: str | None = None,
    metadata_filters: dict[str, str | int | float | bool] | None = None,
) -> list[tuple[DocumentChunk, DocumentVersion, Document, float]]:
    """Devuelve fragmentos con puntaje de similitud (1 = idéntico)."""
    max_version = current_version_number()
    statement = (
        select(DocumentChunk, DocumentVersion, Document)
        .join(
            DocumentVersion,
            and_(
                DocumentChunk.version_id == DocumentVersion.id,
                DocumentChunk.tenant_id == DocumentVersion.tenant_id,
            ),
        )
        .join(
            Document,
            and_(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.tenant_id == Document.tenant_id,
            ),
        )
        .where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            DocumentChunk.embedding.is_not(None),
            DocumentVersion.version_number == max_version,
        )
    )
    if space_id:
        statement = statement.where(Document.space_id == space_id)
    for key, value in (metadata_filters or {}).items():
        # Comparar como texto: en SQLite el operador == de JSON añade comillas
        # y no coincide con los valores guardados.
        if isinstance(value, bool):
            expected = ("true" if value else "false") if USING_PGVECTOR else ("1" if value else "0")
        else:
            expected = str(value)
        statement = statement.where(Document.metadata_json[key].as_string() == expected)

    if USING_PGVECTOR:
        distance = DocumentChunk.embedding.cosine_distance(list(query_vector))
        rows = db.execute(
            statement.add_columns(distance.label("distance")).order_by(distance).limit(top_k)
        ).all()
        return [(row[0], row[1], row[2], 1.0 - float(row[3])) for row in rows]

    # SQLite no tiene pgvector: se calcula la similitud en Python.
    rows = db.execute(statement).all()
    scored = [
        (chunk, version, document, _cosine_similarity(query_vector, chunk.embedding or ()))
        for chunk, version, document in rows
    ]
    scored.sort(key=lambda item: item[3], reverse=True)
    return scored[:top_k]


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
