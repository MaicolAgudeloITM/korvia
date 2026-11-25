import json
from io import BytesIO
from unittest.mock import patch

import pytest

from korvia.embeddings import (
    EMBEDDING_DIM,
    EmbeddingError,
    LocalHashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_provider,
)


def test_el_proveedor_local_es_determinista_y_esta_normalizado() -> None:
    provider = LocalHashEmbeddingProvider()

    first = provider.embed(["El filtro se cambia cada seis meses."])[0]
    second = provider.embed(["El filtro se cambia cada seis meses."])[0]
    other = provider.embed(["Otro texto completamente distinto"])[0]

    assert len(first) == EMBEDDING_DIM
    assert first == second
    assert first != other
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_el_proveedor_por_defecto_es_local(monkeypatch) -> None:
    monkeypatch.delenv("KORVIA_EMBEDDING_PROVIDER", raising=False)

    assert isinstance(get_provider(), LocalHashEmbeddingProvider)


def test_openai_sin_clave_da_error_claro(monkeypatch) -> None:
    monkeypatch.setenv("KORVIA_EMBEDDING_PROVIDER", "openai")
    monkeypatch.delenv("KORVIA_OPENAI_API_KEY", raising=False)

    with pytest.raises(EmbeddingError, match="KORVIA_OPENAI_API_KEY"):
        get_provider()


def test_el_proveedor_openai_llama_a_la_api_y_valida_la_respuesta(monkeypatch) -> None:
    monkeypatch.setenv("KORVIA_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("KORVIA_OPENAI_API_KEY", "clave-de-prueba")
    provider = get_provider()
    assert isinstance(provider, OpenAIEmbeddingProvider)

    response = BytesIO(
        json.dumps(
            {
                "data": [
                    {
                        "index": 1,
                        "embedding": [0.5] * EMBEDDING_DIM,
                    },
                    {
                        "index": 0,
                        "embedding": [0.25] * EMBEDDING_DIM,
                    },
                ]
            }
        ).encode("utf-8")
    )
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        vectors = provider.embed(["primero", "segundo"])

    assert vectors[0] == [0.25] * EMBEDDING_DIM
    assert vectors[1] == [0.5] * EMBEDDING_DIM
    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer clave-de-prueba"
    body = json.loads(request.data)
    assert body["dimensions"] == EMBEDDING_DIM
