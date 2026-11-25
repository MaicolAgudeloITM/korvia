"""Lectura segura de la carpeta local que se va a sincronizar."""

from __future__ import annotations

from pathlib import Path


class SyncError(RuntimeError):
    """La carpeta configurada no se puede sincronizar."""


def collect_source_files(
    root: Path, max_bytes: int, supported_extensions: set[str]
) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Devuelve (archivos, demasiado_grandes) usando rutas relativas con '/'."""
    if not root.is_dir():
        raise SyncError(f"La carpeta de sincronización no existe: {root}")

    root = root.resolve()
    files: list[tuple[str, bytes]] = []
    oversized: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in supported_extensions:
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except ValueError:
            # Un enlace apunta fuera de la carpeta permitida.
            continue
        relative = path.relative_to(root).as_posix()
        if path.stat().st_size > max_bytes:
            oversized.append(relative)
            continue
        files.append((relative, path.read_bytes()))
    return files, oversized
