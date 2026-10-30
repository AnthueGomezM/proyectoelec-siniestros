# Línea base · offline · 2026-10-23 00:33 UTC

Modelo: `reglas-deterministas-v2` · Casos: 22 · Corridas sin error: 22/22

| Cifra | Mediana | Detalle |
|---|---|---|
| Exactitud de urgencia | **100.0 %** | 22 de 22 casos |
| Detección de inconsistencias | **80.0 %** | 4 de 5 esperadas, 1 falsos positivos |
| Latencia por caso | **0.008 s** | p90 0.01 s |
| Tokens por caso | **1866** | total 38137 |

Herramientas por caso: 2.68 · Casos borde acertados: 7/7 · Corridas degradadas: 0

## Caso por caso

| Caso | Esperado | Obtenido | | Inconsistencias | s | tokens |
|---|---|---|---|---|---|---|
| TC-001 | CRITICAL | CRITICAL | ✓ | — | 0.032 | 1872 |
| TC-002 | LOW | LOW | ✓ | — | 0.011 | 1431 |
| TC-003 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.014 | 1880 |
| TC-004 | HIGH | HIGH | ✓ | — | 0.008 | 1898 |
| TC-005 | HIGH | HIGH | ✓ | SEVERITY_CONTRADICTION | 0.01 | 1922 |
| TC-006 | LOW | LOW | ✓ | — | 0.006 | 1395 |
| TC-007 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.008 | 1876 |
| TC-008 | CRITICAL | CRITICAL | ✓ | — | 0.009 | 1860 |
| TC-009 (borde) | HIGH | HIGH | ✓ | — | 0.01 | 1892 |
| TC-010 | LOW | LOW | ✓ | — | 0.009 | 1404 |
| TC-011 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.01 | 1860 |
| TC-012 | LOW | LOW | ✓ | — | 0.007 | 1416 |
| TC-013 | HIGH | HIGH | ✓ | CLAIM_TYPE_MISMATCH | 0.009 | 1930 |
| TC-014 (borde) | CRITICAL | CRITICAL | ✓ | — | 0.007 | 1868 |
| TC-015 | CRITICAL | CRITICAL | ✓ | — | 0.008 | 1856 |
| TC-016 | LOW | LOW | ✓ | — | 0.005 | 1411 |
| TC-017 | CRITICAL | CRITICAL | ✓ | — | 0.008 | 1876 |
| TC-018 (borde) | HIGH | HIGH | ✓ | DAMAGE_DENIED_BUT_SEVERE | 0.007 | 1889 |
| TC-019 | LOW | LOW | ✓ | — | 0.006 | 1413 |
| TC-020 | CRITICAL | CRITICAL | ✓ | — | 0.009 | 1864 |
| TC-021 | CRITICAL | CRITICAL | ✓ | DAMAGE_DENIED_BUT_SEVERE, INJURY_DENIED_BUT_EVIDENCE | 0.007 | 1892 |
| TC-022 (borde) | LOW | LOW | ✓ | — | 0.005 | 1432 |
