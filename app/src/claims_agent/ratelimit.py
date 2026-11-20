"""Límite de frecuencia en memoria (ventana deslizante), sin dependencias.

Es el equivalente, a nivel de entrada, del límite de gasto: `POST /api/claims` es público y
cada reporte dispara varias llamadas al modelo. Sin tope, cualquiera puede agotar la cuota
del proveedor (o la factura) con un bucle de `curl`. Y el inicio de sesión sin tope permite
adivinar claves a fuerza bruta.

Limitaciones asumidas, declaradas:
  * Vive en la memoria del proceso: se reinicia con él y no se comparte entre réplicas. Para
    varias réplicas haría falta Redis o el limitador del proxy; con una sola instancia basta.
  * La clave es la IP del cliente tal como la ve el servidor. Detrás de un proxy inverso todas
    las peticiones parecen venir de él: ahí hay que limitar en el proxy, no aquí.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable


class VentanaDeslizante:
    def __init__(self, maximo: int, ventana_segundos: float,
                 reloj: Callable[[], float] = time.monotonic) -> None:
        self.maximo = maximo
        self.ventana = ventana_segundos
        self._reloj = reloj
        self._golpes: dict[str, deque[float]] = {}

    def _limpiar(self, clave: str, ahora: float) -> deque[float]:
        cola = self._golpes.setdefault(clave, deque())
        while cola and ahora - cola[0] >= self.ventana:
            cola.popleft()
        if len(self._golpes) > 10_000:                       # evita crecer sin límite bajo ataque
            for k in [k for k, v in self._golpes.items() if not v and k != clave]:
                del self._golpes[k]
        return cola

    def espera(self, clave: str) -> float:
        """Segundos hasta que `clave` pueda volver a intentar; 0 si ya puede."""
        ahora = self._reloj()
        cola = self._limpiar(clave, ahora)
        if len(cola) < self.maximo:
            return 0.0
        return max(0.0, self.ventana - (ahora - cola[0]))

    def registrar(self, clave: str) -> None:
        ahora = self._reloj()
        self._limpiar(clave, ahora).append(ahora)

    def intentar(self, clave: str) -> float:
        """Registra un golpe si hay cupo. Devuelve 0 si pasó, o los segundos de espera."""
        espera = self.espera(clave)
        if espera == 0:
            self.registrar(clave)
        return espera

    def reiniciar(self, clave: str) -> None:
        self._golpes.pop(clave, None)
