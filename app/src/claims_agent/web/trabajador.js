/* =============================================================================
   Vista del TRABAJADOR (ajustador):
     1. Cola: siniestros ordenados por urgencia.
     2. Expediente + tira: lo que hizo el agente, en vivo (SSE).
     3. Confirmación y decisión: aprobar la acción del agente y resolver el caso.
   ============================================================================= */
(() => {
  "use strict";
  const {
    $, crear, pedir, brindis, mostrarError, fmtHora, fmtRelativo, accionEs, crearTira,
    avisarDegradado, conectarAviso, URGENCIA_ES, ESTADO_ES, TIPO_ES, CORRIDA_ES,
  } = window.G;

  const SEVERIDAD_ES = { LEVE: "leve", MODERADO: "moderado", SEVERO: "severo", INDETERMINADO: "indeterminado" };

  const estado = {
    filtro: "",
    incluirResueltos: false,
    claims: [],
    seleccion: null,       // claim_id
    runId: null,
    fuente: null,          // EventSource abierto
    pendiente: null,       // acción esperando confirmación
    relojes: null,
  };

  const tira = crearTira($("pasos"), $("tiraTotales"));

  // --------------------------------------------------------------- cola

  async function cargarCola() {
    try {
      const params = new URLSearchParams();
      if (estado.filtro) params.set("urgencia", estado.filtro);
      if (!estado.incluirResueltos) {
        // Por defecto la cola muestra trabajo pendiente, no el archivo histórico.
        params.append("estado", "PENDING");
        params.append("estado", "IN_REVIEW");
      }
      const datos = await pedir(`/api/claims?${params}`);
      estado.claims = datos.items || [];
      pintarCola();
    } catch (error) {
      $("vacio").hidden = false;
      $("vacio").textContent = "No se pudo cargar la cola: " + error.message;
    }
  }

  function pintarCola() {
    const lista = $("fichas");
    lista.textContent = "";
    $("vacio").hidden = estado.claims.length > 0;
    $("vacio").textContent = estado.incluirResueltos
      ? "No hay siniestros con ese filtro."
      : "No hay siniestros pendientes. Cuando un cliente reporte uno, aparecerá aquí.";

    for (const c of estado.claims) {
      const urgencia = c.urgency_level || "NONE";
      lista.append(crear("li", {},
        crear("button", {
          class: `ficha c-${urgencia}`,
          "aria-current": String(estado.seleccion === c.id),
          onclick: () => abrirExpediente(c.id),
        },
          crear("span", { class: "lomo", "aria-hidden": "true" }),
          crear("div", { class: "ficha-cuerpo" },
            crear("div", { class: "ficha-cabecera" },
              crear("span", { class: "ficha-cliente", text: c.customer_id }),
              crear("span", { class: "ficha-tipo", text: TIPO_ES[c.claim_type] || c.claim_type }),
            ),
            crear("p", { class: "ficha-relato", text: c.description }),
            crear("div", { class: "ficha-pie" },
              crear("span", { class: "marca-estado", text: ESTADO_ES[c.status] || c.status }),
              crear("span", { class: "marca-estado", text: fmtRelativo(c.received_at) }),
              c.inconsistencies_flag ? crear("span", { class: "marca-inconsistencia", text: "inconsistencia" }) : null,
              c.assigned_adjuster ? crear("span", { class: "marca-estado", text: `→ ${c.assigned_adjuster}` }) : null,
            ),
          ),
          crear("div", { class: "ficha-lateral" },
            crear("span", { class: `etiqueta-urgencia u-${urgencia}`, text: URGENCIA_ES[urgencia] || "sin evaluar" }),
          ),
        ),
      ));
    }
  }

  // --------------------------------------------------------------- expediente

  async function abrirExpediente(claimId) {
    estado.seleccion = claimId;
    pintarCola();
    cerrarStream();
    try {
      const datos = await pedir(`/api/claims/${claimId}`);
      pintarExpediente(datos.siniestro, datos.corrida, datos.trazas || []);
    } catch (error) {
      brindis("No se pudo abrir el expediente: " + error.message);
    }
  }

  function pintarExpediente(claim, corrida, pasos) {
    $("sinSeleccion").hidden = true;
    $("detalle").hidden = false;
    estado.runId = corrida ? corrida.id : null;

    const urgencia = claim.urgency_level || "NONE";
    const etiqueta = $("detUrgencia");
    etiqueta.className = `etiqueta-urgencia u-${urgencia}`;
    etiqueta.textContent = URGENCIA_ES[urgencia] || "sin evaluar";

    $("detCliente").textContent = `${claim.customer_id} · ${TIPO_ES[claim.claim_type] || claim.claim_type}`;
    const meta = [
      ESTADO_ES[claim.status] || claim.status,
      `recibido ${fmtHora(claim.received_at)}`,
      claim.recommended_action ? accionEs(claim.recommended_action) : null,
      claim.assigned_adjuster ? `ajustador: ${claim.assigned_adjuster}` : null,
    ].filter(Boolean);
    $("detMeta").textContent = meta.join(" — ");
    $("detRelato").textContent = claim.description;

    pintarImagen(claim);
    $("resumenAgente").hidden = !claim.agent_summary;
    $("detResumen").textContent = claim.agent_summary || "";

    pintarReloj(claim);
    pintarEstadoCorrida(corrida);
    tira.pintar(pasos, false);
    pintarPendiente(corrida, pasos);
    $("decision").hidden = ["APPROVED", "REJECTED"].includes(claim.status);
    $("errorDecision").hidden = true;
    $("justificacion").value = "";

    if (corrida && corrida.degraded) {
      avisarDegradado("Este triaje corrió en modo determinista porque el modelo no respondió.");
    }
    if (corrida && corrida.status === "RUNNING") seguirEnVivo(corrida.id);
  }

  function pintarImagen(claim) {
    const contenedor = $("imagenAdjunta");
    if (!claim.has_image) { contenedor.hidden = true; return; }
    $("imagenAdjuntaImg").src = `/api/claims/${claim.id}/image`;
    const a = claim.image_assessment;
    $("imagenAnalisis").textContent = a
      ? `Severidad ${SEVERIDAD_ES[a.severidad] || a.severidad}` +
        (a.coincide_con_relato === false ? " · no coincide con el relato" : "") +
        (a.descripcion ? `: ${a.descripcion}` : "")
      : "El agente todavía no analizó esta foto.";
    contenedor.hidden = false;
  }

  function pintarEstadoCorrida(corrida) {
    const nodo = $("estadoCorrida");
    if (!corrida) { nodo.hidden = true; return; }
    const partes = [`agente ${CORRIDA_ES[corrida.status] || corrida.status}`];
    if (corrida.iterations) partes.push(`${corrida.iterations} iter`);
    if (corrida.latency_ms) partes.push(`${(corrida.latency_ms / 1000).toFixed(1)} s`);
    const tokens = (corrida.tokens_in || 0) + (corrida.tokens_out || 0);
    if (tokens) partes.push(`${tokens} tok`);
    nodo.textContent = partes.join(" · ");
    nodo.hidden = false;
  }

  function pintarReloj(claim) {
    clearInterval(estado.relojes);
    const reloj = $("detReloj");
    if (!claim.sla_minutes || ["APPROVED", "REJECTED"].includes(claim.status)) {
      reloj.hidden = true;
      return;
    }
    const limite = new Date(claim.received_at).getTime() + claim.sla_minutes * 60000;
    const tic = () => {
      const resta = limite - Date.now();
      const signo = resta < 0 ? "-" : "";
      const abs = Math.abs(resta);
      const mm = String(Math.floor(abs / 60000)).padStart(2, "0");
      const ss = String(Math.floor((abs % 60000) / 1000)).padStart(2, "0");
      $("detRelojValor").textContent = `${signo}${mm}:${ss}`;
      reloj.className = "reloj" + (resta < 0 ? " vencido" : resta < claim.sla_minutes * 15000 ? " apretado" : "");
    };
    tic();
    estado.relojes = setInterval(tic, 1000);
    reloj.hidden = false;
  }

  // --------------------------------------------------------------- vivo (SSE)

  function seguirEnVivo(runId) {
    cerrarStream();
    estado.runId = runId;
    $("imprimiendo").hidden = false;
    const fuente = new EventSource(`/api/runs/${runId}/stream`);
    estado.fuente = fuente;
    const vistos = new Set();

    fuente.addEventListener("paso", (evento) => {
      const paso = JSON.parse(evento.data);
      if (vistos.has(paso.idx)) return;
      vistos.add(paso.idx);
      if (vistos.size === 1) tira.reiniciar(new Date(paso.created_at || Date.now()).getTime());
      tira.agregar(paso);
      if ((paso.kind || paso.tipo) === "fallback") {
        avisarDegradado("El modelo falló durante este triaje; el agente continuó con reglas deterministas.");
      }
    });

    fuente.addEventListener("fin", async (evento) => {
      cerrarStream();
      pintarEstadoCorrida(JSON.parse(evento.data));
      if (estado.seleccion) await abrirExpediente(estado.seleccion);
      await cargarCola();
    });

    fuente.onerror = () => {
      cerrarStream();
      brindis("Se perdió la conexión con el agente. Abre el expediente para ver la traza guardada.");
    };
  }

  function cerrarStream() {
    if (estado.fuente) { estado.fuente.close(); estado.fuente = null; }
    $("imprimiendo").hidden = true;
  }

  // --------------------------------------------------------------- confirmación humana

  function pintarPendiente(corrida, pasos) {
    const panel = $("confirmacion");
    const esperando = corrida && corrida.status === "AWAITING_CONFIRMATION";
    panel.hidden = !esperando;
    if (!esperando) { estado.pendiente = null; return; }

    const paso = [...pasos].reverse().find((p) => (p.kind || p.tipo) === "confirmation");
    const args = (paso && (paso.input || paso.entrada)) || {};
    estado.pendiente = { runId: corrida.id, args };
    $("confirmacionTexto").textContent =
      `Asignar el siniestro a «${args.ajustador || "?"}» y pasarlo a En revisión. Motivo: ${args.motivo || "sin motivo"}`;
  }

  async function confirmar(aprobado) {
    if (!estado.pendiente) return;
    const { runId } = estado.pendiente;
    $("aprobar").disabled = $("rechazar").disabled = true;
    try {
      await pedir(`/api/runs/${runId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ aprobado }),   // quién aprueba lo decide la sesión, no el navegador
      });
      brindis(aprobado ? "Asignación aprobada. El agente continúa." : "Acción rechazada. El expediente no se modificó.");
      if (estado.seleccion) await abrirExpediente(estado.seleccion);
      await cargarCola();
    } catch (error) {
      brindis("No se pudo registrar la decisión: " + error.message);
    } finally {
      $("aprobar").disabled = $("rechazar").disabled = false;
    }
  }

  // --------------------------------------------------------------- decisión del ajustador

  async function decidir(estadoNuevo) {
    if (!estado.seleccion) return;
    const justificacion = $("justificacion").value.trim();
    const error = $("errorDecision");
    error.hidden = true;
    try {
      await pedir(`/api/claims/${estado.seleccion}/status`, {
        method: "PATCH",
        body: JSON.stringify({ estado: estadoNuevo, justificacion }),
      });
      brindis(`Siniestro marcado como ${ESTADO_ES[estadoNuevo].toLowerCase()}.`);
      await abrirExpediente(estado.seleccion);
      await cargarCola();
    } catch (err) {
      mostrarError(error, err);
    }
  }

  // --------------------------------------------------------------- arranque

  conectarAviso();
  window.G.conectarSesion();
  $("recargar").addEventListener("click", cargarCola);
  $("verResueltos").addEventListener("click", () => {
    estado.incluirResueltos = !estado.incluirResueltos;
    $("verResueltos").setAttribute("aria-pressed", String(estado.incluirResueltos));
    $("verResueltos").textContent = estado.incluirResueltos ? "Solo pendientes" : "Ver resueltos";
    cargarCola();
  });
  $("aprobar").addEventListener("click", () => confirmar(true));
  $("rechazar").addEventListener("click", () => confirmar(false));

  document.querySelectorAll(".filtros button").forEach((boton) => {
    boton.addEventListener("click", () => {
      estado.filtro = boton.dataset.urgencia;
      document.querySelectorAll(".filtros button").forEach((b) => b.setAttribute("aria-pressed", String(b === boton)));
      cargarCola();
    });
  });

  document.querySelectorAll(".decision-acciones button").forEach((boton) => {
    boton.addEventListener("click", () => decidir(boton.dataset.estado));
  });

  cargarCola();
  // Refresco periódico de la cola, salvo mientras se imprime una traza en vivo.
  setInterval(() => { if (!estado.fuente) cargarCola(); }, 15000);
})();
