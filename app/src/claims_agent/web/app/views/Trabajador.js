// Vista del TRABAJADOR (ajustador): cola de siniestros, expediente y decisión, con avisos en vivo.
//
//   cola (izquierda)  ──selecciona──▶  expediente (derecha; en móvil ocupa toda la pantalla)
//   La cola se refresca sola cuando el servidor avisa (alEvento) y, si se corta la conexión en
//   vivo, cada 15 s como respaldo.
import { html, useState, useEffect, useMemo, useCallback, useRef } from "../lib.js";
import { Icono } from "../icons.js";
import { Boton, Urgencia, Estado, Aviso, Esqueleto, Vacio, useAhora } from "../ui.js";
import { TiraRegistro } from "../tira.js";
import { navegar, useRuta } from "../router.js";
import { pedir, mensajeDeError } from "../api.js";
import { alEvento, conexion, criticos } from "../live.js";
import { toast } from "../ui.js";
import {
  ACCION_ES, CORRIDA_ES, ESTADO_ES, SEVERIDAD_ES, TIPO_ES, TIPO_ICONO, fmtFechaHora, fmtHora, fmtRelativo, fmtNum,
} from "../format.js";

const ABIERTOS = ["PENDING", "IN_REVIEW"];
const FILTROS = [
  { id: "", texto: "Todas" },
  { id: "CRITICAL", texto: "Críticas" },
  { id: "HIGH", texto: "Altas" },
  { id: "LOW", texto: "Leves" },
];

const coincide = (c, q) => {
  if (!q) return true;
  const t = q.toLowerCase();
  return (c.customer_id || "").toLowerCase().includes(t) || (c.description || "").toLowerCase().includes(t)
    || (TIPO_ES[c.claim_type] || "").toLowerCase().includes(t);
};

// --------------------------------------------------------------------------- cola
function Ficha({ c, activa, nueva, ahora, alAbrir }) {
  const urgencia = c.urgency_level || "NONE";
  return html`<button type="button" class=${`ficha ficha--${urgencia} ${nueva ? "ficha--nueva" : ""} ${!c.urgency_level ? "ficha--analizando" : ""}`}
    aria-current=${activa ? "true" : "false"} onClick=${() => alAbrir(c.id)}>
    <span class="ficha__lomo" aria-hidden="true"></span>
    <span class="ficha__cuerpo">
      <span class="ficha__fila">
        <span class="ficha__cliente">${c.customer_id}</span>
        <span class="ficha__tipo"><${Icono} n=${TIPO_ICONO[c.claim_type] || "carpeta"} tam="sm" />${TIPO_ES[c.claim_type] || c.claim_type}</span>
        <span class="ficha__hora">${fmtRelativo(c.received_at, ahora)}</span>
      </span>
      <span class="ficha__relato">${c.description}</span>
      <span class="ficha__pie">
        ${c.urgency_level ? html`<${Urgencia} nivel=${c.urgency_level} />` : html`<span class="insignia insignia--info"><span class="spinner" aria-hidden="true"></span>Clasificando…</span>`}
        <${Estado} valor=${c.status} />
        ${c.inconsistencies_flag ? html`<span class="insignia insignia--HIGH"><${Icono} n="alerta" />Inconsistencia</span>` : null}
        ${c.assigned_adjuster ? html`<span class="insignia">→ ${c.assigned_adjuster}</span>` : null}
      </span>
    </span>
  </button>`;
}

