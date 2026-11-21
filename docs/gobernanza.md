# Ficha de gobernanza

> Cada respuesta dice lo que el sistema **hace hoy** y dónde se verifica en el código.
> Lo que no está construido se declara como pendiente. Las cinco preguntas pueden reordenarse
> o renombrarse para coincidir con la plantilla exacta del curso.

## 1. ¿Qué hace el sistema, para quién y con qué decisión?

Lee el relato de un siniestro, lo clasifica por urgencia (CRITICAL/HIGH/LOW), verifica la póliza,
busca casos parecidos y arma un expediente para un **ajustador humano**. **No decide** el siniestro,
no paga, no niega cobertura. Recomienda la prioridad y propone una asignación.
Una excepción declarada: un caso LOW se marca «aprobación automática» como **recomendación**
(`decisiones.md` § 1); el sistema no ejecuta ningún pago.

## 2. ¿Qué datos usa y quién puede verlos?

| Dato | Quién lo ve | Dónde se verifica |
|---|---|---|
| Relato, tipo, foto del cliente | Rol `trabajador` | `api/routes.py` (`TRABAJADOR`), `test_cada_rol_solo_entra_a_lo_suyo` |
| Póliza (con titular) | Solo el servidor; el agente recibe una vista **sin titular** | `db/03-roles.sh` (`agent_policies`) |
| Trazas y consumo | Rol `ti` | `api/routes.py` (`requiere("ti")`) |
| Datos enviados al proveedor de IA (Google) | Relato y foto reducida a 1024 px, sin EXIF | `storage.reducir_para_modelo` |

Pendiente declarado: no hay política de retención ni borrado de siniestros; los datos de ejemplo
son sintéticos. El cliente no es informado en pantalla de que su relato pasa por un modelo externo.

## 3. ¿Quién supervisa y dónde lo exige el sistema?

Supervisión humana **exigida por código, no por costumbre**:

- `agent/loop.py:359`: si la herramienta tiene `requires_confirmation` y
  `AGENT_REQUIRE_CONFIRMATION` es true, el bucle **no ejecuta**: guarda un paso `confirmation`,
  deja la corrida en `AWAITING_CONFIRMATION` y termina.
- `api/routes.py:480` (`confirmar_accion`): solo una sesión de rol `trabajador` puede reanudar; el
  aprobador queda registrado desde la sesión (`by=sesion.usuario`), no desde el cuerpo de la petición.
- Aprobar dos veces la misma acción devuelve 409 (`loop.py:202`).
- Prueba de ataque: con un modelo que obedece la inyección, 0 asignaciones se ejecutan sin humano
  (`docs/seguridad.md` § 3).

Límite honesto: la supervisión cubre **asignar ajustador**. La urgencia calculada se guarda sin
revisión previa; el ajustador la ve y puede corregirla, pero el sistema no lo obliga.

## 4. ¿Qué puede salir mal y qué límites tiene?

| Riesgo | Límite / control |
|---|---|
| Subestimar un caso grave | Clasificador determinista y auditable; el error barato (falso positivo) manda a revisión humana (`decisiones.md` § 8). Medido: 22/22 casos dorados |
| Modelo engañado por el texto | Arquitectura (sin salida a red, lectura mínima, humano en lo irreversible); ver `seguridad.md` |
| Caída o cuota del proveedor | Degradación al motor determinista; ningún siniestro queda sin nivel |
| Gasto descontrolado | 6 iteraciones, 45 s, 8.000 tokens/corrida, techo diario |
| Fallos conocidos | Falso positivo TC-018; texto en foto sin cerrar; línea base con Gemini pendiente de medir (§ 8 de `decisiones.md`) |

## 5. Si el sistema causa un daño hoy, ¿qué hacemos?

1. **Contener:** `LLM_PROVIDER=offline` (apaga el modelo en un reinicio) o `AGENT_REQUIRE_CONFIRMATION=true`
   (ya es el valor por defecto); `./run.sh down` apaga todo.
2. **Reconstruir:** cada corrida queda en `agent_runs` / `agent_steps` con cada llamada, argumentos y
   resultados, y `claim_status_history` registra los cambios de estado y quién los hizo.
3. **Corregir:** el ajustador reasigna o reabre el caso; se agrega el caso a `eval/casos_dorados.jsonl`
   para que no se repita.
4. **Responsables:** los dos integrantes del equipo (el dueño del sistema es quien lo opera).

Pendiente declarado: no hay canal formal de reclamo para el cliente ni plazo de respuesta definido.
