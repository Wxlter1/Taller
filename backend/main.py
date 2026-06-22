import asyncio
import json
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Dict, List
from .yolo_service import YOLOService

app = FastAPI(title="SmartParking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model = YOLOService("best.pt")

# Base de datos en memoria para el estado de los estacionamientos
parking_spots: Dict[str, dict] = {}

class ParkingSpot(BaseModel):
    spot_id: str
    status: str 
    confidence: float = 0.0
    timestamp: float = 0.0

class ParkingUpdate(BaseModel):
    spots: List[ParkingSpot]

# --- GESTOR DE CONEXIONES SSE ---
class SSEConnectionManager:
    def __init__(self):
        # Almacena las colas de eventos activas de los clientes conectados
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

@app.post("/api/parking/update")
async def update_parking_status(update: ParkingUpdate):
    """Recibe actualizaciones del script de visión artificial y las transmite inmediatamente por SSE."""
    for spot in update.spots:
        parking_spots[spot.spot_id] = {
            "status": spot.status,
            "confidence": spot.confidence,
            "timestamp": spot.timestamp,
        }
    
    # Transmitir el nuevo mapa de distribución a todos los clientes web activos
    payload = build_parking_payload()
    await manager.broadcast(payload)
    
    return {"success": True, "updated_spots": len(update.spots)}

@app.get("/api/parking/stream")
async def parking_stream():
    """Endpoint Server-Sent Events (SSE) que transmite el estado del mapa de forma reactiva."""
    queue = asyncio.Queue()
    await manager.connect(queue)

    async def event_generator():
        try:
            # 1. Enviar el estado actual del mapa de inmediato al conectar por primera vez
            initial_payload = build_parking_payload()
            yield f"data: {json.dumps(initial_payload)}\n\n"

            # 2. Mantenerse esperando de forma asíncrona a que ocurran nuevos cambios distribuidos
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            # Se ejecuta cuando el usuario cierra la pestaña del navegador o pausa el monitoreo
            pass
        finally:
            manager.disconnect(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/parking/status")
def get_parking_status():
    """Fallback tradicional por si se requiere consultar el estado de forma síncrona."""
    return {"success": True, **build_parking_payload()}

@app.post("/detect/")
async def detect(file: UploadFile = File(...)):
    image_bytes = await file.read()
    result = model.predict_image(image_bytes)
    return JSONResponse(content=result)