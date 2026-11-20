// Vista del CLIENTE: reportar un siniestro y seguir su estado.
// El cliente nunca ve urgencia, puntuación, resumen del agente ni trazas: solo /api/public/claims/{id}.
import { html, useState, useEffect, useRef, useCallback } from "../lib.js";
import { Icono, Logo } from "../icons.js";
import { Boton, Aviso, Estado, toast } from "../ui.js";
import { Enlace } from "../router.js";
import { pedir, mensajeDeError } from "../api.js";
import { TIPO_ES, TIPO_ICONO, fmtFechaHora, fmtRelativo } from "../format.js";

const TIPOS = ["AUTO", "MEDICAL", "HOME"];
const CUANDO = [
  { id: "20", texto: "Hace unos minutos" },
  { id: "60", texto: "Hace una hora" },
  { id: "240", texto: "Hace unas horas" },
  { id: "1440", texto: "Ayer" },
];
const MAX_FOTO_MB = 8;
const FORMATOS = ["image/jpeg", "image/png", "image/webp"];
const CLAVE_MIOS = "guardia.misReportes";

const CASOS = {
  Crítico: { claim_type: "AUTO", customer_id: "CUST-000123", description: "Choque en la autopista norte, hay dos heridos y ya llamamos a la ambulancia. El carro quedó completamente destruido." },
  Inconsistente: { claim_type: "AUTO", customer_id: "CUST-009034", description: "No hubo daños ni heridos, pero el vehículo quedó completamente destruido y la ambulancia se llevó al conductor." },
  Leve: { claim_type: "AUTO", customer_id: "CUST-005501", description: "Solo un rayón en la puerta trasera del carro, hecho en el parqueadero del centro comercial." },
  "Póliza vencida": { claim_type: "AUTO", customer_id: "CUST-007781", description: "Se incendió el motor del carro en plena vía y los bomberos tuvieron que apagarlo." },
  "Inválido (error 400)": { claim_type: "AUTO", customer_id: "X", description: "corto" },
};

// Mensajes pensados para un asegurado, no para un ajustador.
const MENSAJES = {
  PENDING: { paso: 0, texto: "Recibimos tu reporte", detalle: "Ya está en la fila para ser revisado. No tienes que hacer nada más; si necesitamos algo, te contactaremos." },
  IN_REVIEW: { paso: 1, texto: "Un ajustador está revisando tu caso", detalle: "Es posible que te llamen para pedirte más información." },
  APPROVED: { paso: 2, texto: "Tu reporte fue aprobado", detalle: "El ajustador se pondrá en contacto contigo para explicarte los siguientes pasos." },
  REJECTED: { paso: 2, texto: "Tu reporte fue revisado y no pudo ser aprobado", detalle: "El ajustador se pondrá en contacto contigo para explicarte el motivo." },
};

// --------------------------------------------------------------------------- memoria local
// Solo por comodidad de quien reporta: la verdad vive en el servidor.
function leerMios() {
  try { return JSON.parse(localStorage.getItem(CLAVE_MIOS) || "[]"); } catch (_) { return []; }
}
function guardarMio(id, tipo) {
  try {
    const lista = leerMios().filter((r) => r.id !== id);
    lista.unshift({ id, tipo, fecha: new Date().toISOString() });
    localStorage.setItem(CLAVE_MIOS, JSON.stringify(lista.slice(0, 8)));
  } catch (_) { /* navegación privada: se omite */ }
}

// --------------------------------------------------------------------------- validación
function validar(f) {
  const e = {};
  if (!/^[A-Za-z0-9_-]{3,64}$/.test(f.cliente.trim())) e.cliente = "Usa de 3 a 64 letras, números, guiones o guion bajo. Ejemplo: CUST-000123.";
  const n = f.descripcion.trim().length;
  if (n < 10) e.descripcion = "Cuéntanos un poco más: escribe al menos 10 caracteres.";
  else if (n > 5000) e.descripcion = "El relato es demasiado largo (máximo 5.000 caracteres).";
  if (f.foto) {
    if (!FORMATOS.includes(f.foto.type)) e.foto = "La foto debe ser JPG, PNG o WebP.";
    else if (f.foto.size > MAX_FOTO_MB * 1024 * 1024) e.foto = `La foto pesa más de ${MAX_FOTO_MB} MB.`;
  }
  return e;
}

