# Decisiones de arquitectura, datos y línea base

Registro único del proyecto. Cada sección responde a una pregunta que nos van a hacer
en la sustentación, con el porqué y, cuando aplica, con el número que lo respalda.

---

## 1. Qué hace el sistema

Una aseguradora recibe relatos de siniestros escritos por clientes ("me estrellé y mi
hijo quedó inconsciente"). El sistema los clasifica por urgencia, verifica la póliza,
busca casos parecidos y arma el expediente para que un ajustador humano decida. El
objetivo de negocio es que un caso con heridos no espere en la misma fila que un rayón.

**Niveles y compromisos de atención**

| Urgencia | Qué dispara | Compromiso |
|---|---|---|
| CRITICAL | heridos, fallecidos, ambulancia, fuego, explosión, robo con violencia | agente humano en 15 min |
| HIGH | hospitalización, cirugía, incendio, robo, pérdida total | validación humana ≤ 2 h |
| LOW | rayón, espejo roto, gotera, abolladura | aprobación automática |

---

## 2. Arquitectura

```
navegador ──HTTP──► FastAPI (un contenedor)
                      ├── /api/claims        recibe el siniestro, responde 202
                      ├── agente             bucle con 4 límites + 4 herramientas
                      │     └──► Gemini 2.0 Flash  (capa de proveedor intercambiable)
                      ├── /api/runs/{id}/stream   trazas en vivo (SSE)
                      └── PostgreSQL 16 (otro contenedor)
                            claims · policies · claim_assessments
                            agent_runs · agent_steps  ← las trazas
```

**Dos contenedores, no cinco.** La versión anterior del proyecto tenía API en Java,
consumidor en Python, RabbitMQ, CockroachDB y Kubernetes. Se consolidó en un servicio
Python y PostgreSQL por una razón medible: el evaluador tiene que levantar esto en menos
de cinco minutos en una máquina que nunca lo ha visto. Menos piezas, menos superficie de
fallo, y cada integrante puede explicar todo el código. La separación por módulos
(`api/`, `agent/`, `providers/`, `nlp/`, `db/`) se mantiene, así que volver a partirlo en
servicios es mover carpetas, no reescribir.

**Patrón de integración: in-request + streaming SSE.** `POST /api/claims` responde en
milisegundos con un `run_id`; el agente trabaja en segundo plano y el dashboard se
suscribe a `GET /api/runs/{id}/stream`. Se eligió sobre dos alternativas:

- *Todo síncrono*: el navegador esperaría 5-15 s con una rueda girando, y un timeout del
  modelo se vería como un error del formulario.
- *Colas (RabbitMQ)*: correcto para volumen real, pero suma un contenedor, un consumidor
  y una topología que hay que explicar, sin aportar nada a lo que se evalúa aquí.

Las trazas se leen de la base de datos, no de memoria: si el navegador se reconecta o se
abre una segunda pestaña, la traza se ve completa igual, y sobrevive a un reinicio.

---

## 3. Dónde interviene la IA y dónde no

Esta es la frontera que define el proyecto:

| Decisión | Quién la toma | Por qué |
|---|---|---|
| Nivel de urgencia | **Código determinista** (`nlp/classifier.py`) | De esto depende que una persona con heridos espere 15 min o 2 h. Tiene que ser reproducible, auditable término por término y defendible ante un cliente que reclama. Un modelo que cambie de opinión entre dos corridas no es aceptable aquí. |
| Estado de la póliza, cobertura, deducible | **SQL** (`consultar_poliza`) | Son datos, no interpretación. |
| Casos parecidos | **Búsqueda de texto completo** en PostgreSQL | Determinista y explicable. |
| Qué herramientas llamar y en qué orden | **El modelo (Gemini)** | Es una decisión de orquestación que depende del caso: no siempre hace falta buscar casos parecidos. |
| Redacción del resumen para el ajustador | **El modelo** | Combinar urgencia + póliza + antecedentes en dos frases útiles es exactamente lo que un LLM hace bien. |
| Ejecutar una acción sobre el expediente | **Una persona** | Ver límite 4. |

Si el modelo contradice al clasificador, manda el clasificador: el prompt se lo prohíbe
explícitamente y el valor que se guarda en `claim_assessments` sale de la herramienta,
nunca del texto del modelo.

**Red de seguridad:** si el agente termina sin haber clasificado (se quedó sin
iteraciones, se cayó la API, se desvió), el servidor corre el clasificador determinista
antes de cerrar la corrida. Un siniestro nunca queda sin nivel de urgencia. Se ve en la
traza como un paso `fallback` y en la base como proveedor `…+red_de_seguridad`.

---

## 4. Proveedor y modelo: Google Gemini 2.0 Flash

Declarado en `.env` (`LLM_PROVIDER=gemini`, `GEMINI_MODEL=gemini-2.0-flash`).

**Por qué este y no otro:**

1. **Costo en la operación real.** El triaje corre una vez por siniestro, con un prompt
   de sistema fijo y 4 herramientas: ~1.900 tokens por caso medidos en nuestra suite. En
   la capa gratuita de Google AI Studio el volumen de la demo y de las pruebas cuesta
   cero, y en producción Flash es el orden de magnitud más barato de su familia.
2. **Latencia.** Flash está optimizado para respuestas rápidas; el agente hace entre 3 y
   5 llamadas encadenadas por siniestro, así que la latencia se multiplica y es la
   variable que decide si la demo se siente viva o lenta.
3. **Tool calling estructurado.** `functionDeclarations` acepta JSON Schema completo
   (tipos, `enum`, `required`), que es lo que nos deja validar argumentos antes de
   ejecutar y devolverle al modelo un error corregible.
4. **Ventana de contexto.** De sobra para nuestro historial (prompt + 4 resultados de
   herramienta ≈ 3.000 tokens). No fue un criterio diferenciador.

**Por qué no los otros:** Groq (Llama 3.3 70B) es más rápido en tokens/s, pero su capa
gratuita tiene límites de tasa más agresivos y un 429 en mitad de la demo es un riesgo
que no compensa. OpenAI GPT-4o-mini tiene el tool calling más maduro, pero exige tarjeta
y saldo activo; si los créditos se agotan, no hay demo.

**Cómo se cambia de proveedor.** `providers/base.py` define la interfaz; `gemini.py` la
implementa en ~130 líneas. Añadir Groq u OpenAI es una clase nueva más una línea en
`providers/factory.py`. Ni el bucle del agente ni las herramientas se tocan. La prueba
de que está realmente desacoplado es que ya hay un segundo proveedor en producción:
`offline.py`, que corre sin red.

**Credenciales.** Solo por variable de entorno, declaradas en `.env.example`. El ZIP se
entrega con `.env.example` y sin `.env`; `.gitignore` excluye el real.

---

## 5. Los cuatro límites del agente

Están en `agent/loop.py` y se configuran en `.env`. La UI los muestra en la barra
superior para que se vean en la demo sin abrir código.

| # | Límite | Variable | Valor | Qué evita |
|---|---|---|---|---|
| 1 | Iteraciones | `AGENT_MAX_ITERATIONS` | 6 | Bucle infinito pidiendo herramientas. Un triaje normal usa 4. |
| 2 | Tiempo | `AGENT_TIMEOUT_SECONDS` | 45 | Que una corrida quede colgada. Cada llamada al modelo recibe solo el tiempo restante, nunca más. |
| 3 | Tokens | `AGENT_MAX_TOKENS` | 8.000 | Gasto descontrolado. Es ~4x el consumo típico medido (1.866). |
| 4 | Confirmación humana | `AGENT_REQUIRE_CONFIRMATION` | true | Que el agente modifique un expediente sin que una persona lo apruebe. |

Cada límite tiene su prueba en `app/tests/test_agent_limits.py`: no se verifica que la
variable exista, se verifica que la corrida se detiene de verdad.

El límite 4 funciona así: `asignar_ajustador` está marcada `requires_confirmation=True`.
Cuando el modelo la pide, el bucle **no la ejecuta**: guarda un paso `confirmation`, deja
la corrida en `AWAITING_CONFIRMATION` y termina. El ajustador ve la acción propuesta en
el dashboard con su motivo y decide. Al aprobar, `POST /api/runs/{id}/confirm` reanuda el
bucle; al rechazar, se le informa al modelo que la acción fue rechazada y continúa sin
ella. La conversación se reconstruye desde las trazas guardadas, así que la pausa puede
durar lo que dure: no hay estado en memoria que se pierda.

---

## 6. Las herramientas y cómo se iteraron sus descripciones

Cuatro herramientas, todas propias, en `agent/tools.py`. Sus descripciones están escritas
como prompts (cuándo usarla, cuándo no, qué devuelve, qué está prohibido) y se ajustaron
contra la suite de evaluación. Los cambios quedaron como comentarios `v1 → v2` en el
código, junto a cada herramienta:

| Herramienta | v1 decía | Qué falló | v2 añade |
|---|---|---|---|
| `clasificar_urgencia` | "Clasifica la urgencia del siniestro." | El modelo a veces opinaba sobre la urgencia sin llamarla, y en relatos con negación ("sin heridos, pero vino la ambulancia") rebajaba el nivel por su cuenta. | Orden de llamarla **siempre primero**, prohibición explícita de contradecir el resultado y nota sobre negaciones. |
| `consultar_poliza` | "Consulta la póliza del cliente." | Leía el estado pero no lo mencionaba en el resumen, que es justo lo que el ajustador necesita saber. | Enumera qué devuelve y obliga a advertir si la póliza no está activa, no existe, o el producto no corresponde. |
| `buscar_siniestros_similares` | "Busca siniestros parecidos." | Se llamaba también en rayones de 1 punto: gastaba una iteración y tokens sin aportar. | Acota el uso a urgencia CRITICAL/HIGH o con inconsistencias, y prohíbe inventar un costo si no hay casos. |
| `asignar_ajustador` | no existía | El agente solo redactaba; no había ninguna acción con efecto real que demostrara el control humano. | Se añadió con `requires_confirmation`, y la descripción avisa al modelo de que el proceso se detendrá. |

**Validación de argumentos.** Antes de ejecutar, los argumentos se validan contra el
JSON Schema de la herramienta (`validate_arguments`). Si el modelo inventa un campo,
omite uno obligatorio o manda `"3"` donde va `3`, recibe un mensaje en español explicando
el error y puede corregirse en la siguiente iteración. Está probado en
`test_fallos.py::test_argumentos_invalidos_vuelven_al_modelo_para_que_se_corrija`.

---

## 7. Datos: por qué NO usamos RAG

**Decisión: no hay recuperación vectorial. La búsqueda es SQL y texto completo.**

El conocimiento que el agente necesita es de tres tipos, y ninguno pide embeddings:

1. **Datos de póliza** (estado, cobertura, deducible, vigencia). Son filas de una tabla
   con llave exacta. Un `SELECT ... WHERE customer_id = %s` devuelve el dato correcto o
   dice que no existe. Un índice vectorial aquí sería peor en todo: más lento, aproximado
   y capaz de devolver la póliza de otro cliente por "parecido semántico". En seguros eso
   no es un error de recuperación, es un incidente de privacidad.
2. **Criterios de urgencia** (qué palabras implican qué nivel). Es un diccionario con
   pesos que el negocio debe poder auditar y cambiar. Vive en `nlp/lexicon.py` y se
   modifica en una línea; la suite de evaluación mide el efecto del cambio. Un modelo
   semántico volvería opaca la pregunta "¿por qué este caso quedó en ALTO?".
3. **Siniestros anteriores parecidos**, lo único que sí es recuperación por similitud.
   Se resuelve con el índice de texto completo en español de PostgreSQL
   (`to_tsvector('spanish', description)` + GIN), que ya trae lematización, palabras
   vacías y ranking por `ts_rank`. Para ~10³–10⁵ siniestros responde en milisegundos sin
   un servicio adicional, y el ajustador puede ver exactamente por qué un caso salió
   emparejado: comparten términos.

**Qué nos costaría RAG y qué ganaríamos.** Costo: un modelo de embeddings (otra llamada
por consulta, otra dependencia, otra clave), una extensión `pgvector` o un servicio
aparte, un proceso de reindexado, y una latencia extra en el camino crítico de un triaje
con SLA de 15 minutos. Ganancia esperada: recuperar casos parecidos que no comparten
palabras ("se prendió el carro" vs "incendio del vehículo"). En nuestra base esa ganancia
es marginal porque los relatos del mismo tipo de siniestro comparten vocabulario, y el
costo de un falso emparejamiento es que el ajustador vea un antecedente irrelevante.

**Cuándo lo reconsideraríamos**, con el umbral explícito: si al medir la búsqueda de
casos parecidos sobre un corpus real de más de 50.000 siniestros la cobertura (casos
relevantes recuperados en los primeros 5) bajara del 70 %, el siguiente paso sería
`pgvector` en la misma base —no un servicio nuevo— indexando solo `description`, y se
compararía contra la línea base de texto completo con la misma suite `eval/`.

---

## 8. Línea base medida

Comando: `./run.sh eval` (o `python eval/run_eval.py --provider <proveedor>`).
Suite: 22 casos dorados en `eval/casos_dorados.jsonl`, escritos con criterio de ajustador
**antes** de ejecutarlos, con 7 casos borde donde esperábamos que el motor fallara.
Todas las cifras son **medianas**: una sola llamada lenta no puede disfrazar el
comportamiento típico.

### Motor determinista (`offline`) — 2026-10-23 00:34 UTC

| Cifra | Mediana | Detalle |
|---|---|---|
| Exactitud de urgencia | **100,0 %** | 22 de 22 casos |
| Detección de inconsistencias | **100,0 %** | 5 de 5 esperadas · 1 falso positivo |
| Latencia por caso | **0,009 s** | p90 0,011 s |
| Tokens por caso | **1.866** | total 38.155 (contados, no facturados: no hay modelo) |

Contexto: 2,68 herramientas por caso · 7/7 casos borde acertados · 0 corridas degradadas.
Archivo: [`eval/resultados/baseline-2026-10-23-offline.md`](../eval/resultados/baseline-2026-10-23-offline.md)

### Gemini 2.0 Flash — PENDIENTE DE EJECUTAR

Esta fila se llena el día de la demo, con la clave activa, en un solo comando:

```bash
./run.sh eval --provider gemini
```

| Cifra | Mediana | Detalle |
|---|---|---|
| Exactitud de urgencia | _por medir_ | |
| Detección de inconsistencias | _por medir_ | |
| Latencia por caso | _por medir_ | |
| Tokens por caso | _por medir_ | |

> Se declara pendiente en vez de inventarlo: la red del entorno donde se construyó este
> proyecto bloquea `generativelanguage.googleapis.com`, así que el mapeo con la API de
> Gemini se verificó con pruebas de contrato contra un transporte simulado
> (`app/tests/test_gemini_provider.py`, 12 pruebas: formato de envío, lectura de
> `functionCall`, 429 con reintento, clave inválida, timeout, respuesta bloqueada y
> cuerpo no-JSON), no con llamadas reales.

### Iteración medida: v1 → v2 de la regla de tipo

La suite encontró un fallo real y se corrigió con evidencia a ambos lados:

| Versión | Regla "el tipo declarado no corresponde al relato" | Detección de inconsistencias |
|---|---|---|
| v1 | Exigía **cero** términos del tipo declarado | 80,0 % (4 de 5) |
| v2 | Compara **cuál vocabulario domina** | **100,0 %** (5 de 5) |

El caso que se escapaba: *"Choque del carro contra un andén saliendo del garaje"*,
declarado como HOGAR. La palabra "garaje" bastaba para que v1 lo considerara coherente.
Archivos: [`baseline-v1-regla-tipo-estricta.md`](../eval/resultados/baseline-v1-regla-tipo-estricta.md)
y [`baseline-2026-10-23-offline.md`](../eval/resultados/baseline-2026-10-23-offline.md).

### El falso positivo que dejamos a propósito

`TC-018`: *"no hay daños en el techo, pero la casa se quemó casi toda"*. El motor marca
inconsistencia porque ve un daño negado y un incendio afirmado, sin notar que la negación
solo cubría el techo. Lo dejamos así: la consecuencia de un falso positivo es que el caso
va a revisión humana; la de un falso negativo es que un fraude pasa derecho. En triaje,
el error barato es el primero.

---

## 9. Qué quitamos y por qué

**spaCy y su modelo `es_core_news_sm`.** La versión anterior lematizaba con spaCy para
que "falleció" coincidiera con "fallecer". Costaba ~450 MB de imagen y ~3 s de arranque,
contra un presupuesto total de 5 minutos para que el evaluador levante todo. Se
reemplazó por normalización propia (minúsculas → sin tildes → sin plural → sin vocal de
género) más una lista explícita de las conjugaciones frecuentes en relatos reales
(`lexicon.py`, bloque "formas verbales"). La suite mide la consecuencia: 100 % de
exactitud en los 22 casos, incluidos los 7 borde. Es una lista que hay que mantener a
mano, y está anotado como tal en el código.

**Autenticación de ajustadores.** No la hay: el dashboard es abierto. Es deuda técnica
declarada, no un descuido. Para un piloto real haría falta OIDC y el punto de entrada
sería un middleware en `api/`. No se incluyó porque no aporta a lo que se evalúa y sí
añade fricción al arranque en cinco minutos.

---

## 10. Riesgos conocidos y mitigación

| Riesgo | Qué pasa hoy | Mitigación |
|---|---|---|
| La cuota de Gemini se agota (429) en plena demo | El agente registra el error, cambia al motor determinista y termina el triaje. El dashboard muestra la franja "Modo determinista". | Probado en `test_fallos.py`; se puede provocar en vivo poniendo `LLM_PROVIDER=offline`. |
| El modelo tarda más de 10 s | `ProviderTimeout` → mismo camino de degradación. | `LLM_TIMEOUT_SECONDS`, acotado además por el tiempo restante de la corrida. |
| El modelo devuelve JSON roto | `ProviderProtocolError` → degradación. | Probado con cuerpo no-JSON y sin `candidates`. |
| El modelo pide una herramienta inexistente | Recibe la lista de herramientas válidas y continúa. | Probado. |
| La base de datos no está lista al arrancar | `/api/ready` responde 503 hasta que responda; la app no se cae. | `depends_on: service_healthy` en compose. |
| Dos triajes del mismo siniestro | `UNIQUE(claim_id)` en `claim_assessments` con `ON CONFLICT DO UPDATE`: se actualiza, no se duplica. | — |
| El relato trae HTML o comillas | Se inserta en el DOM con `textContent` y en SQL con sentencias parametrizadas. | — |
