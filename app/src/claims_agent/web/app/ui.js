// Componentes de interfaz reutilizables: botones, insignias, avisos emergentes, esqueletos…
import { html, useState, useEffect } from "./lib.js";
import { Icono } from "./icons.js";
import { URGENCIA_ES, ESTADO_ES } from "./format.js";

export function Boton({ variante = "secundario", tam = "", icono, cargando = false, bloque = false,
  class: clase = "", disabled = false, type = "button", children, ...otros }) {
  const clases = ["btn", `btn--${variante}`, tam && `btn--${tam}`, bloque && "btn--bloque", clase].filter(Boolean).join(" ");
  return html`<button type=${type} class=${clases} disabled=${disabled || cargando} ...${otros}>
    ${cargando ? html`<span class="spinner" aria-hidden="true"></span>` : icono ? html`<${Icono} n=${icono} tam=${tam === "sm" ? "sm" : ""} />` : null}
    ${children}
  </button>`;
}

export function Urgencia({ nivel }) {
  if (!nivel) return html`<span class="insignia">Sin evaluar</span>`;
  return html`<span class=${`insignia insignia--${nivel}`}>
    ${nivel === "CRITICAL" ? html`<${Icono} n="alerta" />` : null}${URGENCIA_ES[nivel] || nivel}
  </span>`;
}

const CLASE_ESTADO = { PENDING: "", IN_REVIEW: "insignia--info", APPROVED: "insignia--LOW", REJECTED: "insignia--CRITICAL" };
export function Estado({ valor }) {
  return html`<span class=${`insignia insignia--punto ${CLASE_ESTADO[valor] || ""}`}>${ESTADO_ES[valor] || valor}</span>`;
}

export function Aviso({ tipo = "info", icono, children, ...otros }) {
  const ic = icono || (tipo === "error" || tipo === "alto" ? "alerta" : tipo === "exito" ? "check" : "info");
  return html`<div class=${`aviso aviso--${tipo}`} role=${tipo === "error" ? "alert" : "status"} ...${otros}>
    <${Icono} n=${ic} /><div>${children}</div>
  </div>`;
}

export function Esqueleto({ tipo = "linea", corta = false }) {
  return html`<div class=${`esqueleto esqueleto--${tipo} ${corta ? "esqueleto--corta" : ""}`} aria-hidden="true"></div>`;
}

export function Vacio({ icono = "carpeta", titulo, children }) {
  return html`<div class="vacio">
    <div class="vacio__icono"><${Icono} n=${icono} tam="lg" /></div>
    <div class="vacio__titulo">${titulo}</div>
    ${children ? html`<p>${children}</p>` : null}
  </div>`;
}

/** Hora actual que se refresca sola: hace que «hace 5 min» y los relojes se mantengan al día. */
export function useAhora(ms = 30000) {
  const [t, setT] = useState(Date.now());
  useEffect(() => {
    const i = setInterval(() => setT(Date.now()), ms);
    return () => clearInterval(i);
  }, [ms]);
  return t;
}

// --------------------------------------------------------------------------- avisos emergentes

let items = [];
let secuencia = 0;
const escuchas = new Set();
const emitir = () => escuchas.forEach((fn) => fn(items));

export function cerrarToast(id) {
  items = items.filter((t) => t.id !== id);
  emitir();
}

/** Muestra un aviso emergente. `tipo`: critico | alto | leve | exito | info. */
export function toast(titulo, { texto = "", tipo = "info", accion = null, duracion = 6000 } = {}) {
  const id = ++secuencia;
  items = [...items, { id, titulo, texto, tipo, accion }].slice(-4);
  emitir();
  if (duracion) setTimeout(() => cerrarToast(id), duracion);
  return id;
}

const ICONO_TOAST = { critico: "alerta", alto: "alerta", leve: "check", exito: "check", info: "info" };

export function Toasts() {
  const [lista, setLista] = useState(items);
  useEffect(() => {
    escuchas.add(setLista);
    return () => escuchas.delete(setLista);
  }, []);
  return html`<div class="toasts" aria-live="polite">
    ${lista.map((t) => html`<div class=${`toast toast--${t.tipo}`} key=${t.id} role=${t.tipo === "critico" ? "alert" : "status"}>
      <span class="toast__icono"><${Icono} n=${ICONO_TOAST[t.tipo] || "info"} /></span>
      <div>
        <div class="toast__titulo">${t.titulo}</div>
        ${t.texto ? html`<div class="toast__texto">${t.texto}</div>` : null}
        ${t.accion ? html`<div class="toast__acciones">
          <${Boton} tam="sm" variante="primario" onClick=${() => { cerrarToast(t.id); t.accion.fn(); }}>${t.accion.texto}<//>
        </div>` : null}
      </div>
      <${Boton} tam="sm" variante="fantasma" class="btn--icono" aria-label="Cerrar aviso" onClick=${() => cerrarToast(t.id)} icono="cerrar" />
    </div>`)}
  </div>`;
}
