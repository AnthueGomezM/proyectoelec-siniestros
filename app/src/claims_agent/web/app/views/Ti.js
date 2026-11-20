// Vista de TI: salud del servicio, límites, consumo del modelo, errores y corridas del agente.
// Se refresca sola cada 10 s.
import { html, useState, useEffect, useCallback } from "../lib.js";
import { Icono } from "../icons.js";
import { Boton, Aviso, Esqueleto, Vacio, toast } from "../ui.js";
import { TiraRegistro } from "../tira.js";
import { pedir, mensajeDeError } from "../api.js";
import { CORRIDA_ES, fmtFechaHora, fmtNum } from "../format.js";

const ETIQUETA_EVENTO = { error: "error", fallback: "respaldo", limit: "límite" };

function Metrica({ icono, etiqueta, valor, nivel = "", sub }) {
  return html`<div class="metrica">
    <span class="metrica__etiqueta">${icono ? html`<${Icono} n=${icono} tam="sm" />` : null}${etiqueta}</span>
    <b class=${`metrica__valor ${nivel ? `metrica__valor--${nivel}` : ""}`}>${valor}</b>
    ${sub ? html`<span class="metrica__sub">${sub}</span>` : null}
  </div>`;
}

async function sonda(url) {
  try { await pedir(url, { sinRedirigir: true }); return true; } catch (_) { return false; }
}

