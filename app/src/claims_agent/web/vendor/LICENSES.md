# Dependencias de terceros incluidas

Se sirven desde este mismo origen (no desde un CDN), por lo que cumplen la politica de contenido
`script-src 'self'` y la aplicacion funciona sin internet para el JavaScript.

| Archivo | Paquete | Version | Licencia | SHA-256 |
|---|---|---|---|---|
| `htm-preact.js` | `htm/preact/standalone.module.js` (incluye Preact 10 y sus hooks) | htm 3.1.1 | Apache-2.0 (htm) y MIT (Preact) | `72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7` |

Obtenido con `npm pack htm@3.1.1` y copiado sin modificar. Para verificar:
`sha256sum htm-preact.js`. Texto de la licencia de htm: `LICENSE-htm.txt`.

Preact (MIT) Copyright (c) 2015-present Jason Miller.
