"""Herramientas del agente: lo que el modelo puede hacer, y nada más.

Cada herramienta declara:
  * `description`: redactada como un prompt (cuándo usarla, cuándo NO, qué devuelve).
    Estas descripciones se iteraron contra la suite `eval/`; los comentarios "v1 → v2"
    registran qué cambió y por qué (detalle completo en docs/decisiones.md § El agente).
  * `parameters`: JSON Schema. Los argumentos se validan ANTES de ejecutar: si el
    modelo inventa un campo o manda un tipo incorrecto, recibe un error legible y
    puede corregirse, en vez de tumbar la corrida.
  * `requires_confirmation`: si es True, el bucle se detiene y espera que una persona
    apruebe la acción desde el dashboard (cuarto límite del agente).

Ninguna herramienta ejecuta SQL arbitrario ni recibe texto libre que termine en una
consulta: todas usan sentencias parametrizadas del módulo db.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

from claims_agent.db import Database
from claims_agent.nlp.classifier import UrgencyClassifier
from claims_agent.providers.base import ToolSpec
from claims_agent.providers.vision import ImageAnalyzer
from claims_agent.storage import read_image

log = logging.getLogger(__name__)


class ToolValidationError(ValueError):
    """Los argumentos no cumplen el esquema. Se le devuelve al modelo para que reintente."""


class ToolExecutionError(RuntimeError):
    """La herramienta falló por una causa externa (BD caída, por ejemplo)."""


@dataclass
class ToolContext:
    """Todo lo que una herramienta puede tocar. No hay acceso global a nada más."""

    db: Database
    claim: dict[str, Any]
    classifier: UrgencyClassifier
    uploads_dir: Path
    image_analyzer: ImageAnalyzer
    #: Conexión de SOLO LECTURA (rol claims_agent_ro). Las herramientas que solo consultan
    #: la usan; únicamente `asignar_ajustador`, ya aprobada por una persona, usa `db`.
    #: Si no se configura, cae en `db` (pruebas y arranque sin rol separado).
    reader: Database | None = None

    @property
    def lector(self) -> Database:
        return self.reader or self.db


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]
    requires_confirmation: bool = False
    timeout_seconds: float = 8.0
    #: Si es True, `timeout_seconds` es un piso: el bucle lo amplía hasta cubrir
    #: LLM_TIMEOUT_SECONDS, porque el handler hace su propia llamada a un modelo
    #: (no una consulta SQL rápida) y no puede cortarse antes que esa llamada termine.
    uses_llm: bool = False
    notes: str = field(default="", compare=False)
    #: Si no es None, la herramienta es DETERMINISTA y va siempre primero: el sistema la ejecuta
    #: antes del primer turno del modelo con estos argumentos (sacados del siniestro) y el
    #: modelo recibe el resultado ya en la conversación. Así no gasta un viaje completo al
    #: modelo (con todo su contexto) para ejecutar algo que no requiere razonamiento, y su
    #: declaración deja de enviarse en cada llamada (ver `tool_specs`).
    args_previos: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)


# ---------------------------------------------------------------------------- validación

_PY_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Valida contra el subconjunto de JSON Schema que usamos y devuelve los argumentos limpios.

    Se implementa a mano (30 líneas) en vez de traer `jsonschema`: solo usamos
    required/type/enum/min/max, y así el error es un mensaje en español que el modelo
    entiende y puede corregir en la siguiente iteración.
    """
    props: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    limpio: dict[str, Any] = {}

    faltantes = [campo for campo in required if arguments.get(campo) in (None, "")]
    if faltantes:
        raise ToolValidationError(
            f"Faltan argumentos obligatorios: {', '.join(faltantes)}. "
            f"Campos esperados: {', '.join(props)}."
        )

    desconocidos = [k for k in arguments if k not in props]
    if desconocidos:
        raise ToolValidationError(
            f"Argumentos no reconocidos: {', '.join(desconocidos)}. "
            f"Usa solo: {', '.join(props)}."
        )

    for campo, definicion in props.items():
        if campo not in arguments or arguments[campo] is None:
            if "default" in definicion:
                limpio[campo] = definicion["default"]
            continue
        valor = arguments[campo]
        esperado = definicion.get("type")
        py_type = _PY_TYPES.get(esperado) if esperado else None
        if py_type and not isinstance(valor, py_type):
            # Los modelos a veces mandan números como texto: se convierte en vez de fallar.
            if esperado in {"integer", "number"} and isinstance(valor, str):
                try:
                    valor = int(valor) if esperado == "integer" else float(valor)
                except ValueError:
                    raise ToolValidationError(
                        f"El campo '{campo}' debe ser {esperado}; se recibió {valor!r}."
                    ) from None
            else:
                raise ToolValidationError(
                    f"El campo '{campo}' debe ser {esperado}; se recibió {type(valor).__name__}."
                )
        opciones = definicion.get("enum")
        if opciones and valor not in opciones:
            raise ToolValidationError(
                f"El campo '{campo}' debe ser uno de {opciones}; se recibió {valor!r}."
            )
        if esperado == "integer":
            minimo, maximo = definicion.get("minimum"), definicion.get("maximum")
            if minimo is not None and valor < minimo:
                valor = minimo
            if maximo is not None and valor > maximo:
                valor = maximo
        limpio[campo] = valor
    return limpio


