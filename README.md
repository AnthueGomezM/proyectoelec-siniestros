# Triaje de siniestros con agente de IA

Un ajustador de seguros abre su turno con 40 reclamos en cola y no sabe cuál tiene
heridos. Este sistema lee cada relato, lo clasifica por urgencia, verifica la póliza,
busca casos parecidos y arma el expediente —mostrando en pantalla cada paso que dio—
para que la persona decida con contexto en lugar de leer de arriba abajo.

- **Lo que decide la IA:** qué herramientas usar, en qué orden, y cómo resumirlo.
- **Lo que decide el código:** el nivel de urgencia, la cobertura y los datos. Siempre.
- **Lo que decide una persona:** cualquier acción que toque el expediente.

---

## Arranque en un comando

### Requisitos

| Requisito | Versión | Cómo verificar |
|---|---|---|
| Docker Engine | 24+ | `docker --version` |
| Docker Compose | **v2** (`docker compose`, sin guion) | `docker compose version` |
| Sistema | Linux, macOS o Windows con WSL2 | — |
| Puertos libres | 8000 y 5432 | cambiables en `.env` |

No hace falta instalar Python, Node ni PostgreSQL: todo corre en contenedores.

### Pasos

```bash
# 1. Descomprime el ZIP y entra a la carpeta
cd proyectoelec-siniestros

# 2. Crea tu archivo de variables y pon la clave de Gemini
cp .env.example .env
#    Edita .env y pega tu clave en GEMINI_API_KEY=
#    Se obtiene gratis en https://aistudio.google.com/apikey

# 3. Levanta todo
./run.sh
```

En Windows (PowerShell), si no puedes ejecutar `./run.sh`:

```powershell
copy .env.example .env
docker compose up --build
```

Cuando termine verás:

```
✓ Dashboard:   http://localhost:8000
✓ API (docs):  http://localhost:8000/api/docs
✓ Motor de IA: gemini gemini-3.5-flash
```

**Sin clave de Gemini también arranca.** `run.sh` lo detecta y levanta en modo
determinista (`LLM_PROVIDER=offline`): el triaje funciona con reglas, sin llamadas
externas. Sirve para revisar el sistema, pero la demo con IA necesita la clave.

### Verificar antes de presentar

```bash
./run.sh check     # hace UNA llamada real a Gemini y reporta latencia, tokens y modelo
```

Si la clave está vencida o sin cuota, te enteras aquí y no frente al salón.

### Otros comandos

| Comando | Qué hace |
|---|---|
| `./run.sh` | Levanta base de datos y aplicación, y espera a que respondan |
| `./run.sh check` | Prueba la clave del proveedor de IA con una llamada real |
| `./run.sh eval` | Corre los 22 casos dorados y escribe la línea base en `eval/resultados/` |
| `./run.sh test` | Corre las 85 pruebas unitarias en un contenedor limpio |
| `./run.sh logs` | Sigue los logs de la aplicación |
| `./run.sh down` | Apaga (conserva los datos) |
| `./run.sh reset` | Apaga y borra la base para empezar de cero |

---

## Cómo probarlo en dos minutos

1. Abre **http://localhost:8000**.
2. En *Reportar siniestro*, pulsa el botón **Crítico** y luego **Reportar y triar**.
3. Mira la **tira de registro** a la derecha: cada paso del agente se imprime en vivo
   con su latencia y sus tokens.
4. El agente se detiene y pide autorización para asignar un ajustador. Pulsa
   **Aprobar asignación**: el bucle continúa y escribe el resumen.
5. Repite con **Inconsistente** (el cliente niega daños pero describe destrucción),
   **Póliza vencida** (el agente debe advertirlo) e **Inválido**, que devuelve un error
   400 legible en vez de una traza.

---

## Qué hay dentro

```
README.md                  este contrato de arranque
docker-compose.yml         dos servicios: db (PostgreSQL 16) y app (FastAPI)
run.sh                     un comando para levantar, probar, medir y apagar
.env.example               todas las variables, ninguna oculta
db/
  01-schema.sql            esquema relacional (se aplica solo al crear la base)
  02-seed.sql              12 pólizas y 10 siniestros históricos de ejemplo
app/
  Dockerfile               imagen de la aplicación (python:3.12-slim, usuario no root)
  requirements.txt         dependencias con versión exacta
  src/claims_agent/
    main.py                arranque de FastAPI
    config.py              variables de entorno y validación
    db.py                  acceso a PostgreSQL (SQL explícito, sin ORM)
    storage.py             guarda y lee las fotos adjuntas en disco (no en la BD)
    agent/
      loop.py              bucle agéntico con los 4 límites
      tools.py             las 5 herramientas y la validación de argumentos
      prompts.py           instrucción de sistema (versionada)
    providers/
      base.py              interfaz: lo único que el agente conoce del proveedor
      gemini.py            Google Gemini por API REST
      offline.py           motor determinista: respaldo y pruebas sin red
      vision.py            analizador de imágenes (Gemini visión + respaldo offline)
    nlp/
      lexicon.py           diccionario de urgencia con pesos (editable sin tocar código)
      classifier.py        clasificador determinista
    api/                   endpoints, SSE de trazas, manejo de errores
    web/                   dashboard (HTML, CSS y JS sin dependencias)
  tests/                   85 pruebas unitarias
eval/
  casos_dorados.jsonl      22 casos con la urgencia que esperaría un ajustador
  run_eval.py              corre la suite y calcula las medianas
  check_provider.py        verifica la clave del proveedor
  resultados/              líneas base con fecha
docs/
  decisiones.md            arquitectura, datos, proveedor, límites y línea base
  prueba-companero.md      prueba de arranque en máquina ajena, documentada
  guion-demo.md            guion de los 6 minutos y respuestas a las preguntas probables
```

