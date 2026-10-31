/* =============================================================================
   Guardia de triaje — JavaScript sin dependencias ni build.

   Tres responsabilidades:
     1. Cola: listar siniestros ordenados por urgencia y abrir un expediente.
     2. Tira: imprimir en vivo los pasos del agente (EventSource / SSE).
     3. Confirmación: aprobar o rechazar la acción que el agente dejó pendiente.

   Seguridad: todo lo que viene del servidor se inserta con textContent, nunca con
   innerHTML. Los relatos los escribe un cliente y pueden traer cualquier cosa.
   ============================================================================= */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const URGENCIA_ES = { CRITICAL: "Crítico", HIGH: "Alto", LOW: "Leve" };
  const ESTADO_ES = { PENDING: "Pendiente", IN_REVIEW: "En revisión", APPROVED: "Aprobado", REJECTED: "Rechazado" };
  const TIPO_ES = { AUTO: "Auto", MEDICAL: "Médico", HOME: "Hogar" };
  const CORRIDA_ES = {
    RUNNING: "en curso", COMPLETED: "completada", FAILED: "fallida",
    LIMIT_REACHED: "detenida por límite", AWAITING_CONFIRMATION: "esperando aprobación",
  };
  const GLIFOS = {
    llm_call: "◆", tool_call: "▸", confirmation: "⏸", error: "✕",
    limit: "⊘", fallback: "⇄", final: "■",
  };
  const TITULO_PASO = {
    llm_call: (p) => `El modelo decide (${p.name})`,
    tool_call: (p) => `Herramienta ${p.name}`,
    confirmation: (p) => `Pausa: ${p.name} requiere aprobación`,
    error: (p) => `Error en ${p.name || "el proceso"}`,
    limit: (p) => `Límite alcanzado: ${p.name}`,
    fallback: () => "Cambio a motor determinista",
    final: () => "Resumen final",
  };

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

  // --------------------------------------------------------------- utilidades

  const crear = (tag, props = {}, ...hijos) => {
    const nodo = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") nodo.className = v;
      else if (k === "text") nodo.textContent = v;
      else if (k.startsWith("on")) nodo.addEventListener(k.slice(2), v);
      else nodo.setAttribute(k, v === true ? "" : v);
    }
    for (const hijo of hijos.flat()) {
      if (hijo === null || hijo === undefined || hijo === false) continue;
      nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
    }
    return nodo;
  };

  async function pedir(url, opciones = {}) {
    // FormData (reportar con imagen) necesita que el navegador ponga su propio
    // Content-Type con el boundary del multipart; si lo fijamos nosotros, se rompe.
    const esFormData = opciones.body instanceof FormData;
    const respuesta = await fetch(url, {
      headers: { Accept: "application/json", ...(opciones.body && !esFormData ? { "Content-Type": "application/json" } : {}) },
      ...opciones,
    });
    const tipo = respuesta.headers.get("Content-Type") || "";
    const cuerpo = tipo.includes("json") ? await respuesta.json().catch(() => null) : null;
    if (!respuesta.ok) {
      const error = new Error((cuerpo && (cuerpo.detail || cuerpo.title)) || `Error ${respuesta.status}`);
      error.status = respuesta.status;
      error.problema = cuerpo || {};
      throw error;
    }
    return cuerpo;
  }

  function brindis(mensaje) {
    const nodo = $("brindis");
    nodo.textContent = mensaje;
    nodo.hidden = false;
    clearTimeout(brindis._t);
    brindis._t = setTimeout(() => { nodo.hidden = true; }, 3200);
  }

  function mostrarError(contenedor, error) {
    contenedor.textContent = "";
    contenedor.append(error.message || "No se pudo completar la operación.");
    const campos = (error.problema && error.problema.errors) || [];
    if (campos.length) {
      contenedor.append(crear("ul", {}, campos.map((c) => crear("li", { text: `${c.campo}: ${c.mensaje}` }))));
    }
    contenedor.hidden = false;
  }

  const fmtHora = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  const fmtRelativo = (iso) => {
    if (!iso) return "—";
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (min < 1) return "hace instantes";
    if (min < 60) return `hace ${min} min`;
    if (min < 1440) return `hace ${Math.round(min / 60)} h`;
    return new Date(iso).toLocaleDateString("es-CO", { day: "numeric", month: "short" });
  };

  // --------------------------------------------------------------- barra de instrumentos

  async function cargarConfig() {
    try {
      const c = await pedir("/api/config");
      $("i-motor").textContent = c.proveedor === "offline" ? "reglas (sin modelo)" : `${c.proveedor} · ${c.modelo}`;
      $("i-iter").textContent = `máx ${c.limites.max_iteraciones}`;
      $("i-tiempo").textContent = `máx ${Math.round(c.limites.timeout_segundos)} s`;
      $("i-tokens").textContent = `máx ${c.limites.max_tokens.toLocaleString("es-CO")}`;
      $("i-confirm").textContent = c.limites.confirmacion_humana ? "obligatoria" : "desactivada";
      if (c.proveedor === "offline") {
        avisarDegradado("El servicio está configurado sin modelo de lenguaje: el triaje corre solo con reglas.");
      }
    } catch (_) {
      $("i-motor").textContent = "sin conexión";
    }
  }

  function avisarDegradado(detalle) {
    $("avisoDetalle").textContent = detalle;
    $("avisoDegradado").hidden = false;
  }

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
      : "No hay siniestros pendientes. Reporta uno abajo y el agente lo tría en vivo.";

    for (const c of estado.claims) {
      const urgencia = c.urgency_level || "NONE";
      const ficha = crear("li", {},
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
            crear("span", {
              class: `etiqueta-urgencia u-${urgencia}`,
              text: URGENCIA_ES[urgencia] || "sin evaluar",
            }),
          ),
        ),
      );
      lista.append(ficha);
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
    pintarPasos(pasos, false);
    pintarPendiente(corrida, pasos);
    $("decision").hidden = ["APPROVED", "REJECTED"].includes(claim.status);
    $("errorDecision").hidden = true;
    $("justificacion").value = "";

    if (corrida && corrida.degraded) {
      avisarDegradado("Este triaje corrió en modo determinista porque el modelo no respondió.");
    }
    if (corrida && corrida.status === "RUNNING") seguirEnVivo(corrida.id);
  }

  const SEVERIDAD_ES = { LEVE: "leve", MODERADO: "moderado", SEVERO: "severo", INDETERMINADO: "indeterminado" };

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

  const accionEs = (a) => ({
    ASSIGN_AGENT_IMMEDIATELY: "asignar agente ya",
    HUMAN_VALIDATION_2H: "validación humana ≤ 2 h",
    AUTO_APPROVE: "aprobación automática",
    FAST_TRACK_REVIEW: "revisión rápida",
    MANUAL_REVIEW: "revisión manual",
  }[a] || a);

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

  // --------------------------------------------------------------- tira de registro

  function pintarPasos(pasos, animar) {
    const lista = $("pasos");
    lista.textContent = "";
    estado.primerMomento = pasos.length ? new Date(pasos[0].momento || pasos[0].created_at).getTime() : Date.now();
    for (const paso of pasos) agregarPaso(paso, animar);
    actualizarTotales(pasos);
  }

  function agregarPaso(paso, animar = true) {
    const lista = $("pasos");
    const tipo = paso.tipo || paso.kind;
    const nombre = paso.nombre || paso.name;
    const salida = paso.salida || paso.output || {};
    const entrada = paso.entrada || paso.input || {};
    const latencia = paso.latencia_ms ?? paso.latency_ms ?? 0;
    const tIn = paso.tokens_entrada ?? paso.tokens_in ?? 0;
    const tOut = paso.tokens_salida ?? paso.tokens_out ?? 0;
    const momento = new Date(paso.momento || paso.created_at || Date.now()).getTime();
    const transcurrido = Math.max(0, (momento - estado.primerMomento) / 1000);

    const titulo = (TITULO_PASO[tipo] || (() => tipo))({ name: nombre });
    const sub = subtitulo(tipo, nombre, entrada, salida, paso.detalle || paso.detail);

    const cifras = [];
    if (latencia) cifras.push(`${latencia} ms`);
    if (tIn || tOut) cifras.push(`${tIn}→${tOut} tok`);

    const nodo = crear("li", { class: `paso paso-${tipo}${animar ? " paso-entra" : ""}` },
      crear("span", { class: "t", text: `+${transcurrido.toFixed(1)}s` }),
      crear("span", { class: "glifo", "aria-hidden": "true", text: GLIFOS[tipo] || "·" }),
      crear("div", { class: "cuerpo" },
        crear("div", { class: "titulo", text: titulo }),
        sub ? crear("div", { class: "sub", text: sub }) : null,
        detalleAmpliable(tipo, entrada, salida),
      ),
      crear("div", { class: "cifras", text: cifras.join("\n") }),
    );
    lista.append(nodo);
  }

  function subtitulo(tipo, nombre, entrada, salida, detalle) {
    if (tipo === "llm_call") {
      const herramientas = (salida.herramientas || []).map((h) => h.nombre);
      if (herramientas.length) return `pide ejecutar: ${herramientas.join(", ")}`;
      return salida.texto ? "responde con el resumen final" : (detalle || "");
    }
    if (tipo === "tool_call") {
      if (salida.error) return `error: ${salida.error}`;
      if (nombre === "clasificar_urgencia") {
        return `urgencia ${salida.urgencia} · puntuación ${salida.puntuacion} · ${salida.accion_es || ""}`;
      }
      if (nombre === "consultar_poliza") {
        return salida.encontrada
          ? `póliza ${salida.estado}, producto ${salida.producto}, deducible ${fmtPesos(salida.deducible)}`
          : "no existe póliza para ese cliente";
      }
      if (nombre === "analizar_imagen_dano") {
        if (!salida.tiene_imagen) return salida.mensaje || "no hay imagen adjunta";
        return `daño ${salida.severidad}` + (salida.coincide_con_relato === false ? " · no coincide con el relato" : "");
      }
      if (nombre === "buscar_siniestros_similares") {
        return `${salida.total || 0} caso(s) parecido(s) por texto completo`;
      }
      if (nombre === "asignar_ajustador") {
        return salida.asignado ? `asignado a ${salida.ajustador}` : (salida.motivo || "no ejecutada");
      }
      return detalle || "";
    }
    if (tipo === "final") return salida.resumen || detalle || "";
    return detalle || "";
  }

  function detalleAmpliable(tipo, entrada, salida) {
    if (tipo !== "tool_call" && tipo !== "llm_call") return null;
    const contenido = JSON.stringify({ entrada, salida }, null, 1);
    if (contenido.length < 90) return null;
    const pre = crear("pre", { class: "detalle-json", text: contenido });
    pre.hidden = true;
    const boton = crear("button", {
      class: "ejemplos-toggle", type: "button",
      style: "border:0;background:none;padding:0;margin-top:4px;font-size:12px;color:#0E6B72;cursor:pointer",
      text: "ver datos",
      onclick: () => {
        pre.hidden = !pre.hidden;
        boton.textContent = pre.hidden ? "ver datos" : "ocultar datos";
      },
    });
    return crear("div", {}, boton, pre);
  }

  const fmtPesos = (n) => (n === null || n === undefined ? "—" :
    new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 }).format(n));

  function actualizarTotales(pasos) {
    const tokens = pasos.reduce((a, p) => a + (p.tokens_entrada ?? p.tokens_in ?? 0) + (p.tokens_salida ?? p.tokens_out ?? 0), 0);
    const ms = pasos.reduce((a, p) => a + (p.latencia_ms ?? p.latency_ms ?? 0), 0);
    $("tiraTotales").textContent = pasos.length
      ? `${pasos.length} pasos · ${(ms / 1000).toFixed(1)} s · ${tokens} tokens`
      : "";
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
      if (vistos.size === 1) estado.primerMomento = new Date(paso.created_at || Date.now()).getTime();
      agregarPaso(paso);
      if ((paso.kind || paso.tipo) === "fallback") {
        avisarDegradado("El modelo falló durante este triaje; el agente continuó con reglas deterministas.");
      }
    });

    fuente.addEventListener("fin", async (evento) => {
      cerrarStream();
      const corrida = JSON.parse(evento.data);
      pintarEstadoCorrida(corrida);
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
        body: JSON.stringify({ aprobado, por: "ajustador" }),
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

  // --------------------------------------------------------------- reporte

  async function reportar(evento) {
    evento.preventDefault();
    const form = evento.target;
    const error = $("errorFormulario");
    error.hidden = true;
    const formData = new FormData(form);
    formData.set("incident_timestamp", new Date(Date.now() - 20 * 60000).toISOString());
    const customerId = formData.get("customer_id");
    const claimType = formData.get("claim_type");
    const description = formData.get("description");

    $("enviar").disabled = true;
    $("enviar").textContent = "Enviando…";
    try {
      const respuesta = await pedir("/api/claims", { method: "POST", body: formData });
      estado.seleccion = respuesta.claim_id;
      await cargarCola();
      $("sinSeleccion").hidden = true;
      $("detalle").hidden = false;
      $("pasos").textContent = "";
      $("tiraTotales").textContent = "";
      $("resumenAgente").hidden = true;
      $("confirmacion").hidden = true;
      $("imagenAdjunta").hidden = true;
      $("detUrgencia").className = "etiqueta-urgencia u-NONE";
      $("detUrgencia").textContent = "clasificando";
      $("detCliente").textContent = `${customerId} · ${TIPO_ES[claimType]}`;
      $("detMeta").textContent = "recién reportado";
      $("detRelato").textContent = description;
      $("detReloj").hidden = true;
      seguirEnVivo(respuesta.run_id);
      brindis("Reporte recibido. El agente está trabajando.");
      form.imagen.value = "";
      $("previsualizacion").hidden = true;
    } catch (err) {
      mostrarError(error, err);
    } finally {
      $("enviar").disabled = false;
      $("enviar").textContent = "Reportar y triar";
    }
  }

  // --------------------------------------------------------------- arranque

  function conectarEventos() {
    $("formulario").addEventListener("submit", reportar);
    $("recargar").addEventListener("click", cargarCola);
    $("verResueltos").addEventListener("click", () => {
      estado.incluirResueltos = !estado.incluirResueltos;
      $("verResueltos").setAttribute("aria-pressed", String(estado.incluirResueltos));
      $("verResueltos").textContent = estado.incluirResueltos ? "Solo pendientes" : "Ver resueltos";
      cargarCola();
    });
    $("cerrarAviso").addEventListener("click", () => { $("avisoDegradado").hidden = true; });
    $("imagenInput").addEventListener("change", () => {
      const archivo = $("imagenInput").files[0];
      const previsualizacion = $("previsualizacion");
      if (!archivo) { previsualizacion.hidden = true; return; }
      previsualizacion.src = URL.createObjectURL(archivo);
      previsualizacion.hidden = false;
    });
    $("aprobar").addEventListener("click", () => confirmar(true));
    $("rechazar").addEventListener("click", () => confirmar(false));

    document.querySelectorAll(".filtros button").forEach((boton) => {
      boton.addEventListener("click", () => {
        estado.filtro = boton.dataset.urgencia;
        document.querySelectorAll(".filtros button").forEach((b) =>
          b.setAttribute("aria-pressed", String(b === boton)));
        cargarCola();
      });
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

    document.querySelectorAll(".decision-acciones button").forEach((boton) => {
      boton.addEventListener("click", () => decidir(boton.dataset.estado));
    });
  }

  conectarEventos();
  cargarConfig();
  cargarCola();
  setInterval(() => { if (!estado.fuente) cargarCola(); }, 15000);
})();
