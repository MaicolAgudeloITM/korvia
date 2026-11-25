from io import BytesIO
from unittest.mock import patch

import pymupdf as fitz
from fastapi import HTTPException

from korvia.chat import NO_EVIDENCE_ANSWER


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


def upload(auth_client, tenant_id: str, space_id: str, filename: str, text: str) -> dict:
    response = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces/{space_id}/documents",
        files={"file": (filename, BytesIO(make_pdf(text)), "application/pdf")},
    )
    assert response.status_code == 201
    return response.json()


def create_agent(auth_client, tenant_id: str, steps: list[str], **extra) -> dict:
    response = auth_client.post(
        f"/api/tenants/{tenant_id}/agents",
        json={"name": "Revisión de filtros", "steps": steps, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def run_agent(client, tenant_id: str, agent_id: str, headers=None):
    return client.post(
        f"/api/tenants/{tenant_id}/agents/{agent_id}/run", json={}, headers=headers
    )


def add_member(auth_client, client, tenant_id: str, email: str) -> dict[str, str]:
    registered = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "clave-lector-123",
            "company_name": "Empresa del lector",
        },
    ).json()
    added = auth_client.post(
        f"/api/tenants/{tenant_id}/members",
        json={"email": email, "role": "member"},
    )
    assert added.status_code == 201
    headers = {"Authorization": f"Bearer {registered['token']}"}
    me = client.get("/api/auth/me", headers=headers).json()["user"]
    return headers, me


def test_crear_y_listar_un_agente(auth_client) -> None:
    tenant_id, _ = create_space(auth_client)
    steps = ["¿cada cuánto se cambia el filtro?", "¿quién lo revisa?"]

    agent = create_agent(auth_client, tenant_id, steps)
    listing = auth_client.get(f"/api/tenants/{tenant_id}/agents")

    assert agent["name"] == "Revisión de filtros"
    assert agent["steps"] == steps
    assert agent["metadata_filters"] == {}
    assert [item["id"] for item in listing.json()] == [agent["id"]]


