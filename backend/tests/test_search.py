from io import BytesIO
from unittest.mock import patch

import pymupdf as fitz

from korvia.embeddings import EmbeddingError, LocalHashEmbeddingProvider


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def create_space(auth_client, name: str = "General") -> tuple[str, str]:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    response = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces", json={"name": name}
    )
    assert response.status_code == 201
    return tenant_id, response.json()["id"]


def upload(auth_client, tenant_id: str, space_id: str, filename: str, text: str):
    return auth_client.post(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents",
        files={"file": (filename, BytesIO(make_pdf(text)), "application/pdf")},
    )


def test_la_busqueda_devuelve_fragmentos_con_puntaje(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "filtros.pdf", "El filtro se cambia cada seis meses.")
    upload(auth_client, tenant_id, space_id, "secretaria.pdf", "La secretaria atiende a los visitantes.")

    response = auth_client.post(
        f"/api/tenants/{tenant_id}/search", json={"query": "filtro", "top_k": 2}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "local-hash"
    assert len(data["results"]) == 2
    assert data["results"][0]["document_filename"] == "filtros.pdf"
    assert data["results"][0]["score"] > data["results"][1]["score"]
    assert data["results"][0]["sources"] == ["página 1"]


def test_la_busqueda_filtra_por_espacio_y_metadata(auth_client) -> None:
    tenant_id, space_a = create_space(auth_client, "Taller")
    _, space_b = create_space(auth_client, "Oficina")
    upload(auth_client, tenant_id, space_a, "taller.pdf", "Mantenimiento del filtro.")
    oficina = upload(auth_client, tenant_id, space_b, "oficina.pdf", "Filtro de la oficina.")
    assert oficina.status_code == 201
    document_id = oficina.json()["id"]
    space_url = f"/api/tenants/{tenant_id}/spaces/{space_b}/documents/{document_id}"

    patched = auth_client.patch(space_url, json={"metadata": {"area": "Oficina"}})
    assert patched.status_code == 200

    by_space = auth_client.post(
        f"/api/tenants/{tenant_id}/search", json={"query": "filtro", "space_id": space_b}
    )
    assert {item["document_filename"] for item in by_space.json()["results"]} == {"oficina.pdf"}

    by_metadata = auth_client.post(
        f"/api/tenants/{tenant_id}/search",
        json={"query": "filtro", "metadata_filters": {"area": "Oficina"}},
    )
    assert {item["document_filename"] for item in by_metadata.json()["results"]} == {"oficina.pdf"}


def test_los_filtros_de_metadata_aceptan_numeros_y_banderas(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    document = upload(auth_client, tenant_id, space_id, "datos.pdf", "Filtro con datos.").json()
    url = f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document['id']}"
    assert auth_client.patch(
        url, json={"metadata": {"anio": 2026, "publico": True}}
    ).status_code == 200

    numeros = auth_client.post(
        f"/api/tenants/{tenant_id}/search",
        json={"query": "filtro", "metadata_filters": {"anio": 2026}},
    )
    banderas = auth_client.post(
        f"/api/tenants/{tenant_id}/search",
        json={"query": "filtro", "metadata_filters": {"publico": True}},
    )

    assert len(numeros.json()["results"]) == 1
    assert len(banderas.json()["results"]) == 1


def test_la_busqueda_no_devuelve_documentos_borrados(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    document = upload(auth_client, tenant_id, space_id, "borrar.pdf", "Filtro temporal.").json()
    url = f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document['id']}"
    assert auth_client.delete(url).status_code == 204

    response = auth_client.post(f"/api/tenants/{tenant_id}/search", json={"query": "filtro"})

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_reindex_genera_embeddings_faltantes(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    with patch("korvia.main.get_provider", side_effect=EmbeddingError("sin proveedor")):
        uploaded = upload(auth_client, tenant_id, space_id, "pendiente.pdf", "Filtro sin vector.")
    assert uploaded.status_code == 201
    assert "embeddings" in uploaded.json()["warning_messages"][0]

    empty_search = auth_client.post(f"/api/tenants/{tenant_id}/search", json={"query": "filtro"})
    assert empty_search.json()["results"] == []

    with patch("korvia.main.get_provider", return_value=LocalHashEmbeddingProvider()):
        reindex = auth_client.post(f"/api/tenants/{tenant_id}/search/reindex")
        search = auth_client.post(f"/api/tenants/{tenant_id}/search", json={"query": "filtro"})

    assert reindex.status_code == 200
    assert reindex.json()["embedded_chunks"] == 1
    assert len(search.json()["results"]) == 1


def test_un_miembro_puede_buscar_pero_no_reindexar(auth_client, client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "comun.pdf", "Filtro compartido.")

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

    search = client.post(
        f"/api/tenants/{tenant_id}/search", json={"query": "filtro"}, headers=headers
    )
    reindex = client.post(f"/api/tenants/{tenant_id}/search/reindex", headers=headers)

    assert search.status_code == 200
    assert len(search.json()["results"]) == 1
    assert reindex.status_code == 403
