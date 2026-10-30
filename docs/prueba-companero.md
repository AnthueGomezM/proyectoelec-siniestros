# Prueba del compañero

> «Si otro estudiante descarga su ZIP, sigue su README al pie de la letra y la
> aplicación no levanta en menos de 5 minutos, el contrato está roto.»

Este documento es el protocolo para esa prueba y el registro de lo que ya se verificó.

---

## 1. Protocolo (10 minutos, en una máquina que nunca vio el proyecto)

Quien prueba **no** puede pedir ayuda ni abrir el código: solo el README.

| # | Paso | Cómo se mide | Criterio |
|---|---|---|---|
| 1 | Descomprimir el ZIP | — | Sin carpetas pesadas (`node_modules`, `.venv`, `target`, `.git`) |
| 2 | `cp .env.example .env` y pegar la clave de Gemini | Cronómetro desde aquí | El README dice dónde conseguirla |
| 3 | `./run.sh` | Hasta ver «Dashboard: http://localhost:8000» | **< 5 min** con imágenes ya descargadas; < 8 min la primera vez |
| 4 | Abrir el dashboard | — | Carga sin errores en la consola del navegador |
| 5 | Botón «Crítico» → «Reportar y triar» | — | La tira de registro imprime pasos en vivo |
| 6 | «Aprobar asignación» | — | El agente continúa y escribe el resumen |
| 7 | Botón «Inválido (error 400)» | — | Mensaje legible por campo, sin traza de Python |
| 8 | `./run.sh eval` | — | Imprime la tabla de línea base |
| 9 | `./run.sh test` | — | 69 pruebas en verde |

### Registro de la prueba

Rellenar al ejecutarla:

| Campo | Valor |
|---|---|
| Quién probó | _nombre del compañero_ |
| Fecha | |
| Sistema operativo y versión de Docker | |
| ¿Primera vez que descarga las imágenes? | sí / no |
| Tiempo hasta el dashboard (paso 3) | _min:seg_ |
| Pasos 4 a 9 | ✓ / ✗ con observación |
| Dudas que tuvo sin abrir el código | |
| Cambios que provocó en el README | |

---

## 2. Lo que ya se verificó

### En el entorno de construcción, ejecutado de verdad

| Qué | Resultado |
|---|---|
| 69 pruebas unitarias (`pytest`) | **69 pasan**, 2,3 s |
| Suite de casos dorados (`eval/run_eval.py`, 22 casos) | **22/22** en urgencia, 5/5 inconsistencias |
| Aplicación contra PostgreSQL 16 real | Arranca, `/api/ready` responde `{"estado":"UP","base_datos":"UP"}` |
| Esquema y semilla (`db/01-schema.sql`, `db/02-seed.sql`) | Cargan limpio: 6 tablas, 12 pólizas, 10 siniestros |
| Ciclo completo del agente | 4 iteraciones, 3 herramientas, pausa por confirmación, reanudación al aprobar |
| Dashboard en Chromium (Playwright) | Reporte → traza en vivo → aprobación → resumen, sin errores de consola |
| Validación 400 | Devuelve los campos con su error en español |
| Confirmar dos veces la misma acción | 409, sin efectos duplicados |
| Responsive a 390 px | Sin desbordamiento horizontal |

### Lo que NO se pudo verificar aquí, y por qué

La red del entorno donde se construyó el proyecto bloquea Docker Hub, Maven Central y
`generativelanguage.googleapis.com`. Por eso quedan tres verificaciones pendientes, todas
en la lista de arriba:

| Pendiente | Mitigación aplicada | Cómo cerrarlo |
|---|---|---|
| `docker compose up` nunca se ejecutó | Imágenes con versión exacta y estable (`postgres:16-alpine`, `python:3.12-slim`); `app/Dockerfile` sin pasos de compilación; `healthcheck` real en ambos servicios | `./run.sh` en tu máquina |
| Llamada real a Gemini | 12 pruebas de contrato contra transporte simulado: formato de envío, lectura de `functionCall`, 429 con reintento, clave inválida, timeout, bloqueo por filtros, cuerpo no-JSON | `./run.sh check` |
| Línea base con Gemini | La fila está marcada «por medir» en `docs/decisiones.md`, no inventada | `./run.sh eval --provider gemini` |

**Haz las tres antes de la demo.** Si alguna falla, el sistema sigue presentable: con
`LLM_PROVIDER=offline` el triaje corre con reglas y la demo funciona completa, salvo la
parte de orquestación del modelo.

---

## 3. Problemas conocidos de arranque

| Síntoma | Causa | Solución |
|---|---|---|
| `docker: command not found` | Docker no instalado | https://docs.docker.com/get-docker/ |
| `unknown shorthand flag` en `docker compose` | Compose v1 (`docker-compose`) | Instalar Compose v2 |
| `port is already allocated` | Algo usa el 8000 o el 5432 | Cambia `APP_PORT` o `POSTGRES_PORT` en `.env` |
| `permission denied: ./run.sh` | Permiso de ejecución perdido al descomprimir | `chmod +x run.sh` |
| El dashboard carga sin tipografías | Sin internet (se cargan de Google Fonts) | Cosmético: hay tipografías de respaldo del sistema |
| «Modo determinista» al arrancar | `GEMINI_API_KEY` vacía o inválida | Pon la clave en `.env` y `./run.sh` otra vez |
| La base no tiene datos | Volumen de una corrida anterior | `./run.sh reset` |
