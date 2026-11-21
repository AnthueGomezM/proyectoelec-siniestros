# Línea base · gemini · 2026-11-21 15:33 UTC

Modelo: `gemini-3.5-flash` · Casos: 22 · Corridas sin error: 22/22

| Cifra | Mediana | Detalle |
|---|---|---|
| Exactitud de urgencia | **100.0 %** | 22 de 22 casos |
| Detección de inconsistencias | **100.0 %** | 5 de 5 esperadas, 1 falsos positivos |
| Latencia por caso | **45.071 s** | p90 45.186 s |
| Tokens por caso | **1310** | total 32981 |

Herramientas por caso: 0.68 · Casos borde acertados: 7/7 · Corridas degradadas: 16

## Caso por caso

| Caso | Esperado | Obtenido | | Inconsistencias | s | tokens |
|---|---|---|---|---|---|---|
| TC-001 | CRITICAL | CRITICAL | ✓ | — | 45.211 | 1308 |
| TC-002 | LOW | LOW | ✓ | — | 45.15 | 678 |
| TC-003 (borde) | CRITICAL | CRITICAL | ✓ | — | 29.285 | 1825 |
| TC-004 | HIGH | HIGH | ✓ | — | 45.069 | 1334 |
| TC-005 | HIGH | HIGH | ✓ | SEVERITY_CONTRADICTION | 23.493 | 3875 |
| TC-006 | LOW | LOW | ✓ | — | 8.681 | 1808 |
| TC-007 (borde) | CRITICAL | CRITICAL | ✓ | — | 45.064 | 1310 |
| TC-008 | CRITICAL | CRITICAL | ✓ | — | 45.142 | 1302 |
| TC-009 (borde) | HIGH | HIGH | ✓ | — | 41.629 | 3926 |
| TC-010 | LOW | LOW | ✓ | — | 45.064 | 660 |
| TC-011 (borde) | CRITICAL | CRITICAL | ✓ | — | 45.201 | 1302 |
| TC-012 | LOW | LOW | ✓ | — | 18.928 | 1855 |
| TC-013 | HIGH | HIGH | ✓ | CLAIM_TYPE_MISMATCH | 45.072 | 1362 |
| TC-014 (borde) | CRITICAL | CRITICAL | ✓ | — | 20.324 | 1821 |
| TC-015 | CRITICAL | CRITICAL | ✓ | — | 45.069 | 1300 |
| TC-016 | LOW | LOW | ✓ | — | 45.165 | 671 |
| TC-017 | CRITICAL | CRITICAL | ✓ | — | 45.186 | 1310 |
| TC-018 (borde) | HIGH | HIGH | ✓ | DAMAGE_DENIED_BUT_SEVERE | 45.181 | 1335 |
| TC-019 | LOW | LOW | ✓ | CLAIM_TYPE_MISMATCH | 45.149 | 689 |
| TC-020 | CRITICAL | CRITICAL | ✓ | — | 1.718 | 1304 |
| TC-021 | CRITICAL | CRITICAL | ✓ | DAMAGE_DENIED_BUT_SEVERE, INJURY_DENIED_BUT_EVIDENCE | 46.226 | 1318 |
| TC-022 (borde) | LOW | LOW | ✓ | — | 45.171 | 688 |
