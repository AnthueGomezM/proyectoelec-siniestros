/* =============================================================================
   Pantalla de ingreso del personal. La sesión es una cookie HttpOnly que pone el
   servidor: este script nunca ve ni guarda la clave ni el token.
   ============================================================================= */
(() => {
  "use strict";
  const { $, pedir, mostrarError } = window.G;

  // Cada rol solo puede aterrizar en su propia vista. El destino "next" se acepta solo si
  // es una de esas rutas: así no existe una redirección abierta hacia otro sitio.
  const VISTAS = { trabajador: "/trabajador", ti: "/ti" };

  const next = new URLSearchParams(location.search).get("next");
  if (next) {
    $("motivo").textContent = "Inicia sesión para abrir esa sección.";
  }

  $("formulario").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const form = evento.target;
    const error = $("errorFormulario");
    error.hidden = true;
    $("enviar").disabled = true;
    try {
      const r = await pedir("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ usuario: form.usuario.value, clave: form.clave.value }),
      });
      form.clave.value = "";
      const propia = VISTAS[r.rol];
      location.assign(next && next === propia ? next : (r.destino || propia || "/"));
    } catch (err) {
      form.clave.value = "";
      mostrarError(error, err);
      $("enviar").disabled = false;
      form.clave.focus();
    }
  });
})();
