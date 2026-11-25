from io import BytesIO
import os
from pathlib import Path

import pymupdf as fitz


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def create_space(auth_client) -> tuple[str, str]:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    response = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces", json={"name": "General"}
    )
    assert response.status_code == 201
    return tenant_id, response.json()["id"]


def upload(auth_client, tenant_id: str, space_id: str, text: str):
    return auth_client.post(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents",
        files={"file": ("manual.pdf", BytesIO(make_pdf(text)), "application/pdf")},
    )


def test_el_mismo_nombre_crea_una_nueva_version(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    first = upload(auth_client, tenant_id, space_id, "Texto de la primera versión")
    second = upload(auth_client, tenant_id, space_id, "Texto de la segunda versión")

    assert first.status_code == 201
    assert first.json()["version"] == 1
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert second.json()["version_count"] == 2
    assert "segunda versión" in second.json()["chunks"][0]["text"]

    document_id = first.json()["id"]
    versions = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}/versions"
    )
    assert [item["version_number"] for item in versions.json()["versions"]] == [1, 2]

    old_version = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}/versions/1"
    )
    assert "primera versión" in old_version.json()["chunks"][0]["text"]

    storage = Path(os.environ["KORVIA_STORAGE_DIR"]) / tenant_id / space_id
    assert (storage / f"{document_id}_v1.pdf").exists()
    assert (storage / f"{document_id}_v2.pdf").exists()


def test_metadata_se_actualiza_y_se_valida(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    document = upload(auth_client, tenant_id, space_id, "Procedimiento").json()
    url = f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document['id']}"

    response = auth_client.patch(
        url,
        json={"metadata": {"area": "Mantenimiento", "anio": 2026, "confidencial": False}},
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "area": "Mantenimiento",
        "anio": 2026,
        "confidencial": False,
    }

    invalid = auth_client.patch(url, json={"metadata": {"relacion": {"anidado": 1}}})
    assert invalid.status_code == 422


def test_borrado_logico_y_restauracion(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    document = upload(auth_client, tenant_id, space_id, "A borrar").json()
    url = f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document['id']}"
    list_url = f"/api/tenants/{tenant_id}/spaces/{space_id}/documents"

    deleted = auth_client.delete(url)
    assert deleted.status_code == 204
    assert auth_client.get(url).status_code == 404
    assert auth_client.get(list_url).json()["documents"] == []

    restored = auth_client.post(f"{url}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert len(auth_client.get(list_url).json()["documents"]) == 1


def test_un_miembro_no_puede_borrar_ni_cambiar_metadata(auth_client, client) -> None:
    tenant_id, space_id = create_space(auth_client)
    document = upload(auth_client, tenant_id, space_id, "Solo lectura").json()

    miembro = client.post(
        "/api/auth/register",
        json={
            "email": "lector@ejemplo.com",
            "password": "clave-lector-123",
            "company_name": "Empresa del lector",
        },
    ).json()
    headers = {"Authorization": f"Bearer {miembro['token']}"}
    added = auth_client.post(
        f"/api/tenants/{tenant_id}/members",
        json={"email": "lector@ejemplo.com", "role": "member"},
    )
    assert added.status_code == 201

    url = f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document['id']}"
    assert client.get(url, headers=headers).status_code == 200
    assert client.patch(url, json={"metadata": {"x": 1}}, headers=headers).status_code == 403
    assert client.delete(url, headers=headers).status_code == 403
