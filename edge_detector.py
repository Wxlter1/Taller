"""
Edge Computing Script - Parking Detection
Detecta estacionamientos en tiempo real desde video/cámara y envía datos al backend.
Optimizado con GPU (CUDA) para mejor rendimiento.
"""
import os
import cv2
import time
import requests
import json
import torch
from ultralytics import YOLO
from typing import List, Dict

class ParkingDetector:
    def __init__(self, model_path: str, backend_url: str = "http://localhost:8000"):
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Dispositivo: {self.device.upper()}")
        if self.device == 'cuda':
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            print(f"CUDA disponible: {torch.cuda.is_available()}")
        
        self.model = YOLO(model_path)
        self.model.to(self.device)
        
        self.backend_url = os.getenv("BACKEND_URL", backend_url)
        self.parking_spots = {}
        self.confidence_threshold = 0.5
        
    def detect_from_video(self, video_path: str):
        """Detecta estacionamientos desde un archivo de video."""
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            print("Error: No se pudo abrir el video.")
            return
        
        frame_count = 0
        frames_to_skip = 2
        
        print("Iniciando detección de estacionamientos...")
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            

            if frame_count % (frames_to_skip + 1) != 0:
                frame_count += 1
                continue
            

            frame = cv2.resize(frame, (800, 600))
            

            results = self.model.predict(
                source=frame,
                conf=0.5,
                imgsz=416, 
                device=self.device,
                verbose=False,
                half=True if self.device == 'cuda' else False  # fp16 en GPU
            )
            

            self._process_detections(results[0], frame)
            

            annotated_frame = results[0].plot()
            cv2.imshow("Detección de Estacionamientos", annotated_frame)
            

            self._send_update()
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            
            frame_count += 1
        
        cap.release()
        cv2.destroyAllWindows()
    
    def detect_from_camera(self, camera_id: int = 0):
        """Detecta estacionamientos desde una cámara en vivo."""
        cap = cv2.VideoCapture(camera_id)
        
        if not cap.isOpened():
            print("Error: No se pudo acceder a la cámara.")
            return
        
        print("Iniciando detección en vivo desde cámara...")
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            

            results = self.model.predict(
                source=frame,
                conf=0.5,
                imgsz=416,
                device=self.device,
                verbose=False,
                half=True if self.device == 'cuda' else False
            )
            self._process_detections(results[0], frame)
            
            annotated_frame = results[0].plot()
            cv2.imshow("Detección en Vivo", annotated_frame)
            
            self._send_update()
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        cap.release()
        cv2.destroyAllWindows()
    
    def _process_detections(self, results, frame):
        """Procesa las detecciones YOLO para identificar estacionamientos."""
        boxes = results.boxes
        if boxes is None or len(boxes) == 0:
            return
        
        for idx, (box, conf, cls_id) in enumerate(zip(boxes.xyxy, boxes.conf, boxes.cls)):
            x1, y1, x2, y2 = box.tolist()
            class_name = results.names[int(cls_id)]
            confidence = float(conf)
            

            spot_id = f"spot_{idx}"
            

            if class_name == "car":
                status = "occupied"
            elif class_name == "empty":
                status = "free"
            else:
                status = "unknown"
            

            self.parking_spots[spot_id] = {
                "status": status,
                "confidence": confidence,
                "class": class_name,
                "coords": {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}
            }
    
    def _send_update(self):
        """Envía la actualización de estacionamientos al backend."""
        if not self.parking_spots:
            return
        

        spots_data = []
        current_time = time.time()
        
        for spot_id, info in self.parking_spots.items():
            spots_data.append({
                "spot_id": spot_id,
                "status": info["status"],
                "confidence": info["confidence"],
                "timestamp": current_time
            })
        
  
        try:
            response = requests.post(
                f"{self.backend_url}/api/parking/update",
                json={"spots": spots_data},
                timeout=5
            )
            if response.status_code == 200:
                print(f"✓ Enviadas {len(spots_data)} actualizaciones de estacionamientos")
            else:
                print(f"✗ Error al enviar: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"✗ Error de conexión: {e}")


if __name__ == "__main__":
    print("\n" + "="*50)
    print("SmartParking - Edge Detector")
    print("="*50)
    
    detector = ParkingDetector("best.pt")
    
    print("\nOptimizaciones aplicadas:")
    print(f"  • Dispositivo: {detector.device.upper()}")
    print(f"  • imgsz: 416 (reducido de 640 para velocidad)")
    if detector.device == 'cuda':
        print(f"  • Precision: FP16 (half)")
    print(f"  • Confidence threshold: 0.5")
    print("\nPresiona 'Q' en la ventana de video para detener\n")
    

    detector.detect_from_video("video_dia.mp4")
    
    # para usar la camara en vivo es este codigo
    # detector.detect_from_camera(0)
