"""Bucle agéntico con cuatro límites activos.

                 ┌──────────────────────────────────────────────┐
   siniestro ───►│ 1. ¿queda iteración? ¿queda tiempo? ¿tokens?  │
                 │ 2. preguntar al modelo qué hacer              │
                 │ 3. ¿pidió herramienta?                        │
                 │      sí → ¿necesita confirmación humana?      │
                 │            sí → PAUSA, esperar aprobación     │
                 │            no → ejecutar y volver a 1          │
                 │      no → resumen final, terminar             │
                 └──────────────────────────────────────────────┘

Los cuatro límites (rúbrica · "cuatro límites activos"):

  1. ITERACIONES  AGENT_MAX_ITERATIONS (6)   -> corta bucles infinitos de herramientas.
  2. TIEMPO       AGENT_TIMEOUT_SECONDS (45) -> reloj de pared para toda la corrida;
                  cada llamada al modelo recibe solo el tiempo que queda.
  3. TOKENS       AGENT_MAX_TOKENS (8000)    -> presupuesto acumulado de entrada+salida.
  4. CONFIRMACIÓN AGENT_REQUIRE_CONFIRMATION -> ninguna acción con efecto real sobre el
                  expediente se ejecuta sin que una persona la apruebe.

Cada paso se guarda en agent_steps antes de continuar: si el proceso muere, la traza
de lo que alcanzó a hacer queda en la base. Eso es lo que la UI muestra en vivo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from claims_agent.agent.prompts import SYSTEM_PROMPT, build_claim_message
from claims_agent.agent.tools import (
    TOOLS_BY_NAME,
    Tool,
    ToolContext,
    ToolExecutionError,
    ToolValidationError,
    tool_specs,
    validate_arguments,
)
from claims_agent.config import Settings
from claims_agent.db import Database
from claims_agent.nlp.classifier import UrgencyClassifier
from claims_agent.providers.base import (
    LLMProvider,
    Msg,
    ProviderError,
    ToolCall,
)

log = logging.getLogger(__name__)

STATUS_COMPLETED = "COMPLETED"
STATUS_AWAITING = "AWAITING_CONFIRMATION"
STATUS_LIMIT = "LIMIT_REACHED"
STATUS_FAILED = "FAILED"


@dataclass
class AgentResult:
    run_id: UUID
    status: str
    stop_reason: str | None
    summary: str | None
    assessment: dict[str, Any] | None
    pending_tool: dict[str, Any] | None
    degraded: bool
    iterations: int
    tokens_in: int
    tokens_out: int
    latency_ms: int
    provider: str
    model: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "estado": self.status,
            "motivo_parada": self.stop_reason,
            "resumen": self.summary,
            "evaluacion": self.assessment,
            "accion_pendiente": self.pending_tool,
            "degradado": self.degraded,
            "iteraciones": self.iterations,
            "tokens_entrada": self.tokens_in,
            "tokens_salida": self.tokens_out,
            "latencia_ms": self.latency_ms,
            "proveedor": self.provider,
            "modelo": self.model,
        }


class TriageAgent:
    """Orquesta el triaje de un siniestro. Una instancia por proceso."""

    def __init__(self, settings: Settings, db: Database, provider: LLMProvider,
                 fallback: LLMProvider | None = None,
                 classifier: UrgencyClassifier | None = None) -> None:
        self.settings = settings
        self.db = db
        self.provider = provider
        self.fallback = fallback
        self.classifier = classifier or UrgencyClassifier()

    # ------------------------------------------------------------------ API pública

    async def start_run(self, claim: dict[str, Any]) -> UUID:
        """Reserva la corrida y devuelve su id para que la UI pueda seguirla en vivo."""
        return await self.db.create_run(claim.get("id"), self.provider.name, self.provider.model)

    async def run(self, claim: dict[str, Any], run_id: UUID | None = None) -> AgentResult:
        """Tria un siniestro desde cero."""
        if run_id is None:
            run_id = await self.start_run(claim)
        messages = [Msg(role="user", text=build_claim_message(claim))]
        return await self._loop(run_id=run_id, claim=claim, messages=messages, start_idx=0,
                                iterations=0, tokens_in=0, tokens_out=0,
                                provider=self.provider, degraded=False,
                                started=time.perf_counter())

    async def resume(self, run_id: UUID, *, approved: bool, by: str) -> AgentResult:
        """Continúa una corrida detenida esperando confirmación humana."""
        run = await self.db.get_run(run_id)
        if run is None:
            raise LookupError(f"No existe la corrida {run_id}")
        if run["status"] != STATUS_AWAITING:
            raise ValueError(f"La corrida no está esperando confirmación (estado {run['status']})")

        claim = await self.db.get_claim(run["claim_id"]) if run["claim_id"] else {}
        steps = await self.db.get_steps(run_id)
        pendiente = next((s for s in reversed(steps) if s["kind"] == "confirmation"), None)
        if pendiente is None:
            raise ValueError("La corrida no tiene una acción pendiente registrada")

        messages = _messages_from_steps(claim or {}, steps)
        idx = max(s["idx"] for s in steps) + 1
        provider = self.fallback if (run["degraded"] and self.fallback) else self.provider
        ctx = ToolContext(db=self.db, claim=claim or {}, classifier=self.classifier)
        tool = TOOLS_BY_NAME[pendiente["name"]]
        args = pendiente["input"] or {}

        if approved:
            resultado, latency = await self._execute_tool(tool, ctx, args)
            await self.db.add_step(run_id, idx=idx, kind="tool_call", name=tool.name,
                                   detail=f"ejecutada tras aprobación de {by}",
                                   input=args, output=resultado, latency_ms=latency)
        else:
            resultado = {
                "ejecutada": False,
                "motivo": f"La acción fue rechazada por {by}. No se modificó el expediente.",
            }
            await self.db.add_step(run_id, idx=idx, kind="tool_call", name=tool.name,
                                   detail=f"rechazada por {by}", input=args, output=resultado)
        messages.append(Msg(role="model", tool_calls=(ToolCall(tool.name, args),)))
        messages.append(Msg(role="tool", tool_name=tool.name, tool_result=resultado))

        return await self._loop(run_id=run_id, claim=claim or {}, messages=messages, start_idx=idx + 1,
                                iterations=int(run["iterations"]), tokens_in=int(run["tokens_in"]),
                                tokens_out=int(run["tokens_out"]), provider=provider,
                                degraded=bool(run["degraded"]), started=time.perf_counter())

    # ------------------------------------------------------------------ bucle

    async def _loop(self, *, run_id: UUID, claim: dict[str, Any], messages: list[Msg],
                    start_idx: int, iterations: int, tokens_in: int, tokens_out: int,
                    provider: LLMProvider, degraded: bool, started: float) -> AgentResult:
        s = self.settings
        ctx = ToolContext(db=self.db, claim=claim, classifier=self.classifier)
        specs = tool_specs()
        idx = start_idx
        deadline = started + s.agent_timeout_seconds
        summary: str | None = None
        status = STATUS_COMPLETED
        stop_reason: str | None = None
        pending: dict[str, Any] | None = None

        while True:
            # --- LÍMITE 1: iteraciones ---------------------------------------
            if iterations >= s.agent_max_iterations:
                stop_reason = "max_iteraciones"
                status = STATUS_LIMIT
                await self.db.add_step(run_id, idx=idx, kind="limit", name="max_iteraciones",
                                       detail=f"Se alcanzó el máximo de {s.agent_max_iterations} iteraciones.")
                idx += 1
                break

            # --- LÍMITE 2: tiempo --------------------------------------------
            restante = deadline - time.perf_counter()
            if restante <= 0:
                stop_reason = "timeout"
                status = STATUS_LIMIT
                await self.db.add_step(run_id, idx=idx, kind="limit", name="timeout",
                                       detail=f"Se agotaron los {s.agent_timeout_seconds:.0f}s de la corrida.")
                idx += 1
                break

            # --- LÍMITE 3: tokens --------------------------------------------
            usados = tokens_in + tokens_out
            if usados >= s.agent_max_tokens:
                stop_reason = "presupuesto_tokens"
                status = STATUS_LIMIT
                await self.db.add_step(run_id, idx=idx, kind="limit", name="presupuesto_tokens",
                                       detail=f"Se consumieron {usados} tokens del máximo {s.agent_max_tokens}.")
                idx += 1
                break

            iterations += 1
            presupuesto_salida = max(256, min(1024, s.agent_max_tokens - usados))
            t0 = time.perf_counter()
            try:
                respuesta = await provider.complete(
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=specs,
                    max_output_tokens=presupuesto_salida,
                    timeout_seconds=min(s.llm_timeout_seconds, max(1.0, restante)),
                )
            except ProviderError as exc:
                latencia = int((time.perf_counter() - t0) * 1000)
                await self.db.add_step(run_id, idx=idx, kind="error", name=provider.name,
                                       detail=f"{type(exc).__name__}: {exc}",
                                       output={"mensaje_usuario": exc.user_message}, latency_ms=latencia)
                idx += 1
                log.warning("Fallo del proveedor de IA", extra={
                    "run_id": str(run_id), "provider": provider.name, "error": str(exc)})

                if self.fallback is not None and provider is not self.fallback:
                    provider = self.fallback
                    degraded = True
                    await self.db.add_step(
                        run_id, idx=idx, kind="fallback", name=provider.name,
                        detail="El proveedor principal falló; se continúa en modo determinista "
                               "para no dejar el siniestro sin clasificar.")
                    idx += 1
                    continue

                stop_reason = "proveedor_no_disponible"
                status = STATUS_FAILED
                break

            latencia = int((time.perf_counter() - t0) * 1000)
            tokens_in += respuesta.tokens_in
            tokens_out += respuesta.tokens_out
            await self.db.add_step(
                run_id, idx=idx, kind="llm_call", name=provider.name,
                detail=f"iteración {iterations}",
                input={"iteracion": iterations, "mensajes": len(messages), "modelo": provider.model},
                output={
                    "texto": respuesta.text,
                    "herramientas": [{"nombre": c.name, "argumentos": c.arguments} for c in respuesta.tool_calls],
                    "fin": respuesta.raw_finish_reason,
                },
                latency_ms=latencia, tokens_in=respuesta.tokens_in, tokens_out=respuesta.tokens_out)
            idx += 1

            # --- sin herramientas: respuesta final ----------------------------
            if not respuesta.wants_tools:
                summary = (respuesta.text or "").strip() or None
                status = STATUS_COMPLETED
                stop_reason = "respuesta_final"
                await self.db.add_step(run_id, idx=idx, kind="final", name="resumen",
                                       detail=summary, output={"resumen": summary})
                idx += 1
                break

            # --- ejecutar herramientas ----------------------------------------
            pausa = False
            messages.append(Msg(role="model", tool_calls=respuesta.tool_calls))
            for llamada in respuesta.tool_calls:
                tool = TOOLS_BY_NAME.get(llamada.name)
                if tool is None:
                    resultado = {"error": f"La herramienta '{llamada.name}' no existe. "
                                          f"Disponibles: {', '.join(TOOLS_BY_NAME)}."}
                    await self.db.add_step(run_id, idx=idx, kind="error", name=llamada.name,
                                           detail="herramienta inexistente", output=resultado)
                    idx += 1
                    messages.append(Msg(role="tool", tool_name=llamada.name, tool_result=resultado))
                    continue

                # --- LÍMITE 4: confirmación humana ----------------------------
                if tool.requires_confirmation and self.settings.agent_require_confirmation:
                    pending = {"herramienta": tool.name, "argumentos": llamada.arguments,
                               "descripcion": _describe_action(tool, llamada.arguments)}
                    await self.db.add_step(
                        run_id, idx=idx, kind="confirmation", name=tool.name,
                        detail="Esperando aprobación humana para ejecutar esta acción.",
                        input=llamada.arguments, output={"pendiente": True})
                    idx += 1
                    status = STATUS_AWAITING
                    stop_reason = "espera_confirmacion"
                    pausa = True
                    break

                resultado, latencia_tool = await self._execute_tool(tool, ctx, llamada.arguments)
                await self.db.add_step(run_id, idx=idx, kind="tool_call", name=tool.name,
                                       input=llamada.arguments, output=resultado,
                                       latency_ms=latencia_tool)
                idx += 1
                messages.append(Msg(role="tool", tool_name=tool.name, tool_result=resultado))

            if pausa:
                break

        # --- cierre: persistir resultados ------------------------------------
        total_ms = int((time.perf_counter() - started) * 1000)
        await self.db.finish_run(run_id, status=status, stop_reason=stop_reason,
                                 iterations=iterations, tokens_in=tokens_in, tokens_out=tokens_out,
                                 latency_ms=total_ms, degraded=degraded,
                                 provider=provider.name, model=provider.model)

        assessment = _assessment_from_messages(messages)
        if claim.get("id") is not None:
            assessment = await self._persist_assessment(
                run_id=run_id, claim=claim, assessment=assessment, summary=summary,
                provider=provider, degraded=degraded, status=status)

        steps = await self.db.get_steps(run_id, after_idx=start_idx - 1)
        return AgentResult(
            run_id=run_id, status=status, stop_reason=stop_reason, summary=summary,
            assessment=assessment, pending_tool=pending, degraded=degraded,
            iterations=iterations, tokens_in=tokens_in, tokens_out=tokens_out,
            latency_ms=total_ms, provider=provider.name, model=provider.model,
            steps=[_step_public(s) for s in steps])

    # ------------------------------------------------------------------ auxiliares

    async def _execute_tool(self, tool: Tool, ctx: ToolContext,
                            arguments: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Valida, ejecuta con timeout propio y nunca deja escapar una excepción cruda."""
        t0 = time.perf_counter()
        try:
            limpios = validate_arguments(tool.parameters, dict(arguments or {}))
        except ToolValidationError as exc:
            # Error del modelo, no del sistema: se le devuelve para que se corrija.
            return ({"error": str(exc), "reintentable": True}, int((time.perf_counter() - t0) * 1000))

        try:
            resultado = await asyncio.wait_for(tool.handler(ctx, limpios), timeout=tool.timeout_seconds)
        except asyncio.TimeoutError:
            resultado = {"error": f"La herramienta '{tool.name}' superó {tool.timeout_seconds:.0f}s "
                                  f"y se canceló.", "reintentable": False}
        except ToolExecutionError as exc:
            resultado = {"error": str(exc), "reintentable": False}
        except Exception as exc:  # noqa: BLE001 - un bug no puede tumbar el triaje
            log.exception("Fallo inesperado en la herramienta %s", tool.name)
            resultado = {"error": f"La herramienta '{tool.name}' falló por un error interno.",
                         "reintentable": False, "tipo": type(exc).__name__}
        return resultado, int((time.perf_counter() - t0) * 1000)

    async def _persist_assessment(self, *, run_id: UUID, claim: dict[str, Any],
                                  assessment: dict[str, Any] | None, summary: str | None,
                                  provider: LLMProvider, degraded: bool,
                                  status: str) -> dict[str, Any]:
        """Guarda la evaluación. Red de seguridad: si el agente no clasificó, clasifica el código.

        Un siniestro nunca puede quedar sin nivel de urgencia porque el modelo se
        desvió, se quedó sin iteraciones o se cayó la API.
        """
        red_de_seguridad = assessment is None
        if red_de_seguridad:
            determinista = self.classifier.classify(claim.get("description", ""), claim.get("claim_type"))
            assessment = determinista.to_dict()
            await self.db.add_step(
                run_id, idx=10_000, kind="fallback", name="clasificador_determinista",
                detail="El agente terminó sin clasificar; se aplicó el motor de reglas como red de seguridad.",
                output={"urgencia": assessment["urgencia"]})

        await self.db.save_assessment(
            claim_id=claim["id"],
            urgency=assessment["urgencia"],
            score=float(assessment.get("puntuacion") or 0),
            keywords=assessment.get("palabras_clave") or [],
            inconsistencies=assessment.get("inconsistencias") or [],
            action=assessment["accion_recomendada"],
            sla_minutes=assessment.get("sla_minutos"),
            summary=summary,
            provider=provider.name + ("+red_de_seguridad" if red_de_seguridad else ""),
            model=provider.model,
            run_id=run_id,
        )
        return assessment


