#!/usr/bin/env bash
# =============================================================================
# Un comando para todo. Sin argumentos levanta el sistema completo.
#
#   ./run.sh              levanta base de datos + aplicación y espera a que respondan
#   ./run.sh check        verifica que la API key de Gemini funciona (antes de la demo)
#   ./run.sh eval         corre la suite de casos dorados y escribe la línea base
#   ./run.sh test         corre las pruebas unitarias dentro del contenedor
#   ./run.sh logs         sigue los logs de la aplicación
#   ./run.sh down         apaga todo (conserva los datos)
#   ./run.sh reset        apaga y borra la base de datos para empezar de cero
#
# Todas las rutas son relativas al repositorio: funciona desde cualquier carpeta.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

AZUL='\033[0;36m'; VERDE='\033[0;32m'; ROJO='\033[0;31m'; AMBAR='\033[0;33m'; FIN='\033[0m'
info()  { printf "${AZUL}▸${FIN} %s\n" "$*"; }
ok()    { printf "${VERDE}✓${FIN} %s\n" "$*"; }
aviso() { printf "${AMBAR}!${FIN} %s\n" "$*"; }
error() { printf "${ROJO}✗${FIN} %s\n" "$*" >&2; }

# --- comprobaciones previas: fallar temprano y con un mensaje accionable ------
comprobar_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    error "Docker no está instalado. Instálalo desde https://docs.docker.com/get-docker/"
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    error "Necesitas Docker Compose v2 (el comando 'docker compose', sin guion)."
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    error "El demonio de Docker no está corriendo. Abre Docker Desktop y vuelve a intentar."
    exit 1
  fi
}

preparar_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    aviso "Se creó .env a partir de .env.example."
  fi
  # shellcheck disable=SC1091
  set -a; source .env; set +a

  if [[ "${LLM_PROVIDER:-gemini}" == "gemini" && -z "${GEMINI_API_KEY:-}" ]]; then
    aviso "GEMINI_API_KEY está vacía en .env."
    aviso "Consigue una gratis en https://aistudio.google.com/apikey y pégala allí."
    aviso "Mientras tanto se arranca con LLM_PROVIDER=offline (triaje por reglas, sin modelo)."
    export LLM_PROVIDER=offline
    # Se exporta solo para esta corrida; el archivo .env no se modifica.
  fi
}

esperar_salud() {
  local url="http://localhost:${APP_PORT:-8000}/api/ready"
  info "Esperando a que la aplicación responda en $url"
  for i in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      ok "La aplicación está lista (tardó ${i}s)."
      return 0
    fi
    sleep 1
  done
  error "La aplicación no respondió en 60 segundos. Revisa: ./run.sh logs"
  return 1
}

arrancar() {
  comprobar_docker
  preparar_env
  info "Construyendo y levantando contenedores…"
  LLM_PROVIDER="${LLM_PROVIDER:-gemini}" docker compose up --build -d
  esperar_salud || exit 1
  echo
  ok "Dashboard:   http://localhost:${APP_PORT:-8000}"
  ok "API (docs):  http://localhost:${APP_PORT:-8000}/api/docs"
  ok "Motor de IA: $(curl -fsS "http://localhost:${APP_PORT:-8000}/api/config" | python3 -c 'import sys,json;c=json.load(sys.stdin);print(c["proveedor"], c["modelo"])' 2>/dev/null || echo 'consultar /api/config')"
  echo
  info "Siguiente paso sugerido: ./run.sh check   (verifica la clave del modelo)"
}

case "${1:-up}" in
  up|"")
    arrancar
    ;;

  check)
    comprobar_docker
    info "Probando el proveedor de IA con una llamada real…"
    docker compose exec -T app python /app/eval/check_provider.py
    ;;

  eval)
    comprobar_docker
    shift || true
    info "Corriendo la suite de casos dorados…"
    docker compose exec -T app python /app/eval/run_eval.py "$@"
    ;;

  test)
    comprobar_docker
    info "Corriendo las pruebas unitarias en un contenedor limpio…"
    # No necesita la base de datos: la suite usa dobles en memoria.
    docker run --rm -v "$PWD/app:/app" -w /app python:3.12-slim \
      sh -c "pip install --quiet --no-cache-dir -r requirements-dev.txt && python -m pytest -q"
    ;;

  logs)
    docker compose logs -f app
    ;;

  down)
    docker compose down
    ok "Contenedores detenidos. Los datos siguen en el volumen pgdata."
    ;;

  reset)
    docker compose down -v
    ok "Contenedores y datos borrados. El próximo ./run.sh carga el esquema desde cero."
    ;;

  *)
    sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
