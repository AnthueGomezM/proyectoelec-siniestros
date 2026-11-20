// Aplicación de una sola página: enrutado, sesión, estructura del personal y avisos en vivo.
import { html, render, useState, useEffect, useCallback } from "./lib.js";
import { Icono, Logo } from "./icons.js";
import { Boton, Toasts } from "./ui.js";
import { navegar, useRuta, Enlace } from "./router.js";
import { pedir, alSesionVencida } from "./api.js";
import { iniciales } from "./format.js";
import {
  conexion, sinLeer, criticos, prefs, guardarPrefs, iniciarEnVivo, detenerEnVivo, probarAviso, pedirPermisoNotificaciones,
} from "./live.js";
import { Cliente } from "./views/Cliente.js";
import { Ingreso, VISTA_DE } from "./views/Ingreso.js";
import { Trabajador } from "./views/Trabajador.js";
import { Ti } from "./views/Ti.js";

const TITULO = { "/": "Reportar un siniestro", "/ingresar": "Acceso del personal", "/trabajador": "Cola de siniestros", "/ti": "Operación y TI" };
const NAV = {
  trabajador: [{ ruta: "/trabajador", icono: "lista", texto: "Cola" }],
  ti: [{ ruta: "/ti", icono: "panel", texto: "Operación" }],
};

// --------------------------------------------------------------------------- sesión
function useSesion() {
  const [sesion, setSesion] = useState({ estado: "cargando" });
  useEffect(() => {
    pedir("/api/auth/sesion", { sinRedirigir: true })
      .then((yo) => setSesion(yo.autenticado ? { estado: "ok", usuario: yo.usuario, rol: yo.rol } : { estado: "no" }))
      .catch(() => setSesion({ estado: "no" }));
  }, []);
  return [sesion, setSesion];
}

// --------------------------------------------------------------------------- avisos (panel)
function PanelAvisos({ alCerrar }) {
  const p = prefs.usar();
  const permiso = typeof Notification === "undefined" ? "no-soportado" : Notification.permission;

  const alternarEscritorio = async (e) => {
    if (e.target.checked) {
      const ok = await pedirPermisoNotificaciones();
      guardarPrefs({ escritorio: ok });
      if (!ok) e.target.checked = false;
    } else guardarPrefs({ escritorio: false });
  };

  return html`<div class="panel-avisos" role="dialog" aria-label="Preferencias de avisos">
    <h3>Avisos en vivo</h3>
    <label class="interruptor"><span>Sonido en críticos y altos</span>
      <input type="checkbox" checked=${p.sonido} onChange=${(e) => guardarPrefs({ sonido: e.target.checked })} /></label>
    <label class="interruptor"><span>Notificaciones del sistema<br /><small class="campo__ayuda">${
      permiso === "denied" ? "Bloqueadas en el navegador" : permiso === "no-soportado" ? "No disponibles aquí" : "Solo con la pestaña en segundo plano"}</small></span>
      <input type="checkbox" checked=${p.escritorio && permiso === "granted"} disabled=${permiso === "denied" || permiso === "no-soportado"} onChange=${alternarEscritorio} /></label>
    <${Boton} tam="sm" icono="campana" onClick=${probarAviso}>Probar aviso<//>
    <${Boton} tam="sm" variante="fantasma" onClick=${alCerrar}>Cerrar<//>
  </div>`;
}

function EstadoVivo() {
  const estado = conexion.usar();
  const clase = estado === "conectado" ? "estado-vivo--on" : estado === "cerrado" ? "" : "estado-vivo--reconectando";
  const texto = estado === "conectado" ? "En vivo" : estado === "cerrado" ? "Sin conexión" : "Reconectando…";
  return html`<span class=${`estado-vivo ${clase}`} role="status" title="Avisos en tiempo real"><span class="etiqueta">${texto}</span></span>`;
}

