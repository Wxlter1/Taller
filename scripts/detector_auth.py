"""Clave compartida entre el detector y el backend.

El backend la genera al arrancar en backend/.detector_key. Como el detector corre
en el mismo servidor, la lee de ese archivo automáticamente. También se puede
indicar con la variable DETECTOR_API_KEY (o la ruta del archivo con
DETECTOR_KEY_FILE).
"""

import os
import time

# Misma carpeta de datos que usa el backend (DATA_DIR), por defecto backend/.
_DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
_DEFAULT_KEY_FILE = os.path.join(_DATA_DIR, ".detector_key")
_cached_key = None


def _read_key():
    env_key = os.getenv("DETECTOR_API_KEY")
    if env_key:
        return env_key.strip()
    key_file = os.getenv("DETECTOR_KEY_FILE", _DEFAULT_KEY_FILE)
    try:
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def detector_headers():
    """Cabeceras que el detector debe enviar en cada petición al backend."""
    global _cached_key
    if _cached_key is None:
        _cached_key = _read_key()
    return {"X-Detector-Key": _cached_key} if _cached_key else {}


def reset_cached_key():
    """Fuerza a volver a leer la clave (útil si el backend respondió 401)."""
    global _cached_key
    _cached_key = None


def wait_for_key(timeout=30.0):
    """Espera a que el backend haya creado la clave (si se inició al mismo tiempo)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if detector_headers():
            return True
        reset_cached_key()
        time.sleep(1)
    print("✗ No se encontró la clave del detector (backend/.detector_key ni DETECTOR_API_KEY).")
    return False
