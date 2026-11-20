// Acceso a la API. Todo lo que viene del servidor se muestra con texto, nunca como HTML.
const SESION_VENCIDA = "guardia:sesion-vencida";

export async function pedir(url, opciones = {}) {
  const { sinRedirigir = false, ...init } = opciones;
  // FormData (reportar con foto) necesita que el navegador ponga su propio Content-Type con el
  // boundary del multipart; si lo fijamos nosotros, se rompe.
  const esFormData = init.body instanceof FormData;
  const respuesta = await fetch(url, {
    headers: { Accept: "application/json", ...(init.body && !esFormData ? { "Content-Type": "application/json" } : {}) },
    ...init,
  });
  const tipo = respuesta.headers.get("Content-Type") || "";
  const cuerpo = tipo.includes("json") ? await respuesta.json().catch(() => null) : null;
  if (!respuesta.ok) {
    const error = new Error((cuerpo && (cuerpo.detail || cuerpo.title)) || `Error ${respuesta.status}`);
    error.status = respuesta.status;
    error.problema = cuerpo || {};
    if (respuesta.status === 401 && !sinRedirigir) window.dispatchEvent(new Event(SESION_VENCIDA));
    throw error;
  }
  return cuerpo;
}

/** Avisa cuando una llamada devuelve 401 (la sesión venció o nunca existió). */
export function alSesionVencida(fn) {
  window.addEventListener(SESION_VENCIDA, fn);
  return () => window.removeEventListener(SESION_VENCIDA, fn);
}

/** Texto legible de un error de la API, incluyendo los campos inválidos. */
export function mensajeDeError(error) {
  const campos = (error.problema && error.problema.errors) || [];
  const base = error.message || "No se pudo completar la operación.";
  return campos.length ? `${base} ${campos.map((c) => `${c.campo}: ${c.mensaje}`).join(" · ")}` : base;
}
