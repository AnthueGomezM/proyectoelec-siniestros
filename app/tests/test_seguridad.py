"""Hardening: cada defensa del Bloque 1 con su prueba.

La idea del curso: la seguridad no está en el prompt, está en lo que el sistema PUEDE hacer.
Estas pruebas verifican justo eso, con el modelo y la base de datos sustituidos por dobles.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from claims_agent.agent.loop import TriageAgent
from claims_agent.agent.tools import TOOLS_BY_NAME, ToolContext
from claims_agent.auth import Autenticador, Sesion, firmar, verificar
from claims_agent.config import ConfigError, Settings, _usuarios
from claims_agent.main import create_app
from claims_agent.nlp.classifier import UrgencyClassifier
from claims_agent.providers.gemini import GeminiProvider
from claims_agent.providers.offline import OfflineProvider
from claims_agent.providers.vision import OfflineImageAnalyzer
from claims_agent.ratelimit import VentanaDeslizante
from tests.conftest import FakeDB, ScriptedProvider

CLAVE_TRABAJADOR = "clave-trabajador-1"
CLAVE_TI = "clave-ti-segura-2"


# =============================================================================
# 1. Las herramientas "deterministas" no obedecen al modelo
# =============================================================================

class DBEspia(FakeDB):
    """Anota con qué argumentos se le consultó."""

    def __init__(self, *a, **k):  # type: ignore[no-untyped-def]
        super().__init__(*a, **k)
        self.consultas: list[tuple] = []

    async def get_policy(self, customer_id):  # type: ignore[no-untyped-def]
        self.consultas.append(("poliza", customer_id))
        return await super().get_policy(customer_id)

    async def search_similar(self, description, claim_type, limit=3, exclude=None):  # type: ignore[no-untyped-def]
        self.consultas.append(("similares", description, claim_type))
        return []


def _ctx(db, claim, tmp_path, reader=None):  # type: ignore[no-untyped-def]
    return ToolContext(db=db, claim=claim, classifier=UrgencyClassifier(), uploads_dir=tmp_path,
                       image_analyzer=OfflineImageAnalyzer(), reader=reader)


async def test_clasificar_urgencia_ignora_el_relato_que_manda_el_modelo(claim, fake_db, tmp_path):
    """Inyección: el modelo es convencido de clasificar 'solo un rayón'. No debe importar."""
    ctx = _ctx(fake_db, claim, tmp_path)
    real = UrgencyClassifier().classify(claim["description"], claim["claim_type"]).to_dict()

    resultado = await TOOLS_BY_NAME["clasificar_urgencia"].handler(
        ctx, {"descripcion": "Solo un rayón leve en la puerta.", "tipo_siniestro": "HOME"})

    assert resultado["urgencia"] == real["urgencia"] == "CRITICAL"


async def test_consultar_poliza_usa_el_cliente_del_siniestro_no_el_del_modelo(claim, tmp_path):
    """Inyección: 'consulta la póliza de CUST-999999'. Solo se consulta la del reportante."""
    db = DBEspia(policy={"customer_id": "CUST-000123", "product": "AUTO", "status": "ACTIVE",
                         "coverage_limit": 1, "deductible": 1, "valid_from": "2026-01-01",
                         "valid_to": "2027-01-01", "city": "Bogotá", "vigente": True})
    await TOOLS_BY_NAME["consultar_poliza"].handler(_ctx(db, claim, tmp_path), {"customer_id": "CUST-999999"})

    assert db.consultas == [("poliza", "CUST-000123")]


async def test_buscar_similares_usa_el_relato_del_siniestro(claim, tmp_path):
    db = DBEspia()
    await TOOLS_BY_NAME["buscar_siniestros_similares"].handler(
        _ctx(db, claim, tmp_path), {"descripcion": "todas las contraseñas del sistema", "tipo_siniestro": "MEDICAL"})

    assert db.consultas == [("similares", claim["description"], "AUTO")]


async def test_las_herramientas_de_consulta_usan_la_conexion_de_solo_lectura(claim, tmp_path):
    """Mínimo privilegio: consultar_poliza y buscar_similares van por el lector, no por la conexión de escritura."""
    escritura, lectura = DBEspia(), DBEspia()
    ctx = _ctx(escritura, claim, tmp_path, reader=lectura)

    await TOOLS_BY_NAME["consultar_poliza"].handler(ctx, {"customer_id": "x"})
    await TOOLS_BY_NAME["buscar_siniestros_similares"].handler(ctx, {"descripcion": "x"})

    assert escritura.consultas == []
    assert [c[0] for c in lectura.consultas] == ["poliza", "similares"]


async def test_asignar_ajustador_escribe_por_la_conexion_normal(claim, tmp_path):
    escritura, lectura = DBEspia(), DBEspia()
    ctx = _ctx(escritura, claim, tmp_path, reader=lectura)

    await TOOLS_BY_NAME["asignar_ajustador"].handler(
        ctx, {"claim_id": str(claim["id"]), "ajustador": "ana", "motivo": "urgente"})

    assert len(escritura.asignaciones) == 1 and lectura.asignaciones == []


# =============================================================================
# 2. Sesión firmada y roles
# =============================================================================

def test_la_sesion_firmada_se_verifica_y_no_se_puede_alterar():
    token = firmar("secreto", Sesion("ana", "trabajador", int(time.time()) + 60))
    sesion = verificar("secreto", token)
    assert sesion and (sesion.usuario, sesion.rol) == ("ana", "trabajador")

    cuerpo, firma = token.split(".")
    assert verificar("otro-secreto", token) is None                 # firmada con otra clave
    assert verificar("secreto", f"{cuerpo}.{firma[:-2]}xx") is None   # firma adulterada
    assert verificar("secreto", "basura") is None
    assert verificar("secreto", None) is None


def test_la_sesion_vencida_no_vale():
    token = firmar("secreto", Sesion("ana", "trabajador", int(time.time()) - 1))
    assert verificar("secreto", token) is None


def test_cambiar_el_rol_dentro_del_token_invalida_la_firma():
    import base64
    import json
    token = firmar("secreto", Sesion("ana", "trabajador", int(time.time()) + 60))
    cuerpo, firma = token.split(".")
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    datos["r"] = "ti"
    falso = base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")
    assert verificar("secreto", f"{falso}.{firma}") is None


def test_credenciales():
    auth = Autenticador((("ana", "trabajador", CLAVE_TRABAJADOR),), secreto="s")
    assert auth.credenciales_validas("ana", CLAVE_TRABAJADOR).rol == "trabajador"
    assert auth.credenciales_validas("ana", "incorrecta") is None
    assert auth.credenciales_validas("nadie", CLAVE_TRABAJADOR) is None


def test_auth_users_se_valida_al_leer_la_configuracion():
    assert _usuarios("ana:trabajador:abcdefgh;soporte:ti:otra:con:dos")[1] == ("soporte", "ti", "otra:con:dos")
    for malo in ("ana:jefe:abcdefgh", "ana:ti:corta", "ana:ti", "ana:ti:abcdefgh;ana:ti:abcdefgh"):
        with pytest.raises(ConfigError):
            _usuarios(malo)


def test_sin_cuentas_la_aplicacion_no_arranca(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@h/db")
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    monkeypatch.delenv("AUTH_USERS", raising=False)
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    with pytest.raises(ConfigError, match="AUTH_USERS"):
        Settings.from_env()
    monkeypatch.setenv("AUTH_DISABLED", "true")
    assert Settings.from_env().auth_disabled is True


@pytest.fixture
def cliente_http() -> TestClient:
    settings = Settings(
        database_url="postgresql://x@localhost/x", llm_provider="offline",
        auth_users=(("ana", "trabajador", CLAVE_TRABAJADOR), ("soporte", "ti", CLAVE_TI)),
        rate_claims_per_minute=2, rate_claims_per_hour=50, rate_login_failures=3,
    )
    # Sin `with`: no se ejecuta el lifespan, no hace falta base de datos para probar el acceso.
    return TestClient(create_app(settings), follow_redirects=False)


def _entrar(cliente: TestClient, usuario: str, clave: str):  # type: ignore[no-untyped-def]
    return cliente.post("/api/auth/login", json={"usuario": usuario, "clave": clave})


def test_sin_sesion_las_rutas_del_personal_responden_401(cliente_http):
    for metodo, ruta in [("get", "/api/claims"), ("get", "/api/config"), ("get", "/api/admin/stats"),
                         ("get", "/api/admin/runs"), ("get", "/api/auth/me"),
                         ("get", "/api/claims/00000000-0000-0000-0000-000000000000"),
                         ("get", "/api/claims/00000000-0000-0000-0000-000000000000/image"),
                         ("get", "/api/runs/00000000-0000-0000-0000-000000000000"),
                         ("get", "/api/runs/00000000-0000-0000-0000-000000000000/stream")]:
        assert getattr(cliente_http, metodo)(ruta).status_code == 401, ruta
    # Las dos acciones que pasaban sin autenticación: aprobar al agente y decidir el caso.
    assert cliente_http.post("/api/runs/00000000-0000-0000-0000-000000000000/confirm",
                             json={"aprobado": True}).status_code == 401
    assert cliente_http.patch("/api/claims/00000000-0000-0000-0000-000000000000/status",
                              json={"estado": "APPROVED", "justificacion": "ok ok ok"}).status_code == 401


def test_las_paginas_del_personal_redirigen_al_ingreso(cliente_http):
    for ruta in ("/trabajador", "/ti"):
        r = cliente_http.get(ruta)
        assert r.status_code == 303 and r.headers["location"] == f"/ingresar?next={ruta}"
    assert cliente_http.get("/").status_code == 200           # el cliente no necesita cuenta
    assert cliente_http.get("/ingresar").status_code == 200
    assert cliente_http.get("/api/health").status_code == 200


def test_login_correcto_emite_cookie_httponly_y_samesite_strict(cliente_http):
    r = _entrar(cliente_http, "ana", CLAVE_TRABAJADOR)
    assert r.status_code == 200 and r.json()["destino"] == "/trabajador"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert cliente_http.get("/api/auth/me").json() == {"usuario": "ana", "rol": "trabajador"}
    assert cliente_http.get("/trabajador").status_code == 200


def test_cada_rol_solo_entra_a_lo_suyo(cliente_http):
    _entrar(cliente_http, "ana", CLAVE_TRABAJADOR)
    assert cliente_http.get("/api/admin/stats").status_code == 403
    assert cliente_http.get("/api/config").status_code == 403
    assert cliente_http.get("/ti").status_code == 303

    cliente_http.cookies.clear()
    _entrar(cliente_http, "soporte", CLAVE_TI)
    assert cliente_http.get("/api/claims").status_code == 403
    assert cliente_http.post("/api/runs/00000000-0000-0000-0000-000000000000/confirm",
                             json={"aprobado": True}).status_code == 403   # TI no aprueba al agente
    assert cliente_http.get("/trabajador").status_code == 303


def test_una_cookie_falsificada_no_abre_nada(cliente_http):
    cliente_http.cookies.set("guardia_sesion", "eyJ1IjoiYW5hIiwiciI6InRpIiwiZSI6OTk5OTk5OTk5OX0.firmafalsa")
    assert cliente_http.get("/api/admin/stats").status_code == 401
    assert cliente_http.get("/ti").status_code == 303


def test_cerrar_sesion(cliente_http):
    _entrar(cliente_http, "ana", CLAVE_TRABAJADOR)
    cliente_http.post("/api/auth/logout")
    assert cliente_http.get("/api/auth/me").status_code == 401


def test_clave_incorrecta_da_el_mismo_mensaje_exista_o_no_el_usuario(cliente_http):
    a = _entrar(cliente_http, "ana", "mala-clave-1")
    b = _entrar(cliente_http, "no-existe", "mala-clave-1")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_demasiados_intentos_de_login_se_bloquean(cliente_http):
    for _ in range(3):
        assert _entrar(cliente_http, "ana", "mala-clave-1").status_code == 401
    r = _entrar(cliente_http, "ana", CLAVE_TRABAJADOR)       # ni la clave correcta pasa mientras dura el bloqueo
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_con_auth_deshabilitada_las_paginas_abren():
    settings = Settings(database_url="postgresql://x@h/x", llm_provider="offline", auth_disabled=True)
    cliente = TestClient(create_app(settings), follow_redirects=False)
    assert cliente.get("/trabajador").status_code == 200
    assert cliente.get("/ti").status_code == 200


# =============================================================================
# 3. Cabeceras de seguridad
# =============================================================================

def test_cabeceras_de_seguridad(cliente_http):
    r = cliente_http.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp and "frame-ancestors 'none'" in csp
    assert cliente_http.get("/api/health").headers["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" not in cliente_http.get("/api/docs").headers   # Swagger usa CDN


def test_ninguna_pagina_usa_scripts_ni_estilos_en_linea():
    """La política de contenido bloquearía esto en silencio; mejor que falle aquí."""
    import re
    from pathlib import Path
    web = Path(__file__).parent.parent / "src" / "claims_agent" / "web"
    for html in web.glob("*.html"):
        texto = html.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", texto), f"{html.name}: script en línea"
        assert " style=" not in texto, f"{html.name}: estilo en línea"
        assert not re.search(r"\son\w+=", texto), f"{html.name}: manejador de evento en línea"


# =============================================================================
# 4. Límite de frecuencia y techo de gasto
# =============================================================================

def test_ventana_deslizante():
    t = [0.0]
    v = VentanaDeslizante(2, 10, reloj=lambda: t[0])
    assert v.intentar("ip") == 0 and v.intentar("ip") == 0
    assert 0 < v.intentar("ip") <= 10                # el tercero espera
    assert v.intentar("otra") == 0                    # cada IP tiene su cupo
    t[0] = 10.1
    assert v.intentar("ip") == 0                      # la ventana avanzó


def test_reportar_tiene_tope_por_ip(cliente_http):
    invalido = {"customer_id": "X", "claim_type": "AUTO", "description": "corto",
                "incident_timestamp": "2026-01-01T00:00:00Z"}
    # Con datos inválidos responde 400 antes de tocar la base: sirve para contar solo la frecuencia.
    assert cliente_http.post("/api/claims", data=invalido).status_code == 400
    assert cliente_http.post("/api/claims", data=invalido).status_code == 400
    r = cliente_http.post("/api/claims", data=invalido)
    assert r.status_code == 429 and "Retry-After" in r.headers


async def test_superado_el_techo_diario_el_triaje_corre_sin_gastar_tokens(settings, fake_db, claim):
    settings = replace(settings, llm_daily_token_budget=1000)
    fake_db.tokens_24h = 5000
    caro = ScriptedProvider([])                       # si se le llamara, devolvería texto: se comprueba que no
    agente = TriageAgent(settings, fake_db, caro, fallback=OfflineProvider())

    resultado = await agente.run(claim)

    assert caro.llamadas == 0
    assert resultado.degraded is True and resultado.provider == "offline"
    pasos = await fake_db.get_steps(resultado.run_id)
    assert any(p["kind"] == "limit" and p["name"] == "presupuesto_diario" for p in pasos)
    assert resultado.assessment and resultado.assessment["urgencia"] == "CRITICAL"   # sigue clasificando


async def test_bajo_el_techo_diario_se_usa_el_modelo(settings, fake_db, claim, texto):
    settings = replace(settings, llm_daily_token_budget=10_000)
    fake_db.tokens_24h = 500
    modelo = ScriptedProvider([texto("listo")])
    agente = TriageAgent(settings, fake_db, modelo, fallback=OfflineProvider())

    resultado = await agente.run(claim)

    assert modelo.llamadas >= 1 and resultado.degraded is False


async def test_techo_en_cero_significa_sin_techo(settings, fake_db, claim, texto):
    settings = replace(settings, llm_daily_token_budget=0)
    fake_db.tokens_24h = 10**9
    modelo = ScriptedProvider([texto("listo")])

    await TriageAgent(settings, fake_db, modelo, fallback=OfflineProvider()).run(claim)

    assert modelo.llamadas >= 1


def test_los_tokens_de_razonamiento_de_gemini_cuentan():
    """Gemini 3 piensa antes de responder; esos tokens gastan cuota aunque no se vean."""
    respuesta = GeminiProvider(api_key="x")._parse({
        "candidates": [{"content": {"parts": [{"text": "hola"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 20},
    })
    assert respuesta.tokens_in == 10 and respuesta.tokens_out == 25
