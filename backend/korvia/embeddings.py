"""Proveedores de embeddings intercambiables.

Por defecto se usa un proveedor local determinista que sirve para probar el
flujo completo sin red ni credenciales. **No es semántica real**: agrupa texto
parecido por palabras. Para búsqueda semántica de verdad, configurar
KORVIA_EMBEDDING_PROVIDER=openai con una clave API.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Protocol


EMBEDDING_DIM = 384


class EmbeddingError(RuntimeError):
    """El proveedor de embeddings no pudo generar los vectores."""


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbeddingProvider:
    """Embedding determinista basado en hash de palabras; solo para desarrollo."""

    name = "local-hash"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_embed_one(text) for text in texts]


class OpenAIEmbeddingProvider:
    """Proveedor compatible con la API de embeddings de OpenAI."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._url = base_url.rstrip("/") + "/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps(
            {
                "model": self._model,
                "input": texts,
                "dimensions": EMBEDDING_DIM,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
            items = sorted(body["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in items]
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, TimeoutError) as exc:
            raise EmbeddingError(f"No pude obtener embeddings del proveedor: {exc}") from exc

        if len(vectors) != len(texts):
            raise EmbeddingError("El proveedor devolvió una cantidad de vectores incorrecta.")
        for vector in vectors:
            if len(vector) != EMBEDDING_DIM:
                raise EmbeddingError("El proveedor devolvió vectores de otra dimensión.")
        return vectors


def get_provider() -> EmbeddingProvider:
    selected = os.getenv("KORVIA_EMBEDDING_PROVIDER", "local-hash").strip().lower()
    if selected == "local-hash":
        return LocalHashEmbeddingProvider()
    if selected == "openai":
        api_key = os.getenv("KORVIA_OPENAI_API_KEY", "").strip()
        if not api_key:
            raise EmbeddingError("Falta KORVIA_OPENAI_API_KEY para usar el proveedor OpenAI.")
        model = os.getenv("KORVIA_OPENAI_MODEL", "text-embedding-3-small")
        base_url = os.getenv("KORVIA_OPENAI_BASE_URL", "https://api.openai.com/v1")
        return OpenAIEmbeddingProvider(api_key, model, base_url)
    raise EmbeddingError(f"Proveedor de embeddings desconocido: {selected}")


def _embed_one(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    for token in re.findall(r"\w+", text.lower()):
        if len(token) < 2:
            continue
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