# ---------------------------------------------------------------------------- implementaciones

def _del_siniestro(ctx: ToolContext, clave_claim: str, args: dict[str, Any],
                   clave_arg: str, herramienta: str) -> str:
    """El dato sale del siniestro guardado, NUNCA de lo que el modelo escriba.

    El texto del relato es contenido no confiable: si una inyección convence al modelo de
    llamar a `clasificar_urgencia` con otro relato ("solo un rayón"), o a `consultar_poliza`
    con el cliente de otra persona, el modelo estaría gobernando una herramienta que
    debería ser determinista. Por eso el argumento del modelo se descarta y el valor se lee
    del expediente. Si ambos difieren, queda un aviso en el log: es la huella de una
    inyección (o de un modelo confundido), y vale la pena mirarla.
    """
    real = ctx.claim.get(clave_claim)
    pedido = args.get(clave_arg)
    if real in (None, ""):
        # Sin siniestro asociado (herramienta invocada de forma aislada, p. ej. en pruebas).
        return str(pedido or "")
    if pedido not in (None, "") and str(pedido).strip() != str(real).strip():
        log.warning("Argumento del modelo ignorado: no coincide con el siniestro guardado",
                    extra={"herramienta": herramienta, "campo": clave_arg,
                           "claim_id": str(ctx.claim.get("id", ""))})
    return str(real)


