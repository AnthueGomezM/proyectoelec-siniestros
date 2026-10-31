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

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from claims_agent import __version__
from claims_agent.agent.loop import TriageAgent
from claims_agent.api.errors import install_error_handlers
from claims_agent.api.routes import router
from claims_agent.config import ConfigError, Settings
from claims_agent.db import Database
from claims_agent.logging_setup import configure_logging
from claims_agent.nlp.classifier import UrgencyClassifier
from claims_agent.providers.factory import build_fallback, build_image_analyzer, build_provider

log = logging.getLogger("claims_agent")

WEB_DIR = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings: Settings = app.state.settings
    configure_logging(settings.log_level, settings.service_name)
    log.info("Iniciando claims-agent", extra={"version": __version__, "config": settings.redacted()})

    db = Database(settings.database_url)
    await db.open()
    provider = build_provider(settings)
    fallback = build_fallback(settings)
    image_analyzer = build_image_analyzer(settings)

    app.state.db = db
    app.state.agent = TriageAgent(settings, db, provider, fallback, UrgencyClassifier(),
                                  image_analyzer=image_analyzer, uploads_dir=Path(settings.uploads_dir))
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
    install_error_handlers(app)
    app.include_router(router)

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

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
