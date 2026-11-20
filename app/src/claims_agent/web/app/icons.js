// Íconos propios (viewBox 24, trazo): un solo <svg> por ícono, sin dependencias ni imágenes.
import { html } from "./lib.js";

const c = (cx, cy, r) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
const campana = "M6 16.5v-5.5a6 6 0 0 1 12 0v5.5l1.8 2H4.2zM10 21h4";

const ICONOS = {
  auto: `M3 13l2-5.5A2 2 0 0 1 6.9 6h10.2a2 2 0 0 1 1.9 1.5L21 13v4a1 1 0 0 1-1 1h-1M3 13v4a1 1 0 0 0 1 1h1M3 13h18 ${c(7.5, 17, 1.8)} ${c(16.5, 17, 1.8)}`,
  medico: "M3 12h4l2.5-6 4 12 2.5-6H21",
  hogar: "M3 11.5L12 4l9 7.5M5.5 10v10h13V10M10 20v-5.5h4V20",
  camara: `M4 8.5h3.2L9 6h6l1.8 2.5H20V19H4z ${c(12, 13.5, 3.5)}`,
  check: "M5 12.5l4.5 4.5L19 7.5",
  alerta: "M12 3.5l9.5 16.5h-19zM12 10v4.5M12 17.2v.01",
  reloj: `${c(12, 12, 9)} M12 7v5l3 2`,
  usuario: `${c(12, 8, 4)} M4.5 20.5c.6-3.9 3.7-6 7.5-6s6.9 2.1 7.5 6`,
  salir: "M9 4.5H5.5v15H9M15.5 8l4 4-4 4M19.5 12H9",
  campana,
  campanaOff: `${campana} M4 4l16 16`,
  sonido: "M4 10v4h4l5 4V6L8 10zM16.5 9.2a4 4 0 0 1 0 5.6M19 6.7a7.5 7.5 0 0 1 0 10.6",
  buscar: `${c(11, 11, 6.5)} M16 16l4.5 4.5`,
  izquierda: "M15 5l-7 7 7 7",
  cerrar: "M6 6l12 12M18 6L6 18",
  copiar: "M9 9h11v11H9zM5 15H4V4h11v1",
  enviar: "M4 12l16-8-6 16-3-7z",
  escudo: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  servidor: "M4 5h16v5.5H4zM4 13.5h16V19H4zM7.5 7.8v.01M7.5 16.2v.01",
  rayo: "M13 2.5L4.5 14H11l-1 7.5L19.5 10H13z",
  actualizar: "M20 11.5a8 8 0 1 0-2.4 6M20 5v6.5h-6.5",
  lista: "M8.5 6h12M8.5 12h12M8.5 18h12M4 6v.01M4 12v.01M4 18v.01",
  subir: "M12 16V4.5M7 9l5-5 5 5M4.5 20h15",
  info: `${c(12, 12, 9)} M12 11v5M12 8v.01`,
  terminal: "M4 5h16v14H4zM7.5 10l3 2-3 2M12.5 15h4",
  panel: "M4 4h7v7H4zM13 4h7v4h-7zM13 11h7v9h-7zM4 14h7v6H4z",
  cpu: "M7 7h10v10H7zM9.5 4v3M14.5 4v3M9.5 17v3M14.5 17v3M4 9.5h3M4 14.5h3M17 9.5h3M17 14.5h3",
  carpeta: "M3.5 6.5h6l2 2h9v10.5h-17z",
  ojo: `M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z ${c(12, 12, 2.8)}`,
};

export function Icono({ n, tam = "", class: clase = "" }) {
  const d = ICONOS[n] || ICONOS.info;
  return html`<svg class=${`icono ${tam ? `icono--${tam}` : ""} ${clase}`.trim()} viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d=${d}></path></svg>`;
}

export function Logo({ class: clase = "marca__logo" }) {
  return html`<svg class=${clase} viewBox="0 0 32 32" aria-hidden="true">
    <rect width="32" height="32" rx="7" fill="#0E6B72"></rect>
    <rect x="7" y="7" width="4" height="18" rx="1" fill="#FF8A80"></rect>
    <rect x="14" y="9" width="11" height="2.5" rx="1" fill="#F2F4F3"></rect>
    <rect x="14" y="15" width="11" height="2.5" rx="1" fill="#F2F4F3"></rect>
    <rect x="14" y="21" width="7" height="2.5" rx="1" fill="#F2F4F3"></rect>
  </svg>`;
}
