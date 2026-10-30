#!/usr/bin/env python3
"""Verifica que el proveedor de IA configurado responde de verdad.

Córrelo ANTES de la demo: hace una llamada mínima (una herramienta ficticia) y
reporta latencia, tokens y modelo. Si la clave está vencida o sin cuota, se entera
ahora y no delante del salón.

    ./run.sh check
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for _candidato in (RAIZ / "app" / "src", RAIZ / "src", Path("/app/src")):
    if _candidato.is_dir():
        sys.path.insert(0, str(_candidato))
        break

from claims_agent.config import ConfigError, Settings  # noqa: E402
from claims_agent.providers.base import Msg, ProviderError, ToolSpec  # noqa: E402
from claims_agent.providers.factory import build_provider  # noqa: E402

SONDA = [ToolSpec(
    name="saludar",
    description="Devuelve un saludo. Úsala siempre que te pidan comprobar la conexión.",
    parameters={"type": "object", "properties": {"nombre": {"type": "string"}}, "required": ["nombre"]},
)]


async def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"✗ Configuración inválida: {exc}")
        return 2

    provider = build_provider(settings)
    print(f"▸ Proveedor: {provider.name} · modelo: {provider.model}")
    if settings.llm_provider == "offline":
        print("! LLM_PROVIDER=offline: no se hace ninguna llamada externa.")
        print("  El triaje funcionará con reglas deterministas. Para usar Gemini, "
              "pon GEMINI_API_KEY en .env y vuelve a levantar con ./run.sh")
        return 0

    inicio = time.perf_counter()
    try:
        respuesta = await provider.complete(
            system="Eres una sonda de conexión. Llama a la herramienta saludar con nombre='demo'.",
            messages=[Msg(role="user", text="Comprueba la conexión.")],
            tools=SONDA,
            max_output_tokens=64,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    except ProviderError as exc:
        print(f"✗ {type(exc).__name__}: {exc}")
        print(f"  Mensaje para el usuario: {exc.user_message}")
        print("  Revisa GEMINI_API_KEY en .env, o levanta con LLM_PROVIDER=offline para la demo.")
        await provider.aclose()
        return 1
    finally:
        pass

    ms = int((time.perf_counter() - inicio) * 1000)
    herramientas = [c.name for c in respuesta.tool_calls]
    print(f"✓ Respondió en {ms} ms · tokens {respuesta.tokens_in}→{respuesta.tokens_out}")
    print(f"  Herramientas pedidas: {herramientas or 'ninguna'} · texto: {(respuesta.text or '')[:80]!r}")
    if not herramientas:
        print("! El modelo no usó la herramienta en la sonda. El triaje puede funcionar igual, "
              "pero vigila la traza en la demo.")
    await provider.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
