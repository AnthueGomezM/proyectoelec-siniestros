"""Los tres fallos que la rúbrica exige manejar con elegancia.

  1. Timeout del modelo
  2. Caída de la API (429 / 5xx / red)
  3. Validación (argumentos inválidos del modelo y payload inválido del cliente)

En ninguno de los tres el siniestro queda sin clasificar ni el usuario ve una traza.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from claims_agent.agent.loop import (
    STATUS_AWAITING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    TriageAgent,
)
from claims_agent.agent.tools import ToolValidationError, validate_arguments
from claims_agent.providers.base import (
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
)
from claims_agent.providers.offline import OfflineProvider
from tests.conftest import ScriptedProvider


# --------------------------------------------------------------------- 1 y 2: proveedor

@pytest.mark.parametrize("fallo", [
    ProviderTimeout("el modelo no respondió en 20s"),
    ProviderUnavailable("Gemini respondió 429"),
    ProviderProtocolError("JSON inválido"),
])
async def test_fallo_del_modelo_degrada_pero_termina_el_triaje(settings, fake_db, claim, fallo):
    """Si el proveedor falla, el agente sigue con reglas y el siniestro queda clasificado.

    El motor determinista llega hasta pedir la asignación de un ajustador, así que la
    corrida termina esperando confirmación humana: eso también es un final sano.
    """
    provider = ScriptedProvider([fallo])
    agente = TriageAgent(settings, fake_db, provider, fallback=OfflineProvider())

    resultado = await agente.run(claim)

    assert resultado.status in (STATUS_COMPLETED, STATUS_AWAITING)
    assert resultado.status != STATUS_FAILED
    assert resultado.degraded is True
    assert resultado.assessment["urgencia"] == "CRITICAL"
    pasos = await fake_db.get_steps(resultado.run_id)
    assert any(p["kind"] == "error" for p in pasos), "el fallo queda registrado en la traza"
    assert any(p["kind"] == "fallback" for p in pasos), "y el cambio de motor también"


async def test_el_mensaje_del_fallo_es_legible_para_el_usuario(settings, fake_db, claim):
    provider = ScriptedProvider([ProviderTimeout("timeout interno con detalles técnicos")])
    agente = TriageAgent(settings, fake_db, provider, fallback=OfflineProvider())

    resultado = await agente.run(claim)
    pasos = await fake_db.get_steps(resultado.run_id)
    error = next(p for p in pasos if p["kind"] == "error")

    assert error["output"]["mensaje_usuario"] == "El modelo tardó más de lo permitido en responder."
    assert "Traceback" not in str(error)


async def test_sin_respaldo_la_corrida_falla_pero_el_siniestro_queda_clasificado(settings, fake_db, claim):
    """Aun deshabilitando el respaldo, la red de seguridad determinista clasifica el caso."""
    settings = replace(settings, allow_offline_fallback=False)
    provider = ScriptedProvider([ProviderUnavailable("sin cuota")])
    agente = TriageAgent(settings, fake_db, provider, fallback=None)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_FAILED
    assert resultado.stop_reason == "proveedor_no_disponible"
    # La red de seguridad corrió igual: el expediente no se queda sin urgencia.
    assert fake_db.assessments and fake_db.assessments[0]["urgency"] == "CRITICAL"
    assert "red_de_seguridad" in fake_db.assessments[0]["provider"]


# --------------------------------------------------------------------- 3: validación

def test_validacion_rechaza_campos_faltantes():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    with pytest.raises(ToolValidationError, match="Faltan argumentos obligatorios: a"):
        validate_arguments(schema, {})


def test_validacion_rechaza_campos_inventados():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
    with pytest.raises(ToolValidationError, match="no reconocidos: b"):
        validate_arguments(schema, {"b": 1})


def test_validacion_convierte_numeros_en_texto():
    """Los modelos mandan "3" en vez de 3; se convierte en vez de romper la corrida."""
    schema = {"type": "object", "properties": {"limite": {"type": "integer", "minimum": 1, "maximum": 5}}}
    assert validate_arguments(schema, {"limite": "3"})["limite"] == 3


def test_validacion_acota_a_los_limites_del_esquema():
    schema = {"type": "object", "properties": {"limite": {"type": "integer", "minimum": 1, "maximum": 5}}}
    assert validate_arguments(schema, {"limite": 99})["limite"] == 5


def test_validacion_exige_valores_del_enum():
    schema = {"type": "object", "properties": {"t": {"type": "string", "enum": ["AUTO", "HOME"]}}}
    with pytest.raises(ToolValidationError, match="debe ser uno de"):
        validate_arguments(schema, {"t": "MASCOTA"})


async def test_argumentos_invalidos_vuelven_al_modelo_para_que_se_corrija(
        settings, fake_db, claim, herramienta, texto):
    """El error de la herramienta no tumba la corrida: se le devuelve al modelo."""
    provider = ScriptedProvider([
        herramienta("consultar_poliza", {}),                                  # falta customer_id
        herramienta("consultar_poliza", {"customer_id": "CUST-000123"}),      # corregido
        texto("Póliza activa verificada."),
    ])
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_COMPLETED
    pasos = await fake_db.get_steps(resultado.run_id)
    intentos = [p for p in pasos if p["kind"] == "tool_call" and p["name"] == "consultar_poliza"]
    assert len(intentos) == 2
    assert intentos[0]["output"]["reintentable"] is True
    assert intentos[1]["output"]["encontrada"] is True


async def test_herramienta_inexistente_no_rompe_la_corrida(settings, fake_db, claim, herramienta, texto):
    provider = ScriptedProvider([herramienta("borrar_base_de_datos", {}), texto("Sigo con lo que tengo.")])
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_COMPLETED
    pasos = await fake_db.get_steps(resultado.run_id)
    error = next(p for p in pasos if p["kind"] == "error" and p["name"] == "borrar_base_de_datos")
    assert "no existe" in error["output"]["error"]


async def test_una_herramienta_que_revienta_se_reporta_sin_traza(settings, fake_db, claim, herramienta, texto):
    """Un bug dentro de una herramienta se convierte en resultado de error, no en 500."""
    fake_db.fallar_en = "consultar_poliza"
    provider = ScriptedProvider([
        herramienta("consultar_poliza", {"customer_id": "CUST-000123"}),
        texto("No pude verificar la póliza; lo señalo para revisión manual."),
    ])
    agente = TriageAgent(settings, fake_db, provider)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_COMPLETED
    pasos = await fake_db.get_steps(resultado.run_id)
    fallo = next(p for p in pasos if p["kind"] == "tool_call" and p["name"] == "consultar_poliza")
    assert "error interno" in fallo["output"]["error"]
    assert "Traceback" not in str(fallo["output"])