function Cola({ claims, error, filtro, setFiltro, q, setQ, resueltos, setResueltos, nuevos, seleccion, alAbrir, alRefrescar }) {
  const ahora = useAhora(30000);
  const vivo = conexion.usar();
  const conteo = (nivel) => (claims || []).filter((c) => !nivel || c.urgency_level === nivel).length;
  const visibles = useMemo(
    () => (claims || []).filter((c) => (!filtro || c.urgency_level === filtro) && coincide(c, q)),
    [claims, filtro, q],
  );

  return html`<section class="lista-panel" aria-label="Cola de siniestros">
    <div class="lista-panel__cabecera">
      <div class="buscador">
        <${Icono} n="buscar" tam="sm" />
        <input class="input" type="search" placeholder="Buscar por cliente o relato" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Buscar siniestros" />
      </div>
      <div class="chips" role="group" aria-label="Filtrar por urgencia">
        ${FILTROS.map((f) => html`<button type="button" class="chip" key=${f.id} aria-pressed=${filtro === f.id} onClick=${() => setFiltro(f.id)}>
          ${f.texto}<span class="chip__n">${claims ? conteo(f.id) : "·"}</span></button>`)}
      </div>
      <div class="lista-panel__fila">
        <label class="interruptor">
          <span>Incluir resueltos</span>
          <input type="checkbox" checked=${resueltos} onChange=${(e) => setResueltos(e.target.checked)} />
        </label>
        <${Boton} tam="sm" variante="fantasma" icono="actualizar" onClick=${alRefrescar} aria-label="Actualizar la cola">${vivo === "conectado" ? "" : "Actualizar"}<//>
      </div>
    </div>
    <div class="lista" aria-live="polite">
      ${error ? html`<${Aviso} tipo="error">No se pudo cargar la cola: ${error}<//>` : null}
      ${!claims && !error ? [1, 2, 3, 4].map((i) => html`<${Esqueleto} key=${i} tipo="ficha" />`) : null}
      ${claims && !visibles.length ? html`<${Vacio} icono=${q || filtro ? "buscar" : "check"} titulo=${q || filtro ? "Sin resultados" : "Cola al día"}>
        ${q || filtro ? "Ningún siniestro coincide con ese filtro." : "No hay siniestros pendientes. Cuando un cliente reporte uno, aparecerá aquí al instante."}<//>` : null}
      ${visibles.map((c) => html`<${Ficha} key=${c.id} c=${c} activa=${seleccion === c.id} nueva=${!!nuevos[c.id]} ahora=${ahora} alAbrir=${alAbrir} />`)}
    </div>
  </section>`;
}

// --------------------------------------------------------------------------- expediente
function Reloj({ claim }) {
  const ahora = useAhora(1000);
  if (!claim.sla_minutes || !ABIERTOS.includes(claim.status)) return null;
  const limite = new Date(claim.received_at).getTime() + claim.sla_minutes * 60000;
  const resta = limite - ahora;
  const abs = Math.abs(resta);
  const mm = String(Math.floor(abs / 60000)).padStart(2, "0");
  const ss = String(Math.floor((abs % 60000) / 1000)).padStart(2, "0");
  const clase = resta < 0 ? "reloj--vencido" : resta < claim.sla_minutes * 15000 ? "reloj--apretado" : "";
  return html`<div class=${`reloj ${clase}`} role="timer" aria-label="Tiempo para contactar al cliente">
    <b>${resta < 0 ? "-" : ""}${mm}:${ss}</b><em>${resta < 0 ? "SLA vencido" : "para contacto"}</em>
  </div>`;
}

function Expediente({ id, alCambiar, alCerrar }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);
  const [pasos, setPasos] = useState([]);
  const [enVivo, setEnVivo] = useState(false);
  const [justificacion, setJustificacion] = useState("");
  const [errorDecision, setErrorDecision] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(async () => {
    const d = await pedir(`/api/claims/${id}`);
    setDatos(d);
    setPasos(d.trazas || []);
    return d;
  }, [id]);

  useEffect(() => {
    setDatos(null); setError(null); setJustificacion(""); setErrorDecision(null);
    cargar().catch((e) => setError(mensajeDeError(e)));
  }, [id]);

  // Si el servidor avisa de un cambio en ESTE siniestro (triaje listo, aprobación, estado), se recarga.
  useEffect(() => alEvento((ev) => {
    if (ev.tipo === "reconectado" || (ev.claim_id === id && ev.tipo !== "nuevo")) cargar().catch(() => {});
  }), [id]);

  // Si el agente está trabajando, se sigue su traza paso a paso.
  const corridaId = datos && datos.corrida ? datos.corrida.id : null;
  const estadoCorrida = datos && datos.corrida ? datos.corrida.status : null;
  useEffect(() => {
    if (estadoCorrida !== "RUNNING") { setEnVivo(false); return undefined; }
    setEnVivo(true);
    const fuente = new EventSource(`/api/runs/${corridaId}/stream`);
    const vistos = new Set((datos.trazas || []).map((p) => p.idx));
    fuente.addEventListener("paso", (e) => {
      const p = JSON.parse(e.data);
      if (vistos.has(p.idx)) return;
      vistos.add(p.idx);
      setPasos((prev) => [...prev, p]);
    });
    fuente.addEventListener("fin", () => { fuente.close(); setEnVivo(false); cargar().catch(() => {}); alCambiar(); });
    fuente.onerror = () => { fuente.close(); setEnVivo(false); };
    return () => fuente.close();
  }, [corridaId, estadoCorrida]);

  if (error) return html`<div class="detalle"><${Boton} class="detalle__volver" variante="fantasma" icono="izquierda" onClick=${alCerrar}>Volver<//>
    <${Aviso} tipo="error">${error}<//></div>`;
  if (!datos) return html`<div class="detalle" aria-busy="true"><${Esqueleto} tipo="bloque" /><${Esqueleto} /><${Esqueleto} corta=${true} /><${Esqueleto} tipo="bloque" /></div>`;

  const c = datos.siniestro;
  const corrida = datos.corrida;
  const cerrado = !ABIERTOS.includes(c.status);
  const urgencia = c.urgency_level || "NONE";
  const esperando = corrida && corrida.status === "AWAITING_CONFIRMATION";
  const pendiente = esperando ? [...pasos].reverse().find((p) => (p.kind || p.tipo) === "confirmation") : null;
  const args = (pendiente && (pendiente.input || pendiente.entrada)) || {};
  const a = c.image_assessment;

  const confirmar = async (aprobado) => {
    setOcupado(true);
    try {
      await pedir(`/api/runs/${corrida.id}/confirm`, { method: "POST", body: JSON.stringify({ aprobado }) });
      toast(aprobado ? "Asignación aprobada" : "Acción rechazada", {
        texto: aprobado ? "El agente continúa con el resumen." : "El expediente no se modificó.", tipo: "exito", duracion: 4000,
      });
      await cargar();
      alCambiar();
    } catch (e) {
      toast("No se pudo registrar la decisión", { texto: mensajeDeError(e), tipo: "critico" });
    } finally { setOcupado(false); }
  };

  const decidir = async (estado) => {
    setErrorDecision(null);
    setOcupado(true);
    try {
      await pedir(`/api/claims/${id}/status`, { method: "PATCH", body: JSON.stringify({ estado, justificacion: justificacion.trim() }) });
      toast(`Siniestro ${ESTADO_ES[estado].toLowerCase()}`, { tipo: "exito", duracion: 3500 });
      setJustificacion("");
      await cargar();
      alCambiar();
    } catch (e) {
      setErrorDecision(mensajeDeError(e));
    } finally { setOcupado(false); }
  };

  return html`<article class="detalle">
    <${Boton} class="detalle__volver" variante="fantasma" icono="izquierda" onClick=${alCerrar}>Volver a la cola<//>

    <header class="detalle__cabecera">
      <span class=${`etiqueta-urgencia etiqueta-urgencia--${urgencia}`}>
        ${urgencia === "CRITICAL" ? html`<${Icono} n="alerta" tam="sm" />` : null}${c.urgency_level ? `Urgencia ${(ESTADO_URG[urgencia] || urgencia).toLowerCase()}` : "Clasificando…"}
      </span>
      <div class="detalle__titulo">
        <h2>${c.customer_id} · ${TIPO_ES[c.claim_type] || c.claim_type}</h2>
        <div class="detalle__meta">
          <${Estado} valor=${c.status} />
          <span>Recibido ${fmtFechaHora(c.received_at)}</span>
          ${c.recommended_action ? html`<span>${ACCION_ES[c.recommended_action] || c.recommended_action}</span>` : null}
          ${c.assigned_adjuster ? html`<span>Ajustador: ${c.assigned_adjuster}</span>` : null}
        </div>
      </div>
      <${Reloj} claim=${c} />
    </header>

    ${corrida && corrida.degraded ? html`<${Aviso} tipo="alto"><strong>Modo determinista.</strong> Este triaje corrió con el motor de reglas porque el modelo no respondió.<//>` : null}

    ${esperando ? html`<section class="confirmacion" aria-labelledby="t-confirma">
      <h3 id="t-confirma"><${Icono} n="escudo" />El agente pide tu autorización</h3>
      <p>Asignar el siniestro a <strong>${args.ajustador || "?"}</strong> y pasarlo a «En revisión».<br /><span class="campo__ayuda">Motivo: ${args.motivo || "sin motivo"}</span></p>
      <div class="confirmacion__acciones">
        <${Boton} variante="primario" icono="check" cargando=${ocupado} onClick=${() => confirmar(true)}>Aprobar asignación<//>
        <${Boton} disabled=${ocupado} onClick=${() => confirmar(false)}>Rechazar<//>
      </div>
      <p class="confirmacion__nota">Ninguna acción que modifique el expediente se ejecuta sin esta aprobación.</p>
    </section>` : null}

    <section><div class="seccion-etiqueta">Relato del cliente</div><blockquote class="relato">${c.description}</blockquote></section>

    ${c.has_image ? html`<section>
      <div class="seccion-etiqueta"><${Icono} n="camara" tam="sm" />Foto adjunta</div>
      <div class="foto-adjunta">
        <a href=${`/api/claims/${c.id}/image`} target="_blank" rel="noopener"><img src=${`/api/claims/${c.id}/image`} alt="Foto del siniestro adjuntada por el cliente" loading="lazy" /></a>
        <p>${a ? html`<strong>Severidad ${SEVERIDAD_ES[a.severidad] || a.severidad}</strong>${a.coincide_con_relato === false ? " · no coincide con el relato" : ""}${a.descripcion ? `. ${a.descripcion}` : ""}`
          : "El agente todavía no analizó esta foto."}</p>
      </div>
    </section>` : null}

    ${c.agent_summary ? html`<section class="resumen-agente tarjeta"><div class="seccion-etiqueta">Resumen para el ajustador</div><p>${c.agent_summary}</p></section>` : null}

    ${!cerrado ? html`<section class="tarjeta decision" aria-labelledby="t-decision">
      <div class="seccion-etiqueta" id="t-decision">Decisión del ajustador</div>
      <div class="campo">
        <textarea class="textarea" rows="3" maxlength="2000" value=${justificacion} onInput=${(e) => setJustificacion(e.target.value)}
          placeholder="Justificación (obligatoria para aprobar o rechazar)" aria-label="Justificación de la decisión"></textarea>
      </div>
      ${errorDecision ? html`<${Aviso} tipo="error">${errorDecision}<//>` : null}
      <div class="decision__acciones">
        <${Boton} disabled=${ocupado} onClick=${() => decidir("IN_REVIEW")}>Marcar en revisión<//>
        <${Boton} variante="peligro" disabled=${ocupado} onClick=${() => decidir("REJECTED")}>Rechazar<//>
        <${Boton} variante="exito" icono="check" disabled=${ocupado} onClick=${() => decidir("APPROVED")}>Aprobar<//>
      </div>
    </section>` : null}

    ${datos.historial && datos.historial.length ? html`<section class="tarjeta">
      <div class="seccion-etiqueta"><${Icono} n="reloj" tam="sm" />Historial</div>
      <ol class="historial">
        ${datos.historial.map((h, i) => html`<li class="historial__item" key=${i}>
          <strong>${ESTADO_ES[h.to_status] || h.to_status}</strong> · ${h.changed_by}
          <small>${fmtFechaHora(h.changed_at)}${h.justification ? ` — ${h.justification}` : ""}</small></li>`)}
      </ol>
    </section>` : null}

    ${corrida ? html`<div>
      <${TiraRegistro} pasos=${pasos} enVivo=${enVivo} />
      <p class="campo__ayuda">Agente ${CORRIDA_ES[corrida.status] || corrida.status}${corrida.iterations ? ` · ${corrida.iterations} iter.` : ""}${corrida.tokens_in ? ` · ${fmtNum(corrida.tokens_in + corrida.tokens_out)} tokens` : ""}</p>
    </div>` : null}
  </article>`;
}
const ESTADO_URG = { CRITICAL: "Crítica", HIGH: "Alta", LOW: "Leve" };

// --------------------------------------------------------------------------- vista
export function Trabajador() {
  const { busqueda } = useRuta();
  const caso = new URLSearchParams(busqueda).get("caso");
  const [claims, setClaims] = useState(null);
  const [error, setError] = useState(null);
  const [filtro, setFiltro] = useState("");
  const [resueltos, setResueltos] = useState(false);
  const [q, setQ] = useState("");
  const [nuevos, setNuevos] = useState({});
  const refresco = useRef();

  const cargar = useCallback(async () => {
    try {
      const p = new URLSearchParams({ limite: "200" });
      if (!resueltos) ABIERTOS.forEach((s) => p.append("estado", s));
      const d = await pedir(`/api/claims?${p}`);
      setClaims(d.items || []);
      setError(null);
    } catch (e) { setError(mensajeDeError(e)); }
  }, [resueltos]);

  useEffect(() => { setClaims(null); cargar(); }, [cargar]);

  // Avisos en vivo del servidor: la cola se refresca sola (con un pequeño margen para agrupar ráfagas).
  useEffect(() => alEvento((ev) => {
    if (ev.tipo === "nuevo") {
      setNuevos((n) => ({ ...n, [ev.claim_id]: true }));
      setTimeout(() => setNuevos((n) => { const { [ev.claim_id]: _, ...resto } = n; return resto; }), 4500);
    }
    clearTimeout(refresco.current);
    refresco.current = setTimeout(cargar, 250);
  }), [cargar]);

  // Respaldo: si la conexión en vivo está caída, se consulta cada 15 s.
  useEffect(() => {
    const i = setInterval(() => { if (conexion.get() !== "conectado") cargar(); }, 15000);
    return () => clearInterval(i);
  }, [cargar]);

  // El contador de críticos de la barra lateral.
  useEffect(() => {
    criticos.set((claims || []).filter((c) => c.urgency_level === "CRITICAL" && ABIERTOS.includes(c.status)).length);
  }, [claims]);

  const abrir = (id) => navegar(`/trabajador?caso=${id}`);
  const cerrar = () => navegar("/trabajador");

  return html`<div class="maestro-detalle" data-vista=${caso ? "detalle" : "lista"} id="contenido">
    <${Cola} claims=${claims} error=${error} filtro=${filtro} setFiltro=${setFiltro} q=${q} setQ=${setQ}
      resueltos=${resueltos} setResueltos=${setResueltos} nuevos=${nuevos} seleccion=${caso} alAbrir=${abrir} alRefrescar=${cargar} />
    <section class="detalle-panel" aria-label="Expediente">
      ${caso ? html`<${Expediente} key=${caso} id=${caso} alCambiar=${cargar} alCerrar=${cerrar} />`
        : html`<${Vacio} icono="carpeta" titulo="Selecciona un siniestro">Elige uno de la cola para ver qué hizo el agente paso a paso y tomar la decisión.<//>`}
    </section>
  </div>`;
}
