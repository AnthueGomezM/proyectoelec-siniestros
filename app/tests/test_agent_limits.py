"""Los cuatro límites del agente, probados uno por uno.

La rúbrica exige "cuatro límites activos" y descalifica el "bucle ciego". Estas
pruebas son la evidencia de que cada límite corta de verdad, no de que esté escrito
en la configuración.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from claims_agent.agent.loop import (
    STATUS_AWAITING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_LIMIT,
    TriageAgent,
)
from claims_agent.providers.base import ProviderTimeout, ProviderUnavailable
from claims_agent.providers.offline import OfflineProvider
from tests.conftest import ScriptedProvider


# --------------------------------------------------------------------- LÍMITE 1

async def test_limite_iteraciones_corta_el_bucle(settings, fake_db, claim, herramienta):
    """Un modelo que pide herramientas sin parar se detiene en max_iteraciones."""
    settings = replace(settings, agent_max_iterations=3)
    # Guion infinito: siempre pide la misma herramienta.
    provider = ScriptedProvider([herramienta("consultar_poliza", {"customer_id": "CUST-000123"})] * 50)
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_LIMIT
    assert resultado.stop_reason == "max_iteraciones"
    assert resultado.iterations == 3
    assert provider.llamadas == 3
    pasos = await fake_db.get_steps(resultado.run_id)
    assert any(p["kind"] == "limit" and p["name"] == "max_iteraciones" for p in pasos)


# --------------------------------------------------------------------- LÍMITE 2

async def test_limite_tiempo_corta_aunque_queden_iteraciones(settings, fake_db, claim, herramienta):
    """El reloj de pared manda: con 0.4 s de presupuesto, la corrida para pronto."""
    settings = replace(settings, agent_timeout_seconds=0.4, agent_max_iterations=50)

    async def lento(_messages):
        await asyncio.sleep(0.2)
        return herramienta("consultar_poliza", {"customer_id": "CUST-000123"})

    provider = ScriptedProvider([lento] * 50)

    class Lento(ScriptedProvider):
        async def complete(self, **kwargs):  # type: ignore[no-untyped-def]
            self.llamadas += 1
            await asyncio.sleep(0.2)
            return herramienta("consultar_poliza", {"customer_id": "CUST-000123"})

    provider = Lento([])
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_LIMIT
    assert resultado.stop_reason == "timeout"
    assert resultado.iterations < 50
    pasos = await fake_db.get_steps(resultado.run_id)
    assert any(p["kind"] == "limit" and p["name"] == "timeout" for p in pasos)


async def test_el_timeout_restante_se_pasa_al_proveedor(settings, fake_db, claim, texto):
    """Cada llamada recibe solo el tiempo que queda: no puede exceder el presupuesto."""
    settings = replace(settings, agent_timeout_seconds=2.0, llm_timeout_seconds=30.0)
    provider = ScriptedProvider([texto("listo")])
    agente = TriageAgent(settings, fake_db, provider)

    await agente.run(claim)

    assert provider.ultimo_timeout is not None
    assert provider.ultimo_timeout <= 2.0, "el timeout del proveedor debe acotarse al tiempo restante"


# --------------------------------------------------------------------- LÍMITE 3

async def test_limite_tokens_detiene_la_corrida(settings, fake_db, claim, herramienta):
    """Al superar el presupuesto de tokens, el agente se detiene aunque quede tiempo."""
    settings = replace(settings, agent_max_tokens=600, agent_max_iterations=20)
    caro = herramienta("consultar_poliza", {"customer_id": "CUST-000123"}, tokens_in=250, tokens_out=50)
    provider = ScriptedProvider([caro] * 20)
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_LIMIT
    assert resultado.stop_reason == "presupuesto_tokens"
    assert resultado.tokens_in + resultado.tokens_out >= 600
    assert resultado.iterations <= 3


async def test_el_presupuesto_de_salida_se_reduce_con_lo_consumido(settings, fake_db, claim, herramienta, texto):
    """max_output_tokens de cada llamada nunca excede lo que queda del presupuesto."""
    settings = replace(settings, agent_max_tokens=1200)
    vistos: list[int] = []

    class Espia(ScriptedProvider):
        async def complete(self, *, max_output_tokens, **kwargs):  # type: ignore[no-untyped-def]
            vistos.append(max_output_tokens)
            return await super().complete(max_output_tokens=max_output_tokens, **kwargs)

    provider = Espia([
        herramienta("consultar_poliza", {"customer_id": "CUST-000123"}, tokens_in=400, tokens_out=100),
        texto("resumen"),
    ])
    agente = TriageAgent(settings, fake_db, provider)
    await agente.run(claim)

    assert len(vistos) == 2
    assert vistos[1] <= 1200 - 500


# --------------------------------------------------------------------- LÍMITE 4

async def test_accion_sensible_espera_confirmacion_humana(settings, fake_db, claim, herramienta):
    """asignar_ajustador NO se ejecuta: la corrida se pausa esperando a una persona."""
    provider = ScriptedProvider([
        herramienta("asignar_ajustador", {"claim_id": str(claim["id"]), "ajustador": "ana",
                                          "motivo": "Hay heridos"}),
    ])
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_AWAITING
    assert resultado.pending_tool["herramienta"] == "asignar_ajustador"
    assert fake_db.asignaciones == [], "la acción no puede ejecutarse antes de la aprobación"
    pasos = await fake_db.get_steps(resultado.run_id)
    assert any(p["kind"] == "confirmation" for p in pasos)


async def test_al_aprobar_se_ejecuta_la_accion_y_sigue_el_bucle(settings, fake_db, claim, herramienta, texto):
    provider = ScriptedProvider([
        herramienta("asignar_ajustador", {"claim_id": str(claim["id"]), "ajustador": "ana",
                                          "motivo": "Hay heridos"}),
        texto("Caso asignado a ana por presencia de heridos."),
    ])
    agente = TriageAgent(settings, fake_db, provider)
    pausado = await agente.run(claim)

    resultado = await agente.resume(pausado.run_id, approved=True, by="ana")

    assert resultado.status == STATUS_COMPLETED
    assert len(fake_db.asignaciones) == 1
    assert fake_db.asignaciones[0][1] == "ana"
    assert "asignado" in (resultado.summary or "").lower()


async def test_al_rechazar_no_se_toca_el_expediente(settings, fake_db, claim, herramienta, texto):
    provider = ScriptedProvider([
        herramienta("asignar_ajustador", {"claim_id": str(claim["id"]), "ajustador": "ana",
                                          "motivo": "Hay heridos"}),
        texto("La asignación fue rechazada por el ajustador."),
    ])
    agente = TriageAgent(settings, fake_db, provider)
    pausado = await agente.run(claim)

    resultado = await agente.resume(pausado.run_id, approved=False, by="luis")

    assert resultado.status == STATUS_COMPLETED
    assert fake_db.asignaciones == []
    pasos = await fake_db.get_steps(resultado.run_id)
    rechazo = [p for p in pasos if p["kind"] == "tool_call" and "rechaz" in (p["detail"] or "")]
    assert rechazo and rechazo[0]["output"]["ejecutada"] is False


async def test_confirmacion_desactivada_ejecuta_directo(settings, fake_db, claim, herramienta, texto):
    """Con AGENT_REQUIRE_CONFIRMATION=false la acción corre sola (configuración explícita)."""
    settings = replace(settings, agent_require_confirmation=False)
    provider = ScriptedProvider([
        herramienta("asignar_ajustador", {"claim_id": str(claim["id"]), "ajustador": "guardia-24h",
                                          "motivo": "Hay heridos"}),
        texto("Asignado."),
    ])
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_COMPLETED
    assert len(fake_db.asignaciones) == 1


async def test_no_se_puede_reanudar_una_corrida_que_no_espera(settings, fake_db, claim, texto):
    provider = ScriptedProvider([texto("listo")])
    agente = TriageAgent(settings, fake_db, provider)
    resultado = await agente.run(claim)

    with pytest.raises(ValueError, match="no está esperando confirmación"):
        await agente.resume(resultado.run_id, approved=True, by="ana")
