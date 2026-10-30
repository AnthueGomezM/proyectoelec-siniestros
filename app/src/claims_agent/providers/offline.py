"""Proveedor determinista sin red: plan fijo de herramientas.

Cumple dos funciones, ambas deliberadas:

1. **Degradación elegante.** Si Gemini devuelve 429, se cae o tarda demasiado, el
   bucle cambia a este proveedor y el siniestro se sigue triando. El ajustador ve un
   aviso de "modo degradado" en pantalla, no un error. Un reclamo con heridos no
   puede quedarse sin clasificar porque se agotó una cuota.
2. **Pruebas y evaluación reproducibles.** La suite `eval/` corre con este proveedor
   sin gastar tokens ni depender de la red, y da siempre el mismo resultado.

No es "IA falsa": es el plan que un analista escribiría a mano. Decide el siguiente
paso leyendo lo que ya se ejecutó en el historial, igual que haría el modelo, pero
con reglas fijas en vez de inferencia.
"""

from __future__ import annotations

import json
import re
from typing import Any

from claims_agent.providers.base import LLMProvider, LLMResponse, Msg, ToolCall, ToolSpec

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class OfflineProvider(LLMProvider):
    name = "offline"

    def __init__(self, model: str = "reglas-deterministas-v2") -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, *, system: str, messages: list[Msg], tools: list[ToolSpec],
                       max_output_tokens: int, timeout_seconds: float) -> LLMResponse:
        disponibles = {t.name for t in tools}
        claim = _claim_from_history(messages)
        resultados = _tool_results(messages)
        llamadas = set(resultados)

        plan: ToolCall | None = None

        if "clasificar_urgencia" in disponibles and "clasificar_urgencia" not in llamadas:
            plan = ToolCall("clasificar_urgencia", {
                "descripcion": claim.get("descripcion", ""),
                "tipo_siniestro": claim.get("tipo", "AUTO"),
            })
        elif "consultar_poliza" in disponibles and "consultar_poliza" not in llamadas:
            plan = ToolCall("consultar_poliza", {"customer_id": claim.get("customer_id", "")})
        elif ("buscar_siniestros_similares" in disponibles
              and "buscar_siniestros_similares" not in llamadas
              and _urgencia(resultados) in {"CRITICAL", "HIGH"}):
            plan = ToolCall("buscar_siniestros_similares", {
                "descripcion": claim.get("descripcion", ""),
                "tipo_siniestro": claim.get("tipo", "AUTO"),
                "limite": 3,
            })
        elif ("asignar_ajustador" in disponibles
              and "asignar_ajustador" not in llamadas
              and _urgencia(resultados) == "CRITICAL"):
            plan = ToolCall("asignar_ajustador", {
                "claim_id": claim.get("claim_id", ""),
                "ajustador": "guardia-24h",
                "motivo": "Urgencia CRÍTICA: requiere contacto humano inmediato (SLA 15 minutos).",
            })

        texto_entrada = sum(len(m.text or "") for m in messages) + len(system)
        if plan is not None:
            return LLMResponse(
                text=None,
                tool_calls=(plan,),
                tokens_in=texto_entrada // 4,
                tokens_out=24,
                model=self._model,
                meta={"deterministic": True},
            )

        resumen = _resumen(claim, resultados)
        return LLMResponse(
            text=resumen,
            tool_calls=(),
            tokens_in=texto_entrada // 4,
            tokens_out=len(resumen) // 4,
            model=self._model,
            raw_finish_reason="STOP",
            meta={"deterministic": True},
        )


# ---------------------------------------------------------------------------- lectura del historial

def _claim_from_history(messages: list[Msg]) -> dict[str, Any]:
    """El primer mensaje del usuario trae el siniestro como bloque JSON."""
    for msg in messages:
        if msg.role == "user" and msg.text:
            match = _JSON_BLOCK.search(msg.text)
            if match:
                try:
                    data = json.loads(match.group(0))
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    continue
    return {}


def _tool_results(messages: list[Msg]) -> dict[str, dict[str, Any]]:
    return {m.tool_name: (m.tool_result or {}) for m in messages if m.role == "tool" and m.tool_name}


def _urgencia(resultados: dict[str, dict[str, Any]]) -> str | None:
    return (resultados.get("clasificar_urgencia") or {}).get("urgencia")


# ---------------------------------------------------------------------------- resumen final

def _pesos(valor: Any) -> str:
    """Formato de moneda colombiana legible: 800000.0 -> $ 800.000"""
    try:
        entero = int(round(float(valor)))
    except (TypeError, ValueError):
        return str(valor)
    return "$ " + f"{entero:,}".replace(",", ".")


def _resumen(claim: dict[str, Any], resultados: dict[str, dict[str, Any]]) -> str:
    triaje = resultados.get("clasificar_urgencia") or {}
    poliza = resultados.get("consultar_poliza") or {}
    similares = (resultados.get("buscar_siniestros_similares") or {}).get("resultados") or []

    urgencia = triaje.get("urgencia", "desconocida")
    accion = triaje.get("accion_es") or triaje.get("accion_recomendada", "revisión manual")
    partes = [f"Triaje {urgencia}: {accion}."]

    claves = [k.get("matched") for k in (triaje.get("palabras_clave") or []) if not k.get("negated")]
    if claves:
        partes.append("Términos que determinan la urgencia: " + ", ".join(claves[:5]) + ".")

    for inc in triaje.get("inconsistencias") or []:
        partes.append(f"Inconsistencia detectada: {inc.get('description', inc.get('code'))}.")

    if poliza.get("encontrada") is False:
        partes.append("ATENCIÓN: no existe póliza para el cliente reportado; verificar identificación antes de continuar.")
    elif poliza.get("estado") and poliza["estado"] != "ACTIVE":
        partes.append(f"ATENCIÓN: la póliza está en estado {poliza['estado']}; la cobertura debe validarse con suscripción.")
    elif poliza.get("producto") and claim.get("tipo") and poliza["producto"] != claim["tipo"]:
        partes.append(f"ATENCIÓN: la póliza cubre {poliza['producto']} y el siniestro se reportó como {claim['tipo']}.")
    elif poliza.get("deducible") is not None:
        partes.append(f"Póliza activa con deducible de {_pesos(poliza['deducible'])}.")

    if similares:
        costos = [s.get("costo_estimado") for s in similares if s.get("costo_estimado") is not None]
        if costos:
            partes.append(
                f"Casos parecidos resueltos: {len(similares)}, con costos entre "
                f"{_pesos(min(costos))} y {_pesos(max(costos))}."
            )

    partes.append("Resumen generado en modo determinista (sin modelo de lenguaje).")
    return " ".join(partes)
