// Formato y vocabulario compartidos por todas las vistas.
export const URGENCIA_ES = { CRITICAL: "Crítico", HIGH: "Alto", LOW: "Leve" };
export const ESTADO_ES = { PENDING: "Pendiente", IN_REVIEW: "En revisión", APPROVED: "Aprobado", REJECTED: "Rechazado" };
export const TIPO_ES = { AUTO: "Auto", MEDICAL: "Médico", HOME: "Hogar" };
export const TIPO_ICONO = { AUTO: "auto", MEDICAL: "medico", HOME: "hogar" };
export const CORRIDA_ES = {
  RUNNING: "en curso", COMPLETED: "completada", FAILED: "fallida",
  LIMIT_REACHED: "detenida por límite", AWAITING_CONFIRMATION: "esperando aprobación",
};
export const ACCION_ES = {
  ASSIGN_AGENT_IMMEDIATELY: "Asignar agente ya",
  HUMAN_VALIDATION_2H: "Validación humana ≤ 2 h",
  AUTO_APPROVE: "Aprobación automática",
  FAST_TRACK_REVIEW: "Revisión rápida",
  MANUAL_REVIEW: "Revisión manual",
};
export const SEVERIDAD_ES = { LEVE: "leve", MODERADO: "moderado", SEVERO: "severo", INDETERMINADO: "indeterminado" };

const REGION = "es-CO";

export const fmtNum = (n) => Number(n || 0).toLocaleString(REGION);

export const fmtPesos = (n) => (n === null || n === undefined ? "—"
  : new Intl.NumberFormat(REGION, { style: "currency", currency: "COP", maximumFractionDigits: 0 }).format(n));

export const fmtHora = (iso) => (iso ? new Date(iso).toLocaleTimeString(REGION, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");

export const fmtFechaHora = (iso) => (iso
  ? new Date(iso).toLocaleString(REGION, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");

/** «hace 5 min»; el segundo parámetro (la hora actual) hace que se recalcule al actualizar el reloj. */
export function fmtRelativo(iso, ahora = Date.now()) {
  if (!iso) return "—";
  const min = Math.round((ahora - new Date(iso).getTime()) / 60000);
  if (min < 1) return "hace instantes";
  if (min < 60) return `hace ${min} min`;
  if (min < 1440) return `hace ${Math.round(min / 60)} h`;
  return new Date(iso).toLocaleDateString(REGION, { day: "numeric", month: "short" });
}

export function iniciales(nombre = "") {
  return (nombre.trim()[0] || "?").toUpperCase();
}
