// Avisos en vivo para el trabajador: conexión al canal del servidor (SSE) y cómo se avisa.
//
//   servidor ──SSE /api/events──▶ emitir(evento) ──▶ vistas suscritas (refrescan la cola)
//                                          └──────▶ avisar(evento): toast, sonido, notificación
//                                                   del sistema y contador en la pestaña
//
// El navegador reconecta solo si se corta; al volver, se emite «reconectado» y las vistas
// recargan lo que se hayan perdido, así un corte breve no deja la cola desactualizada.
import { crearTienda } from "./store.js";
import { toast } from "./ui.js";
import { navegar } from "./router.js";
import { TIPO_ES } from "./format.js";

const CLAVE_PREFS = "guardia.avisos";
const TIPOS = ["nuevo", "triaje", "aprobacion", "estado"];

function leerPrefs() {
  const base = { sonido: true, escritorio: false };
  try { return { ...base, ...JSON.parse(localStorage.getItem(CLAVE_PREFS) || "{}") }; } catch (_) { return base; }
}

/** Preferencias de aviso del usuario (se recuerdan en este navegador). */
export const prefs = crearTienda(leerPrefs());
/** cerrado | conectando | conectado | reconectando */
export const conexion = crearTienda("cerrado");
/** Avisos recibidos mientras la pestaña estaba oculta (se muestra en el título). */
export const sinLeer = crearTienda(0);
/** Siniestros críticos pendientes en la cola (lo calcula la vista de la cola). */
export const criticos = crearTienda(0);

export function guardarPrefs(cambios) {
  prefs.set((p) => ({ ...p, ...cambios }));
  try { localStorage.setItem(CLAVE_PREFS, JSON.stringify(prefs.get())); } catch (_) { /* navegación privada */ }
}

// --------------------------------------------------------------------------- suscripción

const oyentes = new Set();
export function alEvento(fn) {
  oyentes.add(fn);
  return () => oyentes.delete(fn);
}
const emitir = (e) => oyentes.forEach((fn) => { try { fn(e); } catch (err) { console.error(err); } });

let fuente = null;
let huboCorte = false;
let reintento = null;

export function iniciarEnVivo() {
  if (fuente) return;
  clearTimeout(reintento);
  conexion.set("conectando");
  fuente = new EventSource("/api/events");
  fuente.onopen = () => {
    conexion.set("conectado");
    if (huboCorte) { huboCorte = false; emitir({ tipo: "reconectado" }); }
  };
  fuente.onerror = () => {
    huboCorte = true;
    if (fuente && fuente.readyState === EventSource.CLOSED) {
      // El servidor rechazó la conexión (p. ej. sesión vencida): se reintenta más tarde.
      fuente = null;
      conexion.set("cerrado");
      reintento = setTimeout(iniciarEnVivo, 10000);
    } else {
      conexion.set("reconectando");
    }
  };
  for (const tipo of TIPOS) {
    fuente.addEventListener(tipo, (e) => {
      let evento;
      try { evento = JSON.parse(e.data); } catch (_) { return; }
      emitir(evento);
      avisar(evento);
    });
  }
}

export function detenerEnVivo() {
  clearTimeout(reintento);
  if (fuente) { fuente.close(); fuente = null; }
  conexion.set("cerrado");
}

// --------------------------------------------------------------------------- cómo se avisa

let audio = null;
function pitar(veces = 1, agudo = true) {
  if (!prefs.get().sonido) return;
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === "suspended") audio.resume();
    for (let i = 0; i < veces; i++) {
      const t = audio.currentTime + i * 0.26;
      const osc = audio.createOscillator();
      const ganancia = audio.createGain();
      osc.type = "sine";
      osc.frequency.value = agudo ? 880 : 620;
      ganancia.gain.setValueAtTime(0.0001, t);
      ganancia.gain.exponentialRampToValueAtTime(0.22, t + 0.02);
      ganancia.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
      osc.connect(ganancia).connect(audio.destination);
      osc.start(t);
      osc.stop(t + 0.22);
    }
  } catch (_) { /* el navegador puede bloquear el audio hasta que haya una interacción */ }
}

function notificarSistema(titulo, cuerpo, claimId) {
  if (!prefs.get().escritorio || !document.hidden) return;
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    const n = new Notification(titulo, { body: cuerpo, tag: claimId });
    n.onclick = () => { window.focus(); navegar(`/trabajador?caso=${claimId}`); n.close(); };
  } catch (_) { /* algunos navegadores móviles solo permiten notificaciones desde un service worker */ }
}

function avisar(e) {
  const abrir = { texto: "Abrir", fn: () => navegar(`/trabajador?caso=${e.claim_id}`) };
  const detalle = `${e.cliente || ""} · ${TIPO_ES[e.tipo_siniestro] || e.tipo_siniestro || ""}`;
  let titulo = null;

  if (e.tipo === "triaje") {
    if (e.urgencia === "CRITICAL") {
      titulo = "Siniestro CRÍTICO";
      toast(titulo, { texto: detalle + (e.inconsistencia ? " · con inconsistencias" : ""), tipo: "critico", accion: abrir, duracion: 14000 });
      pitar(2, true);
    } else if (e.urgencia === "HIGH") {
      titulo = "Siniestro de urgencia alta";
      toast(titulo, { texto: detalle, tipo: "alto", accion: abrir, duracion: 9000 });
      pitar(1, false);
    } else {
      titulo = "Nuevo siniestro leve";
      toast(titulo, { texto: detalle, tipo: "leve", accion: abrir, duracion: 5000 });
    }
  } else if (e.tipo === "aprobacion") {
    titulo = "El agente pide tu autorización";
    toast(titulo, { texto: detalle, tipo: "alto", accion: { texto: "Revisar", fn: abrir.fn }, duracion: 12000 });
    pitar(1, true);
  }

  if (titulo) {
    notificarSistema(titulo, detalle, e.claim_id);
    if (document.hidden) sinLeer.set((n) => n + 1);
  }
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) sinLeer.set(0); });
window.addEventListener("focus", () => sinLeer.set(0));

/** Prueba el aviso con el sonido y la notificación configurados (botón del panel de avisos). */
export function probarAviso() {
  toast("Así se verá un aviso", { texto: "CUST-000123 · Auto", tipo: "critico", duracion: 5000 });
  pitar(2, true);
  notificarSistema("Así se verá un aviso", "CUST-000123 · Auto", "prueba");
}

/** Pide permiso para las notificaciones del sistema. Devuelve true si se concedió. */
export async function pedirPermisoNotificaciones() {
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  return (await Notification.requestPermission()) === "granted";
}
