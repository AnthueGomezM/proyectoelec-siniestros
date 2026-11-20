"""Avisos en vivo para el trabajador: de filas de la base a eventos listos para enviar.

El canal (`GET /api/events`, Server-Sent Events) consulta la base cada pocos segundos y empuja
SOLO lo nuevo. Esta parte es pura (sin red ni base) para poder probarla: recibe lo que devolvió
`Database.events_since` y decide qué eventos emitir y hasta dónde avanza el cursor.

Cuatro tipos de evento:

  nuevo       un cliente reportó un siniestro (aún sin clasificar)
  triaje      el agente terminó de clasificarlo: trae la urgencia (es el aviso que importa)
  aprobacion  el agente está detenido esperando que una persona autorice una acción
  estado      alguien cambió el estado del siniestro (aprobado, rechazado, en revisión)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

#: La consulta retrocede un poco desde el cursor para no perder filas cuya transacción terminó
#: después de otra con fecha posterior; los repetidos se descartan con `vistos`.
SOLAPE = timedelta(seconds=2)
MAX_VISTOS = 2000


def _iso(valor: Any) -> str | None:
    return valor.isoformat() if isinstance(valor, datetime) else None


def construir_eventos(datos: dict[str, list[dict[str, Any]]], vistos: set[tuple],
                      cursor: datetime) -> tuple[list[dict[str, Any]], datetime]:
    """Devuelve (eventos nuevos en orden cronológico, cursor actualizado)."""
    eventos: list[dict[str, Any]] = []
    nuevo_cursor = cursor
    for tipo in ("nuevo", "triaje", "aprobacion", "estado"):
        for fila in datos.get(tipo, []):
            momento = fila["momento"]
            clave = (tipo, str(fila["claim_id"]), _iso(momento))
            if momento is not None and momento > nuevo_cursor:
                nuevo_cursor = momento
            if clave in vistos:
                continue
            vistos.add(clave)
            evento: dict[str, Any] = {
                "tipo": tipo,
                "claim_id": str(fila["claim_id"]),
                "cliente": fila.get("customer_id"),
                "tipo_siniestro": fila.get("claim_type"),
                "momento": _iso(momento),
            }
            if tipo == "triaje":
                evento["urgencia"] = fila.get("urgency_level")
                evento["inconsistencia"] = bool(fila.get("inconsistencies_flag"))
            elif tipo == "aprobacion":
                evento["run_id"] = str(fila["run_id"])
            elif tipo == "estado":
                evento["estado"] = fila.get("status")
            eventos.append(evento)
    if len(vistos) > MAX_VISTOS:        # la memoria del canal no crece sin límite
        vistos.clear()
    eventos.sort(key=lambda e: e["momento"] or "")
    return eventos, nuevo_cursor
