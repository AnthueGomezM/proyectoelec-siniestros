"""Analizador de imágenes (Gemini) contra un transporte simulado.

Mismo enfoque que test_gemini_provider.py: la red de este proyecto no llega a
generativelanguage.googleapis.com, así que el contrato (qué se envía como
`inlineData`, qué se entiende de la respuesta JSON, y los fallos) se verifica con
httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from claims_agent.providers.base import ProviderProtocolError, ProviderTimeout, ProviderUnavailable
from claims_agent.providers.vision import GeminiImageAnalyzer, OfflineImageAnalyzer


def _analizador(handler, **kwargs):  # type: ignore[no-untyped-def]
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiImageAnalyzer(api_key="clave-de-prueba", client=cliente, **kwargs)


def _respuesta_json(datos: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(datos)}], "role": "model"},
                            "finishReason": "STOP"}]}


# --------------------------------------------------------------------- petición

async def test_envia_la_imagen_como_inlinedata():
    capturado: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["body"] = json.loads(request.content)
        return httpx.Response(200, json=_respuesta_json({
            "danio_visible": True, "severidad": "MODERADO", "confianza": 0.7,
            "descripcion": "Golpe en la puerta.",
        }))

    analizador = _analizador(handler)
    resultado = await analizador.analyze(image_bytes=b"foto", mime_type="image/jpeg",
                                         claim_type="AUTO", description="Choque leve")

    parte_imagen = capturado["body"]["contents"][0]["parts"][1]["inlineData"]
    assert parte_imagen["mimeType"] == "image/jpeg"
    assert parte_imagen["data"]  # base64, no vacío
    assert capturado["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert resultado["severidad"] == "MODERADO"
    assert resultado["confianza"] == 0.7
    assert resultado["danio_visible"] is True


# --------------------------------------------------------------------- respuesta

async def test_normaliza_severidad_y_confianza_invalidas():
    analizador = _analizador(lambda r: httpx.Response(200, json=_respuesta_json({
        "severidad": "CATASTROFICO", "confianza": "no-es-numero",
    })))
    resultado = await analizador.analyze(image_bytes=b"x", mime_type="image/png",
                                         claim_type="HOME", description="")
    assert resultado["severidad"] == "INDETERMINADO"
    assert resultado["confianza"] == 0.0


async def test_json_invalido_es_error_de_protocolo():
    analizador = _analizador(lambda r: httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"text": "esto no es json"}]}, "finishReason": "STOP"}],
    }))
    with pytest.raises(ProviderProtocolError):
        await analizador.analyze(image_bytes=b"x", mime_type="image/png", claim_type="HOME", description="")


# --------------------------------------------------------------------- fallos

async def test_429_se_reintenta_una_vez_y_luego_se_rinde():
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        return httpx.Response(429, json={"error": {"message": "Quota exceeded"}})

    analizador = _analizador(handler, max_retries=1)
    with pytest.raises(ProviderUnavailable, match="429"):
        await analizador.analyze(image_bytes=b"x", mime_type="image/png", claim_type="HOME", description="")
    assert intentos["n"] == 2


async def test_timeout_de_red():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("demasiado lento", request=request)

    analizador = _analizador(handler)
    with pytest.raises(ProviderTimeout):
        await analizador.analyze(image_bytes=b"x", mime_type="image/png", claim_type="HOME", description="")


def test_no_arranca_sin_clave():
    with pytest.raises(ValueError, match="API key"):
        GeminiImageAnalyzer(api_key="")


# --------------------------------------------------------------------- degradación

async def test_offline_declara_revision_manual_sin_red():
    analizador = OfflineImageAnalyzer()
    resultado = await analizador.analyze(image_bytes=b"x", mime_type="image/png",
                                         claim_type="AUTO", description="")
    assert resultado["severidad"] == "INDETERMINADO"
    assert resultado["confianza"] == 0.0
