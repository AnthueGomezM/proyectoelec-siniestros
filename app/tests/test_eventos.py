"""Avisos en vivo del trabajador: quién puede conectarse y qué eventos se emiten."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from claims_agent.config import Settings
from claims_agent.events import construir_eventos
from claims_agent.main import create_app

T0 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)


def _fila(minutos: int, **extra):  # type: ignore[no-untyped-def]
    return {"claim_id": uuid.uuid4(), "customer_id": "CUST-000123", "claim_type": "AUTO",
            "momento": T0 + timedelta(minutes=minutos), **extra}


def test_cada_tipo_de_evento_lleva_lo_que_la_pantalla_necesita():
    datos = {
        "nuevo": [_fila(1)],
        "triaje": [_fila(2, urgency_level="CRITICAL", inconsistencies_flag=True)],
        "aprobacion": [_fila(3, run_id=uuid.uuid4())],
        "estado": [_fila(4, status="APPROVED")],
    }
    eventos, cursor = construir_eventos(datos, set(), T0)

    assert [e["tipo"] for e in eventos] == ["nuevo", "triaje", "aprobacion", "estado"]
    triaje = eventos[1]
    assert triaje["urgencia"] == "CRITICAL" and triaje["inconsistencia"] is True
    assert triaje["cliente"] == "CUST-000123" and triaje["tipo_siniestro"] == "AUTO"
    assert "run_id" in eventos[2] and eventos[3]["estado"] == "APPROVED"
    assert cursor == T0 + timedelta(minutes=4)                 # avanza hasta lo último que vio


def test_un_evento_ya_visto_no_se_repite():
    """La consulta retrocede unos segundos desde el cursor: lo repetido se descarta."""
    datos = {"triaje": [_fila(1, urgency_level="LOW", inconsistencies_flag=False)]}
    vistos: set = set()

    primero, cursor = construir_eventos(datos, vistos, T0)
    segundo, _ = construir_eventos(datos, vistos, cursor)

    assert len(primero) == 1 and segundo == []


def test_sin_novedades_no_hay_eventos_y_el_cursor_no_retrocede():
    eventos, cursor = construir_eventos({}, set(), T0)
    assert eventos == [] and cursor == T0


def test_los_eventos_salen_en_orden_cronologico_aunque_vengan_de_tablas_distintas():
    datos = {"estado": [_fila(1, status="IN_REVIEW")], "nuevo": [_fila(5)]}
    eventos, _ = construir_eventos(datos, set(), T0)
    assert [e["tipo"] for e in eventos] == ["estado", "nuevo"]


def _cliente() -> TestClient:
    settings = Settings(database_url="postgresql://x@h/x", llm_provider="offline",
                        auth_users=(("ana", "trabajador", "clave-trabajador-1"), ("soporte", "ti", "clave-ti-segura-2")))
    return TestClient(create_app(settings), follow_redirects=False)


def test_el_canal_de_avisos_exige_sesion_de_trabajador():
    cliente = _cliente()
    assert cliente.get("/api/events").status_code == 401                   # nadie anónimo escucha
    cliente.post("/api/auth/login", json={"usuario": "soporte", "clave": "clave-ti-segura-2"})
    assert cliente.get("/api/events").status_code == 403                   # TI no recibe los avisos del trabajador
