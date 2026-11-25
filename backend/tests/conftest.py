"""Base aislada para las pruebas; no requiere un servidor PostgreSQL."""

from __future__ import annotations

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["KORVIA_STORAGE_DIR"] = tempfile.mkdtemp(prefix="korvia-test-storage-")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from korvia.database import Base, engine
from korvia.main import app


def _drop_all_tables() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def reset_test_database():
    _drop_all_tables()
    yield
    _drop_all_tables()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client):
    """Cliente ya registrado con una empresa propia y sesión activa."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "dueno@ejemplo.com",
            "password": "clave-segura-123",
            "company_name": "Empresa de prueba",
        },
    )
    assert response.status_code == 201, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client
