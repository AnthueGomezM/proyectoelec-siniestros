// La tira de registro: cada paso del agente, impreso en orden (la usan el trabajador y TI).
import { html, useState, useRef } from "./lib.js";
import { Icono } from "./icons.js";
import { Boton } from "./ui.js";
import { fmtPesos } from "./format.js";

const GLIFOS = { llm_call: "◆", tool_call: "▸", confirmation: "⏸", error: "✕", limit: "⊘", fallback: "⇄", final: "■" };
const TITULO = {
  llm_call: (n) => `El modelo decide (${n})`,
  tool_call: (n) => `Herramienta ${n}`,
  confirmation: (n) => `Pausa: ${n} requiere aprobación`,
  error: (n) => `Error en ${n || "el proceso"}`,
  limit: (n) => `Límite alcanzado: ${n}`,
  fallback: () => "Cambio a motor determinista",
  final: () => "Resumen final",
};
const DETALLE_PREVIO = "ejecutada por el sistema antes del modelo";

function subtitulo(tipo, nombre, salida, detalle) {
  if (tipo === "llm_call") {
    const herramientas = (salida.herramientas || []).map((h) => h.nombre);
    if (herramientas.length) return `pide ejecutar: ${herramientas.join(", ")}`;
    return salida.texto ? "responde con el resumen final" : (detalle || "");
  }
  if (tipo === "tool_call") {
    if (salida.error) return `error: ${salida.error}`;
    if (nombre === "clasificar_urgencia") return `urgencia ${salida.urgencia} · puntuación ${salida.puntuacion} · ${salida.accion_es || ""}`;
    if (nombre === "consultar_poliza") {
      return salida.encontrada
        ? `póliza ${salida.estado}, producto ${salida.producto}, deducible ${fmtPesos(salida.deducible)}`
        : "no existe póliza para ese cliente";
    }
    if (nombre === "analizar_imagen_dano") {
      if (!salida.tiene_imagen) return salida.mensaje || "no hay imagen adjunta";
      return `daño ${salida.severidad}${salida.coincide_con_relato === false ? " · no coincide con el relato" : ""}`;
    }
    if (nombre === "buscar_siniestros_similares") return `${salida.total || 0} caso(s) parecido(s) por texto completo`;
    if (nombre === "asignar_ajustador") return salida.asignado ? `asignado a ${salida.ajustador}` : (salida.motivo || "no ejecutada");
    return detalle || "";
  }
  if (tipo === "final") return salida.resumen || detalle || "";
  return detalle || "";
}

function Paso({ paso, t0, animar }) {
  const [abierto, setAbierto] = useState(false);
  const tipo = paso.tipo || paso.kind;
  const nombre = paso.nombre || paso.name;
  const salida = paso.salida || paso.output || {};
  const entrada = paso.entrada || paso.input || {};
  const detalle = paso.detalle || paso.detail;
  const latencia = paso.latencia_ms ?? paso.latency_ms ?? 0;
  const tIn = paso.tokens_entrada ?? paso.tokens_in ?? 0;
  const tOut = paso.tokens_salida ?? paso.tokens_out ?? 0;
  const momento = new Date(paso.momento || paso.created_at || Date.now()).getTime();
  const t = Math.max(0, (momento - t0) / 1000);

  const cifras = [];
  if (latencia) cifras.push(`${latencia} ms`);
  if (tIn || tOut) cifras.push(`${tIn}→${tOut} tok`);

  const sub = subtitulo(tipo, nombre, salida, detalle);
  const datos = (tipo === "tool_call" || tipo === "llm_call") ? JSON.stringify({ entrada, salida }, null, 1) : "";
  const previa = tipo === "tool_call" && detalle === DETALLE_PREVIO;

  return html`<li class=${`paso paso--${tipo} ${animar ? "paso--entra" : ""}`}>
    <span class="paso__t">+${t.toFixed(1)}s</span>
    <span class="paso__glifo" aria-hidden="true">${GLIFOS[tipo] || "·"}</span>
    <div>
      <div class="paso__titulo">${(TITULO[tipo] || (() => tipo))(nombre)}${previa ? " · previa al modelo" : ""}</div>
      ${sub ? html`<div class="paso__sub">${sub}</div>` : null}
      ${datos.length >= 90 ? html`<button type="button" class="ver-datos" onClick=${() => setAbierto(!abierto)}>${abierto ? "ocultar datos" : "ver datos"}</button>` : null}
      ${abierto ? html`<pre class="datos-json">${datos}</pre>` : null}
    </div>
    <div class="paso__cifras">${cifras.join("\n")}</div>
  </li>`;
}

export function TiraRegistro({ pasos, enVivo = false, titulo = "Tira de registro" }) {
  const [abierta, setAbierta] = useState(true);
  // Los pasos que ya estaban al abrir no se animan; los que llegan en vivo, sí.
  const iniciales = useRef(null);
  if (iniciales.current === null) iniciales.current = new Set(pasos.map((p) => p.idx));
  const t0 = pasos.length ? new Date(pasos[0].momento || pasos[0].created_at).getTime() : Date.now();

  const tokens = pasos.reduce((a, p) => a + (p.tokens_entrada ?? p.tokens_in ?? 0) + (p.tokens_salida ?? p.tokens_out ?? 0), 0);
  const ms = pasos.reduce((a, p) => a + (p.latencia_ms ?? p.latency_ms ?? 0), 0);

  return html`<section class="tira">
    <div class="tira__cabecera">
      <h3 class="seccion-etiqueta"><${Icono} n="terminal" tam="sm" /> ${titulo}</h3>
      ${pasos.length ? html`<span class="tira__totales">${pasos.length} pasos · ${(ms / 1000).toFixed(1)} s · ${tokens} tokens</span>` : null}
      <${Boton} tam="sm" variante="fantasma" onClick=${() => setAbierta(!abierta)} aria-expanded=${abierta}>${abierta ? "Ocultar" : "Mostrar"}<//>
    </div>
    ${abierta ? html`<ol class="pasos">
      ${pasos.map((p) => html`<${Paso} key=${p.idx} paso=${p} t0=${t0} animar=${!iniciales.current.has(p.idx)} />`)}
    </ol>` : null}
    ${enVivo ? html`<p class="imprimiendo">el agente está trabajando<span class="cursor"></span></p>` : null}
  </section>`;
}
