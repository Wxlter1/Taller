import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, List
from .yolo_service import YOLOService

@asynccontextmanager
async def lifespan(app: FastAPI):
    watchdog_task = asyncio.create_task(detector_watchdog())
    yield
    watchdog_task.cancel()

app = FastAPI(title="SmartParking API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model = YOLOService("models/best.pt")


parking_spots: Dict[str, dict] = {}


DETECTOR_TIMEOUT = 15.0 
last_update_time: float = 0.0
latest_camera_frame: bytes | None = None
latest_camera_frame_id = 0


DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent)))
LAYOUT_FILE = DATA_DIR / "layout.json"
CAMERA_ZONES_FILE = DATA_DIR / "camera_zones.json"

def load_layout_from_disk() -> dict:
    if LAYOUT_FILE.exists():
        try:
            return json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"layout": {}, "cells": {}, "grid": {"cols": 24, "rows": 14}}

def save_layout_to_disk(data: dict) -> None:
    LAYOUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_camera_zones() -> list[dict]:
    if not CAMERA_ZONES_FILE.exists():
        return []
    return json.loads(CAMERA_ZONES_FILE.read_text(encoding="utf-8"))

class ParkingSpot(BaseModel):
    spot_id: str
    status: str 
    confidence: float = 0.0
    timestamp: float = 0.0

class ParkingUpdate(BaseModel):
    spots: List[ParkingSpot]

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


class SSEConnectionManager:
    def __init__(self):
        
        self.active_connections: List[asyncio.Queue] = []

    async def connect(self, queue: asyncio.Queue):
        self.active_connections.append(queue)

    def disconnect(self, queue: asyncio.Queue):
        if queue in self.active_connections:
            self.active_connections.remove(queue)

    async def broadcast(self, data: dict):
        """Envía el nuevo estado a todas las aplicaciones cliente conectadas en tiempo real."""
        for queue in self.active_connections:
            await queue.put(data)

manager = SSEConnectionManager()

async def _reset_parking_state():
    """Limpia el estado en memoria y notifica a todos los clientes conectados."""
    parking_spots.clear()
    await manager.broadcast(build_parking_payload())

async def detector_watchdog():
    """Reinicia el estado si el detector deja de enviar updates (modelo apagado)."""
    global last_update_time
    while True:
        await asyncio.sleep(5)
        if parking_spots and last_update_time and (time.time() - last_update_time) > DETECTOR_TIMEOUT:
            print("Watchdog: detector sin señal, reiniciando estado de estacionamientos.")
            await _reset_parking_state()


def build_parking_payload():
    """Genera el diccionario de respuesta estandarizado con métricas globales."""
    return {
        "spots": parking_spots,
        "total_spots": len(parking_spots),
        "free_spots": sum(1 for s in parking_spots.values() if s["status"] == "free"),
        "occupied_spots": sum(1 for s in parking_spots.values() if s["status"] == "occupied"),
        "leaving_spots": sum(1 for s in parking_spots.values() if s["status"] == "leaving"),
    }

@app.get("/")
def read_root():
    return {"message": "SmartParking backend está en línea con soporte SSE."}

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

@app.post("/api/parking/update")
async def update_parking_status(update: ParkingUpdate):
    """Recibe actualizaciones del script de visión artificial y las transmite inmediatamente por SSE.

    El detector siempre envía la foto COMPLETA de sus zonas, por lo que el estado
    se reemplaza entero: así no quedan spots fantasma de corridas anteriores con
    otros archivos de zonas."""
    global last_update_time
    last_update_time = time.time()
    nuevo_estado = {
        spot.spot_id: {
            "status": normalize_status(spot.status),
            "confidence": spot.confidence,
            "timestamp": spot.timestamp,
        }
        for spot in update.spots
    }
    parking_spots.clear()
    parking_spots.update(nuevo_estado)

    payload = build_parking_payload()
    await manager.broadcast(payload)

    return {"success": True, "updated_spots": len(update.spots)}

@app.post("/actualizar_estado")
async def actualizar_estado_legacy(payload: dict):
    """Compatibilidad con el detector anterior que enviaba un diccionario {estado_plazas}."""
    estado_plazas = payload.get("estado_plazas", {})
    spots = [
        ParkingSpot(
            spot_id=spot_id,
            status=normalize_status(status),
            confidence=1.0,
            timestamp=time.time(),
        )
        for spot_id, status in estado_plazas.items()
    ]
    return await update_parking_status(ParkingUpdate(spots=spots))

@app.get("/api/parking/stream")
async def parking_stream():
    """Endpoint Server-Sent Events (SSE) que transmite el estado del mapa de forma reactiva."""
    queue = asyncio.Queue()
    await manager.connect(queue)

    async def event_generator():
        try:
            initial_payload = build_parking_payload()
            yield f"data: {json.dumps(initial_payload)}\n\n"

            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            manager.disconnect(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/camera/frame")
async def update_camera_frame(request: Request):
    """Recibe un frame JPEG anotado por el detector edge."""
    global latest_camera_frame, latest_camera_frame_id
    frame = await request.body()
    if not frame:
        raise HTTPException(status_code=400, detail="El frame está vacío.")
    if len(frame) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="El frame supera el límite de 5 MB.")
    if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
        raise HTTPException(status_code=415, detail="El frame debe estar codificado como JPEG.")

    latest_camera_frame = frame
    latest_camera_frame_id += 1
    return {"success": True, "frame_id": latest_camera_frame_id}

@app.get("/api/camera/stream")
async def camera_video_stream():
    """Sirve los últimos frames anotados como un stream MJPEG para el navegador."""
    async def frame_generator():
        last_frame_id = 0
        while True:
            if latest_camera_frame is not None and latest_camera_frame_id != last_frame_id:
                frame = latest_camera_frame
                last_frame_id = latest_camera_frame_id
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

@app.get("/api/camera/zones")
def get_camera_zones():
    """Devuelve las plazas dibujadas por el usuario sobre la cámara."""
    return {"zones": load_camera_zones()}

@app.put("/api/camera/zones")
def save_camera_zones(payload: CameraZonesPayload):
    """Guarda los polígonos normalizados que definen las plazas de la cámara."""
    zones = [
        {"id": zone.id, "points": [point.model_dump() for point in zone.points]}
        for zone in payload.zones
    ]
    CAMERA_ZONES_FILE.write_text(
        json.dumps(zones, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"success": True, "saved_zones": len(zones)}

@app.post("/api/parking/reset")
async def reset_parking():
    """Llamado por el detector al apagarse: reinicia el estado sin esperar al watchdog."""
    await _reset_parking_state()
    return {"success": True}

@app.get("/api/parking/status")
def get_parking_status():
    """Fallback tradicional por si se requiere consultar el estado de forma síncrona."""
    return {"success": True, **build_parking_payload()}


@app.get("/api/parking/layout")
def get_layout():
    """Devuelve la matriz guardada: qué celdas son estacionamiento/calle y dónde
    quedó ubicado cada spot_id real reportado por la cámara."""
    return load_layout_from_disk()

@app.post("/api/parking/layout")
def save_layout(payload: LayoutPayload):
    """Guarda la matriz definida en el editor (delimitación del estacionamiento)."""
    data = {
        "layout": payload.layout,
        "cells": payload.cells,
        "grid": {"cols": payload.grid.cols, "rows": payload.grid.rows},
    }
    save_layout_to_disk(data)
    return {"success": True}

@app.post("/detect/")
async def detect(file: UploadFile = File(...)):
    image_bytes = await file.read()
    result = model.predict_image(image_bytes)
    return JSONResponse(content=result)