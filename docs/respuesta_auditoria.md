# Respuesta a la auditoría cruzada

> **ESTADO: PENDIENTE.** Este archivo es solo la estructura. El reporte de auditoría que
> recibió el equipo no está en el repositorio, y no se inventan hallazgos ni respuestas.
> Pegar el reporte, listar cada hallazgo y responder con una de las tres posturas.

Reglas de la rúbrica: cada hallazgo con su respuesta argumentada; **«lo asumimos y por qué»
califica igual que arreglarlo**; prometer un arreglo que no se hizo es lo que más resta.
Solo marcar «Arreglado» si hay commit o prueba que lo demuestre.

| # | Hallazgo (cita del reporte) | Severidad | Postura | Respuesta argumentada | Evidencia |
|---|---|---|---|---|---|
| 1 | _…_ | | Arreglado / Asumido / Refutado | _…_ | commit, prueba o línea |
| 2 | | | | | |

## Hallazgos que el equipo ya conoce (cruzar con el reporte)

Si el auditor los señaló, la respuesta ya está documentada:

| Tema | Postura | Dónde |
|---|---|---|
| Línea base con Gemini sin medir | **Asumido** hasta poder ejecutar la suite con la base levantada | `decisiones.md` § 8 |
| Texto inyectado en la foto | **Asumido**, no cerrado | `seguridad.md` § 4 |
| Claves de cuentas en texto plano | **Asumido** (alcance) | `decisiones.md` § 11 |
| Limitador en memoria por IP | **Asumido** | `decisiones.md` § 11 |
| Sin pruebas automáticas del JavaScript | **Asumido** | `decisiones.md` § 13 |
