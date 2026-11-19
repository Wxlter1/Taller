"""Persistencia de SmartParking en MongoDB, con respaldo en archivos JSON.

Si ``MONGO_URI`` está definida (en .env), los datos se guardan en MongoDB:
  - admins        -> cuenta del administrador        {_id: "admin", username, password}
  - camera_zones  -> plazas dibujadas por cámara     {_id: <camera_id>, zones: [...]}
  - layouts       -> mapa de distribución por cámara {_id: <camera_id>, layout, cells, grid}

Si no está definida, se usan los archivos JSON de ``DATA_DIR`` como antes
(útil para desarrollo sin VPN). La primera vez que se conecta a una base vacía,
se copian a MongoDB los datos que ya existan en los archivos JSON.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env", override=False)

DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent)))
ADMIN_FILE = DATA_DIR / "admin.json"
LAYOUT_FILE = DATA_DIR / "layout.json"
CAMERA_ZONES_FILE = DATA_DIR / "camera_zones.json"

MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB = os.getenv("MONGO_DB", "smartparking").strip() or "smartparking"

_db = None


def use_mongo() -> bool:
    return bool(MONGO_URI)


def get_db():
    """Devuelve la base de datos (conexión perezosa, una sola por proceso)."""
    global _db
    if _db is None:
        from pymongo import MongoClient

        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, appname="smartparking")
        _db = client[MONGO_DB]
    return _db


def check_connection() -> None:
    """Verifica la conexión al arrancar (falla rápido si la base no responde)."""
    if not use_mongo():
        print("MongoDB: MONGO_URI no definida, se usan archivos JSON.", flush=True)
        return
    from pymongo.errors import PyMongoError

    try:
        get_db().client.admin.command("ping")
    except PyMongoError as exc:
        raise RuntimeError(
            "No se pudo conectar a MongoDB. Revisa MONGO_URI en .env y, si estás fuera "
            "de la red de la universidad, conéctate a la VPN. Para trabajar sin base de "
            f"datos deja MONGO_URI vacía (se usarán archivos JSON). Detalle: {exc}"
        ) from None
    print(f"MongoDB: conectado a la base '{MONGO_DB}'.", flush=True)


# ---------- Utilidades JSON (modo sin MongoDB y migración) ----------

def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _zones_from_file(default_camera_id: str) -> dict:
    data = _read_json(CAMERA_ZONES_FILE, {})
    # Formato antiguo (una sola cámara): lista de zonas → se asigna a la primera cámara.
    if isinstance(data, list):
        return {default_camera_id: data}
    return data if isinstance(data, dict) else {}


def _layouts_from_file(default_camera_id: str) -> dict:
    data = _read_json(LAYOUT_FILE, {})
    # Formato antiguo (un solo mapa): {layout, cells, grid} → se asigna a la primera cámara.
    if isinstance(data, dict) and "cells" in data and "cameras" not in data:
        return {default_camera_id: data}
    return data.get("cameras", {}) if isinstance(data, dict) else {}


# ---------- Administrador ----------

def load_admin() -> dict | None:
    if use_mongo():
        doc = get_db().admins.find_one({"_id": "admin"}, {"_id": 0})
        return doc or None
    return _read_json(ADMIN_FILE, None)


def store_admin(data: dict) -> None:
    if use_mongo():
        get_db().admins.replace_one({"_id": "admin"}, data, upsert=True)
    else:
        _write_json(ADMIN_FILE, data)


# ---------- Zonas de cámara ----------

def get_zones(camera_id: str, default_camera_id: str) -> list:
    if use_mongo():
        doc = get_db().camera_zones.find_one({"_id": camera_id})
        return doc["zones"] if doc else []
    return _zones_from_file(default_camera_id).get(camera_id, [])


def save_zones(camera_id: str, zones: list, default_camera_id: str) -> None:
    if use_mongo():
        get_db().camera_zones.replace_one({"_id": camera_id}, {"zones": zones}, upsert=True)
        return
    all_zones = _zones_from_file(default_camera_id)
    all_zones[camera_id] = zones
    _write_json(CAMERA_ZONES_FILE, all_zones)


# ---------- Mapas de distribución ----------

def get_layout(camera_id: str, default_camera_id: str) -> dict | None:
    if use_mongo():
        return get_db().layouts.find_one({"_id": camera_id}, {"_id": 0})
    return _layouts_from_file(default_camera_id).get(camera_id)


def save_layout(camera_id: str, layout: dict, default_camera_id: str) -> None:
    if use_mongo():
        get_db().layouts.replace_one({"_id": camera_id}, layout, upsert=True)
        return
    layouts = _layouts_from_file(default_camera_id)
    layouts[camera_id] = layout
    _write_json(LAYOUT_FILE, {"cameras": layouts})


# ---------- Migración inicial ----------

def migrate_json_to_mongo(default_camera_id: str) -> None:
    """Copia los datos de los archivos JSON a MongoDB solo si las colecciones están vacías."""
    if not use_mongo():
        return
    db = get_db()

    admin = _read_json(ADMIN_FILE, None)
    if admin and db.admins.count_documents({}) == 0:
        db.admins.replace_one({"_id": "admin"}, admin, upsert=True)
        print("MongoDB: administrador migrado desde admin.json.", flush=True)

    if db.camera_zones.count_documents({}) == 0:
        zones = _zones_from_file(default_camera_id)
        for camera_id, camera_zones in zones.items():
            db.camera_zones.replace_one({"_id": camera_id}, {"zones": camera_zones}, upsert=True)
        if zones:
            print(f"MongoDB: zonas de {len(zones)} cámara(s) migradas.", flush=True)

    if db.layouts.count_documents({}) == 0:
        layouts = _layouts_from_file(default_camera_id)
        for camera_id, layout in layouts.items():
            db.layouts.replace_one({"_id": camera_id}, layout, upsert=True)
        if layouts:
            print(f"MongoDB: mapas de {len(layouts)} cámara(s) migrados.", flush=True)
