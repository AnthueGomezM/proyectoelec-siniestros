"""Punto de entrada de la aplicación: FastAPI + agente + dashboard en un solo proceso.

Un solo servicio a propósito: el evaluador debe levantar todo con un comando y en
menos de cinco minutos. Las piezas siguen separadas por módulos (api / agent /
providers / nlp / db), así que partirlo en varios servicios más adelante es mover
carpetas, no reescribir.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from claims_agent import __version__
from claims_agent.agent.loop import TriageAgent
from claims_agent.api.errors import install_error_handlers
from claims_agent.api.routes import router
from claims_agent.auth import Autenticador
from claims_agent.config import ConfigError, Settings
from claims_agent.db import Database
from claims_agent.logging_setup import configure_logging
from claims_agent.nlp.classifier import UrgencyClassifier
from claims_agent.providers.factory import build_fallback, build_image_analyzer, build_provider
from claims_agent.ratelimit import VentanaDeslizante

log = logging.getLogger("claims_agent")

WEB_DIR = Path(__file__).parent / "web"

#: ruta -> (archivo, roles que pueden abrirla; None = pública).
#: El cliente vive en la raíz porque es quien llega sin saber nada del sistema.
#:
#: Es una aplicación de una sola página: las cuatro rutas sirven la MISMA página contenedor y el
#: enrutado entre vistas lo hace el navegador sin recargar. El control de acceso sigue siendo del
#: servidor: sin sesión del rol correcto, /trabajador y /ti redirigen al ingreso (303) y ni
#: siquiera entregan la página; y la API valida el rol en cada llamada.
PAGINA = "index.html"
PAGINAS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "/": (PAGINA, None),
    "/ingresar": (PAGINA, None),
    "/trabajador": (PAGINA, ("trabajador",)),
    "/ti": (PAGINA, ("ti",)),
}

#: Política de contenido: solo se ejecuta JavaScript propio, sin scripts ni estilos en línea.
#: Aunque un relato de cliente lograra colar HTML, el navegador no lo ejecutaría. Las únicas
#: terceras partes permitidas son las tipografías de Google Fonts. (Swagger en /api/docs usa
#: scripts de CDN y estilos en línea, por eso se excluye de esta política.)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def _registrar_pagina(app: FastAPI, ruta: str, archivo: Path, roles: tuple[str, ...] | None) -> None:
    @app.get(ruta, include_in_schema=False)
    async def pagina(request: Request):  # type: ignore[no-untyped-def]
        if roles is not None:
            sesion = request.app.state.auth.leer(request)
            if sesion is None or (sesion.rol != "*" and sesion.rol not in roles):
                # Sin sesión (o con el rol equivocado): al formulario de ingreso, y de vuelta aquí.
                return RedirectResponse(f"/ingresar?next={ruta}", status_code=303)
        return FileResponse(archivo, headers={"Cache-Control": "no-store"})


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings: Settings = app.state.settings
    configure_logging(settings.log_level, settings.service_name)
    log.info("Iniciando claims-agent", extra={"version": __version__, "config": settings.redacted()})

    if any(clave.startswith("cambia-esta-clave") for _, _, clave in settings.auth_users):
        log.warning("AUTH_USERS conserva las claves de ejemplo de .env.example: cámbialas antes de "
                    "exponer la aplicación.")
    if settings.auth_disabled:
        log.warning("AUTH_DISABLED=true: las vistas del trabajador y de TI NO piden sesión. "
                    "Úsalo solo en desarrollo local.")

    db = Database(settings.database_url)
    await db.open()
    # Mínimo privilegio: las herramientas del agente que solo consultan usan un rol de SOLO
    # LECTURA (db/03-roles.sh). Si el agente fuera engañado o alucinara, la base misma le
    # impide escribir o leer lo que no necesita. Sin AGENT_DATABASE_URL se usa la conexión común.
    reader = db
    if settings.agent_database_url:
        reader = Database(settings.agent_database_url, max_size=4)
        await reader.open()
    else:
        log.warning("AGENT_DATABASE_URL vacío: el agente consulta con la misma conexión que la app "
                    "(sin el rol de solo lectura).")
    provider = build_provider(settings)
    fallback = build_fallback(settings)
    image_analyzer = build_image_analyzer(settings)

    app.state.db = db
    app.state.agent = TriageAgent(settings, db, provider, fallback, UrgencyClassifier(),
                                  image_analyzer=image_analyzer, uploads_dir=Path(settings.uploads_dir),
                                  reader=reader)
    app.state.tasks = set()

    if not await db.ping():
        # No se aborta el arranque: /api/ready quedará en 503 hasta que la BD responda,
        # que es como debe comportarse un servicio en un orquestador.
        log.warning("La base de datos no responde todavía; /api/ready seguirá en 503 hasta que lo haga")

    try:
        yield
    finally:
        for task in list(app.state.tasks):
            task.cancel()
        await provider.aclose()
        if fallback is not None:
            await fallback.aclose()
        await image_analyzer.aclose()
        if reader is not db:
            await reader.close()
        await db.close()
        log.info("claims-agent detenido")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Triaje de Siniestros con Agente IA",
        version=__version__,
        description=(
            "API de recepción y triaje de siniestros. El agente orquesta herramientas "
            "propias; la clasificación de urgencia la decide código determinista."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.auth = Autenticador(settings.auth_users, settings.session_secret,
                                  settings.session_ttl_minutes, settings.auth_disabled)
    # Fallos de login: ventana de 5 min. Reportes: dos ventanas (ráfaga y sostenido).
    app.state.limite_login = VentanaDeslizante(settings.rate_login_failures, 300)
    app.state.limite_reporte_min = VentanaDeslizante(settings.rate_claims_per_minute, 60)
    app.state.limite_reporte_hora = VentanaDeslizante(settings.rate_claims_per_hour, 3600)
    install_error_handlers(app)
    app.include_router(router)

    @app.middleware("http")
    async def cabeceras_de_seguridad(request: Request, call_next):  # type: ignore[no-untyped-def]
        respuesta = await call_next(request)
        ruta = request.url.path
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "no-referrer")
        respuesta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not ruta.startswith(("/api/docs", "/api/openapi")):
            respuesta.headers.setdefault("Content-Security-Policy", CSP)
        if ruta.startswith("/api/"):
            respuesta.headers.setdefault("Cache-Control", "no-store")   # nada de la API se guarda en caché
        return respuesta

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        # Una página por audiencia. Comparten /static (estilos y comun.js) y el mismo backend.
        for ruta, (archivo, roles) in PAGINAS.items():
            _registrar_pagina(app, ruta, WEB_DIR / archivo, roles)

    return app


def main() -> None:
    """Arranque para `python -m claims_agent.main` (en Docker lo lanza uvicorn)."""
    import uvicorn

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        configure_logging("INFO")
        log.error("Configuración inválida: %s", exc)
        raise SystemExit(2) from None
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.app_port, log_config=None)


if __name__ == "__main__":
    main()
