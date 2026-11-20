// Pantalla de ingreso del personal. La sesión es una cookie HttpOnly que pone el servidor:
// este código nunca ve ni guarda la clave ni el token.
import { html, useState } from "../lib.js";
import { Icono, Logo } from "../icons.js";
import { Boton, Aviso } from "../ui.js";
import { Enlace, navegar, useRuta } from "../router.js";
import { pedir, mensajeDeError } from "../api.js";

// Cada rol solo puede aterrizar en su propia vista. «next» se acepta solo si es una de esas
// rutas: así no existe una redirección abierta hacia otro sitio.
export const VISTA_DE = { trabajador: "/trabajador", ti: "/ti" };

export function Ingreso({ alEntrar }) {
  const { busqueda } = useRuta();
  const next = new URLSearchParams(busqueda).get("next");
  const [usuario, setUsuario] = useState("");
  const [clave, setClave] = useState("");
  const [mostrar, setMostrar] = useState(false);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(false);

  const entrar = async (e) => {
    e.preventDefault();
    setError(null);
    setCargando(true);
    try {
      const r = await pedir("/api/auth/login", { method: "POST", body: JSON.stringify({ usuario: usuario.trim(), clave }), sinRedirigir: true });
      setClave("");
      alEntrar({ estado: "ok", usuario: r.usuario, rol: r.rol });
      const propia = VISTA_DE[r.rol];
      navegar(next && next === propia ? next : propia || "/");
    } catch (err) {
      setClave("");
      setError(err.status === 429 ? "Demasiados intentos fallidos. Espera unos minutos antes de volver a intentar." : mensajeDeError(err));
      setCargando(false);
    }
  };

  return html`<div class="publico">
    <header class="publico__barra">
      <span class="marca"><${Logo} /><span class="marca__nombre">Guardia de triaje</span></span>
      <${Enlace} href="/" class="btn btn--sm"><${Icono} n="izquierda" tam="sm" />Reportar un siniestro<//>
    </header>
    <main class="publico__cuerpo" id="contenido">
      <form class="tarjeta formulario-ingreso" onSubmit=${entrar} noValidate aria-labelledby="titulo-ingreso">
        <div class="tarjeta__titulo"><h1 id="titulo-ingreso">Acceso del personal</h1></div>
        <p class="campo__ayuda">${next ? "Inicia sesión para abrir esa sección." : "Esta sección es solo para el personal autorizado."}</p>
        <div class="formulario">
          <div class="campo">
            <label class="campo__etiqueta" for="usuario">Usuario</label>
            <input id="usuario" class="input" value=${usuario} onInput=${(e) => setUsuario(e.target.value)} autocomplete="username"
              autocapitalize="none" spellcheck="false" required />
          </div>
          <div class="campo">
            <div class="campo__fila">
              <label class="campo__etiqueta" for="clave">Clave</label>
              <button type="button" class="ver-datos" onClick=${() => setMostrar(!mostrar)}>${mostrar ? "Ocultar" : "Mostrar"}</button>
            </div>
            <input id="clave" class="input" type=${mostrar ? "text" : "password"} value=${clave} onInput=${(e) => setClave(e.target.value)}
              autocomplete="current-password" required />
          </div>
          ${error ? html`<${Aviso} tipo="error">${error}<//>` : null}
          <${Boton} type="submit" variante="primario" bloque cargando=${cargando} disabled=${!usuario.trim() || !clave}>Ingresar<//>
        </div>
      </form>
    </main>
  </div>`;
}
