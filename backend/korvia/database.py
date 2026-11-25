"""Conexión a PostgreSQL en Docker y SQLite para pruebas locales."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/korvia.db")

engine_options: dict[str, object] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
    if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
        engine_options["poolclass"] = StaticPool
    else:
        database_file = DATABASE_URL.removeprefix("sqlite:///").split("?", 1)[0]
        Path(database_file).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


class Base(DeclarativeBase):
    pass


def _alembic_config(connection) -> Config:
    config = Config(str(ALEMBIC_INI))
    # env.py reutiliza esta conexión en lugar de abrir una propia.
    config.attributes["connection"] = connection
    return config


def initialize_database() -> None:
    """Prepara el esquema y deja constancia de la revisión aplicada.

    Una base nueva se crea desde los modelos y se marca como "ya migrada".
    Una base que ya tiene historial de Alembic recibe las migraciones pendientes.
    """
    from korvia import models  # noqa: F401 — registra los modelos en Base.

    with engine.begin() as connection:
        config = _alembic_config(connection)
        tables = inspect(connection).get_table_names()
        if "alembic_version" in tables:
            command.upgrade(config, "head")
        elif not DATABASE_URL.startswith("postgresql"):
            # SQLite de pruebas: crear desde los modelos es más rápido.
            Base.metadata.create_all(bind=connection)
            command.stamp(config, "head")
        else:
            # En PostgreSQL las migraciones crean la extensión vector y el índice.
            command.upgrade(config, "head")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
