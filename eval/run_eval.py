#!/usr/bin/env python3
"""Suite de evaluación: corre los casos dorados contra el agente completo y mide.

    python eval/run_eval.py                      # usa LLM_PROVIDER del entorno
    python eval/run_eval.py --provider offline   # sin modelo, sin gastar tokens
    python eval/run_eval.py --provider gemini    # con el modelo real (requiere clave)

Mide cuatro cifras de línea base, todas con MEDIANA (no promedio: una sola llamada
lenta no puede disfrazar el comportamiento típico):

  1. exactitud_urgencia       % de casos con el nivel esperado por un ajustador
  2. deteccion_inconsistencias % de inconsistencias esperadas efectivamente marcadas
  3. latencia_mediana_s        segundos de extremo a extremo por caso
  4. tokens_mediana            tokens (entrada+salida) consumidos por caso

Escribe eval/resultados/baseline-<fecha>-<proveedor>.json y .md. El .md es el que
se pega en docs/decisiones.md.

Los casos NO se guardan como siniestros reales: el agente corre sobre expedientes en
memoria (claim sin id), así que la base no se contamina con datos de prueba.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
# Funciona igual desde el repositorio (./eval/run_eval.py) y dentro del contenedor
# (/app/eval/run_eval.py), donde el código vive en /app/src.
for _candidato in (RAIZ / "app" / "src", RAIZ / "src", Path("/app/src")):
    if _candidato.is_dir():
        sys.path.insert(0, str(_candidato))
        break

from claims_agent.agent.loop import TriageAgent  # noqa: E402
from claims_agent.config import Settings  # noqa: E402
from claims_agent.db import Database  # noqa: E402
from claims_agent.nlp.classifier import UrgencyClassifier  # noqa: E402
from claims_agent.providers.factory import build_fallback, build_provider  # noqa: E402


def cargar_casos(ruta: Path) -> list[dict[str, Any]]:
    casos = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            casos.append(json.loads(linea))
    return casos


async def evaluar_caso(agente: TriageAgent, caso: dict[str, Any]) -> dict[str, Any]:
    claim = {
        "id": None,                       # expediente en memoria: no se persiste
        "customer_id": caso["customer_id"],
        "claim_type": caso["tipo"],
        "description": caso["relato"],
        "incident_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    inicio = time.perf_counter()
    try:
        resultado = await agente.run(claim)
        error = None
    except Exception as exc:  # noqa: BLE001 - un caso roto no detiene la suite
        return {
            "id": caso["id"], "ok": False, "error": f"{type(exc).__name__}: {exc}",
            "urgencia_esperada": caso["urgencia_esperada"], "urgencia_obtenida": None,
            "latencia_s": round(time.perf_counter() - inicio, 3), "tokens": 0,
            "herramientas": [], "inconsistencias_obtenidas": [],
            "inconsistencias_esperadas": caso["inconsistencias_esperadas"],
            "borde": caso.get("borde", False),
        }

    evaluacion = resultado.assessment or {}
    obtenida = evaluacion.get("urgencia")
    inconsistencias = [i["code"] for i in evaluacion.get("inconsistencias", [])]
    pasos = resultado.steps
    herramientas = [p["nombre"] for p in pasos if p["tipo"] == "tool_call"]

    return {
        "id": caso["id"],
        "ok": True,
        "error": None,
        "urgencia_esperada": caso["urgencia_esperada"],
        "urgencia_obtenida": obtenida,
        "acierto": obtenida == caso["urgencia_esperada"],
        "inconsistencias_esperadas": caso["inconsistencias_esperadas"],
        "inconsistencias_obtenidas": inconsistencias,
        "latencia_s": round(resultado.latency_ms / 1000, 3),
        "tokens": resultado.tokens_in + resultado.tokens_out,
        "iteraciones": resultado.iterations,
        "herramientas": herramientas,
        "estado": resultado.status,
        "degradado": resultado.degraded,
        "borde": caso.get("borde", False),
        "resumen": (resultado.summary or "")[:300],
    }


def resumir(filas: list[dict[str, Any]], proveedor: str, modelo: str) -> dict[str, Any]:
    completados = [f for f in filas if f["ok"]]
    aciertos = [f for f in completados if f.get("acierto")]

    esperadas = sum(len(f["inconsistencias_esperadas"]) for f in filas)
    detectadas = sum(
        len(set(f["inconsistencias_esperadas"]) & set(f["inconsistencias_obtenidas"]))
        for f in completados
    )
    falsos_positivos = sum(
        len(set(f["inconsistencias_obtenidas"]) - set(f["inconsistencias_esperadas"]))
        for f in completados
    )

    latencias = [f["latencia_s"] for f in completados] or [0]
    tokens = [f["tokens"] for f in completados] or [0]

    bordes = [f for f in filas if f["borde"]]
    bordes_ok = [f for f in bordes if f.get("acierto")]

    return {
        "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "proveedor": proveedor,
        "modelo": modelo,
        "casos": len(filas),
        "corridas_sin_error": len(completados),
        # --- las cuatro cifras de línea base ---
        "exactitud_urgencia_pct": round(100 * len(aciertos) / max(1, len(filas)), 1),
        "deteccion_inconsistencias_pct": round(100 * detectadas / esperadas, 1) if esperadas else None,
        "latencia_mediana_s": round(statistics.median(latencias), 3),
        "tokens_mediana": int(statistics.median(tokens)),
        # --- contexto ---
        "latencia_p90_s": round(sorted(latencias)[max(0, int(len(latencias) * 0.9) - 1)], 3),
        "tokens_total": sum(tokens),
        "inconsistencias_esperadas": esperadas,
        "inconsistencias_detectadas": detectadas,
        "inconsistencias_falsos_positivos": falsos_positivos,
        "casos_borde": len(bordes),
        "casos_borde_ok": len(bordes_ok),
        "herramientas_por_caso": round(
            statistics.mean([len(f["herramientas"]) for f in completados]) if completados else 0, 2),
        "corridas_degradadas": sum(1 for f in completados if f.get("degradado")),
    }


def markdown(resumen: dict[str, Any], filas: list[dict[str, Any]]) -> str:
    lineas = [
        f"# Línea base · {resumen['proveedor']} · {resumen['fecha']}",
        "",
        f"Modelo: `{resumen['modelo']}` · Casos: {resumen['casos']} "
        f"· Corridas sin error: {resumen['corridas_sin_error']}/{resumen['casos']}",
        "",
        "| Cifra | Mediana | Detalle |",
        "|---|---|---|",
        f"| Exactitud de urgencia | **{resumen['exactitud_urgencia_pct']} %** | "
        f"{sum(1 for f in filas if f.get('acierto'))} de {resumen['casos']} casos |",
        f"| Detección de inconsistencias | **{resumen['deteccion_inconsistencias_pct']} %** | "
        f"{resumen['inconsistencias_detectadas']} de {resumen['inconsistencias_esperadas']} esperadas, "
        f"{resumen['inconsistencias_falsos_positivos']} falsos positivos |",
        f"| Latencia por caso | **{resumen['latencia_mediana_s']} s** | p90 {resumen['latencia_p90_s']} s |",
        f"| Tokens por caso | **{resumen['tokens_mediana']}** | total {resumen['tokens_total']} |",
        "",
        f"Herramientas por caso: {resumen['herramientas_por_caso']} · "
        f"Casos borde acertados: {resumen['casos_borde_ok']}/{resumen['casos_borde']} · "
        f"Corridas degradadas: {resumen['corridas_degradadas']}",
        "",
        "## Caso por caso",
        "",
        "| Caso | Esperado | Obtenido | | Inconsistencias | s | tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in filas:
        marca = "✓" if f.get("acierto") else "✗"
        inc = ", ".join(f["inconsistencias_obtenidas"]) or "—"
        lineas.append(
            f"| {f['id']}{' (borde)' if f['borde'] else ''} | {f['urgencia_esperada']} | "
            f"{f['urgencia_obtenida'] or 'error'} | {marca} | {inc} | {f['latencia_s']} | {f['tokens']} |"
        )
    fallos = [f for f in filas if not f.get("acierto")]
    if fallos:
        lineas += ["", "## Casos que no acertaron", ""]
        for f in fallos:
            lineas.append(f"- **{f['id']}**: esperado {f['urgencia_esperada']}, "
                          f"obtenido {f['urgencia_obtenida'] or 'error'}. "
                          f"{f.get('error') or ''}")
    return "\n".join(lineas) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["gemini", "offline"], default=None,
                    help="Proveedor a evaluar (por defecto, el de LLM_PROVIDER)")
    ap.add_argument("--casos", type=Path, default=RAIZ / "eval" / "casos_dorados.jsonl")
    ap.add_argument("--salida", type=Path, default=RAIZ / "eval" / "resultados")
    ap.add_argument("--limite", type=int, default=0, help="Evaluar solo los primeros N casos")
    args = ap.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
        if args.provider == "offline":
            os.environ.pop("GEMINI_API_KEY", None)
    settings = Settings.from_env()

    casos = cargar_casos(args.casos)
    if args.limite:
        casos = casos[: args.limite]

    db = Database(settings.database_url, min_size=1, max_size=4)
    await db.open()
    if not await db.ping():
        print("ERROR: la base de datos no responde. ¿Está arriba docker compose?", file=sys.stderr)
        return 2

    provider = build_provider(settings)
    agente = TriageAgent(settings, db, provider, build_fallback(settings), UrgencyClassifier())

    print(f"Evaluando {len(casos)} casos con {provider.name} ({provider.model})…", file=sys.stderr)
    filas = []
    for i, caso in enumerate(casos, 1):
        fila = await evaluar_caso(agente, caso)
        filas.append(fila)
        marca = "✓" if fila.get("acierto") else "✗"
        print(f"  [{i:2}/{len(casos)}] {marca} {fila['id']} "
              f"{fila['urgencia_obtenida'] or 'ERROR'} ({fila['latencia_s']}s)", file=sys.stderr)

    resumen = resumir(filas, provider.name, provider.model)
    await provider.aclose()
    await db.close()

    args.salida.mkdir(parents=True, exist_ok=True)
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = args.salida / f"baseline-{sello}-{provider.name}"
    base.with_suffix(".json").write_text(
        json.dumps({"resumen": resumen, "casos": filas}, ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text(markdown(resumen, filas), encoding="utf-8")

    print("\n" + markdown(resumen, filas).split("## Caso por caso")[0])
    print(f"Resultados en {base.with_suffix('.md').relative_to(RAIZ)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
