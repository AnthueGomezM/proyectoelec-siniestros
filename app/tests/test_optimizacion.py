"""Optimización de tokens: cada ahorro, con su prueba.

El plan gratuito de Gemini se agota por solicitudes y por tokens; un triaje costaba ~3,8
llamadas y ~9.200 tokens, casi todos de entrada porque cada iteración reenvía el prompt, las
declaraciones de herramientas y el historial.
"""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from claims_agent.agent.loop import DETALLE_PREVIO, STATUS_AWAITING, TriageAgent, _messages_from_steps
from claims_agent.agent.prompts import SYSTEM_PROMPT, build_claim_message
from claims_agent.agent.tools import TOOLS_BY_NAME, tool_specs, tools_previas
from claims_agent.providers.base import ProviderProtocolError
from claims_agent.providers.gemini import GeminiProvider
from claims_agent.providers.offline import OfflineProvider
from claims_agent.providers.vision import GeminiImageAnalyzer
from claims_agent.storage import reducir_para_modelo
from tests.conftest import ScriptedProvider


# =============================================================================
# 1. Las herramientas deterministas las ejecuta el sistema, no el modelo
# =============================================================================

def test_las_herramientas_previas_no_se_declaran_al_modelo():
    declaradas = {t.name for t in tool_specs()}
    assert [t.name for t in tools_previas()] == ["clasificar_urgencia", "consultar_poliza"]
    assert not declaradas & {"clasificar_urgencia", "consultar_poliza"}
    assert {"analizar_imagen_dano", "buscar_siniestros_similares", "asignar_ajustador"} <= declaradas


def test_las_declaraciones_pesan_menos():
    """Las dos herramientas previas costaban ~500 tokens de entrada en CADA iteración."""
    todas = sum(len(t.description) + len(json.dumps(t.parameters)) for t in TOOLS_BY_NAME.values())
    enviadas = sum(len(t.description) + len(json.dumps(t.parameters)) for t in tool_specs())
    assert enviadas < todas * 0.65


async def test_el_sistema_clasifica_y_consulta_la_poliza_antes_del_primer_turno(settings, fake_db, claim, texto):
    visto: dict = {}

    def espiar(mensajes):  # type: ignore[no-untyped-def]
        visto["roles"] = [(m.role, m.tool_name or (m.tool_calls[0].name if m.tool_calls else None)) for m in mensajes]
        visto["resultados"] = {m.tool_name: m.tool_result for m in mensajes if m.role == "tool"}
        return texto("Resumen listo.")

    modelo = ScriptedProvider([espiar])
    resultado = await TriageAgent(settings, fake_db, modelo).run(claim)

    # El primer turno del modelo ya trae llamada + respuesta de las dos herramientas, en orden.
    assert visto["roles"] == [("user", None),
                              ("model", "clasificar_urgencia"), ("tool", "clasificar_urgencia"),
                              ("model", "consultar_poliza"), ("tool", "consultar_poliza")]
    assert visto["resultados"]["clasificar_urgencia"]["urgencia"] == "CRITICAL"
    assert visto["resultados"]["consultar_poliza"]["encontrada"] is True
    # Un solo viaje al modelo: antes eran uno por herramienta mas el resumen.
    assert modelo.llamadas == 1 and resultado.iterations == 1
    # La evaluación sale del resultado de la herramienta ejecutada por el sistema.
    assert resultado.assessment["urgencia"] == "CRITICAL"


async def test_los_pasos_previos_quedan_en_la_traza_y_marcados(settings, fake_db, claim, texto):
    resultado = await TriageAgent(settings, fake_db, ScriptedProvider([texto("ok")])).run(claim)
    pasos = await fake_db.get_steps(resultado.run_id)

    previos = [p for p in pasos if p["detail"] == DETALLE_PREVIO]
    assert [p["name"] for p in previos] == ["clasificar_urgencia", "consultar_poliza"]
    assert all(p["kind"] == "tool_call" and p["latency_ms"] >= 0 for p in previos)
    assert [p["idx"] for p in pasos] == sorted(p["idx"] for p in pasos)     # idx consecutivos y únicos
    assert len({p["idx"] for p in pasos}) == len(pasos)


async def test_reanudar_tras_aprobar_reconstruye_las_herramientas_previas(settings, fake_db, claim):
    """El historial se reconstruye de la traza: las previas deben volver como llamada + respuesta."""
    resultado = await TriageAgent(settings, fake_db, OfflineProvider()).run(claim)
    assert resultado.status == STATUS_AWAITING

    pasos = await fake_db.get_steps(resultado.run_id)
    mensajes = _messages_from_steps(claim, pasos)

    # Toda respuesta de herramienta tiene delante la llamada del modelo que la pidió.
    for i, m in enumerate(mensajes):
        if m.role == "tool":
            anterior = mensajes[i - 1]
            assert anterior.role == "model" and anterior.tool_calls[0].name == m.tool_name, (i, m.tool_name)
    assert [m.tool_name for m in mensajes if m.role == "tool"][:2] == ["clasificar_urgencia", "consultar_poliza"]


