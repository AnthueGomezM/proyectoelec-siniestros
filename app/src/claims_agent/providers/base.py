"""Capa de proveedor desacoplada.

El resto de la aplicación (bucle del agente, herramientas, API) NO sabe qué proveedor
de IA hay detrás: solo conoce esta interfaz. Cambiar de Gemini a Groq u OpenAI es
escribir una clase nueva de ~120 líneas y una variable de entorno; no se toca el
bucle ni las herramientas.

Las tres excepciones son el contrato de fallos que el bucle sabe manejar:
  * ProviderTimeout      -> el modelo no respondió a tiempo
  * ProviderUnavailable  -> 429, 5xx o red caída
  * ProviderProtocolError-> respondió, pero rompiendo el contrato (JSON inválido)
Cualquier otra excepción se considera error de programación y sube sin disfraz.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------- errores

class ProviderError(RuntimeError):
    """Base de los fallos esperables de un proveedor de IA."""

    #: Mensaje en español que se puede mostrar al usuario final sin filtrar detalles técnicos.
    user_message = "El servicio de IA no respondió correctamente."


class ProviderTimeout(ProviderError):
    user_message = "El modelo tardó más de lo permitido en responder."


class ProviderUnavailable(ProviderError):
    user_message = "El servicio de IA no está disponible en este momento."


class ProviderProtocolError(ProviderError):
    user_message = "El modelo devolvió una respuesta con formato inesperado."


# ---------------------------------------------------------------------------- tipos

@dataclass(frozen=True)
class ToolSpec:
    """Descripción de una herramienta tal como se le presenta al modelo."""

    name: str
    description: str
    parameters: dict[str, Any]       # JSON Schema (subconjunto soportado por los proveedores)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    #: Firma opaca de razonamiento (Gemini 3+); hay que devolverla tal cual en el historial.
    signature: str | None = None


@dataclass(frozen=True)
class Msg:
    """Mensaje del historial, independiente del proveedor."""

    role: str                                   # "user" | "model" | "tool"
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    tokens_in: int
    tokens_out: int
    model: str
    raw_finish_reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------- interfaz

class LLMProvider(abc.ABC):
    """Contrato que debe cumplir cualquier proveedor de IA."""

    #: Identificador corto para trazas y métricas ("gemini", "offline", ...).
    name: str = "base"

    @property
    @abc.abstractmethod
    def model(self) -> str:
        """Nombre del modelo concreto que se está usando."""

    @abc.abstractmethod
    async def complete(
        self,
        *,
        system: str,
        messages: list[Msg],
        tools: list[ToolSpec],
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> LLMResponse:
        """Pide la siguiente acción al modelo: texto final o llamadas a herramientas."""

    async def aclose(self) -> None:  # pragma: no cover - por defecto no hay nada que cerrar
        return None
