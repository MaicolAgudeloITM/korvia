from korvia.auth import LOGIN_MAX_FAILURES

CORREO = "bloqueo@ejemplo.com"
CLAVE = "clave-segura-123"


def _intentar(client, password: str):
    return client.post("/api/auth/login", json={"email": CORREO, "password": password})


def test_demasiados_intentos_fallidos_bloquean_el_acceso(client) -> None:
    client.post(
        "/api/auth/register",
        json={"email": CORREO, "password": CLAVE, "company_name": "Empresa bloqueada"},
    )
    for _ in range(LOGIN_MAX_FAILURES):
        assert _intentar(client, "clave-mala").status_code == 401

    bloqueado = _intentar(client, "clave-mala")
    correcto_pero_tarde = _intentar(client, CLAVE)

    assert bloqueado.status_code == 429
    assert correcto_pero_tarde.status_code == 429
    assert "Espera unos minutos" in bloqueado.json()["detail"]


def test_un_acierto_reinicia_el_contador(client) -> None:
    client.post(
        "/api/auth/register",
        json={"email": CORREO, "password": CLAVE, "company_name": "Empresa bloqueada"},
    )
    for _ in range(LOGIN_MAX_FAILURES - 1):
        assert _intentar(client, "clave-mala").status_code == 401
    assert _intentar(client, CLAVE).status_code == 200

    for _ in range(LOGIN_MAX_FAILURES - 1):
        assert _intentar(client, "clave-mala").status_code == 401
    assert _intentar(client, CLAVE).status_code == 200


def test_las_respuestas_llevan_cabeceras_de_seguridad(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