# ---------------------------------------------------------------------------- utilidades

def _describe_action(tool: Tool, arguments: dict[str, Any]) -> str:
    if tool.name == "asignar_ajustador":
        return (f"Asignar el siniestro a «{arguments.get('ajustador', '?')}» y pasarlo a EN REVISIÓN. "
                f"Motivo: {arguments.get('motivo', 'sin motivo')}")
    return f"Ejecutar {tool.name} con {arguments}"


def _assessment_from_messages(messages: list[Msg]) -> dict[str, Any] | None:
    """Recupera el resultado de clasificar_urgencia del historial (fuente de la verdad)."""
    for msg in reversed(messages):
        if msg.role == "tool" and msg.tool_name == "clasificar_urgencia":
            resultado = msg.tool_result or {}
            if "urgencia" in resultado:
                return resultado
    return None


def _messages_from_steps(claim: dict[str, Any], steps: list[dict[str, Any]]) -> list[Msg]:
    """Reconstruye el historial de la conversación a partir de la traza guardada.

    La traza ES el estado del agente: no se guarda la conversación en memoria, así que
    una corrida puede reanudarse aunque el proceso se haya reiniciado entre medias.
    """
    messages: list[Msg] = [Msg(role="user", text=build_claim_message(claim))]
    for step in sorted(steps, key=lambda s: s["idx"]):
        if step["kind"] == "llm_call":
            herramientas = (step["output"] or {}).get("herramientas") or []
            if herramientas:
                messages.append(Msg(role="model", tool_calls=tuple(
                    ToolCall(h["nombre"], h.get("argumentos") or {}) for h in herramientas)))
            elif (step["output"] or {}).get("texto"):
                messages.append(Msg(role="model", text=step["output"]["texto"]))
        elif step["kind"] == "tool_call" and step["name"]:
            messages.append(Msg(role="tool", tool_name=step["name"], tool_result=step["output"] or {}))
    return messages


def _step_public(step: dict[str, Any]) -> dict[str, Any]:
    """Forma en la que un paso viaja a la UI."""
    return {
        "idx": step["idx"],
        "tipo": step["kind"],
        "nombre": step["name"],
        "detalle": step["detail"],
        "entrada": step["input"],
        "salida": step["output"],
        "latencia_ms": step["latency_ms"],
        "tokens_entrada": step["tokens_in"],
        "tokens_salida": step["tokens_out"],
        "momento": step["created_at"].isoformat() if step.get("created_at") else None,
    }
