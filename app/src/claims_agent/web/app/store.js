// Tienda de estado mínima: un valor, quienes lo escuchan, y un hook para usarlo en componentes.
import { useState, useEffect } from "./lib.js";

export function crearTienda(inicial) {
  let valor = inicial;
  const escuchas = new Set();
  return {
    get: () => valor,
    set(nuevo) {
      valor = typeof nuevo === "function" ? nuevo(valor) : nuevo;
      escuchas.forEach((fn) => fn(valor));
    },
    // Se llama dentro de un componente: devuelve el valor y lo mantiene al día.
    usar() {
      const [v, setV] = useState(valor);
      useEffect(() => {
        escuchas.add(setV);
        setV(valor);
        return () => escuchas.delete(setV);
      }, []);
      return v;
    },
  };
}
