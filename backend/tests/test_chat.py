import json
from io import BytesIO
from unittest.mock import patch

import pytest

from korvia.chat import (
    NO_EVIDENCE_ANSWER,
    SYSTEM_PROMPT,
    ChatError,
    ChatSource,
    ExtractiveChatProvider,
    OpenAIChatProvider,
    get_chat_provider,
)


def _source() -> ChatSource:
    return ChatSource(
        number=1,
        document_id="d1",
        filename="manual.pdf",
        version=1,
        position=0,
        score=0.5,
    )


def test_el_proveedor_extractivo_muestra_el_contexto_con_citas() -> None:
    provider = ExtractiveChatProvider()

    assert provider.answer("¿qué dice?", "[1] El filtro se cambia cada seis meses.", [_source()]) == (
        "Esto es lo que dice la documentación encontrada:\n\n"
        "[1] El filtro se cambia cada seis meses."
    )
    assert provider.answer("¿qué dice?", "", []) == NO_EVIDENCE_ANSWER


def test_el_proveedor_por_defecto_es_extractivo(monkeypatch) -> None:
    monkeypatch.delenv("KORVIA_CHAT_PROVIDER", raising=False)

    assert isinstance(get_chat_provider(), ExtractiveChatProvider)


def test_openai_sin_clave_da_error_claro(monkeypatch) -> None:
    monkeypatch.setenv("KORVIA_CHAT_PROVIDER", "openai")
    monkeypatch.delenv("KORVIA_CHAT_API_KEY", raising=False)

    with pytest.raises(ChatError, match="KORVIA_CHAT_API_KEY"):
        get_chat_provider()


def test_el_proveedor_openai_envia_el_contexto_y_devuelve_la_respuesta(monkeypatch) -> None:
    monkeypatch.setenv("KORVIA_CHAT_PROVIDER", "openai")
    monkeypatch.setenv("KORVIA_CHAT_API_KEY", "clave-de-prueba")
    provider = get_chat_provider()
    assert isinstance(provider, OpenAIChatProvider)

    response = BytesIO(
        json.dumps({"choices": [{"message": {"content": " Respuesta [1]. "}}]}).encode("utf-8")
    )
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        answer = provider.answer("¿qué dice?", "[1] Texto del fragmento.", [_source()])

    assert answer == "Respuesta [1]."
    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer clave-de-prueba"
    body = json.loads(request.data)
    assert body["messages"][0]["content"] == SYSTEM_PROMPT
    assert "[1] Texto del fragmento." in body["messages"][1]["content"]
    assert body["temperature"] == 0


def test_el_proveedor_openai_rechaza_una_respuesta_vacia(monkeypatch) -> None:
    monkeypatch.setenv("KORVIA_CHAT_PROVIDER", "openai")
    monkeypatch.setenv("KORVIA_CHAT_API_KEY", "clave-de-prueba")
    provider = get_chat_provider()
    response = BytesIO(
        json.dumps({"choices": [{"message": {"content": "   "}}]}).encode("utf-8")
    )

    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(ChatError, match="vacía"):
            provider.answer("¿qué dice?", "[1] Texto.", [_source()])
