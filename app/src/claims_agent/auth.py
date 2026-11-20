"""Acceso del personal: sesión firmada en una cookie, con dos roles.

Por qué existe: la aprobación humana del agente (cuarto límite) solo vale si quien aprueba
es de verdad una persona autorizada. Sin esto, cualquiera que conociera la URL, incluido el
cliente que reportó el siniestro, podía llamar a `/api/runs/{id}/confirm`.

Diseño deliberadamente pequeño (stdlib, sin dependencias):

  * Cuentas en AUTH_USERS (`usuario:rol:clave;...`). Roles: `trabajador` y `ti`.
  * Al iniciar sesión se emite una cookie `usuario|rol|expira` firmada con HMAC-SHA256.
    No guarda nada en el servidor: reiniciar con el mismo SESSION_SECRET no cierra sesiones;
    sin SESSION_SECRET se genera uno al arrancar y las sesiones mueren con el proceso.
  * Cookie HttpOnly (el JavaScript de la página no puede leerla) y SameSite=Strict (el
    navegador no la envía en peticiones que se originan en otro sitio: frena CSRF).
  * Comparaciones en tiempo constante; si el usuario no existe se compara contra una clave
    señuelo para que el tiempo de respuesta no delate qué cuentas existen.

El cliente (quien reporta) NO tiene cuenta: solo puede crear un reporte y consultar su estado.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

COOKIE = "guardia_sesion"

_SENUELO = secrets.token_urlsafe(16)


@dataclass(frozen=True)
class Sesion:
    usuario: str
    rol: str
    expira: int  # epoch, segundos


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def firmar(secreto: str, sesion: Sesion) -> str:
    cuerpo = _b64(json.dumps({"u": sesion.usuario, "r": sesion.rol, "e": sesion.expira},
                             separators=(",", ":")).encode("utf-8"))
    firma = hmac.new(secreto.encode("utf-8"), cuerpo.encode("ascii"), hashlib.sha256).digest()
    return f"{cuerpo}.{_b64(firma)}"


def verificar(secreto: str, token: str | None, ahora: float | None = None) -> Sesion | None:
    """Devuelve la sesión si la firma es válida y no venció; None en cualquier otro caso."""
    if not token or token.count(".") != 1:
        return None
    cuerpo, firma = token.split(".")
    esperada = hmac.new(secreto.encode("utf-8"), cuerpo.encode("ascii"), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(esperada, _desb64(firma)):
            return None
        datos = json.loads(_desb64(cuerpo))
        sesion = Sesion(usuario=str(datos["u"]), rol=str(datos["r"]), expira=int(datos["e"]))
    except (ValueError, KeyError, TypeError):
        return None
    if sesion.expira <= (time.time() if ahora is None else ahora):
        return None
    return sesion


class Autenticador:
    """Valida credenciales y emite/lee sesiones. Una instancia por aplicación."""

    def __init__(self, usuarios: tuple[tuple[str, str, str], ...], secreto: str = "",
                 ttl_minutos: int = 480, deshabilitado: bool = False) -> None:
        self._claves = {u: (rol, clave) for u, rol, clave in usuarios}
        self._secreto = secreto or secrets.token_urlsafe(32)
        self.ttl_segundos = ttl_minutos * 60
        self.deshabilitado = deshabilitado

    def credenciales_validas(self, usuario: str, clave: str) -> Sesion | None:
        rol, esperada = self._claves.get(usuario, ("", _SENUELO))
        coincide = hmac.compare_digest(clave.encode("utf-8"), esperada.encode("utf-8"))
        if not coincide or not rol:
            return None
        return Sesion(usuario=usuario, rol=rol, expira=int(time.time()) + self.ttl_segundos)

    def emitir(self, sesion: Sesion) -> str:
        return firmar(self._secreto, sesion)

    def leer(self, request: Request) -> Sesion | None:
        if self.deshabilitado:
            # Modo desarrollo declarado en la configuración: se avisa al arrancar.
            return Sesion(usuario="dev", rol="*", expira=int(time.time()) + 3600)
        return verificar(self._secreto, request.cookies.get(COOKIE))


def sesion_actual(request: Request) -> Sesion | None:
    return request.app.state.auth.leer(request)


def requiere(*roles: str):  # type: ignore[no-untyped-def]
    """Dependencia de FastAPI: exige sesión y que el rol esté entre los permitidos."""

    def dependencia(request: Request) -> Sesion:
        sesion = sesion_actual(request)
        if sesion is None:
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
        if sesion.rol != "*" and sesion.rol not in roles:
            raise HTTPException(status_code=403, detail="Tu cuenta no tiene permiso para esta acción.")
        return sesion

    return dependencia