def test_ejecutar_el_agente_entrega_un_informe_con_fuentes(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "filtros.pdf", "El filtro se cambia cada seis meses.")
    agent = create_agent(auth_client, tenant_id, ["¿cada cuánto se cambia el filtro?"])

    response = run_agent(auth_client, tenant_id, agent["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert len(data["steps"]) == 1
    assert "[1]" in data["steps"][0]["answer"]
    assert "seis meses" in data["report"]
    assert "filtros.pdf v1 [1]" in data["report"]
    assert data["steps"][0]["sources"][0]["filename"] == "filtros.pdf"


def test_un_paso_sin_evidencia_no_inventa_una_respuesta(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "secretaria.pdf", "La secretaria atiende a los visitantes.")
    agent = create_agent(
        auth_client, tenant_id, ["¿cuál es el presupuesto anual?", "¿quién atiende?"]
    )

    response = run_agent(auth_client, tenant_id, agent["id"])
    data = response.json()

    assert [step["insufficient_evidence"] for step in data["steps"]] == [True, False]
    assert NO_EVIDENCE_ANSWER in data["report"]
    assert "Fuentes: ninguna" in data["report"]


def test_el_agente_respeta_el_espacio_y_la_metadata(auth_client) -> None:
    tenant_id, space_a = create_space(auth_client, "Taller")
    _, space_b = create_space(auth_client, "Oficina")
    upload(auth_client, tenant_id, space_a, "taller.pdf", "Mantenimiento del filtro.")
    document = upload(auth_client, tenant_id, space_b, "oficina.pdf", "Filtro de la oficina.")
    patched = auth_client.patch(
        f"/api/tenants/{tenant_id}/spaces/{space_b}/documents/{document['id']}",
        json={"metadata": {"area": "Oficina"}},
    )
    assert patched.status_code == 200

    by_space = create_agent(
        auth_client, tenant_id, ["filtro"], space_id=space_b
    )
    by_metadata = create_agent(
        auth_client, tenant_id, ["filtro"], name="Por área", metadata_filters={"area": "Oficina"}
    )

    space_result = run_agent(auth_client, tenant_id, by_space["id"]).json()
    metadata_result = run_agent(auth_client, tenant_id, by_metadata["id"]).json()

    assert [item["filename"] for item in space_result["steps"][0]["sources"]] == ["oficina.pdf"]
    assert [item["filename"] for item in metadata_result["steps"][0]["sources"]] == ["oficina.pdf"]


def test_un_miembro_puede_ejecutar_pero_no_crear_agentes(auth_client, client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "comun.pdf", "Filtro compartido.")
    agent = create_agent(auth_client, tenant_id, ["filtro"])
    headers, user = add_member(auth_client, client, tenant_id, "lector-agente@ejemplo.com")

    denied = client.post(
        f"/api/tenants/{tenant_id}/agents",
        json={"name": "No permitido", "steps": ["filtro"]},
        headers=headers,
    )
    allowed = run_agent(client, tenant_id, agent["id"], headers)

    assert denied.status_code == 403
    assert allowed.status_code == 200
    history = client.get(
        f"/api/tenants/{tenant_id}/agents/{agent['id']}/runs", headers=headers
    ).json()
    assert history[0]["triggered_by"] == user["id"]
    assert history[0]["steps_count"] == 1


def test_el_historial_guarda_el_resultado_y_los_pasos(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "manual.pdf", "El filtro se cambia cada seis meses.")
    agent = create_agent(auth_client, tenant_id, ["filtro", "otra pregunta"])
    run_agent(auth_client, tenant_id, agent["id"])

    history = auth_client.get(f"/api/tenants/{tenant_id}/agents/{agent['id']}/runs")

    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["status"] == "ok"
    assert history.json()[0]["steps_count"] == 2
    assert history.json()[0]["error"] is None


def test_un_fallo_en_un_paso_queda_registrado(auth_client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "manual.pdf", "Filtro del taller.")
    agent = create_agent(auth_client, tenant_id, ["filtro"])

    with patch(
        "korvia.main._answer_question", side_effect=HTTPException(status_code=503, detail="sin modelo")
    ):
        failed = run_agent(auth_client, tenant_id, agent["id"])

    history = auth_client.get(f"/api/tenants/{tenant_id}/agents/{agent['id']}/runs").json()
    assert failed.status_code == 503
    assert history[0]["status"] == "error"
    assert "sin modelo" in history[0]["error"]


def test_nombres_duplicados_y_pasos_invalidos(auth_client) -> None:
    tenant_id, _ = create_space(auth_client)
    create_agent(auth_client, tenant_id, ["filtro"])

    duplicate = auth_client.post(
        f"/api/tenants/{tenant_id}/agents",
        json={"name": "Revisión de filtros", "steps": ["otro"]},
    )
    blank = auth_client.post(
        f"/api/tenants/{tenant_id}/agents",
        json={"name": "Pasos vacíos", "steps": ["   "]},
    )
    too_many = auth_client.post(
        f"/api/tenants/{tenant_id}/agents",
        json={"name": "Muchos pasos", "steps": [f"pregunta {i}" for i in range(11)]},
    )

    assert duplicate.status_code == 409
    assert blank.status_code == 422
    assert too_many.status_code == 422


def test_otra_empresa_no_puede_usar_el_agente(auth_client, client) -> None:
    tenant_id, space_id = create_space(auth_client)
    upload(auth_client, tenant_id, space_id, "manual.pdf", "Filtro del taller.")
    agent = create_agent(auth_client, tenant_id, ["filtro"])
    other = client.post(
        "/api/auth/register",
        json={
            "email": "otra-empresa@ejemplo.com",
            "password": "clave-otra-123",
            "company_name": "Otra empresa",
        },
    ).json()
    headers = {"Authorization": f"Bearer {other['token']}"}

    denied = run_agent(client, tenant_id, agent["id"], headers)

    assert denied.status_code == 403
