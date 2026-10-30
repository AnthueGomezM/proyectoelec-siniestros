"""Motor determinista de urgencia: niveles, negaciones e inconsistencias."""

from __future__ import annotations

import pytest

from claims_agent.nlp.classifier import (
    ASSIGN_AGENT_IMMEDIATELY,
    AUTO_APPROVE,
    HUMAN_VALIDATION_2H,
    MANUAL_REVIEW,
    UrgencyClassifier,
    normalize,
)
from claims_agent.nlp.lexicon import ClaimType, UrgencyLevel


@pytest.fixture(scope="module")
def clasificador() -> UrgencyClassifier:
    return UrgencyClassifier()


@pytest.mark.parametrize("relato", [
    "Choque en la autopista, hay dos heridos graves.",
    "El conductor del otro vehículo falleció en el lugar.",
    "Llamamos a la ambulancia porque mi hija está inconsciente.",
    "Escuchamos una explosión en la cocina.",
    "Me robaron el carro a mano armada en un semáforo.",
    "Mi papá tuvo un infarto y lo llevaron a urgencias.",
])
def test_casos_criticos(clasificador, relato):
    resultado = clasificador.classify(relato, ClaimType.AUTO)
    assert resultado.urgency_level is UrgencyLevel.CRITICAL, resultado.to_dict()["palabras_clave"]
    assert resultado.recommended_action == ASSIGN_AGENT_IMMEDIATELY
    assert resultado.sla_minutes == 15


@pytest.mark.parametrize("relato", [
    "Mi madre requiere hospitalización por una caída.",
    "El médico indicó cirugía de rodilla la próxima semana.",
    "Hubo un incendio pequeño en el garaje, ya controlado.",
    "Me robaron la bicicleta que estaba en el garaje.",
    "La casa sufrió inundación por la tubería rota.",
])
def test_casos_altos(clasificador, relato):
    resultado = clasificador.classify(relato, ClaimType.MEDICAL)
    assert resultado.urgency_level is UrgencyLevel.HIGH, resultado.to_dict()["palabras_clave"]


@pytest.mark.parametrize("relato", [
    "Un rayón en la puerta trasera del carro en el parqueadero.",
    "Tengo el espejo roto por un roce con una moto.",
    "Se dañó la pintura del capó con granizo.",
    "Una abolladura leve en el parachoques.",
])
def test_casos_leves_se_aprueban_solos(clasificador, relato):
    resultado = clasificador.classify(relato, ClaimType.AUTO)
    assert resultado.urgency_level is UrgencyLevel.LOW
    assert resultado.recommended_action == AUTO_APPROVE
    assert resultado.sla_minutes is None


@pytest.mark.parametrize("relato", [
    "Choque leve sin heridos, solo rayones.",
    "No hubo heridos, únicamente un rayón en la puerta.",
    "Nadie resultó herido; espejo roto.",
])
def test_la_negacion_no_sube_la_urgencia(clasificador, relato):
    resultado = clasificador.classify(relato, ClaimType.AUTO)
    assert resultado.urgency_level is UrgencyLevel.LOW
    assert any(k.negated for k in resultado.keywords)


def test_la_negacion_no_cruza_la_conjuncion(clasificador):
    resultado = clasificador.classify("No hubo daños en el carro, pero hay heridos", ClaimType.AUTO)
    assert resultado.urgency_level is UrgencyLevel.CRITICAL


def test_gana_la_frase_mas_larga(clasificador):
    """'robo con violencia' (CRÍTICO) no puede quedarse en 'robo' (ALTO)."""
    resultado = clasificador.classify("Denuncio un robo con violencia en mi casa", ClaimType.HOME)
    terminos = [k.term for k in resultado.keywords]
    assert "robo con violencia" in terminos and "robo" not in terminos
    assert resultado.urgency_level is UrgencyLevel.CRITICAL


def test_relato_sin_terminos_va_a_revision_manual(clasificador):
    resultado = clasificador.classify("Quiero reportar lo que pasó ayer con mi vehículo.", ClaimType.AUTO)
    assert resultado.recommended_action == MANUAL_REVIEW
    assert resultado.evidence_found is False


@pytest.mark.parametrize("relato,codigo", [
    ("Sin daños importantes, aunque el auto quedó completamente destruido.", "DAMAGE_DENIED_BUT_SEVERE"),
    ("No hubo heridos. La ambulancia trasladó al conductor.", "INJURY_DENIED_BUT_EVIDENCE"),
    ("Solo un rayón en la puerta, el vehículo quedó destruido.", "SEVERITY_CONTRADICTION"),
])
def test_inconsistencias(clasificador, relato, codigo):
    resultado = clasificador.classify(relato, ClaimType.AUTO)
    assert codigo in {i.code for i in resultado.inconsistencies}
    assert resultado.inconsistencies_flag


def test_tipo_que_no_corresponde_al_relato(clasificador):
    resultado = clasificador.classify("Choque del carro contra un taxi en la autopista.", ClaimType.HOME)
    assert "CLAIM_TYPE_MISMATCH" in {i.code for i in resultado.inconsistencies}


def test_un_critico_inconsistente_sigue_asignando_agente(clasificador):
    """La seguridad de las personas primero: la inconsistencia no rebaja un CRÍTICO."""
    resultado = clasificador.classify("No hubo heridos. La ambulancia se llevó al conductor.", ClaimType.AUTO)
    assert resultado.urgency_level is UrgencyLevel.CRITICAL
    assert resultado.recommended_action == ASSIGN_AGENT_IMMEDIATELY


def test_mayusculas_y_tildes_faltantes(clasificador):
    resultado = clasificador.classify("EXPLOSION EN LA COCINA, HAY HERIDAS", ClaimType.HOME)
    assert resultado.urgency_level is UrgencyLevel.CRITICAL


@pytest.mark.parametrize("palabra,clave", [
    ("Heridos", "herid"), ("herida", "herid"), ("rayones", "rayon"),
    ("rayón", "rayon"), ("daños", "dano"), ("explosión", "explosion"),
])
def test_normalizacion(palabra, clave):
    assert normalize(palabra) == clave


def test_el_resultado_es_serializable_para_la_traza(clasificador):
    d = clasificador.classify("Hay heridos y fuego", ClaimType.AUTO).to_dict()
    import json
    assert json.loads(json.dumps(d))["urgencia"] == "CRITICAL"
    assert {"urgencia", "puntuacion", "accion_recomendada", "palabras_clave"} <= set(d)