async def _clasificar_urgencia(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    descripcion = _del_siniestro(ctx, "description", args, "descripcion", "clasificar_urgencia")
    tipo = _del_siniestro(ctx, "claim_type", args, "tipo_siniestro", "clasificar_urgencia") or None
    return ctx.classifier.classify(descripcion, tipo).to_dict()


async def _consultar_poliza(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    customer_id = _del_siniestro(ctx, "customer_id", args, "customer_id", "consultar_poliza")
    poliza = await ctx.lector.get_policy(customer_id.strip())
    if poliza is None:
        return {
            "encontrada": False,
            "customer_id": customer_id,
            "mensaje": "No existe una póliza con ese identificador de cliente.",
        }
    return {
        "encontrada": True,
        "customer_id": poliza["customer_id"],
        "producto": poliza["product"],
        "estado": poliza["status"],
        "vigente": bool(poliza["vigente"]),
        "limite_cobertura": float(poliza["coverage_limit"]),
        "deducible": float(poliza["deductible"]),
        "vigencia": f"{poliza['valid_from']} a {poliza['valid_to']}",
        "ciudad": poliza["city"],
    }


async def _analizar_imagen(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    claim_id = ctx.claim.get("id")
    if not isinstance(claim_id, UUID):
        return {"tiene_imagen": False, "mensaje": "No hay un siniestro asociado a esta corrida."}
    adjunto = await ctx.lector.get_attachment(claim_id)
    if adjunto is None:
        return {"tiene_imagen": False, "mensaje": "El cliente no adjuntó ninguna imagen con este reporte."}
    datos = read_image(ctx.uploads_dir, adjunto["file_path"])
    resultado = await ctx.image_analyzer.analyze(
        image_bytes=datos, mime_type=adjunto["mime_type"],
        claim_type=ctx.claim.get("claim_type", ""), description=ctx.claim.get("description", ""),
    )
    resultado["tiene_imagen"] = True
    return resultado


async def _buscar_similares(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    claim_id = ctx.claim.get("id")
    filas = await ctx.lector.search_similar(
        _del_siniestro(ctx, "description", args, "descripcion", "buscar_siniestros_similares"),
        _del_siniestro(ctx, "claim_type", args, "tipo_siniestro", "buscar_siniestros_similares") or None,
        limit=int(args.get("limite", 3)),
        exclude=claim_id if isinstance(claim_id, UUID) else None,
    )
    return {
        "total": len(filas),
        "metodo": "busqueda_texto_completo_postgres_es",
        "resultados": [
            {
                "id": str(f["id"]),
                "tipo": f["claim_type"],
                "resumen": (f["description"][:160] + "…") if len(f["description"]) > 160 else f["description"],
                "costo_estimado": float(f["estimated_cost"]) if f["estimated_cost"] is not None else None,
                "estado": f["status"],
                "relevancia": float(f["relevancia"]),
            }
            for f in filas
        ],
    }


async def _asignar_ajustador(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    claim_id = ctx.claim.get("id")
    if not isinstance(claim_id, UUID):
        raise ToolExecutionError("No hay un siniestro asociado a esta corrida.")
    ok = await ctx.db.assign_adjuster(claim_id, args["ajustador"].strip(), args["motivo"].strip())
    if not ok:
        raise ToolExecutionError("El siniestro ya no existe.")
    return {
        "asignado": True,
        "ajustador": args["ajustador"],
        "claim_id": str(claim_id),
        "nuevo_estado": "IN_REVIEW",
    }


# ---------------------------------------------------------------------------- catálogo

TOOLS: tuple[Tool, ...] = (
    Tool(
        name="clasificar_urgencia",
        # v1: "Clasifica la urgencia del siniestro."
        # v2: se añadió (a) la orden de llamarla SIEMPRE primero, porque el modelo a veces
        #     respondía con su propia opinión de urgencia sin llamarla; (b) la prohibición
        #     explícita de contradecir el resultado; (c) la nota sobre negaciones, porque
        #     con relatos como "sin heridos, pero vino la ambulancia" el modelo tendía a
        #     rebajar el nivel por su cuenta.
        description=(
            "Clasifica la urgencia de un siniestro en CRITICAL, HIGH o LOW usando el motor "
            "de reglas oficial de la aseguradora. ÚSALA SIEMPRE PRIMERO, antes que cualquier "
            "otra herramienta, y una sola vez por siniestro. Devuelve el nivel de urgencia, la "
            "acción recomendada, el SLA en minutos, las palabras clave detectadas (marcando "
            "cuáles están negadas) y las inconsistencias encontradas en el relato. El nivel que "
            "devuelve esta herramienta es la decisión oficial: no lo contradigas, no lo ajustes "
            "y no propongas otro nivel en tu respuesta final, aunque el relato te parezca más o "
            "menos grave. Si el resultado trae inconsistencias, menciónalas en tu resumen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "descripcion": {
                    "type": "string",
                    "description": "Relato del siniestro. El sistema usa el relato guardado del expediente; este valor se ignora.",
                },
                "tipo_siniestro": {
                    "type": "string",
                    "enum": ["AUTO", "MEDICAL", "HOME"],
                    "description": "Tipo del siniestro. El sistema usa el del expediente; este valor se ignora.",
                },
            },
            "required": ["descripcion", "tipo_siniestro"],
        },
        handler=_clasificar_urgencia,
        args_previos=lambda c: {"descripcion": c.get("description", ""),
                                "tipo_siniestro": c.get("claim_type", "AUTO")},
        notes="Determinista: mismo texto, mismo resultado. No llama al modelo.",
    ),
    Tool(
        name="consultar_poliza",
        # v1: "Consulta la póliza del cliente."
        # v2: se enumeró qué devuelve y se añadió la instrucción de avisar cuando la póliza
        #     no está ACTIVE o el producto no coincide: antes el modelo leía el estado pero
        #     no lo mencionaba en el resumen, que es justo lo que el ajustador necesita ver.
        description=(
            "Consulta la póliza del cliente en la base de datos de la aseguradora. Úsala "
            "siempre después de clasificar la urgencia. Devuelve si la póliza existe, el "
            "producto cubierto (AUTO, MEDICAL o HOME), el estado (ACTIVE, LAPSED o CANCELLED), "
            "si está vigente hoy, el límite de cobertura y el deducible. Si la póliza no existe, "
            "no está ACTIVE, o el producto no corresponde al tipo de siniestro reportado, "
            "DEBES advertirlo de forma explícita en tu respuesta final: es información que "
            "cambia la decisión del ajustador. Nunca inventes montos ni fechas de cobertura: "
            "usa solo lo que devuelve esta herramienta."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Identificador del cliente. El sistema consulta el del siniestro; este valor se ignora.",
                },
            },
            "required": ["customer_id"],
        },
        handler=_consultar_poliza,
        args_previos=lambda c: {"customer_id": c.get("customer_id", "")},
    ),
    Tool(
        name="analizar_imagen_dano",
        description=(
            "Analiza con visión por computador la foto que el cliente adjuntó al reporte, si la "
            "hay. Describe el daño visible, estima su severidad (LEVE, MODERADO, SEVERO o "
            "INDETERMINADO) e indica si lo que se ve es consistente con el relato escrito. "
            "Úsala SOLO si el campo 'tiene_imagen' del siniestro es verdadero; si no hay imagen "
            "adjunta, no la llames ni la menciones en tu resumen. No reemplaza a "
            "clasificar_urgencia ni cambia su nivel oficial: es información adicional para el "
            "ajustador. Si el daño visible contradice claramente el relato (por severidad o por "
            "tipo de daño), trátalo como una inconsistencia más en tu resumen."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_analizar_imagen,
        timeout_seconds=20.0,
        uses_llm=True,
        notes=("Llama a un modelo de visión (Gemini) en modo gemini; en modo offline devuelve "
              "'revisión manual' sin red ni tokens."),
    ),
    Tool(
        name="buscar_siniestros_similares",
        # v1: "Busca siniestros parecidos."
        # v2: se acotó el uso ("solo para urgencia CRITICAL o HIGH") porque el modelo la
        #     llamaba también en rayones de 1 punto, gastando una iteración y tokens sin
        #     aportar nada a la decisión.
        description=(
            "Busca siniestros anteriores ya resueltos con un relato parecido, por coincidencia "
            "de términos en español. Úsala SOLO cuando la urgencia sea CRITICAL o HIGH, o cuando "
            "se hayan detectado inconsistencias: en siniestros leves no aporta a la decisión y "
            "gasta tiempo. Devuelve hasta 5 casos con su costo real liquidado, lo que sirve para "
            "anticipar el monto de la reserva. Si no hay casos parecidos, el total es 0 y debes "
            "decirlo así en vez de estimar un costo por tu cuenta."
        ),
        parameters={
            "type": "object",
            "properties": {
                "descripcion": {
                    "type": "string",
                    "description": "Relato del siniestro actual. El sistema usa el del expediente; este valor se ignora.",
                },
                "tipo_siniestro": {
                    "type": "string",
                    "enum": ["AUTO", "MEDICAL", "HOME"],
                    "description": "Tipo del siniestro. El sistema usa el del expediente; este valor se ignora.",
                },
                "limite": {
                    "type": "integer",
                    "description": "Cuántos casos devolver, entre 1 y 5.",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                },
            },
            "required": ["descripcion"],
        },
        handler=_buscar_similares,
        notes="Búsqueda de texto completo de PostgreSQL en español; sin embeddings (ver decisiones.md).",
    ),
    Tool(
        name="asignar_ajustador",
        # v1: no existía; el agente solo redactaba una recomendación y un humano la ejecutaba.
        # v2: se añadió para tener una acción con efecto real y, sobre todo, para demostrar el
        #     cuarto límite: ninguna acción que cambie el estado de un siniestro se ejecuta sin
        #     que una persona la apruebe en pantalla.
        description=(
            "Asigna un ajustador humano al siniestro y lo pasa a estado EN REVISIÓN. "
            "Úsala únicamente cuando la urgencia sea CRITICAL. Esta acción modifica el "
            "expediente y SIEMPRE requiere la aprobación de una persona antes de ejecutarse: "
            "al llamarla, el proceso se detiene y espera la confirmación del ajustador de turno. "
            "Explica en el campo 'motivo', en una frase y en español, por qué este caso necesita "
            "atención humana inmediata."
        ),
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "Identificador del siniestro que se está triando.",
                },
                "ajustador": {
                    "type": "string",
                    "enum": ["guardia-24h", "ana", "luis"],
                    "description": "Cola o persona a la que se asigna. Usa 'guardia-24h' si no hay un criterio mejor.",
                },
                "motivo": {
                    "type": "string",
                    "description": "Una frase en español explicando por qué requiere atención inmediata.",
                },
            },
            "required": ["claim_id", "ajustador", "motivo"],
        },
        handler=_asignar_ajustador,
        requires_confirmation=True,
        notes="Cuarto límite: acción con efecto real, bloqueada tras confirmación humana.",
    ),
)

TOOLS_BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


def tool_specs() -> list[ToolSpec]:
    """Lo que se le declara al modelo en cada llamada.

    Las herramientas previas NO se declaran: el sistema ya las ejecutó y sus resultados viajan
    en la conversación. Declararlas costaba ~500 tokens de entrada en CADA iteración.
    """
    return [t.spec() for t in TOOLS if t.args_previos is None]


def tools_previas() -> list[Tool]:
    """Herramientas que el sistema ejecuta antes del modelo, en orden."""
    return [t for t in TOOLS if t.args_previos is not None]
