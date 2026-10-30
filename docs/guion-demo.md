# Guion de la demo · 6 minutos + 3 de preguntas

Regla de oro: **se abre con la aplicación funcionando, no con diapositivas.**

---

## Antes de entrar al salón (15 minutos)

```bash
./run.sh            # levantar y dejar levantado
./run.sh check      # confirmar que la clave de Gemini responde
./run.sh eval --provider gemini   # llenar la fila pendiente de docs/decisiones.md
./run.sh reset && ./run.sh        # cola limpia para la demo
```

- Pestaña 1: `http://localhost:8000` (dashboard).
- Pestaña 2: `docs/decisiones.md` abierto en la sección de línea base.
- Terminal visible con `./run.sh logs` corriendo (los logs JSON se ven en vivo).
- Ten a mano el caso de respaldo: si Gemini falla, el sistema degrada solo y **eso
  también es parte de la demo** — dilo en voz alta cuando pase.

---

## Minuto a minuto

### 0:00 – 0:40 · El problema, con la pantalla ya abierta

> «Un ajustador abre su turno con 40 reclamos y no sabe cuál tiene heridos. Esto lee
> cada relato, lo prioriza y arma el expediente. Lo que ven arriba es el motor que está
> operando ahora mismo y sus cuatro límites.»

Señalar la barra superior: motor, iteraciones, tiempo, tokens, confirmación.

### 0:40 – 2:10 · Un siniestro crítico, de punta a punta

1. Pulsar **Crítico** → **Reportar y triar**.
2. Mientras se imprime la tira: ir narrando los pasos.

> «Cada línea es un paso real del agente, con su latencia y sus tokens. Primero el
> modelo decide llamar a `clasificar_urgencia`; eso no lo decide la IA, lo decide código
> determinista, porque de este nivel depende que alguien con heridos espere 15 minutos o
> 2 horas. Después verifica la póliza. Y aquí se detiene.»

3. Señalar el panel de confirmación.

> «El agente quiere asignar un ajustador. No lo hace: pide autorización. Este es el
> cuarto límite: ninguna acción que toque el expediente se ejecuta sola.»

4. Pulsar **Aprobar asignación** → el bucle continúa y escribe el resumen.

### 2:10 – 3:00 · Dónde interviene la IA y dónde no

Abrir «ver datos» en el paso de `clasificar_urgencia`.

> «La IA decide **qué herramientas usar y cómo resumir**. El nivel de urgencia, la
> cobertura y los antecedentes salen de código y de SQL. Si el modelo contradice al
> clasificador, manda el clasificador: está prohibido en el prompt y el valor que se
> guarda sale de la herramienta, no del texto.»

### 3:00 – 4:00 · Un caso que un lector rápido aprobaría

1. Pulsar **Inconsistente** → **Reportar y triar**.
2. Señalar las dos inconsistencias detectadas.

> «El cliente dice que no hubo daños ni heridos, y en la misma frase que el carro quedó
> destruido y la ambulancia se llevó al conductor. El motor marca las dos contradicciones
> y manda el caso a revisión humana. Esto es fraude o es pánico; en los dos casos lo
> decide una persona.»

### 4:00 – 4:40 · Cuando algo falla

Elegir **uno** según el tiempo:

- **Validación:** botón **Inválido (error 400)** → «campo por campo, en español, sin una
  sola traza de Python en pantalla».
- **Caída del modelo:** si ya ocurrió sola durante la demo, mostrar la franja «Modo
  determinista» → «se cayó la API y el siniestro se clasificó igual; el ajustador ve el
  aviso, no un error».

### 4:40 – 5:40 · Las cifras

Cambiar a `docs/decisiones.md`, sección de línea base.

> «22 casos dorados escritos con criterio de ajustador antes de ejecutarlos, 7 de ellos
> casos borde. Medianas, no promedios. La suite encontró un fallo real: la regla que
> detecta el tipo de siniestro equivocado se le escapaba "choque del carro saliendo del
> garaje" declarado como hogar, porque la palabra garaje bastaba. Lo corregimos y la
> detección de inconsistencias pasó de 80 a 100 por ciento. Las dos líneas base están
> en el repositorio, con fecha.»

