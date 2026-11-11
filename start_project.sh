#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Variables sensibles (dominio, certificado, enlaces de cámaras). Ver .env.example
if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "Aviso: no existe .env; copia .env.example como .env y completa los valores." >&2
fi
for env_file in "$ROOT_DIR/smartparking.env" "$ROOT_DIR/.env"; do
    if [[ -f "$env_file" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
    fi
done

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${BACKEND_PORT:-8000}"
RUNTIME_DIR="$ROOT_DIR/.runtime"
FRONTEND_DIST="$ROOT_DIR/frontend/dist"

export SITE_ADDRESS="${SITE_ADDRESS:-localhost}"
export CADDY_TLS="${CADDY_TLS:-internal}"
export FRONTEND_DIST BACKEND_PORT RUNTIME_DIR

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "No se encontró Python ejecutable en: $PYTHON_BIN" >&2
    echo "Crea .venv con python3 -m venv .venv e instala backend/requirements.txt." >&2
    exit 1
fi
if [[ ! -f "$ROOT_DIR/models/Det_V2.pt" ]]; then
    echo "No se encontró el modelo models/Det_V2.pt." >&2
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "No se encontró npm. Instala Node.js antes de iniciar el proyecto." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "No se encontró curl, necesario para esperar al backend." >&2
    exit 1
fi
CADDY_BIN="$(command -v caddy || true)"
if [[ -z "$CADDY_BIN" ]]; then
    echo "No se encontró Caddy. Instálalo siguiendo la sección 'Publicar con HTTPS' del README." >&2
    exit 1
fi
if [[ "$(id -u)" -ne 0 ]] && command -v getcap >/dev/null 2>&1 \
    && ! getcap "$CADDY_BIN" 2>/dev/null | grep -q cap_net_bind_service; then
    echo "Caddy necesita permiso para usar los puertos 80 y 443. Ejecuta una vez:" >&2
    echo "  sudo setcap cap_net_bind_service=+ep $CADDY_BIN" >&2
    exit 1
fi
if [[ ! -f "$ROOT_DIR/backend/admin.json" ]]; then
    echo "AVISO: aún no hay cuenta de administrador. Créala con:"
    echo "  $PYTHON_BIN -m backend.create_admin"
    echo
fi

if [[ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]]; then
    echo "Instalando dependencias del frontend..."
    (cd "$ROOT_DIR/frontend" && npm ci)
fi

echo "Compilando el frontend..."
(cd "$ROOT_DIR/frontend" && npm run build --silent)

mkdir -p "$RUNTIME_DIR"

is_running() {
    local pid_file="$1"
    local expected="$2"
    local pid
    [[ -f "$pid_file" ]] || return 1
    read -r pid < "$pid_file"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    ps -p "$pid" -o args= | grep -F -- "$expected" >/dev/null
}

start_service() {
    local name="$1"
    local expected="$2"
    shift 2
    local pid_file="$RUNTIME_DIR/$name.pid"

    if is_running "$pid_file" "$expected"; then
        echo "$name ya está iniciado (PID $(<"$pid_file"))."
        return 0
    fi

    rm -f "$pid_file"
    nohup "$@" >"$RUNTIME_DIR/$name.log" 2>&1 </dev/null &
    echo "$!" > "$pid_file"
    echo "$name iniciado (PID $(<"$pid_file")); registro: $RUNTIME_DIR/$name.log"
}

# El backend solo escucha en 127.0.0.1: desde fuera únicamente se llega a él a través de Caddy.
# --forwarded-allow-ips permite ver la IP real del visitante (necesario para el bloqueo de intentos de login).
start_service backend "uvicorn backend.main:app" \
    "$PYTHON_BIN" -m uvicorn backend.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
    --proxy-headers --forwarded-allow-ips 127.0.0.1

echo "Esperando al backend..."
backend_ready=false
for _ in $(seq 1 60); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:$BACKEND_PORT/" >/dev/null; then
        backend_ready=true
        break
    fi
    sleep 1
done
if [[ "$backend_ready" != true ]]; then
    echo "El backend no respondió. Revisa $RUNTIME_DIR/backend.log" >&2
    exit 1
fi

# Un detector por cámara de cameras.json (retransmisión, o video de respaldo si no hay imagen).
# Leen la clave compartida desde backend/.detector_key (la crea el backend al arrancar).
start_service detector "scripts/run_detectors.py" \
    env BACKEND_URL="http://127.0.0.1:$BACKEND_PORT" \
    "$PYTHON_BIN" -u scripts/run_detectors.py

start_service caddy "caddy run --config $ROOT_DIR/Caddyfile" \
    "$CADDY_BIN" run --config "$ROOT_DIR/Caddyfile" --adapter caddyfile

echo
echo "SmartParking está iniciado:"
echo "  Página: https://${SITE_ADDRESS#https://}"
echo "Registros y PID: $RUNTIME_DIR/"
echo "Para detener los servicios: ./stop_project.sh"