---

## El agente

**Cinco herramientas propias** (`app/src/claims_agent/agent/tools.py`), con descripciones
escritas como prompts e iteradas contra la suite de evaluación:

| Herramienta | Qué hace | Determinista |
|---|---|---|
| `clasificar_urgencia` | Nivel, puntuación, palabras clave e inconsistencias | Sí, sin IA |
| `consultar_poliza` | Estado, vigencia, cobertura y deducible | Sí, SQL |
| `analizar_imagen_dano` | Daño visible, severidad y si coincide con el relato, a partir de la foto adjunta (opcional) | No, visión por modelo (Gemini); en offline devuelve "revisión manual" |
| `buscar_siniestros_similares` | Casos resueltos parecidos con su costo real | Sí, texto completo |
| `asignar_ajustador` | Asigna y pasa a *En revisión* | **Requiere aprobación humana** |

El cliente puede adjuntar una foto del daño al reportar (`POST /api/claims` acepta
`multipart/form-data`, un solo archivo JPEG/PNG/WEBP de hasta `MAX_IMAGE_MB`). La foto
se guarda en un volumen Docker (`UPLOADS_DIR`), no en la base de datos; solo la ruta
queda en `claim_attachments`. El agente la analiza con `analizar_imagen_dano` únicamente
si el reporte trae imagen, y su resultado queda junto a la urgencia en el expediente.

**Cuatro límites activos**, visibles en la barra superior del dashboard:

| Límite | Variable | Valor |
|---|---|---|
| Iteraciones | `AGENT_MAX_ITERATIONS` | 6 |
| Tiempo | `AGENT_TIMEOUT_SECONDS` | 45 s |
| Tokens | `AGENT_MAX_TOKENS` | 8.000 |
| Confirmación humana | `AGENT_REQUIRE_CONFIRMATION` | obligatoria |

**Capa de proveedor desacoplada:** el bucle solo conoce la interfaz de
`providers/base.py`. Hoy hay dos implementaciones (Gemini y el motor determinista);
añadir Groq u OpenAI es una clase nueva y una línea en `providers/factory.py`.

---

## Proveedor de IA y credenciales

- **Proveedor:** Google Gemini · **Modelo:** `gemini-3.5-flash`
- **Por qué:** costo cero en la capa gratuita para el volumen del triaje (~1.900 tokens
  por caso), baja latencia —el agente encadena 3 a 5 llamadas por siniestro— y
  `functionDeclarations` con JSON Schema completo, que permite validar los argumentos
  antes de ejecutar. La justificación larga y la comparación con Groq y OpenAI están en
  [`docs/decisiones.md`](docs/decisiones.md#4-proveedor-y-modelo-google-gemini-35-flash).
- **Credenciales:** solo por variable de entorno. `.env.example` declara
  `GEMINI_API_KEY=`, `GEMINI_MODEL=` y `DATABASE_URL=`. **El ZIP no incluye ninguna clave
  real**; cada quien pone la suya en `.env`, que está excluido por `.gitignore`.

---

## Qué pasa cuando algo falla

| Fallo | Qué ve el usuario | Dónde está probado |
|---|---|---|
| El modelo no responde a tiempo | El triaje termina igual con el motor determinista y aparece la franja "Modo determinista" | `test_fallos.py` |
| La API devuelve 429 o se cae | Lo mismo: un reintento, y si sigue fallando, degradación visible en la traza | `test_fallos.py`, `test_gemini_provider.py` |
| El reporte viene mal | 400 con la lista de campos y qué le falta a cada uno, en español | `test_fallos.py` |
| El modelo inventa argumentos | Recibe el error, se corrige y sigue | `test_fallos.py` |
| La base de datos no responde | 503 "Servicio no disponible, reintenta en unos segundos" | `api/errors.py` |
| Cualquier bug no previsto | 500 con un identificador de correlación; la traza va al log, nunca a la pantalla | `api/errors.py` |

En ningún caso el usuario ve una traza de Python, y en ningún caso un siniestro queda
sin nivel de urgencia.

---

## Medición

22 casos dorados escritos con criterio de ajustador antes de ejecutarlos, 7 de ellos
casos borde. Todas las cifras son medianas.

| Cifra | Motor determinista (2026-10-23) | Gemini 3.5 Flash |
|---|---|---|
| Exactitud de urgencia | 100,0 % (22/22) | `./run.sh eval --provider gemini` |
| Detección de inconsistencias | 100,0 % (5/5, 1 falso positivo) | ídem |
| Latencia por caso | 0,009 s | ídem |
| Tokens por caso | 1.866 | ídem |

La fila de Gemini está pendiente a propósito: la red donde se construyó el proyecto
bloquea la API de Google, así que el contrato con Gemini se verificó con 12 pruebas
contra un transporte simulado en vez de inventar números. Se llena con un comando el día
de la demo. Detalle completo, incluida la iteración medida v1 → v2 que subió la detección
de inconsistencias de 80 % a 100 %, en [`docs/decisiones.md`](docs/decisiones.md#8-línea-base-medida).

---

## Documentación

- [`docs/decisiones.md`](docs/decisiones.md) — arquitectura, frontera IA/código, proveedor, por qué no RAG, línea base y riesgos
- [`docs/prueba-companero.md`](docs/prueba-companero.md) — arranque verificado en una máquina ajena, con tiempos
- [`docs/guion-demo.md`](docs/guion-demo.md) — guion de 6 minutos y respuestas preparadas
