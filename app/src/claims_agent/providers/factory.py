"""Fábrica de proveedores: el único punto del código que conoce los nombres concretos.

Añadir Groq u OpenAI = una clase nueva que implemente LLMProvider + una línea aquí.
"""

from __future__ import annotations

import logging

from claims_agent.config import Settings
from claims_agent.providers.base import LLMProvider
from claims_agent.providers.offline import OfflineProvider
from claims_agent.providers.vision import ImageAnalyzer, OfflineImageAnalyzer

log = logging.getLogger(__name__)


def build_provider(settings: Settings) -> LLMProvider:
    """Construye el proveedor principal declarado en LLM_PROVIDER."""
    if settings.llm_provider == "gemini":
        from claims_agent.providers.gemini import GeminiProvider  # import tardío: httpx solo si se usa

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            temperature=settings.llm_temperature,
        )
    if settings.llm_provider == "offline":
        return OfflineProvider()
    raise ValueError(f"Proveedor no soportado: {settings.llm_provider!r}")


def build_fallback(settings: Settings) -> LLMProvider | None:
    """Proveedor de respaldo si el principal falla (None si está deshabilitado)."""
    if not settings.allow_offline_fallback or settings.llm_provider == "offline":
        return None
    return OfflineProvider()


def build_image_analyzer(settings: Settings) -> ImageAnalyzer:
    """Analizador de imágenes para la herramienta `analizar_imagen_dano`."""
    if settings.llm_provider == "gemini":
        from claims_agent.providers.vision import GeminiImageAnalyzer  # import tardío: ver build_provider

        return GeminiImageAnalyzer(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return OfflineImageAnalyzer()
