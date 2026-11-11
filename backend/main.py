import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Literal, Optional
from .auth import (
    authenticate,
    create_token,
    get_detector_key,
    require_admin,
    require_admin_or_detector,
    require_admin_query,
    require_detector,
)
from .cameras import load_cameras
from .yolo_service import YOLOService

# ---------- Configuración ----------

CAMERAS = load_cameras()
CAMERAS_BY_ID = {camera["id"]: camera for camera in CAMERAS}
# Los endpoints antiguos (/api/parking/update, /actualizar_estado) escriben en la primera cámara.
DEFAULT_CAMERA_ID = CAMERAS[0]["id"]

DETECTOR_TIMEOUT = 15.0
MAX_FRAME_BYTES = 5 * 1024 * 1024

DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent)))
LAYOUT_FILE = DATA_DIR / "layout.json"
CAMERA_ZONES_FILE = DATA_DIR / "camera_zones.json"

# Orígenes autorizados a llamar a la API desde el navegador (separados por coma).
# En producción, detrás de Caddy, frontend y API comparten dominio y CORS no interviene.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Genera la clave del detector al arrancar, para que exista antes de que el detector la lea.
    get_detector_key()
    watchdog_task = asyncio.create_task(detector_watchdog())
    yield
    watchdog_task.cancel()