### 5:40 – 6:00 · Cierre

> «Dos contenedores, un comando, cinco minutos para levantarlo. Cuatro herramientas
> propias, cuatro límites activos, y toda la traza visible y guardada en la base de
> datos: lo que acaban de ver no es un log de pantalla, se puede auditar después.»

---

## Preguntas probables y respuestas

**¿Por qué Gemini y no Groq u OpenAI?**
Costo cero en la capa gratuita para ~1.900 tokens por caso, baja latencia (el agente
encadena 3 a 5 llamadas por siniestro) y `functionDeclarations` con JSON Schema completo,
que nos deja validar argumentos antes de ejecutar. Groq es más rápido pero su cuota
gratuita se agota antes; OpenAI exige saldo activo y si se acaba, no hay demo.

**¿Qué pasa si el modelo alucina un nivel de urgencia?**
No puede: el nivel que se guarda sale de `clasificar_urgencia`, no del texto del modelo.
Y si el agente termina sin clasificar, el servidor corre el clasificador antes de cerrar.
Se ve en la traza como paso `fallback`.

**¿Por qué no usan RAG?**
Porque el conocimiento es estructurado. Las pólizas son filas con llave exacta: un
índice vectorial sería más lento, aproximado y capaz de devolver la póliza de otro
cliente por parecido semántico, que en seguros es un incidente de privacidad. Lo único
que sí es búsqueda por similitud —casos parecidos— se resuelve con el índice de texto
completo en español de PostgreSQL, que es determinista y explicable. El umbral para
reconsiderarlo está escrito: más de 50.000 siniestros y cobertura bajo 70 %.

**¿Cómo evitan el bucle infinito?**
Cuatro límites, cada uno con su prueba en `test_agent_limits.py`: 6 iteraciones, 45
segundos de reloj de pared (y cada llamada recibe solo el tiempo restante), 8.000 tokens
acumulados y confirmación humana para cualquier acción con efecto.

**Señáleme esta función y explíquela** → ver la sección siguiente.

**¿Esto escala?**
Hoy es un contenedor con un proceso asíncrono: el cuello de botella sería el proveedor de
IA, no la app. El camino es mover el triaje a una cola y escalar consumidores; la
frontera ya está lista porque el agente no sabe quién lo invoca. No se hizo porque no
aporta a lo que se evalúa y sí añade dos contenedores al arranque.

**¿Qué harían distinto con más tiempo?**
Autenticación de ajustadores (hoy el dashboard es abierto, está declarado como deuda en
`decisiones.md`), y medir con un corpus real de siniestros en vez de 22 casos escritos
por nosotros.

---

## Reparto para «explique este bloque de código»

Cada integrante debe poder abrir y explicar **sin leer**:

| Integrante | Archivos | Preguntas que debe aguantar |
|---|---|---|
| 1 | `agent/loop.py` | Dónde se aplica cada límite; qué pasa si el proveedor falla a mitad; cómo se reanuda tras la confirmación (respuesta: la conversación se reconstruye desde las trazas). |
| 2 | `agent/tools.py`, `agent/prompts.py` | Por qué las descripciones están escritas así; qué cambió de v1 a v2 y por qué; qué hace `validate_arguments` con `"3"` en vez de `3`. |
| 3 | `nlp/classifier.py`, `nlp/lexicon.py` | Cómo se normaliza una palabra; por qué «no hubo daños, pero hay heridos» es CRÍTICO; qué regla cambió entre las dos líneas base. |
| Todos | `providers/base.py` | Por qué el bucle no conoce a Gemini; qué habría que escribir para añadir Groq. |

Las tres preguntas que más probablemente caigan, porque son las que tienen respuesta
corta y verificable en pantalla:

1. «¿Dónde exactamente interviene la IA?» → el paso `llm_call` de la tira: ahí y solo ahí.
2. «Muéstreme el límite de tokens funcionando» → `test_agent_limits.py`, o bajar
   `AGENT_MAX_TOKENS` a 500 en `.env`, reiniciar y reportar un siniestro.
3. «¿Y si no hay internet?» → `LLM_PROVIDER=offline`, el triaje sigue corriendo.
