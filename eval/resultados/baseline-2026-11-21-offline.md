# Línea base · offline · 2026-11-21 15:19 UTC

Modelo: `reglas-deterministas-v2` · Casos: 22 · Corridas sin error: 22/22

| Cifra | Mediana | Detalle |
|---|---|---|
| Exactitud de urgencia | **100.0 %** | 22 de 22 casos |
| Detección de inconsistencias | **100.0 %** | 5 de 5 esperadas, 1 falsos positivos |
| Latencia por caso | **0.01 s** | p90 0.011 s |
| Tokens por caso | **1305** | total 24497 |

Herramientas por caso: 0.68 · Casos borde acertados: 7/7 · Corridas degradadas: 0

## Caso por caso

| Caso | Esperado | Obtenido | | Inconsistencias | s | tokens |
|---|---|---|---|---|---|---|
| TC-001 | CRITICAL | CRITICAL | ✓ | — | 0.027 | 1308 |
| TC-002 | LOW | LOW | ✓ | — | 0.005 | 678 |
| TC-003 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.014 | 1312 |
| TC-004 | HIGH | HIGH | ✓ | — | 0.011 | 1334 |
| TC-005 | HIGH | HIGH | ✓ | SEVERITY_CONTRADICTION | 0.01 | 1356 |
| TC-006 | LOW | LOW | ✓ | — | 0.004 | 657 |
| TC-007 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.01 | 1310 |
| TC-008 | CRITICAL | CRITICAL | ✓ | — | 0.01 | 1302 |
| TC-009 (borde) | HIGH | HIGH | ✓ | — | 0.011 | 1332 |
| TC-010 | LOW | LOW | ✓ | — | 0.004 | 660 |
| TC-011 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.01 | 1302 |
| TC-012 | LOW | LOW | ✓ | — | 0.004 | 663 |
| TC-013 | HIGH | HIGH | ✓ | CLAIM_TYPE_MISMATCH | 0.01 | 1362 |
| TC-014 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.012 | 1306 |
| TC-015 | CRITICAL | CRITICAL | ✓ | — | 0.01 | 1300 |
| TC-016 | LOW | LOW | ✓ | — | 0.004 | 671 |
| TC-017 | CRITICAL | CRITICAL | ✓ | — | 0.011 | 1310 |
| TC-018 (borde) | HIGH | HIGH | ✓ | DAMAGE_DENIED_BUT_SEVERE | 0.01 | 1335 |
| TC-019 | LOW | LOW | ✓ | CLAIM_TYPE_MISMATCH | 0.004 | 689 |
| TC-020 | CRITICAL | CRITICAL | ✓ | — | 0.011 | 1304 |
| TC-021 | CRITICAL | CRITICAL | ✓ | DAMAGE_DENIED_BUT_SEVERE, INJURY_DENIED_BUT_EVIDENCE | 0.009 | 1318 |
| TC-022 (borde) | LOW | LOW | ✓ | — | 0.004 | 688 |