function Campo({ etiqueta, error, ayuda, children, ...resto }) {
  return html`<div class=${`campo ${error ? "campo--error" : ""}`} ...${resto}>
    <div class="campo__fila"><span class="campo__etiqueta">${etiqueta}</span>${ayuda ? html`<span class="campo__ayuda">${ayuda}</span>` : null}</div>
    ${children}
    ${error ? html`<div class="campo__error" role="alert"><${Icono} n="alerta" tam="sm" />${error}</div>` : null}
  </div>`;
}

// --------------------------------------------------------------------------- formulario
function Formulario({ alEnviado }) {
  const [f, setF] = useState({ cliente: "CUST-000123", tipo: "AUTO", cuando: "20", descripcion: "", foto: null });
  const [tocados, setTocados] = useState({});
  const [enviando, setEnviando] = useState(false);
  const [errorGeneral, setErrorGeneral] = useState(null);
  const [sobre, setSobre] = useState(false);
  const [previa, setPrevia] = useState(null);
  const errores = validar(f);

  useEffect(() => {
    if (!f.foto) { setPrevia(null); return undefined; }
    const url = URL.createObjectURL(f.foto);
    setPrevia(url);
    return () => URL.revokeObjectURL(url);
  }, [f.foto]);

  const poner = (campo) => (e) => setF((x) => ({ ...x, [campo]: e.target.value }));
  const tocar = (campo) => () => setTocados((t) => ({ ...t, [campo]: true }));
  const ver = (campo) => (tocados[campo] || tocados.todos ? errores[campo] : null);

  const elegirFoto = (archivo) => { if (archivo) { setF((x) => ({ ...x, foto: archivo })); setTocados((t) => ({ ...t, foto: true })); } };

  const enviar = async (e) => {
    e.preventDefault();
    setTocados({ todos: true });
    setErrorGeneral(null);
    if (Object.keys(errores).length) return;
    const datos = new FormData();
    datos.set("customer_id", f.cliente.trim());
    datos.set("claim_type", f.tipo);
    datos.set("description", f.descripcion.trim());
    datos.set("incident_timestamp", new Date(Date.now() - Number(f.cuando) * 60000).toISOString());
    if (f.foto) datos.set("imagen", f.foto);
    setEnviando(true);
    try {
      const r = await pedir("/api/claims", { method: "POST", body: datos, sinRedirigir: true });
      guardarMio(r.claim_id, f.tipo);
      alEnviado(r.claim_id);
    } catch (err) {
      setErrorGeneral(err.status === 429 ? "Enviaste muchos reportes seguidos. Espera un momento e inténtalo de nuevo." : mensajeDeError(err));
    } finally {
      setEnviando(false);
    }
  };

  const usarCaso = (nombre) => {
    const c = CASOS[nombre];
    setF((x) => ({ ...x, cliente: c.customer_id, tipo: c.claim_type, descripcion: c.description }));
    setTocados({});
  };

  return html`<form onSubmit=${enviar} noValidate class="tarjeta" aria-labelledby="titulo-reporte">
    <div class="tarjeta__titulo"><h2 id="titulo-reporte">Cuéntanos qué pasó</h2></div>
    <div class="formulario" role="group">
      <${Campo} etiqueta="Tipo de siniestro">
        <div class="segmentos" role="radiogroup" aria-label="Tipo de siniestro">
          ${TIPOS.map((t) => html`<button type="button" role="radio" class="segmento" key=${t} aria-checked=${f.tipo === t}
            onClick=${() => setF((x) => ({ ...x, tipo: t }))}><${Icono} n=${TIPO_ICONO[t]} />${TIPO_ES[t]}</button>`)}
        </div>
      <//>

      <div class="cuadricula-2">
        <${Campo} etiqueta="Número de cliente" error=${ver("cliente")}>
          <input class="input" name="customer_id" value=${f.cliente} onInput=${poner("cliente")} onBlur=${tocar("cliente")}
            autocomplete="off" spellcheck="false" aria-invalid=${!!ver("cliente")} />
        <//>
        <${Campo} etiqueta="¿Cuándo ocurrió?">
          <select class="select" value=${f.cuando} onChange=${poner("cuando")}>
            ${CUANDO.map((c) => html`<option key=${c.id} value=${c.id}>${c.texto}</option>`)}
          </select>
        <//>
      </div>

      <${Campo} etiqueta="¿Qué pasó?" ayuda=${`${f.descripcion.length}/5000`} error=${ver("descripcion")}>
        <textarea class="textarea" name="description" rows="5" maxlength="5000" value=${f.descripcion}
          placeholder="Cuéntalo con tus palabras: dónde, cuándo y qué daños o heridos hubo."
          onInput=${poner("descripcion")} onBlur=${tocar("descripcion")} aria-invalid=${!!ver("descripcion")}></textarea>
      <//>

      <${Campo} etiqueta="Foto del daño (opcional)" ayuda=${`JPG, PNG o WebP · hasta ${MAX_FOTO_MB} MB`} error=${ver("foto")}>
        ${f.foto ? html`<div class="foto-previa">
          ${previa ? html`<img src=${previa} alt="Vista previa de la foto adjunta" />` : null}
          <div class="foto-previa__datos"><strong>${f.foto.name}</strong><span>${(f.foto.size / 1024 / 1024).toFixed(1)} MB</span></div>
          <${Boton} tam="sm" variante="fantasma" onClick=${() => setF((x) => ({ ...x, foto: null }))} icono="cerrar">Quitar<//>
        </div>` : html`<label class=${`zona-foto ${sobre ? "zona-foto--sobre" : ""}`}
          onDragOver=${(e) => { e.preventDefault(); setSobre(true); }} onDragLeave=${() => setSobre(false)}
          onDrop=${(e) => { e.preventDefault(); setSobre(false); elegirFoto(e.dataTransfer.files[0]); }}>
          <${Icono} n="camara" tam="lg" />
          <span><strong>Toca para tomar o elegir una foto</strong></span>
          <small>o arrástrala hasta aquí</small>
          <input type="file" name="imagen" accept=${FORMATOS.join(",")} onChange=${(e) => elegirFoto(e.target.files[0])} />
        </label>`}
      <//>

      ${errorGeneral ? html`<${Aviso} tipo="error">${errorGeneral}<//>` : null}
      <${Boton} type="submit" variante="primario" bloque cargando=${enviando} icono="enviar">${enviando ? "Enviando…" : "Enviar reporte"}<//>

      <details class="demo">
        <summary>Casos de prueba (demostración)</summary>
        <div class="demo__botones">
          ${Object.keys(CASOS).map((n) => html`<${Boton} key=${n} tam="sm" onClick=${() => usarCaso(n)}>${n}<//>`)}
        </div>
      </details>
    </div>
  </form>`;
}

// --------------------------------------------------------------------------- seguimiento
function Seguimiento({ id, recienEnviado, alVolver }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef();

  const cargar = useCallback(async () => {
    try {
      const r = await pedir(`/api/public/claims/${encodeURIComponent(id)}`, { sinRedirigir: true });
      setD(r);
      setError(null);
      clearTimeout(timer.current);
      if (r.estado === "PENDING" || r.estado === "IN_REVIEW") timer.current = setTimeout(cargar, 8000);
    } catch (e) {
      setError(e.status === 400 || e.status === 422
        ? "Ese número no tiene el formato correcto. Cópialo tal como te lo dimos."
        : e.status === 404 ? "No encontramos un reporte con ese número." : mensajeDeError(e));
    }
  }, [id]);

  useEffect(() => { setD(null); setError(null); cargar(); return () => clearTimeout(timer.current); }, [id]);

  const copiar = async () => {
    try { await navigator.clipboard.writeText(id); toast("Número copiado", { tipo: "exito", duracion: 2500 }); }
    catch (_) { toast("No se pudo copiar", { texto: "Selecciona el número y cópialo a mano.", tipo: "alto" }); }
  };

  if (error) {
    return html`<div class="tarjeta"><${Aviso} tipo="error">${error}<//>
      <${Boton} bloque onClick=${alVolver} icono="izquierda">Volver<//></div>`;
  }
  if (!d) return html`<div class="tarjeta" aria-busy="true"><div class="exito"><span class="spinner spinner--grande"></span><p>Buscando tu reporte…</p></div></div>`;

  const m = MENSAJES[d.estado] || MENSAJES.PENDING;
  return html`<div class="tarjeta" aria-live="polite">
    <div class="exito">
      ${recienEnviado ? html`<span class="exito__marca"><${Icono} n="check" /></span>` : null}
      <h2>${recienEnviado && d.estado === "PENDING" ? "Tu reporte fue recibido" : m.texto}</h2>
      <p class="campo__ayuda">${m.detalle}</p>
    </div>
    <div class=${`progreso progreso--${d.estado}`} role="list" aria-label="Avance del reporte">
      ${["Recibido", "En revisión", "Resuelto"].map((t, i) => html`<div role="listitem" key=${t}
        class=${`progreso__paso ${i < m.paso ? "progreso__paso--hecho" : i === m.paso ? "progreso__paso--actual" : ""}`}
        aria-current=${i === m.paso ? "step" : null}>${t}</div>`)}
    </div>
    <div class="campo">
      <span class="campo__etiqueta">Número de seguimiento</span>
      <div class="numero-seguimiento"><code>${d.id}</code>
        <${Boton} tam="sm" onClick=${copiar} icono="copiar">Copiar<//></div>
      <span class="campo__ayuda">${TIPO_ES[d.tipo] || d.tipo} · recibido el ${fmtFechaHora(d.recibido)} · <${Estado} valor=${d.estado} /></span>
    </div>
    <div class="tarjeta__titulo"></div>
    <${Boton} bloque onClick=${alVolver} icono="izquierda">${recienEnviado ? "Reportar otro siniestro" : "Volver"}<//>
  </div>`;
}

