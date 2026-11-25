from io import BytesIO

import pymupdf as fitz

import korvia.main as main_module

REGISTRO = {
    "email": "auditor@ejemplo.com",
    "password": "clave-segura-123",
    "company_name": "Empresa auditada",
}


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_registro_e_inicio_de_sesion_quedan_registrados(client) -> None:
    registered = client.post("/api/auth/register", json=REGISTRO).json()
    headers = {"Authorization": f"Bearer {registered['token']}"}

    client.post(
        "/api/auth/login",
        json={"email": REGISTRO["email"], "password": REGISTRO["password"]},
    )
    response = client.get(f"/api/tenants/{registered['tenant']['id']}/audit", headers=headers)

    assert response.status_code == 200
    actions = [event["action"] for event in response.json()]
    assert "registro" in actions
    assert "inicio_sesion" in actions
    assert all(event["actor_email"] == REGISTRO["email"] for event in response.json())


def test_documentos_preguntas_y_agentes_dejan_huella(auth_client) -> None:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    space = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces", json={"name": "General"}
    ).json()
    auth_client.post(
        f"/api/tenants/{tenant_id}/spaces/{space['id']}/documents",
        files={"file": ("manual.pdf", BytesIO(make_pdf("Filtro cada seis meses.")), "application/pdf")},
    )
    auth_client.post(
        f"/api/tenants/{tenant_id}/ask", json={"question": "¿cada cuánto se cambia?"}
    )
    agent = auth_client.post(
        f"/api/tenants/{tenant_id}/agents",
        json={"name": "Revisión", "steps": ["filtro"]},
    ).json()
    auth_client.post(f"/api/tenants/{tenant_id}/agents/{agent['id']}/run", json={})

    events = auth_client.get(f"/api/tenants/{tenant_id}/audit").json()
    actions = [event["action"] for event in events]

    assert "subir_documento" in actions
    assert "pregunta" in actions
    assert "crear_agente" in actions
    assert "ejecutar_agente" in actions
    upload = next(event for event in events if event["action"] == "subir_documento")
    assert upload["target_type"] == "documento"
    assert "manual.pdf" in upload["summary"]
    assert upload["created_at"]


def test_espacios_y_agentes_guardan_su_id_en_la_auditoria(auth_client) -> None:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    space = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces", json={"name": "Taller"}
    ).json()
    agent = auth_client.post(
        f"/api/tenants/{tenant_id}/agents",
        json={"name": "Revisión", "steps": ["filtro"]},
    ).json()

    events = auth_client.get(f"/api/tenants/{tenant_id}/audit").json()
    espacio = next(event for event in events if event["action"] == "crear_espacio")
    agente = next(event for event in events if event["action"] == "crear_agente")

    assert espacio["target_id"] == space["id"]
    assert agente["target_id"] == agent["id"]


def test_la_sincronizacion_tambien_queda_registrada(auth_client, tmp_path, monkeypatch) -> None:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    space = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces", json={"name": "General"}
    ).json()
    folder = tmp_path / "entrada"
    folder.mkdir()
    (folder / "manual.pdf").write_bytes(make_pdf("Filtro del taller."))
    monkeypatch.setattr(main_module, "SYNC_ROOT", str(folder))

    auth_client.post(f"/api/tenants/{tenant_id}/spaces/{space['id']}/sync")
    events = auth_client.get(f"/api/tenants/{tenant_id}/audit").json()

    sync_event = next(event for event in events if event["action"] == "sincronizar")
    assert "1 creados" in sync_event["summary"]


def test_un_miembro_no_puede_ver_la_auditoria(auth_client, client) -> None:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "lector-audit@ejemplo.com",
            "password": "clave-lector-123",
            "company_name": "Otra empresa",
        },
    ).json()
    auth_client.post(
        f"/api/tenants/{tenant_id}/members",
        json={"email": "lector-audit@ejemplo.com", "role": "member"},
    )
    headers = {"Authorization": f"Bearer {registered['token']}"}

    response = client.get(f"/api/tenants/{tenant_id}/audit", headers=headers)

    assert response.status_code == 403


def test_el_limite_de_eventos_esta_acotado(auth_client) -> None:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]

    bad = auth_client.get(f"/api/tenants/{tenant_id}/audit?limit=0")
    good = auth_client.get(f"/api/tenants/{tenant_id}/audit?limit=10")

    assert bad.status_code == 422
    assert good.status_code == 200