// --------------------------------------------------------------------------- estructura del personal
function Estructura({ sesion, ruta, alSalir, children }) {
  const [avisos, setAvisos] = useState(false);
  const numCriticos = criticos.usar();
  const pendientes = sinLeer.usar();
  const preferencias = prefs.usar();
  const esTrabajador = sesion.rol === "trabajador";
  const items = NAV[sesion.rol] || [];

  // Título de la pestaña con el contador de avisos sin leer, como en un correo.
  useEffect(() => {
    document.title = `${pendientes ? `(${pendientes}) ` : ""}${TITULO[ruta] || "Guardia de triaje"} · Guardia de triaje`;
  }, [pendientes, ruta]);

  // Los avisos en vivo solo existen para el trabajador.
  useEffect(() => {
    if (!esTrabajador) return undefined;
    iniciarEnVivo();
    return () => detenerEnVivo();
  }, [esTrabajador]);

  const enlaces = (clase) => items.map((i) => html`<${Enlace} key=${i.ruta} href=${i.ruta} class=${clase} aria-current=${ruta === i.ruta ? "page" : null}>
    <${Icono} n=${i.icono} /><span>${i.texto}</span>
    ${esTrabajador && numCriticos ? html`<span class="nav-enlace__contador" aria-label=${`${numCriticos} críticos pendientes`}>${numCriticos}</span>` : null}
  <//>`);

  return html`<div class="shell">
    <aside class="nav-lateral" aria-label="Navegación principal">
      <${Enlace} href="/" class="marca"><${Logo} /><span class="marca__nombre">Guardia de triaje<span class="marca__sub">Personal</span></span><//>
      <nav class="nav-lista">
        ${enlaces("nav-enlace")}
        <${Enlace} href="/" class="nav-enlace"><${Icono} n="enviar" /><span>Vista del cliente</span><//>
      </nav>
      <div class="nav-pie">
        <div class="usuario">
          <span class="usuario__avatar" aria-hidden="true">${iniciales(sesion.usuario)}</span>
          <span><span class="usuario__nombre">${sesion.usuario}</span><br /><span class="usuario__rol">${esTrabajador ? "Trabajador" : "TI"}</span></span>
        </div>
        <button type="button" class="nav-enlace" onClick=${alSalir}><${Icono} n="salir" /><span>Cerrar sesión</span></button>
      </div>
    </aside>

    <div class="contenido">
      <header class="barra">
        <${Enlace} href="/" class="marca"><${Logo} /><span class="marca__nombre">Guardia</span><//>
        <h1 class="barra__titulo">${TITULO[ruta]}</h1>
        <div class="barra__acciones">
          ${esTrabajador ? html`<${EstadoVivo} />
            <div class="relativo">
              <${Boton} variante="fantasma" class="btn--icono" aria-label="Preferencias de avisos" aria-expanded=${avisos} onClick=${() => setAvisos(!avisos)}
                icono=${preferencias.sonido ? "campana" : "campanaOff"} />
              ${avisos ? html`<${PanelAvisos} alCerrar=${() => setAvisos(false)} />` : null}
            </div>` : null}
        </div>
      </header>
      <main class="contenido__cuerpo">${children}</main>
    </div>

    <nav class="nav-inferior" aria-label="Navegación">
      ${enlaces("nav-enlace")}
      <${Enlace} href="/" class="nav-enlace"><${Icono} n="enviar" /><span>Cliente</span><//>
      <button type="button" class="nav-enlace" onClick=${alSalir}><${Icono} n="salir" /><span>Salir</span></button>
    </nav>
  </div>`;
}

// --------------------------------------------------------------------------- aplicación
function Cargando() {
  return html`<div class="arranque" role="status"><span class="spinner spinner--grande" aria-hidden="true"></span><p>Cargando…</p></div>`;
}

function App() {
  const { ruta } = useRuta();
  const [sesion, setSesion] = useSesion();
  const privada = ruta === "/trabajador" || ruta === "/ti";

  // Una llamada devolvió 401: la sesión venció.
  useEffect(() => alSesionVencida(() => setSesion({ estado: "no" })), []);

  useEffect(() => {
    if (!privada || sesion.estado === "cargando") return;
    if (sesion.estado === "no") navegar(`/ingresar?next=${ruta}`, { reemplazar: true });
    else if (VISTA_DE[sesion.rol] !== ruta) navegar(VISTA_DE[sesion.rol] || "/", { reemplazar: true });   // rol equivocado: a lo suyo
  }, [privada, sesion.estado, sesion.rol, ruta]);

  // Quien ya inició sesión no necesita ver la pantalla de ingreso.
  useEffect(() => {
    if (ruta === "/ingresar" && sesion.estado === "ok") navegar(VISTA_DE[sesion.rol] || "/", { reemplazar: true });
  }, [ruta, sesion.estado, sesion.rol]);

  useEffect(() => { if (!privada) document.title = `${TITULO[ruta] || "No encontrada"} · Guardia de triaje`; }, [ruta, privada]);

  const salir = useCallback(async () => {
    try { await pedir("/api/auth/logout", { method: "POST", sinRedirigir: true }); } catch (_) { /* se sale igual */ }
    detenerEnVivo();
    setSesion({ estado: "no" });
    navegar("/ingresar");
  }, []);

  let pantalla;
  if (ruta === "/") pantalla = html`<${Cliente} />`;
  else if (ruta === "/ingresar") pantalla = sesion.estado === "cargando" ? html`<${Cargando} />` : html`<${Ingreso} alEntrar=${setSesion} />`;
  else if (privada) {
    if (sesion.estado !== "ok" || VISTA_DE[sesion.rol] !== ruta) pantalla = html`<${Cargando} />`;
    else pantalla = html`<${Estructura} sesion=${sesion} ruta=${ruta} alSalir=${salir}>${ruta === "/trabajador" ? html`<${Trabajador} />` : html`<${Ti} />`}<//>`;
  } else {
    pantalla = html`<div class="publico"><main class="publico__cuerpo" id="contenido"><div class="tarjeta"><h1>Página no encontrada</h1>
      <p class="campo__ayuda">La dirección no existe.</p><${Enlace} href="/" class="btn btn--primario">Ir al inicio<//></div></main></div>`;
  }

  return html`${pantalla}<${Toasts} />`;
}

render(html`<${App} />`, document.getElementById("app"));
