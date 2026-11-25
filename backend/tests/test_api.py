from io import BytesIO
import os
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from korvia.document_processing import OCRUnavailableError


def make_pdf(text: str | None = None) -> bytes:
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_health_endpoint(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_inspect_endpoint_returns_cited_pdf_text(auth_client) -> None:
    response = auth_client.post(
        "/api/documents/inspect",
        files={"file": ("manual.pdf", BytesIO(make_pdf("El filtro se cambia cada seis meses.")), "application/pdf")},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["extraction_method"] == "text"
    assert result["chunks"][0]["sources"] == ["página 1"]


def test_inspect_endpoint_accepts_markdown(auth_client) -> None:
    content = b"# Mantenimiento\nEl filtro se cambia cada seis meses."

    response = auth_client.post(
        "/api/documents/inspect",
        files={"file": ("manual.md", BytesIO(content), "text/markdown")},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["extraction_method"] == "text"
    assert result["chunks"][0]["sources"] == ["línea 1", "línea 2"]


def test_inspect_endpoint_rejects_unsupported_format(auth_client) -> None:
    response = auth_client.post(
        "/api/documents/inspect",
        files={"file": ("datos.csv", b"a,b\n1,2", "text/csv")},
    )

    assert response.status_code == 415


def test_inspect_endpoint_reports_when_ocr_is_not_available(auth_client) -> None:
    with patch(
        "korvia.document_processing._ocr_pdf_page",
        side_effect=OCRUnavailableError("Tesseract no está instalado."),
    ):
        response = auth_client.post(
            "/api/documents/inspect",
            files={"file": ("escaneo.pdf", BytesIO(make_pdf()), "application/pdf")},
        )

    assert response.status_code == 503
    assert "Tesseract" in response.json()["detail"]


def create_test_space(client, company_name: str) -> tuple[str, str]:
    tenant_response = client.post("/api/tenants", json={"name": company_name})
    assert tenant_response.status_code == 201
    tenant_id = tenant_response.json()["id"]

    space_response = client.post(
        f"/api/tenants/{tenant_id}/spaces", json={"name": "General"}
    )
    assert space_response.status_code == 201
    return tenant_id, space_response.json()["id"]


def test_upload_persists_document_chunks_and_sources(auth_client) -> None:
    tenant_id, space_id = create_test_space(auth_client, "Empresa de prueba")
    content = make_pdf("El filtro se cambia cada seis meses.")

    response = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents",
        files={"file": ("manual.pdf", BytesIO(content), "application/pdf")},
    )

    assert response.status_code == 201
    document = response.json()
    assert document["filename"] == "manual.pdf"
    assert document["chunk_count"] == 1
    assert document["chunks"][0]["sources"] == ["página 1"]
    stored_file = (
        Path(os.environ["KORVIA_STORAGE_DIR"])
        / tenant_id
        / space_id
        / f"{document['id']}_v1.pdf"
    )
    assert stored_file.exists()

    list_response = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents"
    )
    assert len(list_response.json()["documents"]) == 1

    detail_response = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document['id']}"
    )
    assert detail_response.status_code == 200
    assert "cada seis meses" in detail_response.json()["chunks"][0]["text"]


def test_same_version_is_not_added_twice(auth_client) -> None:
    tenant_id, space_id = create_test_space(auth_client, "Empresa sin duplicados")
    content = make_pdf("Contenido de prueba")
    url = f"/api/tenants/{tenant_id}/spaces/{space_id}/documents"

    first = auth_client.post(url, files={"file": ("manual.pdf", BytesIO(content), "application/pdf")})
    repeated = auth_client.post(url, files={"file": ("manual.pdf", BytesIO(content), "application/pdf")})

    assert first.status_code == 201
    assert repeated.status_code == 409
    assert "ya está guardada" in repeated.json()["detail"]


def test_documents_are_listed_only_in_their_own_space(auth_client, client) -> None:
    tenant_a, space_a = create_test_space(auth_client, "Empresa A")
    content = make_pdf("Solo para Empresa A")
    uploaded = auth_client.post(
        f"/api/tenants/{tenant_a}/spaces/{space_a}/documents",
        files={"file": ("a.pdf", BytesIO(content), "application/pdf")},
    )
    assert uploaded.status_code == 201

    otro_usuario = client.post(
        "/api/auth/register",
        json={
            "email": "otro@ejemplo.com",
            "password": "otra-clave-123",
            "company_name": "Empresa ajena",
        },
    ).json()
    sin_acceso = client.get(
        f"/api/tenants/{tenant_a}/spaces/{space_a}/documents",
        headers={"Authorization": f"Bearer {otro_usuario['token']}"},
    )
    assert sin_acceso.status_code == 403

    tenant_b, space_b = create_test_space(auth_client, "Empresa B")
    response_b = auth_client.get(
        f"/api/tenants/{tenant_b}/spaces/{space_b}/documents"
    )
    guessed_document = auth_client.get(
        f"/api/tenants/{tenant_b}/spaces/{space_b}/documents/{uploaded.json()['id']}"
    )

    assert response_b.status_code == 200
    assert response_b.json()["documents"] == []
    assert guessed_document.status_code == 404
