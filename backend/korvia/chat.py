"""Proveedores de respuesta para RAG.

Por defecto se usa un proveedor extractivo: devuelve los fragmentos recuperados
con sus citas, sin inventar nada y sin llamar a ningún servicio externo.
Para respuestas generadas por un modelo, configurar KORVIA_CHAT_PROVIDER=openai
con un endpoint compatible con la API de chat de OpenAI.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, Sequence


NO_EVIDENCE_ANSWER = "No encontré información suficiente en los documentos de esta empresa."

SYSTEM_PROMPT = (
    "Eres el asistente de KORVIA. Responde únicamente con la información de los "
    "fragmentos numerados que recibes. Cita cada afirmación con su número, por "
    "ejemplo [1]. No inventes datos, fechas ni documentos. Si los fragmentos no "
    "contienen la respuesta, responde exactamente: " + NO_EVIDENCE_ANSWER
)


class ChatError(RuntimeError):
    """El proveedor de respuestas no pudo generar una respuesta."""


@dataclass(frozen=True)
class ChatSource:
    number: int
    document_id: str
    filename: str
    version: int
    position: int
    score: float


class ChatProvider(Protocol):
    name: str

    def answer(self, question: str, context: str, sources: Sequence[ChatSource]) -> str: ...


class ExtractiveChatProvider:
    """Sin modelo de IA: muestra los fragmentos encontrados con sus citas."""

    name = "extractive"

    def answer(self, question: str, context: str, sources: Sequence[ChatSource]) -> str:
        if not sources:
            return NO_EVIDENCE_ANSWER
        return "Esto es lo que dice la documentación encontrada:\n\n" + context


class OpenAIChatProvider:
    """Proveedor compatible con el endpoint de chat de OpenAI."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._url = base_url.rstrip("/") + "/chat/completions"

    def answer(self, question: str, context: str, sources: Sequence[ChatSource]) -> str:
        payload = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Pregunta: {question}\n\nFragmentos disponibles:\n{context}",
                    },
                ],
                "temperature": 0,
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
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.load(response)
            answer = body["choices"][0]["message"]["content"].strip()
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            KeyError,
            IndexError,
            ValueError,
            TimeoutError,
        ) as exc:
            raise ChatError(f"No pude obtener una respuesta del proveedor: {exc}") from exc
        if not answer:
            raise ChatError("El proveedor devolvió una respuesta vacía.")
        return answer


def get_chat_provider() -> ChatProvider:
    selected = os.getenv("KORVIA_CHAT_PROVIDER", "extractive").strip().lower()
    if selected == "extractive":
        return ExtractiveChatProvider()
    if selected == "openai":
        api_key = os.getenv("KORVIA_CHAT_API_KEY", "").strip()
        if not api_key:
            raise ChatError("Falta KORVIA_CHAT_API_KEY para usar el proveedor de chat OpenAI.")
        model = os.getenv("KORVIA_CHAT_MODEL", "gpt-4o-mini")
        base_url = os.getenv("KORVIA_CHAT_BASE_URL", "https://api.openai.com/v1")
        return OpenAIChatProvider(api_key, model, base_url)
    raise ChatError(f"Proveedor de chat desconocido: {selected}")