async def test_el_proveedor_determinista_no_repite_lo_que_ya_hizo_el_sistema(settings, fake_db, claim):
    resultado = await TriageAgent(settings, fake_db, OfflineProvider()).run(claim)
    pasos = await fake_db.get_steps(resultado.run_id)
    veces = [p["name"] for p in pasos if p["kind"] == "tool_call"]
    assert veces.count("clasificar_urgencia") == 1 and veces.count("consultar_poliza") == 1


def test_el_prompt_ya_no_ordena_llamar_a_las_herramientas_previas():
    assert "no debes volver a llamarlas" in SYSTEM_PROMPT
    assert "1. Llama SIEMPRE primero" not in SYSTEM_PROMPT


def test_el_mensaje_del_siniestro_va_compacto():
    texto = build_claim_message({"id": "x", "customer_id": "CUST-000123", "claim_type": "AUTO",
                                 "description": "Choque", "tiene_imagen": False})
    assert "\n  " not in texto and texto.count("\n") == 1        # una línea de cabecera + JSON en una línea
    assert json.loads(texto.split("\n", 1)[1])["customer_id"] == "CUST-000123"


# =============================================================================
# 2. Menos razonamiento
# =============================================================================

def _capturar(cuerpo_respuesta: dict):  # type: ignore[no-untyped-def]
    visto: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        visto["body"] = json.loads(request.content)
        return httpx.Response(200, json=cuerpo_respuesta)

    return visto, httpx.AsyncClient(transport=httpx.MockTransport(handler))


_TEXTO = {"candidates": [{"content": {"parts": [{"text": "hola"}]}}],
          "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}}


@pytest.mark.parametrize("nivel,esperado", [("low", {"thinkingLevel": "low"}), ("", None)])
async def test_el_nivel_de_razonamiento_se_envia_solo_si_esta_configurado(nivel, esperado):
    visto, cliente = _capturar(_TEXTO)
    modelo = GeminiProvider(api_key="k", client=cliente, thinking_level=nivel)

    await modelo.complete(system="s", messages=[], tools=[], max_output_tokens=256, timeout_seconds=5)

    assert visto["body"]["generationConfig"].get("thinkingConfig") == esperado


# =============================================================================
# 3. Fotos más pequeñas
# =============================================================================

def _foto(ancho: int, alto: int, formato: str = "JPEG") -> bytes:
    import random
    rng = random.Random(7)
    imagen = Image.frombytes("RGB", (ancho, alto), bytes(rng.randrange(256) for _ in range(ancho * alto * 3)))
    salida = io.BytesIO()
    imagen.save(salida, formato)
    return salida.getvalue()


def test_una_foto_grande_se_reduce_sin_tocar_el_original():
    original = _foto(2400, 1800)
    reducida, mime = reducir_para_modelo(original, "image/jpeg", 1024)

    ancho, alto = Image.open(io.BytesIO(reducida)).size
    assert max(ancho, alto) == 1024 and mime == "image/jpeg"
    assert abs(ancho / alto - 2400 / 1800) < 0.01               # conserva la proporción
    assert len(reducida) < len(original) * 0.5
    assert Image.open(io.BytesIO(original)).size == (2400, 1800)   # el original no cambió


def test_la_foto_se_reencodifica_sin_exif():
    imagen = Image.new("RGB", (1600, 1200), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "Camara-secreta"                              # fabricante
    salida = io.BytesIO()
    imagen.save(salida, "JPEG", exif=exif)
    assert b"Camara-secreta" in salida.getvalue()

    reducida, _ = reducir_para_modelo(salida.getvalue(), "image/jpeg", 1024)
    assert b"Camara-secreta" not in reducida


def test_una_imagen_pequena_no_se_agranda():
    pequena = _foto(200, 150, "PNG")
    resultado, mime = reducir_para_modelo(pequena, "image/png", 1024)
    assert len(resultado) <= len(pequena) and Image.open(io.BytesIO(resultado)).size == (200, 150)


def test_un_archivo_que_no_es_imagen_se_rechaza():
    with pytest.raises(ValueError):
        reducir_para_modelo(b"esto no es una imagen", "image/jpeg", 1024)


async def test_el_analizador_envia_la_foto_reducida_y_pide_poco_razonamiento():
    visto, cliente = _capturar({"candidates": [{"content": {"parts": [{"text": json.dumps({
        "danio_visible": True, "tipo_danio": "x", "severidad": "LEVE", "coincide_con_relato": True,
        "descripcion": "ok", "confianza": 0.9})}]}}]})
    analizador = GeminiImageAnalyzer(api_key="k", client=cliente, thinking_level="low", max_side=800)

    await analizador.analyze(image_bytes=_foto(3000, 2000), mime_type="image/jpeg",
                             claim_type="AUTO", description="choque")

    parte = visto["body"]["contents"][0]["parts"][1]["inlineData"]
    enviada = Image.open(io.BytesIO(base64.b64decode(parte["data"])))
    assert max(enviada.size) == 800 and parte["mimeType"] == "image/jpeg"
    assert visto["body"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


async def test_una_foto_ilegible_da_un_error_de_protocolo_claro():
    _, cliente = _capturar({})
    analizador = GeminiImageAnalyzer(api_key="k", client=cliente)
    with pytest.raises(ProviderProtocolError, match="No se pudo leer la imagen"):
        await analizador.analyze(image_bytes=b"basura", mime_type="image/jpeg", claim_type="AUTO", description="x")
