"""Inicia un detector (edge_detector.py) por cada cámara definida en cameras.json.

- Cada detector corre en su propio proceso: si uno falla, los demás siguen.
- Si un detector se cae, se reinicia automáticamente a los 5 segundos.
- Ctrl+C (o SIGTERM, usado por stop_project.sh) detiene todos los detectores.

Uso:
    python -u scripts/run_detectors.py              # todas las cámaras
    python -u scripts/run_detectors.py face ac      # solo las indicadas
"""
import os
import signal
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, ROOT_DIR)
from backend.cameras import load_cameras  # noqa: E402

RESTART_DELAY_SECONDS = 5
stopping = threading.Event()


def _forward_output(process, camera_id):
    for line in process.stdout:
        print(line.rstrip(), flush=True)


def supervise(camera_id):
    """Mantiene vivo el detector de una cámara."""
    command = [sys.executable, "-u", os.path.join(BASE_DIR, "edge_detector.py"), "--camera", camera_id]
    # La salida del detector pasa por una tubería: se fuerza UTF-8 para que en Windows
    # los símbolos (✓, ✗, tildes) no provoquen errores de codificación.
    child_env = dict(os.environ, PYTHONIOENCODING="utf-8")
    while not stopping.is_set():
        process = subprocess.Popen(
            command, cwd=ROOT_DIR, env=child_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        processes[camera_id] = process
        _forward_output(process, camera_id)
        code = process.wait()
        if stopping.is_set():
            break
        print(f"[{camera_id}] El detector terminó (código {code}); reiniciando en {RESTART_DELAY_SECONDS} s...", flush=True)
        stopping.wait(RESTART_DELAY_SECONDS)


processes: dict[str, subprocess.Popen] = {}


def stop_all(*_):
    if stopping.is_set():
        return
    stopping.set()
    print("Deteniendo detectores...", flush=True)
    for process in processes.values():
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 10
    for process in processes.values():
        try:
            process.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    # Si la consola no admite algún carácter, se reemplaza en vez de detener el lanzador.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    cameras = [camera["id"] for camera in load_cameras()]
    selected = sys.argv[1:] or cameras
    unknown = [camera_id for camera_id in selected if camera_id not in cameras]
    if unknown:
        raise SystemExit(f"Cámaras desconocidas: {', '.join(unknown)} (disponibles: {', '.join(cameras)})")

    signal.signal(signal.SIGTERM, stop_all)
    print(f"Iniciando detectores para: {', '.join(selected)}", flush=True)
    threads = [threading.Thread(target=supervise, args=(camera_id,), daemon=True) for camera_id in selected]
    for thread in threads:
        thread.start()
    try:
        while any(thread.is_alive() for thread in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_all()
    for thread in threads:
        thread.join(timeout=12)


if __name__ == "__main__":
    main()
