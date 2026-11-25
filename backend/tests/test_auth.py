from io import BytesIO

import pymupdf as fitz

from korvia.database import SessionLocal
from korvia.models import User


REGISTRO = {
    "email": "dueno@ejemplo.com",
    "password": "clave-segura-123",
    "company_name": "Empresa de prueba",
}


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_registro_crea_empresa_usuario_dueno_y_sesion(client) -> None:
    response = client.post("/api/auth/register", json=REGISTRO)

    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == "dueno@ejemplo.com"
    assert data["tenant"]["name"] == "Empresa de prueba"
    assert data["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200
    assert me.json()["memberships"] == [
        {
            "tenant_id": data["tenant"]["id"],
            "tenant_name": "Empresa de prueba",
            "role": "owner",
        }
    ]

    with SessionLocal() as db:
        user = db.query(User).filter_by(email="dueno@ejemplo.com").one()
        assert user.password_hash != REGISTRO["password"]
        assert REGISTRO["password"] not in user.password_hash


def test_no_se_puede_registrar_el_mismo_correo_dos_veces(client) -> None:
    first = client.post("/api/auth/register", json=REGISTRO)
    second = client.post("/api/auth/register", json=REGISTRO)

    assert first.status_code == 201
    assert second.status_code == 409


def test_login_devuelve_token_y_rechaza_clave_incorrecta(client) -> None:
    client.post("/api/auth/register", json=REGISTRO)

    correcto = client.post(
        "/api/auth/login", json={"email": REGISTRO["email"], "password": REGISTRO["password"]}
    )
    incorrecto = client.post(
        "/api/auth/login", json={"email": REGISTRO["email"], "password": "mala-clave"}
    )
    desconocido = client.post(
        "/api/auth/login", json={"email": "no@existe.com", "password": "mala-clave"}
    )

    assert correcto.status_code == 200
    assert correcto.json()["token"]
    assert incorrecto.status_code == 401
    assert desconocido.status_code == 401


def test_las_rutas_privadas_requieren_sesion(client) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/tenants", json={"name": "Otra"}).status_code == 401
    assert client.get("/api/tenants/cualquiera/spaces").status_code == 401
    assert client.post(
        "/api/documents/inspect",
        files={"file": ("manual.pdf", BytesIO(make_pdf("texto")), "application/pdf")},
    ).status_code == 401


def test_token_invalido_y_logout_cierran_la_sesion(client) -> None:
    token = client.post("/api/auth/register", json=REGISTRO).json()["token"]

    assert client.get("/api/auth/me", headers={"Authorization": "Bearer inventado"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    salida = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert salida.status_code == 204
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_el_dueno_puede_agregar_miembros_y_el_miembro_solo_consulta(auth_client, client) -> None:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]

    otro = client.post(
        "/api/auth/register",
        json={
            "email": "miembro@ejemplo.com",
            "password": "clave-miembro-123",
            "company_name": "Empresa del miembro",
        },
    ).json()
    headers_miembro = {"Authorization": f"Bearer {otro['token']}"}

    alta = auth_client.post(
        f"/api/tenants/{tenant_id}/members",
        json={"email": "miembro@ejemplo.com", "role": "member"},
    ).json()
    assert alta["role"] == "member"

    lista = auth_client.get(f"/api/tenants/{tenant_id}/members")
    assert len(lista.json()["members"]) == 2

    espacio = auth_client.post(
        f"/api/tenants/{tenant_id}/spaces", json={"name": "General"}
    ).json()
    assert client.get(
        f"/api/tenants/{tenant_id}/spaces", headers=headers_miembro
    ).status_code == 200

    sin_permiso = client.post(
        f"/api/tenants/{tenant_id}/spaces",
        json={"name": "No permitido"},
        headers=headers_miembro,
    )
    subida = client.post(
        f"/api/tenants/{tenant_id}/spaces/{espacio['id']}/documents",
        files={"file": ("manual.pdf", BytesIO(make_pdf("texto")), "application/pdf")},
        headers=headers_miembro,
    )
    gestionar = client.get(
        f"/api/tenants/{tenant_id}/members", headers=headers_miembro
    )

    assert sin_permiso.status_code == 403
    assert subida.status_code == 403
    assert gestionar.status_code == 403


def test_no_se_puede_agregar_a_quien_ya_pertenece(auth_client) -> None:
    tenant_id = auth_client.get("/api/auth/me").json()["memberships"][0]["tenant_id"]

    respuesta = auth_client.post(
        f"/api/tenants/{tenant_id}/members",
        json={"email": "dueno@ejemplo.com", "role": "member"},
    )

    assert respuesta.status_code == 409
