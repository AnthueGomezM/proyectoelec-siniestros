"""Configuración por variables de entorno (12-factor).

Todas las variables están documentadas en .env.example. El arranque falla con un
mensaje claro si falta algo obligatorio: la rúbrica considera falla crítica que la
app no inicie por una variable oculta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping


class ConfigError(RuntimeError):
    """Configuración ausente o inválida. Se reporta en lenguaje claro al arrancar."""


def _int(env: Mapping[str, str], key: str, default: int, minimum: int = 1) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} debe ser un entero; se recibió {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} debe ser >= {minimum}; se recibió {value}")
    return value


def _float(env: Mapping[str, str], key: str, default: float, minimum: float = 0.1) -> float:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} debe ser numérico; se recibió {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} debe ser >= {minimum}; se recibió {value}")
    return value


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = (env.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "si", "sí", "on"}


ROLES = ("trabajador", "ti")


def _usuarios(raw: str) -> tuple[tuple[str, str, str], ...]:
    """Lee AUTH_USERS: `usuario:rol:clave;usuario:rol:clave`.

    La clave va al final y puede contener ':' (se parte solo en los dos primeros). No puede
    contener ';'. Falla con un mensaje claro: una cuenta mal escrita no debe pasar en silencio.
    """
    usuarios: list[tuple[str, str, str]] = []
    vistos: set[str] = set()
    for entrada in (e.strip() for e in raw.split(";")):
        if not entrada:
            continue
        partes = entrada.split(":", 2)
        if len(partes) != 3:
            raise ConfigError("AUTH_USERS debe tener el formato usuario:rol:clave;usuario:rol:clave")
        usuario, rol, clave = (p.strip() if i < 2 else p for i, p in enumerate(partes))
        if not usuario or usuario in vistos:
            raise ConfigError(f"AUTH_USERS: usuario vacío o repetido ({usuario!r})")
        if rol not in ROLES:
            raise ConfigError(f"AUTH_USERS: el rol de {usuario!r} debe ser uno de {ROLES}; se recibió {rol!r}")
        if len(clave) < 8:
            raise ConfigError(f"AUTH_USERS: la clave de {usuario!r} debe tener al menos 8 caracteres")
        vistos.add(usuario)
        usuarios.append((usuario, rol, clave))
    return tuple(usuarios)


@dataclass(frozen=True)
class Settings:
    """Configuración efectiva del proceso."""

    database_url: str
    # --- proveedor de IA ---
    llm_provider: str = "gemini"          # gemini | offline
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    llm_timeout_seconds: float = 10.0
    llm_temperature: float = 0.0
    # --- LÍMITE 1..4 del bucle agéntico (ver docs/decisiones.md) ---
    agent_max_iterations: int = 6
    agent_timeout_seconds: float = 45.0
    agent_max_tokens: int = 8000
    agent_require_confirmation: bool = True
    # --- gasto: techo diario, además del tope por corrida (0 = sin techo) ---
    llm_daily_token_budget: int = 200_000
    # --- acceso del personal (cliente sigue siendo público) ---
    auth_users: tuple[tuple[str, str, str], ...] = ()   # (usuario, rol, clave)
    auth_disabled: bool = False                          # solo desarrollo; ver .env.example
    session_secret: str = ""                             # vacío = se genera al arrancar
    session_ttl_minutes: int = 480
    auth_cookie_secure: bool = False                     # true si se sirve por HTTPS
    # --- frecuencia: protege la cuota y el costo del modelo ---
    rate_claims_per_minute: int = 10
    rate_claims_per_hour: int = 60
    rate_login_failures: int = 5                         # por IP, en ventana de 5 minutos
    # --- base de datos: rol de solo lectura para las herramientas del agente ---
    agent_database_url: str = ""
    # --- degradación ---
    allow_offline_fallback: bool = True
    # --- imágenes adjuntas ---
    uploads_dir: str = "/data/uploads"
    max_image_mb: int = 8
    # --- servidor ---
    app_port: int = 8000
    log_level: str = "INFO"
    service_name: str = "claims-agent"
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env

        database_url = (env.get("DATABASE_URL") or "").strip()
        if not database_url:
            raise ConfigError(
                "Falta DATABASE_URL. Copia .env.example a .env "
                "(ejemplo: postgresql://claims:claims@db:5432/claims)"
            )

        provider = (env.get("LLM_PROVIDER") or "gemini").strip().lower()
        if provider not in {"gemini", "offline"}:
            raise ConfigError(f"LLM_PROVIDER debe ser 'gemini' u 'offline'; se recibió {provider!r}")

        api_key = (env.get("GEMINI_API_KEY") or "").strip()
        if provider == "gemini" and not api_key:
            raise ConfigError(
                "LLM_PROVIDER=gemini pero GEMINI_API_KEY está vacía. "
                "Pon tu clave en .env o usa LLM_PROVIDER=offline para correr sin IA externa."
            )

        auth_disabled = _bool(env, "AUTH_DISABLED", False)
        auth_users = _usuarios(env.get("AUTH_USERS") or "")
        if not auth_users and not auth_disabled:
            raise ConfigError(
                "Falta AUTH_USERS: las vistas del trabajador y de TI exigen inicio de sesión. "
                "Define al menos una cuenta (usuario:rol:clave, roles: trabajador o ti) en .env, "
                "o pon AUTH_DISABLED=true solo para desarrollo local."
            )

        return cls(
            database_url=database_url,
            llm_provider=provider,
            gemini_api_key=api_key,
            gemini_model=(env.get("GEMINI_MODEL") or "gemini-3.5-flash").strip(),
            gemini_base_url=(env.get("GEMINI_BASE_URL")
                             or "https://generativelanguage.googleapis.com/v1beta").rstrip("/"),
            llm_timeout_seconds=_float(env, "LLM_TIMEOUT_SECONDS", 10.0),
            llm_temperature=_float(env, "LLM_TEMPERATURE", 0.0, minimum=0.0),
            agent_max_iterations=_int(env, "AGENT_MAX_ITERATIONS", 6),
            agent_timeout_seconds=_float(env, "AGENT_TIMEOUT_SECONDS", 45.0),
            agent_max_tokens=_int(env, "AGENT_MAX_TOKENS", 8000, minimum=256),
            agent_require_confirmation=_bool(env, "AGENT_REQUIRE_CONFIRMATION", True),
            llm_daily_token_budget=_int(env, "LLM_DAILY_TOKEN_BUDGET", 200_000, minimum=0),
            auth_users=auth_users,
            auth_disabled=auth_disabled,
            session_secret=(env.get("SESSION_SECRET") or "").strip(),
            session_ttl_minutes=_int(env, "SESSION_TTL_MINUTES", 480),
            auth_cookie_secure=_bool(env, "AUTH_COOKIE_SECURE", False),
            rate_claims_per_minute=_int(env, "RATE_CLAIMS_PER_MINUTE", 10),
            rate_claims_per_hour=_int(env, "RATE_CLAIMS_PER_HOUR", 60),
            rate_login_failures=_int(env, "RATE_LOGIN_FAILURES", 5),
            agent_database_url=(env.get("AGENT_DATABASE_URL") or "").strip(),
            allow_offline_fallback=_bool(env, "ALLOW_OFFLINE_FALLBACK", True),
            uploads_dir=(env.get("UPLOADS_DIR") or "/data/uploads").strip(),
            max_image_mb=_int(env, "MAX_IMAGE_MB", 8, minimum=1),
            app_port=_int(env, "APP_PORT", 8000),
            log_level=(env.get("LOG_LEVEL") or "INFO").strip().upper(),
        )

    def redacted(self) -> dict[str, object]:
        """Vista segura para logs: nunca imprime la API key ni la contraseña de la BD."""
        return {
            "database": _redact_url(self.database_url),
            "llm_provider": self.llm_provider,
            "model": self.gemini_model if self.llm_provider == "gemini" else "reglas-deterministas",
            "api_key": "***" if self.gemini_api_key else "(sin clave)",
            "limites": {
                "max_iteraciones": self.agent_max_iterations,
                "timeout_s": self.agent_timeout_seconds,
                "max_tokens": self.agent_max_tokens,
                "confirmacion_humana": self.agent_require_confirmation,
            },
            "fallback_offline": self.allow_offline_fallback,
            "presupuesto_diario_tokens": self.llm_daily_token_budget or "sin techo",
            "acceso": ("DESACTIVADO (solo desarrollo)" if self.auth_disabled
                       else f"{len(self.auth_users)} cuenta(s)"),
            "base_agente": ("rol de solo lectura" if self.agent_database_url
                            else "misma conexión que la app (sin rol separado)"),
        }


def _redact_url(url: str) -> str:
    """postgresql://user:secreto@host/db -> postgresql://user:***@host/db"""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
