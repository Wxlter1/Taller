"""
Edge Computing Script - Parking Detection
Detecta estacionamientos en tiempo real desde video/cámara y envía datos al backend.
Optimizado con GPU (CUDA) para mejor rendimiento.
"""
import os
import cv2
import threading
import numpy as np
import time
import requests
import torch
from ultralytics import YOLO
from typing import Union

BASE_DIR = os.path.dirname(__file__)
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "../models/best.pt"))
VIDEO_PATH = os.getenv("VIDEO_PATH", os.path.join(BASE_DIR, "../videos/videoparkingubb2.mp4"))
CAMERA_STREAM_URL = os.getenv(
    "CAMERA_STREAM_URL",
    "rtsp://146.83.194.142:1935/share-w5DiM5QUILZ3lyTd70vCnEbt6Y9IkRNG_q9D5pPxYKU",
)
DETECTOR_SOURCE = os.getenv("DETECTOR_SOURCE", "stream").strip().lower()
BACKEND_URL_ENV = os.getenv("BACKEND_URL", "http://localhost:8000")

class ParkingDetector:
    def __init__(self, model_path: str = MODEL_PATH, backend_url: str = BACKEND_URL_ENV):
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Dispositivo: {self.device.upper()}")
        if self.device == 'cuda':
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            print(f"CUDA disponible: {torch.cuda.is_available()}")
        
        self.model = YOLO(model_path)
        self.model.to(self.device)
        self.camera_http = requests.Session()
        
        self.backend_url = backend_url
        self.parking_spots = {}
        self.confidence_threshold = 0.5
        self.camera_zones = []
        self.last_zones_refresh = 0.0
        self.latest_frame_lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_id = 0
        
    def detect_from_source(self, source: Union[str, int]):
        """Detecta estacionamientos desde un archivo, una retransmisión o una cámara."""
        print(f"Iniciando detección de estacionamientos desde: {source}")

        if isinstance(source, str) and not source.lower().startswith(("rtsp://", "http://", "https://")):
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                print(f"Error: No se pudo abrir la fuente de video: {source}")
                cap.release()
                return
            try:
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        break
                    frame = self._resize_frame(frame)
                    results = self.model.predict(
                        source=frame,
                        conf=0.5,
                        imgsz=416,
                        device=self.device,
                        verbose=False,
                        half=True if self.device == 'cuda' else False,
                    )
                    self._refresh_camera_zones()
                    self._process_detections(results[0], frame)
                    self._send_camera_frame(frame)
                    self._send_update()
            finally:
                cap.release()
                self.camera_http.close()
            return

        stop_event = threading.Event()

        def capture_frames():
            while not stop_event.is_set():
                capture = None
                try:
                    backend = cv2.CAP_FFMPEG if isinstance(source, str) else cv2.CAP_ANY
                    capture = cv2.VideoCapture(source, backend)
                    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if isinstance(source, str) and hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                        capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                        capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

                    if not capture.isOpened():
                        print("No se pudo abrir la retransmisión.")
                    else:
                        while not stop_event.is_set() and capture.isOpened():
                            ret, frame = capture.read()
                            if not ret:
                                break
                            frame = self._resize_frame(frame)
                            with self.latest_frame_lock:
                                self.latest_frame = frame
                                self.latest_frame_id += 1
                except Exception as e:
                    print(f"Error leyendo la retransmisión: {e}")
                finally:
                    if capture is not None:
                        capture.release()

                if not stop_event.is_set():
                    print("Retransmisión interrumpida; reconectando en 2 segundos...")
                    stop_event.wait(2)

        capture_thread = threading.Thread(target=capture_frames, daemon=True)
        publisher_thread = threading.Thread(
            target=self._publish_latest_frames,
            args=(stop_event,),
            daemon=True,
        )
        capture_thread.start()
        publisher_thread.start()

        last_detected_frame_id = 0
        try:
            while not stop_event.is_set():
                with self.latest_frame_lock:
                    frame_id = self.latest_frame_id
                    frame = self.latest_frame.copy() if self.latest_frame is not None else None

                if frame is None or frame_id == last_detected_frame_id:
                    stop_event.wait(0.01)
                    continue

                last_detected_frame_id = frame_id
                results = self.model.predict(
                    source=frame,
                    conf=0.5,
                    imgsz=416,
                    device=self.device,
                    verbose=False,
                    half=True if self.device == 'cuda' else False,
                )
                self._refresh_camera_zones()
                self._process_detections(results[0], frame)
                self._send_update()
        finally:
            stop_event.set()
            capture_thread.join(timeout=2)
            publisher_thread.join(timeout=2)
            self.camera_http.close()

    @staticmethod
    def _resize_frame(frame):
        source_height, source_width = frame.shape[:2]
        output_width = min(960, source_width)
        output_height = round(output_width * source_height / source_width)
        return cv2.resize(frame, (output_width, output_height))

    def detect_from_video(self, video_path: str):
        """Detecta estacionamientos desde un archivo de video."""
        self.detect_from_source(video_path)
    
    def detect_from_camera(self, camera_id: int = 0):
        """Detecta estacionamientos desde una cámara en vivo."""
        self.detect_from_source(camera_id)

    def _send_camera_frame(self, frame):
        """Publica un frame reciente sin esperar a la inferencia de YOLO."""
        encoded, buffer = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 75],
        )
        if not encoded:
            print("✗ No se pudo codificar el frame de cámara")
            return

        try:
            response = self.camera_http.post(
                f"{self.backend_url}/api/camera/frame",
                data=buffer.tobytes(),
                headers={"Content-Type": "image/jpeg"},
                timeout=2,
            )
            if response.status_code != 200:
                print(f"✗ Error al enviar frame al backend: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"✗ Error de conexión al enviar frame: {e}")

    def _publish_latest_frames(self, stop_event):
        """Publica continuamente el último frame, independientemente de YOLO."""
        last_frame_id = 0
        while not stop_event.is_set():
            with self.latest_frame_lock:
                frame_id = self.latest_frame_id
                frame = self.latest_frame.copy() if self.latest_frame is not None else None

            if frame is not None and frame_id != last_frame_id:
                self._send_camera_frame(frame)
                last_frame_id = frame_id
            else:
                stop_event.wait(0.02)
    
    def _refresh_camera_zones(self):
        """Actualiza periódicamente las plazas configuradas desde el backend."""
        if time.time() - self.last_zones_refresh < 5:
            return
        self.last_zones_refresh = time.time()
        try:
            response = requests.get(
                f"{self.backend_url}/api/camera/zones",
                timeout=3,
            )
            response.raise_for_status()
            self.camera_zones = response.json()["zones"]
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            print(f"✗ No se pudieron actualizar las plazas de cámara: {e}")

    def _process_detections(self, results, frame):
        """Determina si las plazas configuradas contienen vehículos detectados."""
        boxes = results.boxes
        vehicles = []
        if boxes is not None:
            for box, confidence, class_id in zip(boxes.xyxy, boxes.conf, boxes.cls):
                class_name = results.names[int(class_id)]
                if class_name not in {"car", "vehicle"}:
                    continue
                x1, y1, x2, y2 = box.tolist()
                vehicles.append(((x1 + x2) / 2, (y1 + y2) / 2, float(confidence)))

        self.parking_spots = {}
        frame_height, frame_width = frame.shape[:2]
        for zone in self.camera_zones:
            points = [
                (round(point["x"] * (frame_width - 1)), round(point["y"] * (frame_height - 1)))
                for point in zone["points"]
            ]
            polygon = np.array(points, dtype="int32")
            occupied_confidence = 0.0
            for center_x, center_y, confidence in vehicles:
                if cv2.pointPolygonTest(
                    polygon,
                    (float(center_x), float(center_y)),
                    False,
                ) >= 0:
                    occupied_confidence = max(occupied_confidence, confidence)

            occupied = occupied_confidence > 0
            status = "occupied" if occupied else "free"
            self.parking_spots[zone["id"]] = {
                "status": status,
                "confidence": occupied_confidence if occupied else 1.0,
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

    detector = ParkingDetector()
    if DETECTOR_SOURCE == "stream":
        source = CAMERA_STREAM_URL
    elif DETECTOR_SOURCE == "video":
        source = VIDEO_PATH
    elif DETECTOR_SOURCE == "camera":
        source = 0
    else:
        raise ValueError(
            "DETECTOR_SOURCE debe ser 'stream', 'video' o 'camera'."
        )

    print("\nOptimizaciones aplicadas:")
    print(f"  • Modelo: {MODEL_PATH}")
    print(f"  • Fuente: {source}")
    print(f"  • Dispositivo: {detector.device.upper()}")
    print(f"  • imgsz: 416 (reducido de 640 para velocidad)")
    if detector.device == 'cuda':
        print(f"  • Precision: FP16 (half)")
    print(f"  • Confidence threshold: 0.5")
    print("\nPresiona Ctrl+C para detener\n")

    detector.detect_from_source(source)
