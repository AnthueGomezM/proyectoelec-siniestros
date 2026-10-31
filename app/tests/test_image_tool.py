"""Herramienta `analizar_imagen_dano`: une la foto adjunta con el analizador de visión.

El contrato del modelo de visión en sí (Gemini) se prueba en test_vision_provider.py.
Aquí se verifica que la herramienta: no llama a nada si no hay foto adjunta, lee el
archivo correcto cuando sí la hay, y que el resultado queda persistido junto a la
urgencia cuando el agente completo la ejecuta.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from claims_agent.agent.loop import STATUS_COMPLETED, TriageAgent, _effective_timeout
from claims_agent.agent.tools import TOOLS_BY_NAME, ToolContext
from claims_agent.providers.vision import ImageAnalyzer
from tests.conftest import ScriptedProvider


class FakeImageAnalyzer(ImageAnalyzer):
    name = "fake-vision"

    def __init__(self, resultado: dict) -> None:
        self._resultado = resultado
        self.llamadas: list[dict] = []

    async def analyze(self, *, image_bytes, mime_type, claim_type, description):  # type: ignore[no-untyped-def]
        self.llamadas.append({"image_bytes": image_bytes, "mime_type": mime_type,
                              "claim_type": claim_type, "description": description})
        return dict(self._resultado)


async def test_sin_imagen_adjunta_no_llama_al_analizador(fake_db, claim, tmp_path):
    analizador = FakeImageAnalyzer({})
    ctx = ToolContext(db=fake_db, claim=claim, classifier=None, uploads_dir=tmp_path,
                      image_analyzer=analizador)

    resultado = await TOOLS_BY_NAME["analizar_imagen_dano"].handler(ctx, {})

    assert resultado == {"tiene_imagen": False,
                         "mensaje": "El cliente no adjuntó ninguna imagen con este reporte."}
    assert analizador.llamadas == []


async def test_con_imagen_adjunta_lee_el_archivo_y_llama_al_analizador(fake_db, claim, tmp_path):
    (tmp_path / "foto.jpg").write_bytes(b"contenido-de-prueba")
    await fake_db.create_attachment(claim["id"], file_path="foto.jpg", mime_type="image/jpeg", size_bytes=20)
    analizador = FakeImageAnalyzer({
        "danio_visible": True, "tipo_danio": "parabrisas roto", "severidad": "MODERADO",
        "coincide_con_relato": True, "descripcion": "Parabrisas con grietas.", "confianza": 0.8,
    })
    ctx = ToolContext(db=fake_db, claim=claim, classifier=None, uploads_dir=tmp_path,
                      image_analyzer=analizador)

    resultado = await TOOLS_BY_NAME["analizar_imagen_dano"].handler(ctx, {})

    assert resultado["tiene_imagen"] is True
    assert resultado["severidad"] == "MODERADO"
    assert analizador.llamadas == [{
        "image_bytes": b"contenido-de-prueba", "mime_type": "image/jpeg",
        "claim_type": claim["claim_type"], "description": claim["description"],
    }]


async def test_el_agente_persiste_el_analisis_de_imagen_junto_a_la_urgencia(
        settings, fake_db, claim, herramienta, texto, tmp_path):
    (tmp_path / "foto.png").write_bytes(b"bytes")
    await fake_db.create_attachment(claim["id"], file_path="foto.png", mime_type="image/png", size_bytes=5)
    analizador = FakeImageAnalyzer({
        "danio_visible": True, "tipo_danio": "carroceria", "severidad": "SEVERO",
        "coincide_con_relato": True, "descripcion": "Daño severo visible.", "confianza": 0.9,
    })
    claim = {**claim, "tiene_imagen": True}
    provider = ScriptedProvider([
        herramienta("clasificar_urgencia", {"descripcion": claim["description"], "tipo_siniestro": "AUTO"}),
        herramienta("analizar_imagen_dano", {}),
        texto("Resumen con daño severo confirmado por la foto."),
    ])
    agente = TriageAgent(settings, fake_db, provider, image_analyzer=analizador, uploads_dir=tmp_path)

    resultado = await agente.run(claim)

    assert resultado.status == STATUS_COMPLETED
    assert fake_db.assessments[0]["image_assessment"]["severidad"] == "SEVERO"
    pasos = await fake_db.get_steps(resultado.run_id)
    paso_imagen = next(p for p in pasos if p["kind"] == "tool_call" and p["name"] == "analizar_imagen_dano")
    assert paso_imagen["output"]["tiene_imagen"] is True


# --------------------------------------------------------------------- timeout dinámico

def test_el_timeout_de_analizar_imagen_escala_con_llm_timeout_seconds(settings):
    """Antes de este fix, la herramienta heredaba el default genérico de 8s, que corta
    una llamada real a un modelo de visión mucho antes de que termine."""
    tool = TOOLS_BY_NAME["analizar_imagen_dano"]

    corto = replace(settings, llm_timeout_seconds=5)
    assert _effective_timeout(tool, corto) == tool.timeout_seconds, "el piso de la herramienta manda"

    largo = replace(settings, llm_timeout_seconds=60)
    assert _effective_timeout(tool, largo) == 65, "LLM_TIMEOUT_SECONDS + margen debe ganarle al piso"


def test_el_timeout_de_una_herramienta_determinista_no_escala(settings):
    """consultar_poliza no llama a ningún modelo: su timeout no debe moverse nunca."""
    tool = TOOLS_BY_NAME["consultar_poliza"]
    otra = replace(settings, llm_timeout_seconds=9999)
    assert _effective_timeout(tool, otra) == tool.timeout_seconds
