#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-5173}"
CAMERA_STREAM_URL="${CAMERA_STREAM_URL:-rtsp://146.83.194.142:1935/share-w5DiM5QUILZ3lyTd70vCnEbt6Y9IkRNG_q9D5pPxYKU}"
RUNTIME_DIR="$ROOT_DIR/.runtime"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "No se encontró Python ejecutable en: $PYTHON_BIN" >&2
    echo "Crea .venv con python3 -m venv .venv e instala backend/requirements.txt." >&2
    exit 1
fi
if [[ ! -f "$ROOT_DIR/models/best.pt" ]]; then
    echo "No se encontró el modelo models/best.pt." >&2
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

if [[ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]]; then
    echo "Instalando dependencias del frontend..."
    (cd "$ROOT_DIR/frontend" && npm ci)
fi

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

start_service backend "uvicorn backend.main:app" \
    "$PYTHON_BIN" -m uvicorn backend.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"

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

start_service detector "scripts/edge_detector.py" \
    env BACKEND_URL="http://127.0.0.1:$BACKEND_PORT" \
    CAMERA_STREAM_URL="$CAMERA_STREAM_URL" DETECTOR_SOURCE=stream \
    MODEL_PATH="$ROOT_DIR/models/best.pt" \
    "$PYTHON_BIN" -u scripts/edge_detector.py

start_service frontend "node_modules/.bin/vite --host" \
    "$ROOT_DIR/frontend/node_modules/.bin/vite" --host "$WEB_HOST" --port "$WEB_PORT"

echo
echo "SmartParking está iniciado:"
echo "  Frontend: http://<IP-del-servidor>:$WEB_PORT"
echo "  Backend:  http://<IP-del-servidor>:$BACKEND_PORT"
echo "Registros y PID: $RUNTIME_DIR/"
echo "Para detener los servicios: ./stop_project.sh"
