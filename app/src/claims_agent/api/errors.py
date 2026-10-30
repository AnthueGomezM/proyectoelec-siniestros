"""Manejo de errores: el usuario nunca ve una traza de Python.

Las tres fallas que la rúbrica pide manejar con elegancia se traducen así:

  | Falla                        | HTTP | Qué ve el usuario                                   |
  |------------------------------|------|-----------------------------------------------------|
  | Validación del reporte       | 400  | Lista de campos con el error concreto de cada uno    |
  | Timeout del modelo o del bucle| 200 + estado LIMIT_REACHED | El triaje sigue, con aviso en pantalla |
  | Caída de la API de IA        | 200 + modo degradado       | Banner "modo determinista" y resultado |
  | Base de datos caída          | 503  | "Servicio temporalmente no disponible" + reintentar  |
  | Cualquier bug no previsto    | 500  | Mensaje genérico + id de correlación para soporte    |

El detalle técnico (traza incluida) va al log en JSON, nunca a la respuesta.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


def problem(status: int, title: str, detail: str, *, request: Request | None = None,
            errors: list[dict[str, Any]] | None = None, extra: dict[str, Any] | None = None) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://claims-triage.local/problemas/{title.lower().replace(' ', '-')}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if request is not None:
        body["instance"] = str(request.url.path)
        body["correlationId"] = getattr(request.state, "correlation_id", None)
    if errors:
        body["errors"] = errors
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


def install_error_handlers(app: FastAPI) -> None:

    @app.middleware("http")
    async def correlation_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.correlation_id = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = request.state.correlation_id
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        errores = []
        for e in exc.errors():
            campo = ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path"))
            errores.append({"campo": campo or "cuerpo", "mensaje": _mensaje_es(e)})
        log.warning("Reporte rechazado por validación",
                    extra={"path": request.url.path, "errores": len(errores)})
        return problem(400, "Solicitud inválida",
                       f"El reporte tiene {len(errores)} error(es) de validación.",
                       request=request, errors=errores)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
        titulos = {404: "No encontrado", 405: "Método no permitido", 409: "Conflicto"}
        return problem(exc.status_code, titulos.get(exc.status_code, "Error"),
                       str(exc.detail), request=request)

    @app.exception_handler(PoolTimeout)
    @app.exception_handler(OperationalError)
    async def _db(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        log.error("Base de datos no disponible", extra={"path": request.url.path, "error": str(exc)})
        return problem(503, "Servicio no disponible",
                       "La base de datos no está respondiendo. Reintenta en unos segundos.",
                       request=request, extra={"reintentar_en_segundos": 5})

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        # La traza completa va al log; el cliente solo recibe el id para reportarlo.
        log.exception("Error no controlado", extra={"path": request.url.path})
        return problem(500, "Error interno",
                       "Ocurrió un error inesperado. Reporta el correlationId a soporte.",
                       request=request)


def _mensaje_es(error: dict[str, Any]) -> str:
    tipo = error.get("type", "")
    ctx = error.get("ctx") or {}
    traducciones = {
        "missing": "es obligatorio",
        "string_too_short": f"debe tener al menos {ctx.get('min_length', '?')} caracteres",
        "string_too_long": f"no puede superar {ctx.get('max_length', '?')} caracteres",
        "string_pattern_mismatch": "tiene un formato inválido",
        "greater_than_equal": f"debe ser mayor o igual a {ctx.get('ge', '?')}",
        "less_than_equal": f"debe ser menor o igual a {ctx.get('le', '?')}",
        "enum": f"debe ser uno de: {ctx.get('expected', '?')}",
        "datetime_parsing": "debe ser una fecha ISO-8601 válida",
        "value_error": str(ctx.get("error", error.get("msg", "valor inválido"))),
    }
    return traducciones.get(tipo, error.get("msg", "valor inválido"))