// --------------------------------------------------------------------------- consulta
function Consulta({ alAbrir }) {
  const [numero, setNumero] = useState("");
  const [mios, setMios] = useState(leerMios);
  useEffect(() => setMios(leerMios()), []);
  const buscar = (e) => { e.preventDefault(); if (numero.trim()) alAbrir(numero.trim()); };

  return html`<div class="tarjeta">
    <div class="tarjeta__titulo"><h2>Consultar un reporte</h2></div>
    <form onSubmit=${buscar} class="formulario" noValidate>
      <${Campo} etiqueta="Número de seguimiento">
        <input class="input" value=${numero} onInput=${(e) => setNumero(e.target.value)} placeholder="Pega aquí el número que recibiste"
          autocomplete="off" spellcheck="false" />
      <//>
      <${Boton} type="submit" variante="primario" bloque icono="buscar" disabled=${!numero.trim()}>Consultar<//>
    </form>
    ${mios.length ? html`<div class="seccion-etiqueta">Enviados desde este dispositivo</div>
      <div class="lista-reportes">
        ${mios.map((r) => html`<button type="button" class="reporte" key=${r.id} onClick=${() => alAbrir(r.id)}>
          <span class="reporte__icono"><${Icono} n=${TIPO_ICONO[r.tipo] || "carpeta"} /></span>
          <span class="reporte__datos"><strong>${TIPO_ES[r.tipo] || r.tipo}</strong><small>${r.id.slice(0, 8)}… · ${fmtRelativo(r.fecha)}</small></span>
          <${Icono} n="ojo" />
        </button>`)}
      </div>` : null}
  </div>`;
}

