"""Analizador de imágenes adjuntas a un siniestro.

Deliberadamente NO es parte de `providers/base.py`: el bucle agéntico habla con el
modelo en turnos de texto + function calling, y mezclar una imagen en ese historial
lo acoplaría a un proveedor multimodal concreto. En cambio, el daño visible se analiza
con una llamada de un solo turno, sin herramientas, detrás de la herramienta propia
`analizar_imagen_dano` (ver `agent/tools.py`). Mismo proveedor hoy (Gemini), interfaz
separada: cambiarlo no toca el bucle ni las otras herramientas.
"""

from __future__ import annotations

import abc
import asyncio
import base64
import json
import logging
from typing import Any

import httpx

from claims_agent.providers.base import ProviderProtocolError, ProviderTimeout, ProviderUnavailable

log = logging.getLogger(__name__)

#: Códigos que significan "vuelve a intentar más tarde" (cuota o indisponibilidad).
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

_NIVELES_SEVERIDAD = {"LEVE", "MODERADO", "SEVERO", "INDETERMINADO"}

_PROMPT = """\
Eres un perito de seguros. Observa la imagen adjunta a un siniestro de tipo {tipo} \
cuyo relato es: "{descripcion}"

Responde EXCLUSIVAMENTE con un objeto JSON (sin texto adicional, sin marcadores de \
código) con estos campos:
{{
  "danio_visible": true o false,
  "tipo_danio": "texto corto describiendo qué se ve dañado, o null si no aplica",
  "severidad": "LEVE", "MODERADO", "SEVERO" o "INDETERMINADO",
  "coincide_con_relato": true, false o null si no se puede determinar,
  "descripcion": "1-2 frases en español describiendo lo que se observa en la imagen",
  "confianza": número entre 0.0 y 1.0
}}

Si la imagen no permite evaluar nada (borrosa, no corresponde a un siniestro, etc.), \
usa severidad "INDETERMINADO" y confianza baja."""


class ImageAnalyzer(abc.ABC):
    """Contrato que debe cumplir cualquier analizador de imágenes de siniestros."""

    name: str = "base"

    @abc.abstractmethod
    async def analyze(self, *, image_bytes: bytes, mime_type: str,
                      claim_type: str, description: str) -> dict[str, Any]:
        """Devuelve la evaluación de la imagen, ya en español y con claves fijas."""

    async def aclose(self) -> None:  # pragma: no cover - por defecto no hay nada que cerrar
        return None


class GeminiImageAnalyzer(ImageAnalyzer):
    name = "gemini-vision"

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash",
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 client: httpx.AsyncClient | None = None, timeout_seconds: float = 15.0,
                 max_retries: int = 1) -> None:
        if not api_key:
            raise ValueError("GeminiImageAnalyzer requiere una API key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def analyze(self, *, image_bytes: bytes, mime_type: str,
                      claim_type: str, description: str) -> dict[str, Any]:
        prompt = _PROMPT.format(tipo=claim_type or "desconocido",
                                descripcion=description or "(sin relato)")
        body = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": mime_type,
                                    "data": base64.b64encode(image_bytes).decode("ascii")}},
                ],
            }],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }

        url = f"{self._base_url}/models/{self._model}:generateContent"
        attempt = 0
        while True:
            try:
                response = await self._client.post(
                    url, params={"key": self._api_key}, json=body, timeout=self._timeout,
                    headers={"Content-Type": "application/json"},
                )
            except httpx.TimeoutException as exc:
                raise ProviderTimeout(f"El análisis de imagen no respondió en {self._timeout}s") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(
                    f"No se pudo contactar al servicio de visión: {type(exc).__name__}") from exc

            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                attempt += 1
                await asyncio.sleep(min(2.0, 0.8 * attempt))
                continue
            break

        if response.status_code in RETRYABLE_STATUS:
            raise ProviderUnavailable(
                f"El servicio de visión respondió {response.status_code} tras {attempt} reintento(s)")
        if response.status_code >= 400:
            raise ProviderUnavailable(f"El servicio de visión rechazó la petición ({response.status_code})")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderProtocolError("El servicio de visión devolvió un cuerpo que no es JSON") from exc

        candidates = payload.get("candidates") or []
        if not candidates:
            raise ProviderProtocolError("La respuesta de visión no trae 'candidates'")
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        texto = "".join(p.get("text", "") for p in parts).strip()
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise ProviderProtocolError("El modelo de visión no devolvió JSON válido") from exc
        if not isinstance(datos, dict):
            raise ProviderProtocolError("El modelo de visión no devolvió un objeto JSON")
        return _normaliza(datos)


def _normaliza(datos: dict[str, Any]) -> dict[str, Any]:
    severidad = str(datos.get("severidad") or "INDETERMINADO").upper()
    if severidad not in _NIVELES_SEVERIDAD:
        severidad = "INDETERMINADO"
    try:
        confianza = max(0.0, min(1.0, float(datos.get("confianza"))))
    except (TypeError, ValueError):
        confianza = 0.0
    return {
        "danio_visible": bool(datos.get("danio_visible", False)),
        "tipo_danio": datos.get("tipo_danio"),
        "severidad": severidad,
        "coincide_con_relato": datos.get("coincide_con_relato"),
        "descripcion": str(datos.get("descripcion") or "")[:500],
        "confianza": round(confianza, 2),
    }


class OfflineImageAnalyzer(ImageAnalyzer):
    """Sin modelo de visión disponible: declara que la imagen necesita revisión manual.

    Mismo rol que `OfflineProvider` para el texto: degradación elegante (si Gemini
    falla) y pruebas reproducibles sin red ni tokens.
    """

    name = "offline-vision"

    async def analyze(self, *, image_bytes: bytes, mime_type: str,
                      claim_type: str, description: str) -> dict[str, Any]:
        return {
            "danio_visible": None,
            "tipo_danio": None,
            "severidad": "INDETERMINADO",
            "coincide_con_relato": None,
            "descripcion": ("Modo determinista: no hay modelo de visión disponible; "
                            "la imagen requiere revisión manual."),
            "confianza": 0.0,
        }
