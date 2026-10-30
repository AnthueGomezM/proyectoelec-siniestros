"""Proveedor Gemini contra un transporte simulado.

La red de este proyecto no llega a generativelanguage.googleapis.com desde CI, así que
el contrato con la API se verifica con httpx.MockTransport: se comprueba qué se envía
(formato de `contents`, `functionDeclarations`, `functionResponse`) y qué se entiende
de la respuesta, incluidos los fallos. Es la prueba de que el mapeo es correcto; la
llamada real se valida el día de la demo con la clave activa (`./run.sh check`).
"""

from __future__ import annotations

import json

import httpx
import pytest

from claims_agent.providers.base import (
    Msg,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
    ToolCall,
    ToolSpec,
)
from claims_agent.providers.gemini import GeminiProvider

HERRAMIENTAS = [ToolSpec(
    name="consultar_poliza",
    description="Consulta la póliza del cliente.",
    parameters={"type": "object", "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"]},
)]


def _provider(handler, **kwargs):  # type: ignore[no-untyped-def]
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiProvider(api_key="clave-de-prueba", client=cliente, **kwargs)


def _respuesta_texto(texto: str) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": texto}], "role": "model"}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30, "totalTokenCount": 150},
    }


def _respuesta_herramienta(nombre: str, args: dict) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"functionCall": {"name": nombre, "args": args}}],
                                    "role": "model"}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 18},
    }


# --------------------------------------------------------------------- petición

async def test_envia_el_formato_que_espera_gemini():
    capturado: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        capturado["body"] = json.loads(request.content)
        return httpx.Response(200, json=_respuesta_texto("listo"))

    provider = _provider(handler, model="gemini-2.0-flash")
    await provider.complete(
        system="Eres el asistente de triaje.",
        messages=[
            Msg(role="user", text="Tria este siniestro"),
            Msg(role="model", tool_calls=(ToolCall("consultar_poliza", {"customer_id": "CUST-1"}),)),
            Msg(role="tool", tool_name="consultar_poliza", tool_result={"encontrada": True}),
        ],
        tools=HERRAMIENTAS, max_output_tokens=512, timeout_seconds=10,
    )

    assert "models/gemini-2.0-flash:generateContent" in capturado["url"]
    assert "key=clave-de-prueba" in capturado["url"]
    cuerpo = capturado["body"]
    assert cuerpo["systemInstruction"]["parts"][0]["text"].startswith("Eres el asistente")
    assert cuerpo["generationConfig"]["maxOutputTokens"] == 512
    assert cuerpo["generationConfig"]["temperature"] == 0.0
    # Las herramientas viajan como functionDeclarations
    declaraciones = cuerpo["tools"][0]["functionDeclarations"]
    assert declaraciones[0]["name"] == "consultar_poliza"
    assert declaraciones[0]["parameters"]["required"] == ["customer_id"]
    # El historial conserva los tres tipos de turno
    roles = [c["role"] for c in cuerpo["contents"]]
    assert roles == ["user", "model", "user"]
    assert "functionCall" in cuerpo["contents"][1]["parts"][0]
    assert cuerpo["contents"][2]["parts"][0]["functionResponse"]["name"] == "consultar_poliza"


# --------------------------------------------------------------------- respuesta

async def test_entiende_una_llamada_a_herramienta():
    provider = _provider(lambda r: httpx.Response(
        200, json=_respuesta_herramienta("consultar_poliza", {"customer_id": "CUST-000123"})))

    respuesta = await provider.complete(system="s", messages=[Msg(role="user", text="hola")],
                                        tools=HERRAMIENTAS, max_output_tokens=256, timeout_seconds=5)

    assert respuesta.wants_tools
    assert respuesta.tool_calls[0].name == "consultar_poliza"
    assert respuesta.tool_calls[0].arguments == {"customer_id": "CUST-000123"}
    assert respuesta.tokens_in == 200 and respuesta.tokens_out == 18


async def test_entiende_una_respuesta_de_texto():
    provider = _provider(lambda r: httpx.Response(200, json=_respuesta_texto("Urgencia crítica confirmada.")))

    respuesta = await provider.complete(system="s", messages=[Msg(role="user", text="hola")],
                                        tools=[], max_output_tokens=256, timeout_seconds=5)

    assert not respuesta.wants_tools
    assert respuesta.text == "Urgencia crítica confirmada."
    assert respuesta.raw_finish_reason == "STOP"


# --------------------------------------------------------------------- fallos

async def test_429_se_reintenta_una_vez_y_luego_se_rinde():
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        return httpx.Response(429, json={"error": {"message": "Quota exceeded"}})

    provider = _provider(handler, max_retries=1)
    with pytest.raises(ProviderUnavailable, match="429"):
        await provider.complete(system="s", messages=[Msg(role="user", text="hola")],
                                tools=[], max_output_tokens=256, timeout_seconds=5)
    assert intentos["n"] == 2, "un intento original y un reintento"


async def test_429_pasajero_se_recupera_en_el_reintento():
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        if intentos["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json=_respuesta_texto("ok"))

    provider = _provider(handler, max_retries=1)
    respuesta = await provider.complete(system="s", messages=[Msg(role="user", text="hola")],
                                        tools=[], max_output_tokens=256, timeout_seconds=5)
    assert respuesta.text == "ok"


async def test_clave_invalida_no_se_reintenta():
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})

    provider = _provider(handler)
    with pytest.raises(ProviderUnavailable, match="API key not valid"):
        await provider.complete(system="s", messages=[Msg(role="user", text="h")],
                                tools=[], max_output_tokens=256, timeout_seconds=5)
    assert intentos["n"] == 1


async def test_timeout_de_red():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("demasiado lento", request=request)

    provider = _provider(handler)
    with pytest.raises(ProviderTimeout):
        await provider.complete(system="s", messages=[Msg(role="user", text="h")],
                                tools=[], max_output_tokens=256, timeout_seconds=1)


async def test_red_caida():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin DNS", request=request)

    provider = _provider(handler)
    with pytest.raises(ProviderUnavailable):
        await provider.complete(system="s", messages=[Msg(role="user", text="h")],
                                tools=[], max_output_tokens=256, timeout_seconds=1)


async def test_cuerpo_sin_candidatos_es_error_de_protocolo():
    provider = _provider(lambda r: httpx.Response(200, json={"usageMetadata": {}}))
    with pytest.raises(ProviderProtocolError, match="candidates"):
        await provider.complete(system="s", messages=[Msg(role="user", text="h")],
                                tools=[], max_output_tokens=256, timeout_seconds=5)


async def test_respuesta_bloqueada_por_filtros():
    provider = _provider(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ProviderUnavailable, match="SAFETY"):
        await provider.complete(system="s", messages=[Msg(role="user", text="h")],
                                tools=[], max_output_tokens=256, timeout_seconds=5)


async def test_cuerpo_que_no_es_json():
    provider = _provider(lambda r: httpx.Response(200, text="<html>502 Bad Gateway</html>"))
    with pytest.raises(ProviderProtocolError):
        await provider.complete(system="s", messages=[Msg(role="user", text="h")],
                                tools=[], max_output_tokens=256, timeout_seconds=5)


def test_no_arranca_sin_clave():
    with pytest.raises(ValueError, match="API key"):
        GeminiProvider(api_key="")
