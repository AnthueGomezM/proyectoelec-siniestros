"""Proveedor Google Gemini (API REST `generateContent`).

Se habla HTTP directo con `httpx` en vez de usar el SDK oficial: son ~130 líneas, el
contrato de la API es estable y evitamos arrastrar una dependencia grande con sus
propias versiones de protobuf. Además deja a la vista exactamente qué se envía, que
es justo lo que hay que poder explicar en la sustentación.

Mapeo de nuestro historial neutro al formato de Gemini:

    Msg(role="user",  text=...)                -> {"role": "user",  "parts": [{"text": ...}]}
    Msg(role="model", tool_calls=[...])        -> {"role": "model", "parts": [{"functionCall": {...}}]}
    Msg(role="tool",  tool_name, tool_result)  -> {"role": "user",  "parts": [{"functionResponse": {...}}]}

Gemini devuelve las llamadas a herramienta como `functionCall` dentro de
`candidates[0].content.parts`, y el consumo de tokens en `usageMetadata`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from claims_agent.providers.base import (
    LLMProvider,
    LLMResponse,
    Msg,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
    ToolCall,
    ToolSpec,
)

log = logging.getLogger(__name__)

#: Códigos que significan "vuelve a intentar más tarde" (cuota o indisponibilidad).
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash",
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 temperature: float = 0.0, client: httpx.AsyncClient | None = None,
                 max_retries: int = 1) -> None:
        if not api_key:
            raise ValueError("GeminiProvider requiere una API key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._max_retries = max_retries

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ petición

    async def complete(self, *, system: str, messages: list[Msg], tools: list[ToolSpec],
                       max_output_tokens: int, timeout_seconds: float) -> LLMResponse:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [_to_content(m) for m in messages],
            "generationConfig": {
                "temperature": self._temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if tools:
            body["tools"] = [{
                "functionDeclarations": [
                    {"name": t.name, "description": t.description, "parameters": t.parameters}
                    for t in tools
                ]
            }]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        url = f"{self._base_url}/models/{self._model}:generateContent"
        attempt = 0
        while True:
            try:
                response = await self._client.post(
                    url,
                    params={"key": self._api_key},
                    json=body,
                    timeout=timeout_seconds,
                    headers={"Content-Type": "application/json"},
                )
            except httpx.TimeoutException as exc:
                raise ProviderTimeout(f"Gemini no respondió en {timeout_seconds}s") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(f"No se pudo contactar a Gemini: {type(exc).__name__}") from exc

            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                attempt += 1
                wait = min(2.0, 0.8 * attempt)
                log.warning("Gemini respondió %s; reintento %s en %.1fs",
                            response.status_code, attempt, wait,
                            extra={"status": response.status_code, "attempt": attempt})
                await asyncio.sleep(wait)
                continue
            break

        if response.status_code in RETRYABLE_STATUS:
            raise ProviderUnavailable(f"Gemini respondió {response.status_code} tras {attempt} reintento(s)")
        if response.status_code >= 400:
            # 400/401/403: clave inválida o petición mal formada. No se reintenta.
            detail = _error_detail(response)
            raise ProviderUnavailable(f"Gemini rechazó la petición ({response.status_code}): {detail}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderProtocolError("Gemini devolvió un cuerpo que no es JSON") from exc

        return self._parse(payload)

    # ------------------------------------------------------------------ respuesta

    def _parse(self, payload: dict[str, Any]) -> LLMResponse:
        if "promptFeedback" in payload and not payload.get("candidates"):
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "desconocido")
            raise ProviderUnavailable(f"Gemini bloqueó la petición por filtros de seguridad: {reason}")

        candidates = payload.get("candidates") or []
        if not candidates:
            raise ProviderProtocolError("La respuesta de Gemini no trae 'candidates'")

        candidate = candidates[0]
        parts = ((candidate.get("content") or {}).get("parts")) or []
        texts: list[str] = []
        calls: list[ToolCall] = []
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"] or {}
                nombre = fc.get("name")
                if not nombre:
                    raise ProviderProtocolError("functionCall sin nombre de herramienta")
                args = fc.get("args")
                calls.append(ToolCall(name=nombre, arguments=args if isinstance(args, dict) else {},
                                      signature=part.get("thoughtSignature")))
            elif "text" in part and part["text"]:
                texts.append(part["text"])

        usage = payload.get("usageMetadata") or {}
        return LLMResponse(
            text="\n".join(texts).strip() or None,
            tool_calls=tuple(calls),
            tokens_in=int(usage.get("promptTokenCount") or 0),
            tokens_out=int(usage.get("candidatesTokenCount") or 0),
            model=self._model,
            raw_finish_reason=candidate.get("finishReason"),
        )


# ---------------------------------------------------------------------------- utilidades

def _to_content(msg: Msg) -> dict[str, Any]:
    if msg.role == "tool":
        return {
            "role": "user",
            "parts": [{"functionResponse": {
                "name": msg.tool_name,
                "response": msg.tool_result or {},
            }}],
        }
    if msg.role == "model":
        if msg.tool_calls:
            return {
                "role": "model",
                "parts": [_call_part(c, primera=(i == 0)) for i, c in enumerate(msg.tool_calls)],
            }
        return {"role": "model", "parts": [{"text": msg.text or ""}]}
    return {"role": "user", "parts": [{"text": msg.text or ""}]}


#: Valor documentado por Google para llamadas que no vienen del modelo (p. ej. un
#: historial reconstruido tras una aprobación humana) y por tanto no tienen firma real.
_FIRMA_OMITIDA = "skip_thought_signature_validator"


def _call_part(call: ToolCall, primera: bool) -> dict[str, Any]:
    part: dict[str, Any] = {"functionCall": {"name": call.name, "args": call.arguments}}
    # Gemini 3 exige la firma en la primera llamada de cada turno; en paralelas solo la primera la trae.
    if call.signature or primera:
        part["thoughtSignature"] = call.signature or _FIRMA_OMITIDA
    return part


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    message = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
    return (message or response.text)[:200]
