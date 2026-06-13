from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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


parking_spots: Dict[str, dict] = {}


class ParkingSpot(BaseModel):
    spot_id: str
    status: str 
    confidence: float = 0.0
    timestamp: float = 0.0


class ParkingUpdate(BaseModel):
    spots: List[ParkingSpot]


@app.get("/")
def read_root():
    return {"message": "SmartParking backend esta en linea."}


@app.post("/api/parking/update")
async def update_parking_status(update: ParkingUpdate):
    """Recibe actualizaciones de estado de estacionamientos."""
    for spot in update.spots:
        parking_spots[spot.spot_id] = {
            "status": spot.status,
            "confidence": spot.confidence,
            "timestamp": spot.timestamp,
        }
    return {"success": True, "updated_spots": len(update.spots)}


@app.get("/api/parking/status")
def get_parking_status():
    """Obtiene el estado actual de todos los estacionamientos."""
    return {
        "success": True,
        "spots": parking_spots,
        "total_spots": len(parking_spots),
        "free_spots": sum(1 for s in parking_spots.values() if s["status"] == "free"),
        "occupied_spots": sum(1 for s in parking_spots.values() if s["status"] == "occupied"),
        "leaving_spots": sum(1 for s in parking_spots.values() if s["status"] == "leaving"),
    }


@app.get("/api/parking/spot/{spot_id}")
def get_spot_status(spot_id: str):
    """Obtiene el estado de un estacionamiento específico."""
    if spot_id not in parking_spots:
        return {"success": False, "error": "Estacionamiento no encontrado."}
    return {"success": True, "spot_id": spot_id, **parking_spots[spot_id]}


@app.post("/detect/")
async def detect(file: UploadFile = File(...)):
    image_bytes = await file.read()
    result = model.predict_image(image_bytes)
    return JSONResponse(content=result)
