"""Almacenamiento local de archivos originales para el prototipo."""

from __future__ import annotations

import os
from pathlib import Path


def _storage_root() -> Path:
    return Path(os.getenv("KORVIA_STORAGE_DIR", "./data/uploads")).resolve()


def save_original(
    *,
    tenant_id: str,
    space_id: str,
    document_id: str,
    version_number: int,
    extension: str,
    content: bytes,
) -> str:
    """Guarda cada versión con su propio nombre, sin sobrescribir la anterior."""
    root = _storage_root()
    relative_path = Path(tenant_id) / space_id / f"{document_id}_v{version_number}{extension}"
    destination = (root / relative_path).resolve()
    if root not in destination.parents:
        raise ValueError("La ruta de almacenamiento no es válida.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    return relative_path.as_posix()


def remove_original(storage_key: str) -> None:
    root = _storage_root()
    destination = (root / Path(storage_key)).resolve()
    if root not in destination.parents:
        raise ValueError("La ruta de almacenamiento no es válida.")
    if destination.exists():
        destination.unlink()
