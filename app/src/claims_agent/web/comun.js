/* =============================================================================
   Guardia de triaje — utilidades compartidas por las tres vistas
   (cliente, trabajador y TI). JavaScript sin dependencias ni build.

   Seguridad: todo lo que viene del servidor se inserta con textContent, nunca con
   innerHTML. Los relatos los escribe un cliente y pueden traer cualquier cosa.
   ============================================================================= */
window.G = (() => {
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
    if (respuesta.status === 401 && ["/trabajador", "/ti"].includes(location.pathname)) {
      // La sesión venció (o nunca existió): de vuelta al ingreso, y luego a esta misma vista.
      location.assign(`/ingresar?next=${location.pathname}`);
    }
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
    return new Date(iso).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  const fmtFechaHora = (iso) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleString("es-CO", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  const fmtRelativo = (iso) => {
    if (!iso) return "—";
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (min < 1) return "hace instantes";
    if (min < 60) return `hace ${min} min`;
    if (min < 1440) return `hace ${Math.round(min / 60)} h`;
    return new Date(iso).toLocaleDateString("es-CO", { day: "numeric", month: "short" });
  };

  const fmtPesos = (n) => (n === null || n === undefined ? "—" :
    new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 }).format(n));

  const fmtNum = (n) => Number(n || 0).toLocaleString("es-CO");

  const accionEs = (a) => ({
    ASSIGN_AGENT_IMMEDIATELY: "asignar agente ya",
    HUMAN_VALIDATION_2H: "validación humana ≤ 2 h",
    AUTO_APPROVE: "aprobación automática",
    FAST_TRACK_REVIEW: "revisión rápida",
    MANUAL_REVIEW: "revisión manual",
  }[a] || a);

  // --------------------------------------------------------------- tira de registro
  // Cada paso del agente, impreso en orden. La usan el trabajador y TI.

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
      class: "ver-datos", type: "button", text: "ver datos",
      onclick: () => {
        pre.hidden = !pre.hidden;
        boton.textContent = pre.hidden ? "ver datos" : "ocultar datos";
      },
    });
    return crear("div", {}, boton, pre);
  }

  /** Crea una tira ligada a una lista <ol> y (opcional) a un elemento de totales. */
  function crearTira(lista, totales) {
    let primerMomento = Date.now();

    function agregar(paso, animar = true) {
      const tipo = paso.tipo || paso.kind;
      const nombre = paso.nombre || paso.name;
      const salida = paso.salida || paso.output || {};
      const entrada = paso.entrada || paso.input || {};
      const latencia = paso.latencia_ms ?? paso.latency_ms ?? 0;
      const tIn = paso.tokens_entrada ?? paso.tokens_in ?? 0;
      const tOut = paso.tokens_salida ?? paso.tokens_out ?? 0;
      const momento = new Date(paso.momento || paso.created_at || Date.now()).getTime();
      const transcurrido = Math.max(0, (momento - primerMomento) / 1000);

      const titulo = (TITULO_PASO[tipo] || (() => tipo))({ name: nombre });
      const sub = subtitulo(tipo, nombre, entrada, salida, paso.detalle || paso.detail);

      const cifras = [];
      if (latencia) cifras.push(`${latencia} ms`);
      if (tIn || tOut) cifras.push(`${tIn}→${tOut} tok`);

      lista.append(crear("li", { class: `paso paso-${tipo}${animar ? " paso-entra" : ""}` },
        crear("span", { class: "t", text: `+${transcurrido.toFixed(1)}s` }),
        crear("span", { class: "glifo", "aria-hidden": "true", text: GLIFOS[tipo] || "·" }),
        crear("div", { class: "cuerpo" },
          crear("div", { class: "titulo", text: titulo }),
          sub ? crear("div", { class: "sub", text: sub }) : null,
          detalleAmpliable(tipo, entrada, salida),
        ),
        crear("div", { class: "cifras", text: cifras.join("\n") }),
      ));
    }

    function totalizar(pasos) {
      if (!totales) return;
      const tokens = pasos.reduce((a, p) => a + (p.tokens_entrada ?? p.tokens_in ?? 0) + (p.tokens_salida ?? p.tokens_out ?? 0), 0);
      const ms = pasos.reduce((a, p) => a + (p.latencia_ms ?? p.latency_ms ?? 0), 0);
      totales.textContent = pasos.length
        ? `${pasos.length} pasos · ${(ms / 1000).toFixed(1)} s · ${tokens} tokens`
        : "";
    }

    return {
      pintar(pasos, animar = false) {
        lista.textContent = "";
        primerMomento = pasos.length ? new Date(pasos[0].momento || pasos[0].created_at).getTime() : Date.now();
        for (const paso of pasos) agregar(paso, animar);
        totalizar(pasos);
      },
      agregar,
      reiniciar(momentoInicial) {
        primerMomento = momentoInicial ?? Date.now();
      },
      vaciar() {
        lista.textContent = "";
        if (totales) totales.textContent = "";
      },
    };
  }

  // --------------------------------------------------------------- aviso de modo degradado

  function avisarDegradado(detalle) {
    const aviso = $("avisoDegradado");
    if (!aviso) return;
    $("avisoDetalle").textContent = detalle;
    aviso.hidden = false;
  }

  function conectarAviso() {
    const cerrar = $("cerrarAviso");
    if (cerrar) cerrar.addEventListener("click", () => { $("avisoDegradado").hidden = true; });
  }

  // --------------------------------------------------------------- sesión del personal

  /** Muestra quién está conectado y conecta el botón «Salir» (vistas del trabajador y de TI). */
  async function conectarSesion() {
    const salir = $("salir");
    if (!salir) return;
    try {
      const yo = await pedir("/api/auth/me");
      $("usuarioActual").textContent = `${yo.usuario} · ${yo.rol === "ti" ? "TI" : "trabajador"}`;
    } catch (_) { /* pedir() ya redirige al ingreso si la sesión no es válida */ }
    salir.addEventListener("click", async () => {
      try { await pedir("/api/auth/logout", { method: "POST" }); } catch (_) { /* se sale igual */ }
      location.assign("/ingresar");
    });
  }

  return {
    $, crear, pedir, brindis, mostrarError, conectarSesion,
    fmtHora, fmtFechaHora, fmtRelativo, fmtPesos, fmtNum, accionEs,
    URGENCIA_ES, ESTADO_ES, TIPO_ES, CORRIDA_ES,
    crearTira, avisarDegradado, conectarAviso,
  };
})();