app = FastAPI(title="SmartParking API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)

model = YOLOService("models/best.pt")


# ---------- Estado en memoria, por cámara ----------

class CameraState:
    def __init__(self):
        self.spots: Dict[str, dict] = {}
        self.last_update: float = 0.0
        self.source: Optional[str] = None       # "stream" | "video" | "camera"
        self.frame: Optional[bytes] = None
        self.frame_id: int = 0

    def is_online(self) -> bool:
        return bool(self.last_update) and (time.time() - self.last_update) <= DETECTOR_TIMEOUT

    def reset(self) -> None:
        self.spots.clear()
        self.last_update = 0.0
        self.source = None


camera_states: Dict[str, CameraState] = {camera["id"]: CameraState() for camera in CAMERAS}


def get_camera_state(camera_id: str) -> CameraState:
    state = camera_states.get(camera_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No existe la cámara '{camera_id}'.")
    return state


# ---------- Persistencia (zonas y mapas, por cámara) ----------

def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all_zones() -> Dict[str, list]:
    data = _read_json(CAMERA_ZONES_FILE, {})
    # Formato antiguo (una sola cámara): lista de zonas → se asigna a la primera cámara.
    if isinstance(data, list):
        return {DEFAULT_CAMERA_ID: data}
    return data if isinstance(data, dict) else {}


def load_all_layouts() -> Dict[str, dict]:
    data = _read_json(LAYOUT_FILE, {})
    # Formato antiguo (un solo mapa): {layout, cells, grid} → se asigna a la primera cámara.
    if isinstance(data, dict) and "cells" in data and "cameras" not in data:
        return {DEFAULT_CAMERA_ID: data}
    return data.get("cameras", {}) if isinstance(data, dict) else {}


EMPTY_LAYOUT = {"layout": {}, "cells": {}, "grid": {"cols": 24, "rows": 14}}


# ---------- Modelos ----------

class ParkingSpot(BaseModel):
    spot_id: str
    status: str
    confidence: float = 0.0
    timestamp: float = 0.0

class ParkingUpdate(BaseModel):
    spots: List[ParkingSpot]
    source: Optional[Literal["stream", "video", "camera"]] = None

class GridSize(BaseModel):
    cols: int
    rows: int

class LayoutPayload(BaseModel):
    layout: Dict[str, dict] = {}
    cells: Dict[str, str] = {}
    grid: GridSize = GridSize(cols=24, rows=14)

class CameraPoint(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)

class CameraZone(BaseModel):
    id: str
    points: List[CameraPoint] = Field(min_length=3)

class CameraZonesPayload(BaseModel):
    zones: List[CameraZone]

class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


# ---------- SSE ----------

class SSEConnectionManager:
    def __init__(self):
        self.active_connections: List[asyncio.Queue] = []

    async def connect(self, queue: asyncio.Queue):
        self.active_connections.append(queue)

    def disconnect(self, queue: asyncio.Queue):
        if queue in self.active_connections:
            self.active_connections.remove(queue)

    async def broadcast(self, data: dict):
        """Envía el nuevo estado a todos los clientes. Si un cliente va atrasado,
        se descarta su mensaje más viejo (solo importa el estado más reciente)."""
        for queue in self.active_connections:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(data)

manager = SSEConnectionManager()


def _summarize(spots: Dict[str, dict]) -> dict:
    return {
        "total_spots": len(spots),
        "free_spots": sum(1 for s in spots.values() if s["status"] == "free"),
        "occupied_spots": sum(1 for s in spots.values() if s["status"] == "occupied"),
        "leaving_spots": sum(1 for s in spots.values() if s["status"] == "leaving"),
    }


def build_parking_payload() -> dict:
    """Estado público: plazas de cada cámara + totales globales (no incluye fuentes ni URLs)."""
    cameras = {}
    all_spots: Dict[str, dict] = {}
    for camera in CAMERAS:
        state = camera_states[camera["id"]]
        cameras[camera["id"]] = {
            "name": camera["name"],
            "online": state.is_online(),
            "spots": state.spots,
            **_summarize(state.spots),
        }
        all_spots.update({f"{camera['id']}:{spot_id}": info for spot_id, info in state.spots.items()})
    return {"cameras": cameras, **_summarize(all_spots)}


async def broadcast_state() -> None:
    await manager.broadcast(build_parking_payload())


async def detector_watchdog():
    """Limpia el estado de una cámara si su detector deja de enviar datos."""
    while True:
        await asyncio.sleep(5)
        changed = False
        for camera_id, state in camera_states.items():
            if state.last_update and not state.is_online():
                print(f"Watchdog: cámara '{camera_id}' sin señal, reiniciando su estado.")
                state.reset()
                changed = True
        if changed:
            await broadcast_state()


def normalize_status(status: str) -> str:
    if status is None:
        return "free"
    normalized = str(status).strip().lower()
    if normalized in {"disponible", "free", "libre"}:
        return "free"
    if normalized in {"ocupado", "occupied", "busy"}:
        return "occupied"
    if normalized in {"leaving", "salida", "departing"}:
        return "leaving"
    return normalized


# ---------- General ----------

@app.get("/")
def read_root():
    return {"message": "SmartParking backend está en línea con soporte SSE."}


# ---------- Autenticación del administrador ----------

@app.post("/api/auth/login")
def login(payload: LoginPayload, request: Request):
    """Valida usuario y contraseña del administrador y entrega un token de sesión."""
    client_ip = request.client.host if request.client else "desconocido"
    username = authenticate(payload.username, payload.password, client_ip)
    token, expires_at = create_token(username)
    return {"token": token, "username": username, "expires_at": expires_at}

@app.get("/api/auth/me")
def current_admin(user: str = Depends(require_admin)):
    """Permite al frontend comprobar si su token sigue siendo válido."""
    return {"username": user}


# ---------- Estado público ----------

@app.get("/api/parking/stream")
async def parking_stream():
    """Server-Sent Events: transmite el estado de todas las cámaras en tiempo real."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    await manager.connect(queue)

    async def event_generator():
        try:
            yield f"data: {json.dumps(build_parking_payload())}\n\n"
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            manager.disconnect(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/parking/status")
def get_parking_status():
    """Consulta síncrona del estado de todas las cámaras."""
    return {"success": True, **build_parking_payload()}

@app.get("/api/cameras/{camera_id}/layout")
def get_layout(camera_id: str):
    """Mapa de distribución de un estacionamiento (celdas y ubicación de cada plaza)."""
    get_camera_state(camera_id)
    return load_all_layouts().get(camera_id, EMPTY_LAYOUT)


# ---------- Administrador ----------

@app.get("/api/cameras")
def list_cameras(_admin: str = Depends(require_admin)):
    """Lista de cámaras con su fuente activa (retransmisión o video de respaldo)."""
    result = []
    for camera in CAMERAS:
        state = camera_states[camera["id"]]
        result.append({
            "id": camera["id"],
            "name": camera["name"],
            "online": state.is_online(),
            "source": state.source if state.is_online() else None,
            "has_stream": bool(camera["stream_url"]),
            "has_fallback_video": bool(camera["fallback_video"]),
            "watch_url": camera["watch_url"],
            **_summarize(state.spots),
        })
    return {"cameras": result}

@app.get("/api/cameras/{camera_id}/stream")
async def camera_video_stream(camera_id: str, _admin: str = Depends(require_admin_query)):
    """Video MJPEG con las detecciones de una cámara."""
    state = get_camera_state(camera_id)

    async def frame_generator():
        last_frame_id = 0
        while True:
            if state.frame is not None and state.frame_id != last_frame_id:
                frame = state.frame
                last_frame_id = state.frame_id
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                    + frame
                    + b"\r\n"
                )
            await asyncio.sleep(0.04)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )

@app.put("/api/cameras/{camera_id}/zones")
def save_camera_zones(camera_id: str, payload: CameraZonesPayload, _admin: str = Depends(require_admin)):
    """Guarda los polígonos (normalizados 0–1) que definen las plazas de una cámara."""
    get_camera_state(camera_id)
    all_zones = load_all_zones()
    all_zones[camera_id] = [
        {"id": zone.id, "points": [point.model_dump() for point in zone.points]}
        for zone in payload.zones
    ]
    _write_json(CAMERA_ZONES_FILE, all_zones)
    return {"success": True, "saved_zones": len(all_zones[camera_id])}

@app.post("/api/cameras/{camera_id}/layout")
def save_layout(camera_id: str, payload: LayoutPayload, _admin: str = Depends(require_admin)):
    """Guarda el mapa de distribución de un estacionamiento."""
    get_camera_state(camera_id)
    layouts = load_all_layouts()
    layouts[camera_id] = {
        "layout": payload.layout,
        "cells": payload.cells,
        "grid": {"cols": payload.grid.cols, "rows": payload.grid.rows},
    }
    _write_json(LAYOUT_FILE, {"cameras": layouts})
    return {"success": True}

@app.post("/detect/")
async def detect(file: UploadFile = File(...), _admin: str = Depends(require_admin)):
    image_bytes = await file.read()
    result = model.predict_image(image_bytes)
    return JSONResponse(content=result)


# ---------- Detector ----------

@app.get("/api/cameras/{camera_id}/zones", dependencies=[Depends(require_admin_or_detector)])
def get_camera_zones(camera_id: str):
    """Plazas dibujadas sobre una cámara (para el administrador y el detector)."""
    get_camera_state(camera_id)
    return {"zones": load_all_zones().get(camera_id, [])}

@app.post("/api/cameras/{camera_id}/update", dependencies=[Depends(require_detector)])
async def update_camera_spots(camera_id: str, update: ParkingUpdate):
    """Recibe el estado COMPLETO de las plazas de una cámara (reemplaza el anterior)."""
    state = get_camera_state(camera_id)
    state.last_update = time.time()
    if update.source:
        state.source = update.source
    state.spots = {
        spot.spot_id: {
            "status": normalize_status(spot.status),
            "confidence": spot.confidence,
            "timestamp": spot.timestamp,
        }
        for spot in update.spots
    }
    await broadcast_state()
    return {"success": True, "updated_spots": len(update.spots)}

@app.post("/api/cameras/{camera_id}/frame", dependencies=[Depends(require_detector)])
async def update_camera_frame(camera_id: str, request: Request):
    """Recibe un frame JPEG anotado por el detector de una cámara."""
    state = get_camera_state(camera_id)
    frame = await request.body()
    if not frame:
        raise HTTPException(status_code=400, detail="El frame está vacío.")
    if len(frame) > MAX_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="El frame supera el límite de 5 MB.")
    if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
        raise HTTPException(status_code=415, detail="El frame debe estar codificado como JPEG.")
    state.frame = frame
    state.frame_id += 1
    return {"success": True, "frame_id": state.frame_id}

@app.post("/api/cameras/{camera_id}/reset", dependencies=[Depends(require_detector)])
async def reset_camera(camera_id: str):
    """Llamado por el detector al apagarse: limpia el estado de su cámara al instante."""
    get_camera_state(camera_id).reset()
    await broadcast_state()
    return {"success": True}


# ---------- Compatibilidad con detectores anteriores (primera cámara) ----------

@app.post("/api/parking/update", dependencies=[Depends(require_detector)])
async def update_parking_status_legacy(update: ParkingUpdate):
    return await update_camera_spots(DEFAULT_CAMERA_ID, update)

@app.post("/api/parking/reset", dependencies=[Depends(require_detector)])
async def reset_parking_legacy():
    return await reset_camera(DEFAULT_CAMERA_ID)

@app.post("/actualizar_estado", dependencies=[Depends(require_detector)])
async def actualizar_estado_legacy(payload: dict):
    """Detector antiguo que enviaba un diccionario {estado_plazas}."""
    spots = [
        ParkingSpot(spot_id=spot_id, status=normalize_status(status), confidence=1.0, timestamp=time.time())
        for spot_id, status in payload.get("estado_plazas", {}).items()
    ]
    return await update_camera_spots(DEFAULT_CAMERA_ID, ParkingUpdate(spots=spots))
