#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"

stop_service() {
    local name="$1"
    local expected="$2"
    local pid_file="$RUNTIME_DIR/$name.pid"
    local pid

    if [[ ! -f "$pid_file" ]]; then
        echo "$name no tiene un PID registrado."
        return 0
    fi

    read -r pid < "$pid_file"
    if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        echo "$name ya estaba detenido."
        return 0
    fi

    if ! ps -p "$pid" -o args= | grep -F -- "$expected" >/dev/null; then
        rm -f "$pid_file"
        echo "PID obsoleto para $name; no se terminó ningún proceso."
        return 0
    fi

    kill "$pid"
    for _ in $(seq 1 10); do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$pid_file"
            echo "$name detenido."
            return 0
        fi
        sleep 1
    done

    echo "$name no terminó después de SIGTERM; se conserva el PID para revisión." >&2
    return 1
}

stop_service frontend "node_modules/.bin/vite --host"
stop_service detector "scripts/edge_detector.py"
stop_service backend "uvicorn backend.main:app"