// --------------------------------------------------------------------------- vista
export function Cliente() {
  const [modo, setModo] = useState("reportar");           // reportar | consultar
  const [abierto, setAbierto] = useState(null);           // { id, nuevo }

  const volver = () => { setAbierto(null); setModo("reportar"); };

  return html`<div class="publico">
    <header class="publico__barra">
      <span class="marca"><${Logo} /><span class="marca__nombre">Guardia de triaje</span></span>
      <${Enlace} href="/ingresar" class="btn btn--sm"><${Icono} n="usuario" tam="sm" />Acceso del personal<//>
    </header>
    <section class="publico__hero">
      <h1>Reporta tu siniestro</h1>
      <p>Cuéntanos qué pasó y te avisaremos de cada avance. Toma pocos minutos.</p>
    </section>
    <main class="publico__cuerpo" id="contenido">
      ${abierto ? html`<${Seguimiento} key=${abierto.id} id=${abierto.id} recienEnviado=${abierto.nuevo} alVolver=${volver} />` : html`
        <div class="segmentos segmentos--fila" role="tablist" aria-label="¿Qué quieres hacer?">
          <button class="segmento" role="tab" aria-selected=${modo === "reportar"} onClick=${() => setModo("reportar")}><${Icono} n="enviar" tam="sm" />Reportar</button>
          <button class="segmento" role="tab" aria-selected=${modo === "consultar"} onClick=${() => setModo("consultar")}><${Icono} n="buscar" tam="sm" />Consultar un reporte</button>
        </div>
        ${modo === "reportar"
          ? html`<${Formulario} alEnviado=${(id) => setAbierto({ id, nuevo: true })} />`
          : html`<${Consulta} alAbrir=${(id) => setAbierto({ id, nuevo: false })} />`}`}
    </main>
    <footer class="publico__pie">Tu reporte lo revisa un ajustador. No compartas contraseñas ni datos bancarios.</footer>
  </div>`;
}
