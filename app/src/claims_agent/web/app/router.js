// Enrutador mínimo sobre la History API: navegar sin recargar la página.
import { html, useState, useEffect } from "./lib.js";

const EVENTO = "guardia:ruta";
const leer = () => ({ ruta: location.pathname, busqueda: location.search });

export function navegar(destino, { reemplazar = false } = {}) {
  const url = new URL(destino, location.origin);
  if (url.origin !== location.origin) { location.assign(destino); return; }
  const actual = location.pathname + location.search;
  const nueva = url.pathname + url.search;
  const cambioDePagina = url.pathname !== location.pathname;
  if (actual !== nueva) (reemplazar ? history.replaceState : history.pushState).call(history, {}, "", nueva);
  window.dispatchEvent(new Event(EVENTO));
  if (cambioDePagina) window.scrollTo(0, 0);
}

export function useRuta() {
  const [estado, setEstado] = useState(leer);
  useEffect(() => {
    const fn = () => setEstado(leer());
    window.addEventListener("popstate", fn);
    window.addEventListener(EVENTO, fn);
    return () => { window.removeEventListener("popstate", fn); window.removeEventListener(EVENTO, fn); };
  }, []);
  return estado;
}

/** Enlace que navega sin recargar, pero conserva el comportamiento normal (clic derecho, nueva pestaña). */
export function Enlace({ href, children, class: clase = "", onClick, ...resto }) {
  const alHacerClic = (e) => {
    if (onClick) onClick(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (resto.target && resto.target !== "_self") return;
    e.preventDefault();
    navegar(href);
  };
  return html`<a href=${href} class=${clase} onClick=${alHacerClic} ...${resto}>${children}</a>`;
}
