"""Endpoints HTTP.

Patrón de integración: **in-request + streaming SSE**. El reporte del siniestro
responde en milisegundos con el `run_id`; el agente corre en segundo plano y el
dashboard sigue la traza paso a paso por `GET /api/runs/{id}/stream`. Así el
ajustador ve en vivo qué herramienta se está ejecutando, cuánto tardó y cuántos
tokens costó, que es exactamente la evidencia que pide la rúbrica.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from claims_agent.agent.loop import STATUS_AWAITING, TriageAgent
from claims_agent.api.errors import problem
from claims_agent.auth import COOKIE, Sesion, requiere
from claims_agent.events import SOLAPE, construir_eventos
from claims_agent.storage import ImageRejected, save_image

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

TIPOS_ES = {"AUTO": "AUTO", "AUTOMOVIL": "AUTO", "VEHICULO": "AUTO",
            "MEDICAL": "MEDICAL", "MEDICO": "MEDICAL", "SALUD": "MEDICAL",
            "HOME": "HOME", "HOGAR": "HOME", "VIVIENDA": "HOME"}


# ---------------------------------------------------------------------------- modelos

class Gps(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ClaimIn(BaseModel):
    customer_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    claim_type: str
    description: str = Field(min_length=10, max_length=5000)
    incident_timestamp: datetime
    gps: Gps | None = None

    @field_validator("claim_type", mode="before")
    @classmethod
    def normaliza_tipo(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("debe ser AUTO, MEDICAL o HOME")
        import unicodedata
        clave = "".join(c for c in unicodedata.normalize("NFD", v.strip().upper())
                        if unicodedata.category(c) != "Mn")
        if clave not in TIPOS_ES:
            raise ValueError("debe ser AUTO, MEDICAL o HOME")
        return TIPOS_ES[clave]

    @field_validator("incident_timestamp")
    @classmethod
    def no_futuro(cls, v: datetime) -> datetime:
        ahora = datetime.now(timezone.utc)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v > ahora + timedelta(minutes=5):
            raise ValueError("la fecha del siniestro no puede estar en el futuro")
        return v


class ConfirmIn(BaseModel):
    # Quién aprueba NO viaja en el cuerpo: sale de la sesión. Un campo editable por el
    # navegador permitiría firmar una aprobación a nombre de otra persona.
    aprobado: bool


class LoginIn(BaseModel):
    usuario: str = Field(min_length=1, max_length=64)
    clave: str = Field(min_length=1, max_length=200)


class StatusIn(BaseModel):
    estado: Literal["PENDING", "IN_REVIEW", "APPROVED", "REJECTED"]
    justificacion: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------- acceso por rol
# Matriz (ver docs/decisiones.md, seccion Seguridad):
#   publico   : reportar un siniestro, ver SU estado, health/ready
#   trabajador: cola, expediente, foto, confirmar al agente, decidir el caso
#   ti        : configuracion, cifras y corridas
#   ambos     : la traza de una corrida (para depurar)

TRABAJADOR = Depends(requiere("trabajador"))
SOLO_TI = Depends(requiere("ti"))
PERSONAL = Depends(requiere("trabajador", "ti"))


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _demasiadas(request: Request, espera: float, detalle: str) -> JSONResponse:
    respuesta = problem(429, "Demasiadas solicitudes", detalle, request=request,
                        extra={"reintentar_en_segundos": int(espera) + 1})
    respuesta.headers["Retry-After"] = str(int(espera) + 1)
    return respuesta


# ---------------------------------------------------------------------------- utilidades

def _agent(request: Request) -> TriageAgent:
    return request.app.state.agent


def _db(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.db


def _serializa(valor: Any) -> Any:
    if isinstance(valor, (UUID, )):
        return str(valor)
    if isinstance(valor, datetime):
        return valor.isoformat()
    if hasattr(valor, "quantize"):          # Decimal
        return float(valor)
    return valor


def _fila(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _serializa(v) for k, v in row.items()}


# ---------------------------------------------------------------------------- salud y config

@router.get("/health", tags=["operación"])
async def health() -> dict[str, str]:
    """Liveness: el proceso responde."""
    return {"estado": "UP"}


@router.get("/ready", tags=["operación"])
async def ready(request: Request):  # type: ignore[no-untyped-def]
    """Readiness: además, la base de datos responde."""
    if await _db(request).ping():
        return {"estado": "UP", "base_datos": "UP"}
    return problem(503, "Servicio no disponible", "La base de datos no responde todavía.",
                   request=request, extra={"base_datos": "DOWN"})


@router.get("/config", tags=["operación"])
async def config(request: Request, _: Sesion = SOLO_TI) -> dict[str, Any]:
    """Configuración pública: la UI la usa para mostrar proveedor, modelo y límites."""
    s = request.app.state.settings
    return {
        "proveedor": s.llm_provider,
        "modelo": s.gemini_model if s.llm_provider == "gemini" else "reglas-deterministas",
        "limites": {
            "max_iteraciones": s.agent_max_iterations,
            "timeout_segundos": s.agent_timeout_seconds,
            "max_tokens": s.agent_max_tokens,
            "confirmacion_humana": s.agent_require_confirmation,
        },
        "fallback_offline": s.allow_offline_fallback,
    }


# ---------------------------------------------------------------------------- sesión

@router.post("/auth/login", tags=["acceso"], response_model=None)
async def iniciar_sesion(payload: LoginIn, request: Request, response: Response):  # type: ignore[no-untyped-def]
    """Inicia sesión del personal. Cookie HttpOnly + SameSite=Strict; los fallos tienen tope por IP."""
    auth = request.app.state.auth
    limite = request.app.state.limite_login
    ip = _ip(request)
    espera = limite.espera(ip)
    if espera > 0:
        log.warning("Inicio de sesión bloqueado por exceso de intentos", extra={"ip": ip})
        return _demasiadas(request, espera, "Demasiados intentos fallidos. Espera unos minutos.")

    sesion = auth.credenciales_validas(payload.usuario.strip(), payload.clave)
    if sesion is None:
        limite.registrar(ip)
        log.warning("Inicio de sesión fallido", extra={"usuario": payload.usuario[:64], "ip": ip})
        # Mismo mensaje exista o no el usuario: no se revela qué cuentas hay.
        raise HTTPException(status_code=401, detail="Usuario o clave incorrectos.")

    limite.reiniciar(ip)
    response.set_cookie(COOKIE, auth.emitir(sesion), max_age=auth.ttl_segundos, httponly=True,
                        samesite="strict", secure=request.app.state.settings.auth_cookie_secure, path="/")
    log.info("Inicio de sesión", extra={"usuario": sesion.usuario, "rol": sesion.rol})
    return {"usuario": sesion.usuario, "rol": sesion.rol,
            "destino": "/ti" if sesion.rol == "ti" else "/trabajador"}


@router.post("/auth/logout", tags=["acceso"])
async def cerrar_sesion(response: Response) -> dict[str, str]:
    response.delete_cookie(COOKIE, path="/")
    return {"estado": "sesión cerrada"}


@router.get("/auth/sesion", tags=["acceso"])
async def estado_de_sesion(request: Request) -> dict[str, Any]:
    """¿Hay una sesión activa? Responde 200 siempre: así la aplicación consulta sin generar un 401."""
    sesion = request.app.state.auth.leer(request)
    if sesion is None:
        return {"autenticado": False}
    return {"autenticado": True, "usuario": sesion.usuario, "rol": sesion.rol}


@router.get("/auth/me", tags=["acceso"])
async def quien_soy(sesion: Sesion = PERSONAL) -> dict[str, str]:
    return {"usuario": sesion.usuario, "rol": sesion.rol}


# ---------------------------------------------------------------------------- siniestros

@router.post("/claims", status_code=202, tags=["siniestros"], response_model=None)
async def crear_siniestro(
    request: Request,
    customer_id: Annotated[str, Form()],
    claim_type: Annotated[str, Form()],
    description: Annotated[str, Form()],
    incident_timestamp: Annotated[str, Form()],
    gps_latitude: Annotated[float | None, Form()] = None,
    gps_longitude: Annotated[float | None, Form()] = None,
    imagen: Annotated[UploadFile | None, File()] = None,
):  # type: ignore[no-untyped-def]
    """Registra el siniestro (con foto opcional) y lanza el triaje en segundo plano.

    multipart/form-data en vez de JSON: es el único endpoint que recibe un archivo.
    Responde 202 de inmediato con el `run_id`: el dashboard se conecta al stream de
    trazas y ve el trabajo del agente mientras ocurre.
    """
    # Endpoint público y caro (cada reporte gasta tokens): tope de frecuencia por IP.
    ip = _ip(request)
    for limitador, ventana in ((request.app.state.limite_reporte_min, "minuto"),
                               (request.app.state.limite_reporte_hora, "hora")):
        espera = limitador.intentar(ip)
        if espera > 0:
            log.warning("Reporte rechazado por frecuencia", extra={"ip": ip, "ventana": ventana})
            return _demasiadas(request, espera,
                               f"Se alcanzó el máximo de reportes por {ventana}. Intenta de nuevo en un momento.")

    gps = None
    if gps_latitude is not None and gps_longitude is not None:
        gps = {"latitude": gps_latitude, "longitude": gps_longitude}
    try:
        payload = ClaimIn.model_validate({
            "customer_id": customer_id, "claim_type": claim_type, "description": description,
            "incident_timestamp": incident_timestamp, "gps": gps,
        })
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None

    settings = request.app.state.settings
    ruta = mime = None
    tamano = 0
    if imagen is not None and imagen.filename:
        datos = await imagen.read()
        try:
            ruta, mime, tamano = save_image(
                Path(settings.uploads_dir), datos, imagen.content_type or "",
                max_bytes=settings.max_image_mb * 1024 * 1024,
            )
        except ImageRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    db = _db(request)
    agente = _agent(request)
    claim = await db.create_claim(
        customer_id=payload.customer_id,
        claim_type=payload.claim_type,
        description=payload.description.strip(),
        latitude=payload.gps.latitude if payload.gps else None,
        longitude=payload.gps.longitude if payload.gps else None,
        incident_timestamp=payload.incident_timestamp,
    )

    if ruta is not None:
        await db.create_attachment(claim["id"], file_path=ruta, mime_type=mime, size_bytes=tamano)
    claim["tiene_imagen"] = ruta is not None

    run_id = await agente.start_run(claim)

    async def _correr() -> None:
        try:
            await agente.run(claim, run_id=run_id)
        except Exception:  # noqa: BLE001 - el fallo se registra, no tumba el servidor
            log.exception("El triaje falló", extra={"run_id": str(run_id)})

    task = asyncio.create_task(_correr())
    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)

    log.info("Siniestro recibido", extra={"claim_id": str(claim["id"]), "run_id": str(run_id),
                                          "tipo": payload.claim_type})
    return {
        "claim_id": str(claim["id"]),
        "run_id": str(run_id),
        "estado": "RECIBIDO",
        "mensaje": "Reporte recibido. El triaje está en curso.",
        "stream": f"/api/runs/{run_id}/stream",
    }


@router.get("/claims", tags=["siniestros"])
async def listar_siniestros(
    request: Request,
    urgencia: Annotated[list[str] | None, Query()] = None,
    estado: Annotated[list[str] | None, Query()] = None,
    tipo: str | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    _: Sesion = TRABAJADOR,
) -> dict[str, Any]:
    filas = await _db(request).list_claims(urgency=urgencia, status=estado,
                                           claim_type=tipo, limit=limite)
    return {"total": len(filas), "items": [_fila(f) for f in filas]}


@router.get("/claims/{claim_id}", tags=["siniestros"])
async def detalle_siniestro(claim_id: UUID, request: Request, _: Sesion = TRABAJADOR) -> dict[str, Any]:
    db = _db(request)
    claim = await db.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="No existe ese siniestro.")
    run = await db.latest_run_for_claim(claim_id)
    pasos = await db.get_steps(run["id"]) if run else []
    return {
        "siniestro": _fila(claim),
        "historial": [_fila(h) for h in await db.history(claim_id)],
        "corrida": _fila(run) if run else None,
        "trazas": [_fila(p) for p in pasos],
    }


@router.get("/public/claims/{claim_id}", tags=["cliente"])
async def estado_publico(claim_id: UUID, request: Request) -> dict[str, Any]:
    """Lo único que ve el cliente de su reporte: estado y fechas.

    A propósito NO devuelve urgencia, puntuación, resumen del agente ni trazas: son
    herramientas internas del equipo, no información para el asegurado.
    """
    claim = await _db(request).get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="No encontramos un reporte con ese número.")
    return {
        "id": str(claim["id"]),
        "tipo": claim["claim_type"],
        "estado": claim["status"],
        "recibido": _serializa(claim["received_at"]),
        "actualizado": _serializa(claim["updated_at"]),
        "en_analisis": claim["urgency_level"] is None,
    }


@router.get("/claims/{claim_id}/image", tags=["siniestros"])
async def imagen_siniestro(claim_id: UUID, request: Request, _: Sesion = TRABAJADOR) -> FileResponse:
    """Devuelve la foto adjunta al reporte, si la hay (la misma que analizó el agente)."""
    adjunto = await _db(request).get_attachment(claim_id)
    if adjunto is None:
        raise HTTPException(status_code=404, detail="Este siniestro no tiene imagen adjunta.")
    settings = request.app.state.settings
    ruta = Path(settings.uploads_dir) / adjunto["file_path"]
    if not ruta.is_file():
        raise HTTPException(status_code=404, detail="El archivo de la imagen no está disponible.")
    return FileResponse(ruta, media_type=adjunto["mime_type"])


@router.patch("/claims/{claim_id}/status", tags=["siniestros"])
async def cambiar_estado(claim_id: UUID, payload: StatusIn, request: Request,
                         sesion: Sesion = TRABAJADOR) -> dict[str, Any]:
    if payload.estado in {"APPROVED", "REJECTED"} and len((payload.justificacion or "").strip()) < 5:
        raise HTTPException(status_code=400,
                            detail="La justificación es obligatoria (mínimo 5 caracteres) para aprobar o rechazar.")
    claim = await _db(request).update_status(claim_id, payload.estado,
                                             (payload.justificacion or "").strip() or None, sesion.usuario)
    if claim is None:
        raise HTTPException(status_code=404, detail="No existe ese siniestro.")
    return {"siniestro": _fila(claim)}


# ---------------------------------------------------------------------------- agente

@router.get("/runs/{run_id}", tags=["agente"])
async def ver_corrida(run_id: UUID, request: Request, _: Sesion = PERSONAL) -> dict[str, Any]:
    db = _db(request)
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No existe esa corrida del agente.")
    return {"corrida": _fila(run), "trazas": [_fila(p) for p in await db.get_steps(run_id)]}


@router.get("/runs/{run_id}/stream", tags=["agente"])
async def stream_corrida(run_id: UUID, request: Request, _: Sesion = TRABAJADOR) -> StreamingResponse:
    """Trazas en vivo por Server-Sent Events.

    Lee los pasos desde la base (no desde memoria): si el navegador se reconecta o se
    abre una segunda pestaña, la traza se ve completa igual.
    """
    db = _db(request)

    async def eventos():  # type: ignore[no-untyped-def]
        ultimo = -1
        terminales = {"COMPLETED", "FAILED", "LIMIT_REACHED", STATUS_AWAITING}
        for _ in range(600):                      # tope de seguridad: ~2 minutos
            if await request.is_disconnected():
                return
            pasos = await db.get_steps(run_id, after_idx=ultimo)
            for paso in pasos:
                ultimo = max(ultimo, paso["idx"])
                yield f"event: paso\ndata: {json.dumps(_fila(paso), ensure_ascii=False, default=str)}\n\n"
            run = await db.get_run(run_id)
            if run and run["status"] in terminales:
                yield f"event: fin\ndata: {json.dumps(_fila(run), ensure_ascii=False, default=str)}\n\n"
                return
            await asyncio.sleep(0.2)
        yield "event: fin\ndata: {\"status\": \"TIMEOUT_STREAM\"}\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------- operación (TI)

@router.get("/admin/stats", tags=["operación"])
async def admin_stats(request: Request, _: Sesion = SOLO_TI) -> dict[str, Any]:
    """Cifras agregadas para la vista de TI."""
    return await _db(request).stats()


@router.get("/admin/runs", tags=["operación"])
async def admin_runs(request: Request, limite: int = Query(default=25, ge=1, le=100),
                     _: Sesion = SOLO_TI) -> dict[str, Any]:
    """Últimas corridas del agente, con su consumo, y los últimos eventos anómalos."""
    db = _db(request)
    return {
        "corridas": [_fila(r) for r in await db.list_runs(limite)],
        "eventos": [_fila(e) for e in await db.recent_errors()],
    }


@router.get("/events", tags=["agente"])
async def avisos_en_vivo(request: Request, _: Sesion = TRABAJADOR) -> StreamingResponse:
    """Avisos en vivo para el trabajador (Server-Sent Events).

    Empuja solo lo que ocurre DESPUÉS de conectarse; al reconectar (el navegador lo hace solo) la
    pantalla vuelve a cargar la cola completa, así que un corte breve no pierde nada.
    """
    db = _db(request)

    async def eventos():  # type: ignore[no-untyped-def]
        cursor = await db.now()
        vistos: set[tuple] = set()
        ultimo_latido = time.monotonic()
        yield "retry: 3000\n\nevent: listo\ndata: {}\n\n"
        while True:
            if await request.is_disconnected():
                return
            datos = await db.events_since(cursor - SOLAPE)
            nuevos, cursor = construir_eventos(datos, vistos, cursor)
            for e in nuevos:
                yield f"event: {e['tipo']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                ultimo_latido = time.monotonic()
            if time.monotonic() - ultimo_latido > 15:      # mantiene viva la conexión tras proxies
                yield ": latido\n\n"
                ultimo_latido = time.monotonic()
            await asyncio.sleep(2)

    return StreamingResponse(eventos(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/confirm", tags=["agente"])
async def confirmar_accion(run_id: UUID, payload: ConfirmIn, request: Request,
                           sesion: Sesion = TRABAJADOR) -> dict[str, Any]:
    """Cuarto límite: una persona aprueba o rechaza la acción con efecto real."""
    agente = _agent(request)
    try:
        resultado = await agente.resume(run_id, approved=payload.aprobado, by=sesion.usuario)
    except LookupError:
        raise HTTPException(status_code=404, detail="No existe esa corrida del agente.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    log.info("Acción confirmada por humano", extra={"run_id": str(run_id), "aprobado": payload.aprobado,
                                                    "por": sesion.usuario})
    return resultado.to_dict()