export function Ti() {
  const [salud, setSalud] = useState(null);
  const [config, setConfig] = useState(null);
  const [stats, setStats] = useState(null);
  const [corridas, setCorridas] = useState(null);
  const [eventos, setEventos] = useState([]);
  const [traza, setTraza] = useState(null);
  const [error, setError] = useState(null);
  const [actualizado, setActualizado] = useState(null);

  const cargar = useCallback(async () => {
    try {
      const [api, bd] = await Promise.all([sonda("/api/health"), sonda("/api/ready")]);
      setSalud({ api, bd });
      const [c, s, r] = await Promise.all([pedir("/api/config"), pedir("/api/admin/stats"), pedir("/api/admin/runs?limite=25")]);
      setConfig(c); setStats(s); setCorridas(r.corridas || []); setEventos(r.eventos || []);
      setError(null);
      setActualizado(new Date());
    } catch (e) { setError(mensajeDeError(e)); }
  }, []);

  useEffect(() => { cargar(); const i = setInterval(cargar, 10000); return () => clearInterval(i); }, [cargar]);

  const abrirTraza = async (runId) => {
    try {
      const d = await pedir(`/api/runs/${runId}`);
      setTraza({ id: runId, pasos: d.trazas || [] });
      setTimeout(() => document.getElementById("traza-ti")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 50);
    } catch (e) { toast("No se pudo abrir la traza", { texto: mensajeDeError(e), tipo: "critico" }); }
  };

  const cargando = !stats || !config || !salud;
  const c = stats ? stats.corridas : null;
  const tokens = c ? c.tokens_in + c.tokens_out : 0;
  const offline = config && config.proveedor === "offline";

  return html`<div class="panel-ti" id="contenido">
    ${error ? html`<${Aviso} tipo="error">No se pudieron cargar las cifras: ${error}<//>` : null}

    <section class="seccion-ti" aria-labelledby="h-salud">
      <h2 id="h-salud"><${Icono} n="servidor" tam="sm" />Salud del servicio</h2>
      ${cargando ? html`<div class="metricas">${[1, 2, 3, 4].map((i) => html`<${Esqueleto} key=${i} tipo="bloque" />`)}</div>` : html`<div class="metricas">
        <${Metrica} etiqueta="API" valor=${salud.api ? "operativa" : "caída"} nivel=${salud.api ? "ok" : "mal"} />
        <${Metrica} etiqueta="Base de datos" valor=${salud.bd ? "responde" : "sin respuesta"} nivel=${salud.bd ? "ok" : "mal"} />
        <${Metrica} etiqueta="Motor de IA" valor=${offline ? "reglas" : config.modelo} nivel=${offline ? "aviso" : "ok"} sub=${offline ? "sin modelo de lenguaje" : config.proveedor} />
        <${Metrica} etiqueta="Modo degradado" valor=${c.degradadas ? `${c.degradadas} corrida(s)` : "ninguna"} nivel=${c.degradadas ? "aviso" : "ok"} />
      </div>`}
      <p class="campo__ayuda">
        <a href="/api/docs" target="_blank" rel="noopener">Documentación de la API</a> · <a href="/api/health" target="_blank" rel="noopener">health</a> · <a href="/api/ready" target="_blank" rel="noopener">ready</a>
        ${actualizado ? ` · actualizado ${actualizado.toLocaleTimeString("es-CO")} (se refresca cada 10 s)` : ""}
      </p>
    </section>

    ${config ? html`<section class="seccion-ti" aria-labelledby="h-limites">
      <h2 id="h-limites"><${Icono} n="escudo" tam="sm" />Límites del agente</h2>
      <dl class="limites">
        <div><dt>Iteraciones</dt><dd>máx ${config.limites.max_iteraciones}</dd></div>
        <div><dt>Tiempo</dt><dd>máx ${Math.round(config.limites.timeout_segundos)} s</dd></div>
        <div><dt>Tokens por corrida</dt><dd>máx ${fmtNum(config.limites.max_tokens)}</dd></div>
        <div><dt>Confirmación humana</dt><dd>${config.limites.confirmacion_humana ? "obligatoria" : "desactivada"}</dd></div>
        <div><dt>Respaldo sin IA</dt><dd>${config.fallback_offline ? "activado" : "desactivado"}</dd></div>
      </dl>
    </section>` : null}

    ${c ? html`<section class="seccion-ti" aria-labelledby="h-consumo">
      <h2 id="h-consumo"><${Icono} n="rayo" tam="sm" />Consumo del modelo</h2>
      <div class="metricas">
        <${Metrica} etiqueta="Corridas (24 h)" valor=${fmtNum(c.corridas_24h)} />
        <${Metrica} etiqueta="Tokens (24 h)" valor=${fmtNum(c.tokens_24h)} />
        <${Metrica} etiqueta="Tokens acumulados" valor=${fmtNum(tokens)} />
        <${Metrica} etiqueta="Tokens por corrida" valor=${c.corridas ? fmtNum(Math.round(tokens / c.corridas)) : "—"} />
        <${Metrica} etiqueta="Latencia media" valor=${c.latencia_media_ms ? `${(c.latencia_media_ms / 1000).toFixed(1)} s` : "—"} />
        <${Metrica} etiqueta="Iteraciones por corrida" valor=${c.corridas ? (c.iteraciones / c.corridas).toFixed(1) : "—"} />
      </div>
      <div class="metricas">
        <${Metrica} etiqueta="Corridas totales" valor=${fmtNum(c.corridas)} />
        <${Metrica} etiqueta="Fallidas" valor=${fmtNum(c.fallidas)} nivel=${c.fallidas ? "mal" : ""} />
        <${Metrica} etiqueta="Detenidas por límite" valor=${fmtNum(c.por_limite)} nivel=${c.por_limite ? "aviso" : ""} />
        <${Metrica} etiqueta="En modo degradado" valor=${fmtNum(c.degradadas)} nivel=${c.degradadas ? "aviso" : ""} />
        <${Metrica} etiqueta="Esperando aprobación" valor=${fmtNum(c.esperando)} />
      </div>
    </section>` : null}

    ${stats ? html`<section class="seccion-ti" aria-labelledby="h-siniestros">
      <h2 id="h-siniestros"><${Icono} n="carpeta" tam="sm" />Siniestros</h2>
      <div class="metricas">
        <${Metrica} etiqueta="Pendientes" valor=${fmtNum(stats.siniestros_por_estado.PENDING)} />
        <${Metrica} etiqueta="En revisión" valor=${fmtNum(stats.siniestros_por_estado.IN_REVIEW)} />
        <${Metrica} etiqueta="Aprobados" valor=${fmtNum(stats.siniestros_por_estado.APPROVED)} />
        <${Metrica} etiqueta="Rechazados" valor=${fmtNum(stats.siniestros_por_estado.REJECTED)} />
        <${Metrica} etiqueta="Críticos / altos / leves"
          valor=${`${stats.siniestros_por_urgencia.CRITICAL || 0} / ${stats.siniestros_por_urgencia.HIGH || 0} / ${stats.siniestros_por_urgencia.LOW || 0}`} />
      </div>
    </section>` : null}

    <section class="seccion-ti" aria-labelledby="h-eventos">
      <h2 id="h-eventos"><${Icono} n="alerta" tam="sm" />Errores y eventos anómalos recientes</h2>
      ${eventos.length ? html`<ul class="eventos">
        ${eventos.map((e, i) => html`<li class="evento" key=${i}>
          <span class=${`chip-estado ${e.kind === "error" ? "chip-estado--FAILED" : "chip-estado--LIMIT_REACHED"}`}>${ETIQUETA_EVENTO[e.kind] || e.kind}</span>
          <span class="evento__cuerpo">${e.name || "—"}${e.detail ? ` — ${e.detail}` : ""}</span>
          <span class="evento__hora">${fmtFechaHora(e.created_at)}</span>
          <${Boton} tam="sm" variante="fantasma" onClick=${() => abrirTraza(e.run_id)}>Ver traza<//>
        </li>`)}
      </ul>` : html`<div class="tarjeta"><${Vacio} icono="check" titulo="Todo en orden">Sin errores, cambios a modo determinista ni límites alcanzados.<//></div>`}
    </section>

    <section class="seccion-ti" aria-labelledby="h-corridas">
      <h2 id="h-corridas"><${Icono} n="terminal" tam="sm" />Últimas corridas del agente</h2>
      <div class="tabla-envoltura">
        <table class="tabla tabla--tarjetas">
          <thead><tr><th>Inicio</th><th>Cliente</th><th>Motor</th><th>Estado</th><th class="num">Iter.</th><th class="num">Tokens</th><th class="num">Latencia</th><th></th></tr></thead>
          <tbody>
            ${!corridas ? html`<tr><td colspan="8"><${Esqueleto} /></td></tr>` : null}
            ${corridas && !corridas.length ? html`<tr><td colspan="8">Todavía no hay corridas del agente.</td></tr>` : null}
            ${(corridas || []).map((r) => html`<tr key=${r.id}>
              <td data-etiqueta="Inicio">${fmtFechaHora(r.started_at)}</td>
              <td data-etiqueta="Cliente" class="mono">${r.customer_id || "—"}</td>
              <td data-etiqueta="Motor" class="mono">${r.provider} · ${r.model}</td>
              <td data-etiqueta="Estado"><span class=${`chip-estado chip-estado--${r.status}`}>${(CORRIDA_ES[r.status] || r.status) + (r.degraded ? " · degradada" : "")}</span></td>
              <td data-etiqueta="Iteraciones" class="num">${r.iterations || 0}</td>
              <td data-etiqueta="Tokens" class="num">${fmtNum((r.tokens_in || 0) + (r.tokens_out || 0))}</td>
              <td data-etiqueta="Latencia" class="num">${r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)} s` : "—"}</td>
              <td><${Boton} tam="sm" variante="fantasma" onClick=${() => abrirTraza(r.id)}>Ver traza<//></td>
            </tr>`)}
          </tbody>
        </table>
      </div>
      ${traza ? html`<div class="traza-ti" id="traza-ti">
        <${TiraRegistro} key=${traza.id} pasos=${traza.pasos} titulo=${`Traza de la corrida ${String(traza.id).slice(0, 8)}…`} />
        <${Boton} tam="sm" variante="fantasma" icono="cerrar" onClick=${() => setTraza(null)}>Cerrar traza<//>
      </div>` : null}
    </section>
  </div>`;
}
