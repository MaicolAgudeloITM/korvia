from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pymupdf as fitz

from korvia.chat import NO_EVIDENCE_ANSWER, ChatError


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def create_space(auth_client, name: str = "General") -> tuple[str, str]:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    response = auth_client.post(f"/api/tenants/{tenant_id}/spaces", json={"name": name})
    assert response.status_code == 201
    return tenant_id, response.json()["id"]


def upload(auth_client, tenant_id: str, space_id: str, filename: str, text: str):
    return auth_client.post(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents",
        files={"file": (filename, BytesIO(make_pdf(text)), "application/pdf")},
    )


def ask(auth_client, tenant_id: str, question: str, **extra):
    return auth_client.post(
        f"/api/tenants/{tenant_id}/ask", json={"question": question, **extra}
    )


def test_la_respuesta_cita_las_fuentes(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "filtros.pdf", "El filtro se cambia cada seis meses.")

    response = ask(auth_client, tenant_id, "¿cada cuánto se cambia el filtro?")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "extractive"
    assert data["insufficient_evidence"] is False
    assert "[1]" in data["answer"]
    assert "seis meses" in data["answer"]
    assert len(data["sources"]) == 1
    assert data["sources"][0]["filename"] == "filtros.pdf"
    assert data["sources"][0]["version"] == 1
    assert data["sources"][0]["score"] > 0


def test_sin_evidencia_no_inventa_una_respuesta(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "secretaria.pdf", "La secretaria atiende a los visitantes.")

    response = ask(auth_client, tenant_id, "¿cuál es el presupuesto anual?")

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == NO_EVIDENCE_ANSWER
    assert data["sources"] == []
    assert data["insufficient_evidence"] is True
    assert data["provider"] == "ninguno"


def test_la_respuesta_usa_solo_la_version_vigente(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "manual.pdf", "El filtro se cambia cada seis meses.")
    upload(auth_client, tenant_id, space_id, "manual.pdf", "El filtro se cambia cada doce meses.")

    response = ask(auth_client, tenant_id, "¿cada cuánto se cambia el filtro?")

    data = response.json()
    assert "doce meses" in data["answer"]
    assert "seis meses" not in data["answer"]
    assert [source["version"] for source in data["sources"]] == [2]


def test_la_respuesta_respeta_espacio_y_metadata(auth_client) -> None:
    tenant_id, space_a = create_space(auth_client, "Taller")
    _, space_b = create_space(auth_client, "Oficina")
    upload(auth_client, tenant_id, space_a, "taller.pdf", "Mantenimiento del filtro.")
    document = upload(
        auth_client, tenant_id, space_b, "oficina.pdf", "Filtro de la oficina."
    ).json()
    patched = auth_client.patch(
        f"/api/tenants/{tenant_id}/spaces/{space_b}/documents/{document['id']}",
        json={"metadata": {"area": "Oficina"}},
    )
    assert patched.status_code == 200

    by_space = ask(auth_client, tenant_id, "filtro", space_id=space_b)
    by_metadata = ask(auth_client, tenant_id, "filtro", metadata_filters={"area": "Oficina"})

    assert [item["filename"] for item in by_space.json()["sources"]] == ["oficina.pdf"]
    assert [item["filename"] for item in by_metadata.json()["sources"]] == ["oficina.pdf"]


def test_un_miembro_puede_preguntar(auth_client, client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "comun.pdf", "Filtro compartido.")

    miembro = client.post(
        "/api/auth/register",
        json={
            "email": "lector-rag@ejemplo.com",
            "password": "clave-lector-123",
            "company_name": "Empresa del lector",
        },
    ).json()
    headers = {"Authorization": f"Bearer {miembro['token']}"}
    added = auth_client.post(
        f"/api/tenants/{tenant_id}/members",
        json={"email": "lector-rag@ejemplo.com", "role": "member"},
    )
    assert added.status_code == 201

    response = client.post(
        f"/api/tenants/{tenant_id}/ask", json={"question": "filtro"}, headers=headers
    )

    assert response.status_code == 200
    assert len(response.json()["sources"]) == 1


def test_el_proveedor_de_chat_recibe_el_contexto(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "filtros.pdf", "El filtro se cambia cada seis meses.")
    proveedor = SimpleNamespace(name="proveedor-prueba", answer=Mock(return_value="Respuesta [1]."))

    with patch("korvia.main.get_chat_provider", return_value=proveedor):
        response = ask(auth_client, tenant_id, "¿cada cuánto se cambia el filtro?")

    assert response.status_code == 200
    assert response.json()["answer"] == "Respuesta [1]."
    assert response.json()["provider"] == "proveedor-prueba"
    question, context, sources = proveedor.answer.call_args.args
    assert "filtro" in question
    assert "[1]" in context and "filtros.pdf" in context
    assert sources[0].number == 1


def test_un_fallo_del_proveedor_de_chat_devuelve_503(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "filtros.pdf", "El filtro se cambia cada seis meses.")

    with patch("korvia.main.get_chat_provider", side_effect=ChatError("sin modelo")):
        response = ask(auth_client, tenant_id, "filtro")

    assert response.status_code == 503
    assert "sin modelo" in response.json()["detail"]
