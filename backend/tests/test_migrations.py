"""Comprueba que las migraciones reproducen el esquema de los modelos."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import UniqueConstraint, create_engine, inspect

from korvia import models  # noqa: F401 — asegura que las tablas estén registradas.
from korvia.database import ALEMBIC_INI, Base


def test_las_claves_foraneas_compuestas_tienen_columnas_unicas() -> None:
    """PostgreSQL exige que el destino de una FK compuesta sea único."""
    for table in Base.metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            if len(constraint.elements) < 2:
                continue
            destino = {element.column for element in constraint.elements}
            assert any(
                set(unique.columns) == destino
                for unique in constraint.referred_table.constraints
                if isinstance(unique, UniqueConstraint)
            ), f"{constraint.name} apunta a columnas que no son únicas"


def test_la_migracion_inicial_crea_el_esquema(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migracion.db'}"
    engine = create_engine(database_url)
    config = Config(str(ALEMBIC_INI))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {
            "alembic_version",
            "tenants",
            "knowledge_spaces",
            "documents",
            "document_chunks",
        } <= tables

        # No debe quedar ningún cambio sin reflejar en un archivo de migración.
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "documents" not in tables
        assert "tenants" not in tables

    engine.dispose()
