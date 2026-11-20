/* =============================================================================
   Vista del CLIENTE: reportar un siniestro y seguir su estado.

   El cliente nunca ve urgencia, puntuación, resumen del agente ni trazas: solo
   consulta /api/public/claims/{id}, que devuelve estado y fechas.
   ============================================================================= */
(() => {
  "use strict";
  const { $, crear, pedir, brindis, mostrarError, fmtFechaHora, fmtRelativo, TIPO_ES } = window.G;

  const CASOS = {
    critico: { claim_type: "AUTO", customer_id: "CUST-000123",
      description: "Choque en la autopista norte, hay dos heridos y ya llamamos a la ambulancia. El carro quedó completamente destruido." },
    inconsistente: { claim_type: "AUTO", customer_id: "CUST-009034",
      description: "No hubo daños ni heridos, pero el vehículo quedó completamente destruido y la ambulancia se llevó al conductor." },
    leve: { claim_type: "AUTO", customer_id: "CUST-005501",
      description: "Solo un rayón en la puerta trasera del carro, hecho en el parqueadero del centro comercial." },
    poliza: { claim_type: "AUTO", customer_id: "CUST-007781",
      description: "Se incendió el motor del carro en plena vía y los bomberos tuvieron que apagarlo." },
    invalido: { claim_type: "AUTO", customer_id: "X", description: "corto" },
  };

  // Mensajes pensados para un asegurado, no para un ajustador.
  const MENSAJES = {
    PENDING: {
      paso: 0,
      texto: "Recibimos tu reporte y ya está en la fila para ser revisado.",
      nota: "No tienes que hacer nada más. Si necesitamos algo, te contactaremos.",
    },
    IN_REVIEW: {
      paso: 1,
      texto: "Un ajustador está revisando tu caso.",
      nota: "Es posible que te llamen para pedirte más información.",
    },
    APPROVED: {
      paso: 2,
      texto: "Tu reporte fue aprobado.",
      nota: "El ajustador se pondrá en contacto contigo para explicarte los siguientes pasos.",
    },
    REJECTED: {
      paso: 2,
      texto: "Tu reporte fue revisado y no pudo ser aprobado.",
      nota: "El ajustador se pondrá en contacto contigo para explicarte el motivo.",
    },
  };

  const CLAVE = "guardia.misReportes";
  let sondeo = null;

  // --------------------------------------------------------------- memoria local
  // Solo para comodidad de quien reporta: la verdad vive en el servidor.

  function leerMios() {
    try { return JSON.parse(localStorage.getItem(CLAVE) || "[]"); } catch (_) { return []; }
  }
  function guardarMio(id, tipo) {
    try {
      const lista = leerMios().filter((r) => r.id !== id);
      lista.unshift({ id, tipo, fecha: new Date().toISOString() });
      localStorage.setItem(CLAVE, JSON.stringify(lista.slice(0, 8)));
    } catch (_) { /* navegación privada: se omite */ }
  }

  function pintarMios() {
    const ul = $("misReportes");
    ul.textContent = "";
    for (const r of leerMios()) {
      ul.append(crear("li", {},
        crear("button", { type: "button", class: "mio", onclick: () => seguir(r.id) },
          crear("span", { class: "mio-tipo", text: TIPO_ES[r.tipo] || r.tipo }),
          crear("span", { class: "mio-id", text: r.id.slice(0, 8) + "…" }),
          crear("span", { class: "mio-fecha", text: fmtRelativo(r.fecha) }),
        )));
    }
  }

  // --------------------------------------------------------------- seguimiento

  async function seguir(id, { silencioso = false } = {}) {
    clearTimeout(sondeo);
    try {
      const d = await pedir(`/api/public/claims/${encodeURIComponent(id)}`);
      pintarSeguimiento(d);
      $("errorConsulta").hidden = true;
      // Mientras no esté resuelto, se vuelve a consultar solo.
      if (d.estado === "PENDING" || d.estado === "IN_REVIEW") {
        sondeo = setTimeout(() => seguir(id, { silencioso: true }), 8000);
      }
    } catch (error) {
      if (silencioso) return;
      $("seguimiento").hidden = true;
      mostrarError($("errorConsulta"), error.status === 400 || error.status === 422
        ? new Error("Ese número no tiene el formato correcto. Cópialo tal como te lo dimos.")
        : error);
    }
  }

  function pintarSeguimiento(d) {
    const m = MENSAJES[d.estado] || MENSAJES.PENDING;
    $("seguimiento").hidden = false;
    $("segMensaje").textContent = m.texto;
    $("segNumero").textContent = d.id;
    $("segNota").textContent = `${m.nota} Recibido el ${fmtFechaHora(d.recibido)}.`;
    document.querySelectorAll("#progreso li").forEach((li, i) => {
      li.className = i < m.paso ? "hecho" : i === m.paso ? "actual" : "";
      if (i === m.paso) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    $("progreso").dataset.resultado = d.estado;
  }

  // --------------------------------------------------------------- reporte

  async function reportar(evento) {
    evento.preventDefault();
    const form = evento.target;
    const error = $("errorFormulario");
    error.hidden = true;
    const formData = new FormData(form);
    formData.set("incident_timestamp", new Date(Date.now() - 20 * 60000).toISOString());

    $("enviar").disabled = true;
    $("enviar").textContent = "Enviando…";
    try {
      const respuesta = await pedir("/api/claims", { method: "POST", body: formData });
      guardarMio(respuesta.claim_id, formData.get("claim_type"));
      pintarMios();
      await seguir(respuesta.claim_id);
      $("seguimiento").scrollIntoView({ behavior: "smooth", block: "start" });
      brindis("Reporte enviado.");
      form.imagen.value = "";
      $("previsualizacion").hidden = true;
    } catch (err) {
      mostrarError(error, err);
    } finally {
      $("enviar").disabled = false;
      $("enviar").textContent = "Enviar reporte";
    }
  }

  // --------------------------------------------------------------- arranque

  $("formulario").addEventListener("submit", reportar);

  $("consulta").addEventListener("submit", (e) => {
    e.preventDefault();
    const numero = e.target.numero.value.trim();
    if (!numero) return;
    seguir(numero);
  });

  $("copiarNumero").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("segNumero").textContent);
      brindis("Número copiado.");
    } catch (_) {
      brindis("No se pudo copiar; selecciónalo y cópialo a mano.");
    }
  });

  $("imagenInput").addEventListener("change", () => {
    const archivo = $("imagenInput").files[0];
    const previa = $("previsualizacion");
    if (!archivo) { previa.hidden = true; return; }
    previa.src = URL.createObjectURL(archivo);
    previa.hidden = false;
  });

  document.querySelectorAll(".ejemplos button").forEach((boton) => {
    boton.addEventListener("click", () => {
      const caso = CASOS[boton.dataset.caso];
      if (!caso) return;
      const form = $("formulario");
      form.customer_id.value = caso.customer_id;
      form.claim_type.value = caso.claim_type;
      form.description.value = caso.description;
    });
  });

  pintarMios();
})();
