"""Lectura de la configuración de cámaras (cameras.json en la raíz del proyecto).

Cada cámara define:
  id              identificador corto (se usa en las URLs de la API y en el frontend)
  name            nombre visible
  stream_url      retransmisión RTSP/HTTP (vacío si la cámara aún no tiene una)
  fallback_video  video que se reproduce en bucle si la retransmisión no está disponible
  watch_url       enlace "Cámara original" que ve solo el administrador

Los valores pueden referenciar variables de entorno con ${NOMBRE}. Las direcciones
sensibles (retransmisiones, enlaces) van en el archivo .env de la raíz, que no se
sube al repositorio; ver .env.example.
"""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
# Carga .env (sin pisar variables ya definidas en el sistema). Lo usan backend y detectores.
load_dotenv(ROOT_DIR / ".env", override=False)

CAMERAS_FILE = Path(os.getenv("CAMERAS_FILE", str(ROOT_DIR / "cameras.json")))
_VALID_ID = re.compile(r"^[a-z0-9_-]{1,40}$")
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value) -> str:
    """Reemplaza ${NOMBRE} por la variable de entorno; si no existe, queda vacío."""
    text = str(value or "").strip()
    missing = [name for name in _ENV_REF.findall(text) if name not in os.environ]
    if missing:
        print(f"Aviso: {', '.join(missing)} no está definida en .env; se deja vacía.", flush=True)
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), text).strip()


def load_cameras() -> list[dict]:
    try:
        data = json.loads(CAMERAS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"No se encontró la configuración de cámaras: {CAMERAS_FILE}")
    cameras = []
    for raw in data.get("cameras", []):
        camera_id = str(raw.get("id", "")).strip().lower()
        if not _VALID_ID.match(camera_id):
            raise RuntimeError(f"Id de cámara inválido en {CAMERAS_FILE}: {raw.get('id')!r}")
        cameras.append({
            "id": camera_id,
            "name": raw.get("name") or camera_id,
            "stream_url": _expand(raw.get("stream_url")),
            "fallback_video": _expand(raw.get("fallback_video")),
            "watch_url": _expand(raw.get("watch_url")),
        })
    if not cameras:
        raise RuntimeError(f"{CAMERAS_FILE} no define ninguna cámara.")
    if len({c["id"] for c in cameras}) != len(cameras):
        raise RuntimeError(f"{CAMERAS_FILE} tiene ids de cámara repetidos.")
    return cameras
