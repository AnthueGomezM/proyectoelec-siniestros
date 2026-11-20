/* =============================================================================
   Vista de TI: salud del servicio, límites, consumo del modelo, errores y
   corridas del agente. Se refresca sola cada 10 s.
   ============================================================================= */
(() => {
  "use strict";
  const { $, crear, pedir, brindis, fmtFechaHora, fmtNum, CORRIDA_ES, crearTira } = window.G;

  const tira = crearTira($("pasos"), $("tiraTotales"));

  const ETIQUETA_EVENTO = { error: "error", fallback: "respaldo", limit: "límite" };

  function estadoValor(id, texto, nivel) {
    const nodo = $(id);
    nodo.textContent = texto;
    nodo.className = "m-valor" + (nivel ? ` nivel-${nivel}` : "");
  }

  // --------------------------------------------------------------- salud y límites

  async function cargarSalud() {
    const sonda = async (url) => {
      try { await pedir(url); return true; } catch (_) { return false; }
    };
    const [api, bd] = await Promise.all([sonda("/api/health"), sonda("/api/ready")]);
    estadoValor("s-api", api ? "operativa" : "caída", api ? "ok" : "mal");
    estadoValor("s-bd", bd ? "responde" : "sin respuesta", bd ? "ok" : "mal");

    try {
      const c = await pedir("/api/config");
      const offline = c.proveedor === "offline";
      estadoValor("s-motor", offline ? "reglas (sin modelo)" : `${c.proveedor} · ${c.modelo}`, offline ? "aviso" : "ok");
      $("i-iter").textContent = `máx ${c.limites.max_iteraciones}`;
      $("i-tiempo").textContent = `máx ${Math.round(c.limites.timeout_segundos)} s`;
      $("i-tokens").textContent = `máx ${fmtNum(c.limites.max_tokens)}`;
      $("i-confirm").textContent = c.limites.confirmacion_humana ? "obligatoria" : "desactivada";
      $("i-fallback").textContent = c.fallback_offline ? "activado" : "desactivado";
    } catch (_) {
      estadoValor("s-motor", "sin datos", "mal");
    }
  }

  // --------------------------------------------------------------- consumo y siniestros

  async function cargarStats() {
    try {
      const s = await pedir("/api/admin/stats");
      const c = s.corridas;
      const tokens = c.tokens_in + c.tokens_out;
      $("c-corridas24").textContent = fmtNum(c.corridas_24h);
      $("c-tokens24").textContent = fmtNum(c.tokens_24h);
      $("c-tokens").textContent = fmtNum(tokens);
      $("c-latencia").textContent = c.latencia_media_ms ? `${(c.latencia_media_ms / 1000).toFixed(1)} s` : "—";
      $("c-iter").textContent = c.corridas ? (c.iteraciones / c.corridas).toFixed(1) : "—";
      $("c-total").textContent = fmtNum(c.corridas);
      $("c-fallidas").textContent = fmtNum(c.fallidas);
      $("c-limite").textContent = fmtNum(c.por_limite);
      $("c-degradadas").textContent = fmtNum(c.degradadas);
      $("c-esperando").textContent = fmtNum(c.esperando);
      estadoValor("c-fallidas", fmtNum(c.fallidas), c.fallidas ? "mal" : "");
      estadoValor("c-limite", fmtNum(c.por_limite), c.por_limite ? "aviso" : "");
      estadoValor("c-degradadas", fmtNum(c.degradadas), c.degradadas ? "aviso" : "");
      estadoValor("s-degradado", c.degradadas ? `${c.degradadas} corrida(s)` : "ninguna", c.degradadas ? "aviso" : "ok");

      for (const k of ["PENDING", "IN_REVIEW", "APPROVED", "REJECTED"]) {
        $(`n-${k}`).textContent = fmtNum(s.siniestros_por_estado[k] || 0);
      }
      const u = s.siniestros_por_urgencia;
      $("n-urg").textContent = `${u.CRITICAL || 0} / ${u.HIGH || 0} / ${u.LOW || 0}`;
    } catch (error) {
      brindis("No se pudieron cargar las cifras: " + error.message);
    }
  }

  // --------------------------------------------------------------- corridas y eventos

  async function cargarCorridas() {
    try {
      const d = await pedir("/api/admin/runs?limite=25");
      pintarEventos(d.eventos || []);
      pintarCorridas(d.corridas || []);
    } catch (error) {
      brindis("No se pudieron cargar las corridas: " + error.message);
    }
  }

  function pintarEventos(eventos) {
    const ul = $("eventos");
    ul.textContent = "";
    $("sinEventos").hidden = eventos.length > 0;
    for (const e of eventos) {
      ul.append(crear("li", { class: `evento evento-${e.kind}` },
        crear("span", { class: "evento-tipo", text: ETIQUETA_EVENTO[e.kind] || e.kind }),
        crear("span", { class: "evento-cuerpo", text: `${e.name || "—"}${e.detail ? " — " + e.detail : ""}` }),
        crear("span", { class: "evento-hora", text: fmtFechaHora(e.created_at) }),
        crear("button", { type: "button", class: "ver-datos", text: "ver traza", onclick: () => abrirTraza(e.run_id) }),
      ));
    }
  }

  function pintarCorridas(corridas) {
    const cuerpo = $("corridas");
    cuerpo.textContent = "";
    for (const r of corridas) {
      const tokens = (r.tokens_in || 0) + (r.tokens_out || 0);
      cuerpo.append(crear("tr", {},
        crear("td", { text: fmtFechaHora(r.started_at) }),
        crear("td", { class: "mono", text: r.customer_id || "—" }),
        crear("td", { class: "mono", text: `${r.provider} · ${r.model}` }),
        crear("td", {}, crear("span", {
          class: `chip chip-${r.status}`,
          text: (CORRIDA_ES[r.status] || r.status) + (r.degraded ? " · degradada" : ""),
        })),
        crear("td", { class: "num mono", text: String(r.iterations || 0) }),
        crear("td", { class: "num mono", text: fmtNum(tokens) }),
        crear("td", { class: "num mono", text: r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)} s` : "—" }),
        crear("td", {}, crear("button", { type: "button", class: "ver-datos", text: "ver traza", onclick: () => abrirTraza(r.id) })),
      ));
    }
    if (!corridas.length) {
      cuerpo.append(crear("tr", {}, crear("td", { colspan: "8", class: "vacio-tabla", text: "Todavía no hay corridas del agente." })));
    }
  }

  async function abrirTraza(runId) {
    try {
      const d = await pedir(`/api/runs/${runId}`);
      $("trazaTi").hidden = false;
      $("trazaTitulo").textContent = `Traza de la corrida ${String(runId).slice(0, 8)}…`;
      tira.pintar(d.trazas || [], false);
      $("trazaTi").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      brindis("No se pudo abrir la traza: " + error.message);
    }
  }

  // --------------------------------------------------------------- arranque

  async function refrescar() {
    await Promise.all([cargarSalud(), cargarStats(), cargarCorridas()]);
    $("actualizado").textContent = `Actualizado ${new Date().toLocaleTimeString("es-CO")} · se refresca cada 10 s`;
  }

  window.G.conectarSesion();
  $("cerrarTraza").addEventListener("click", () => { $("trazaTi").hidden = true; });
  refrescar();
  setInterval(refrescar, 10000);
})();
