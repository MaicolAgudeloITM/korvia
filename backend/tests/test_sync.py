from pathlib import Path

import pymupdf as fitz
import pytest

import korvia.main as main_module


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def create_space(auth_client) -> tuple[str, str]:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces", json={"name": "General"})
    assert response.status_code == 201
    return tenant_id, response.json()["id"]


@pytest.fixture
def sync_folder(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "origen"
    folder.mkdir()
    monkeypatch.setattr(main_module, "SYNC_ROOT", str(folder))
    return folder


def write_pdf(folder: Path, relative: str, text: str) -> Path:
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_pdf(text))
    return path


def test_la_sincronizacion_tambien_acepta_markdown(auth_client, sync_folder) -> None:
    tenant_id, space_id = create_space(auth_client)
    (sync_folder / "notas.md").write_bytes(
        b"# Procedimiento\nEl filtro se cambia cada seis meses."
    )

    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    documents = auth_client.get(f"/api/tenants/{tenant_id}/spaces/{space_id}/documents")

    assert response.status_code == 200
    assert response.json()["creados"] == 1
    assert [item["filename"] for item in documents.json()["documents"]] == ["notas.md"]


def test_la_primera_sincronizacion_crea_el_documento(auth_client, sync_folder) -> None:
    tenant_id, space_id = create_space(auth_client)
    write_pdf(sync_folder, "manual.pdf", "El filtro se cambia cada seis meses.")

    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    status = auth_client.get(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    documents = auth_client.get(f"/api/tenants/{tenant_id}/spaces/{space_id}/documents")

    assert response.status_code == 200
    assert response.json() == {
        "revisados": 1,
        "creados": 1,
        "actualizados": 0,
        "sin_cambios": 0,
        "eliminados": 0,
        "errores": [],
    }
    assert [item["filename"] for item in documents.json()["documents"]] == ["manual.pdf"]
    assert status.json()["last_sync_at"] is not None
    assert status.json()["files"][0]["status"] == "synced"


def test_sincronizar_dos_veces_no_duplica_el_documento(auth_client, sync_folder) -> None:
    tenant_id, space_id = create_space(auth_client)
    write_pdf(sync_folder, "manual.pdf", "El filtro se cambia cada seis meses.")
    first = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    document_id = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents"
    ).json()["documents"][0]["id"]

    second = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    document = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}"
    )

    assert first.json()["creados"] == 1
    assert second.json()["creados"] == 0
    assert second.json()["sin_cambios"] == 1
    assert document.json()["version_count"] == 1


def test_un_archivo_modificado_crea_una_version_nueva(auth_client, sync_folder) -> None:
    tenant_id, space_id = create_space(auth_client)
    path = write_pdf(sync_folder, "manual.pdf", "El filtro se cambia cada seis meses.")
    auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    document_id = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents"
    ).json()["documents"][0]["id"]

    path.write_bytes(make_pdf("El filtro se cambia cada doce meses."))
    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    document = auth_client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}"
    )
    search = auth_client.post(
        f"/api/tenants/{tenant_id}/search", json={"query": "doce meses"}
    )

    assert response.json()["actualizados"] == 1
    assert document.json()["version"] == 2
    assert "doce meses" in document.json()["chunks"][0]["text"]
    assert search.json()["results"][0]["document_id"] == document_id


def test_un_archivo_borrado_oculta_el_documento(auth_client, sync_folder) -> None:
    tenant_id, space_id = create_space(auth_client)
    path = write_pdf(sync_folder, "manual.pdf", "Mantenimiento del filtro.")
    auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")

    path.unlink()
    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    documents = auth_client.get(f"/api/tenants/{tenant_id}/spaces/{space_id}/documents")
    status = auth_client.get(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")

    assert response.json()["eliminados"] == 1
    assert documents.json()["documents"] == []
    assert status.json()["files"][0]["status"] == "missing"


def test_el_mismo_nombre_en_carpetas_distintas_son_documentos_distintos(
    auth_client, sync_folder
) -> None:
    tenant_id, space_id = create_space(auth_client)
    write_pdf(sync_folder, "taller/manual.pdf", "Mantenimiento del filtro.")
    write_pdf(sync_folder, "oficina/manual.pdf", "Filtro de la oficina.")

    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    documents = auth_client.get(f"/api/tenants/{tenant_id}/spaces/{space_id}/documents")

    assert response.json()["creados"] == 2
    assert {item["filename"] for item in documents.json()["documents"]} == {
        "taller/manual.pdf",
        "oficina/manual.pdf",
    }


def test_un_archivo_grande_se_registra_como_error(auth_client, sync_folder, monkeypatch) -> None:
    tenant_id, space_id = create_space(auth_client)
    write_pdf(sync_folder, "grande.pdf", "Contenido extenso de prueba.")
    monkeypatch.setattr(main_module, "MAX_UPLOAD_BYTES", 100)

    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")
    documents = auth_client.get(f"/api/tenants/{tenant_id}/spaces/{space_id}/documents")

    assert response.json()["creados"] == 0
    assert "grande.pdf" in response.json()["errores"][0]
    assert documents.json()["documents"] == []


def test_un_miembro_no_puede_sincronizar_pero_si_ver_el_estado(
    auth_client, client, sync_folder
) -> None:
    tenant_id, space_id = create_space(auth_client)
    write_pdf(sync_folder, "manual.pdf", "Filtro compartido.")

    miembro = client.post(
        "/api/auth/register",
        json={
            "email": "lector-sync@ejemplo.com",
            "password": "clave-lector-123",
            "company_name": "Empresa del lector",
        },
    ).json()
    headers = {"Authorization": f"Bearer {miembro['token']}"}
    added = auth_client.post(
        f"/api/tenants/{tenant_id}/members",
        json={"email": "lector-sync@ejemplo.com", "role": "member"},
    )
    assert added.status_code == 201

    denied = client.post(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/sync", headers=headers
    )
    allowed = client.get(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/sync", headers=headers
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_sin_carpeta_configurada_devuelve_503(auth_client, sync_folder, monkeypatch) -> None:
    tenant_id, space_id = create_space(auth_client)
    monkeypatch.setattr(main_module, "SYNC_ROOT", "")

    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space_id}/sync")

    assert response.status_code == 503
    assert "KORVIA_SYNC_ROOT" in response.json()["detail"]
