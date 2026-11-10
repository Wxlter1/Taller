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

        self.inference_size = int(os.getenv("DETECTOR_IMAGE_SIZE", "320"))
        if self.inference_size < 32:
            raise ValueError("DETECTOR_IMAGE_SIZE debe ser al menos 32.")
        
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
        self.latest_annotated_frame = None
        self.latest_annotated_frame_id = 0
        self.last_inference_at = None
        self.inference_fps = 0.0
        
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
                    results = self._track_frame(frame)
                    self._refresh_camera_zones()
                    annotated_frame = self._process_detections(results[0], frame)
                    self._send_camera_frame(annotated_frame)
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
                results = self._track_frame(frame)
                self._refresh_camera_zones()
                annotated_frame = self._process_detections(results[0], frame)
                with self.latest_frame_lock:
                    self.latest_annotated_frame = annotated_frame
                    self.latest_annotated_frame_id += 1
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

    def _track_frame(self, frame):
        now = time.perf_counter()
        if self.last_inference_at is not None:
            elapsed = now - self.last_inference_at
            if elapsed > 0:
                self.inference_fps = 1.0 / elapsed
        self.last_inference_at = now
        return self.model.track(
            source=frame,
            conf=0.5,
            imgsz=self.inference_size,
            device=self.device,
            verbose=False,
            half=True if self.device == 'cuda' else False,
            persist=True,
            tracker="bytetrack.yaml",
        )

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
        """Publica el último frame procesado por YOLO sin bloquear la inferencia."""
        last_frame_id = 0
        while not stop_event.is_set():
            with self.latest_frame_lock:
                frame_id = self.latest_annotated_frame_id
                frame = (
                    self.latest_annotated_frame.copy()
                    if self.latest_annotated_frame is not None
                    else None
                )

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
        """Calcula la ocupación y anota vehículos, IDs de seguimiento y plazas."""
        boxes = results.boxes
        vehicles = []
        if boxes is not None:
            track_ids = boxes.id
            for index, (box, confidence, class_id) in enumerate(
                zip(boxes.xyxy, boxes.conf, boxes.cls)
            ):
                class_id = int(class_id)
                class_name = str(results.names[class_id])
                if class_name not in {"car", "vehicle"}:
                    continue
                x1, y1, x2, y2 = box.tolist()
                vehicles.append({
                    "box": (int(x1), int(y1), int(x2), int(y2)),
                    "center": ((x1 + x2) / 2, (y1 + y2) / 2),
                    "confidence": float(confidence),
                    "class_name": class_name,
                    "track_id": int(track_ids[index]) if track_ids is not None else None,
                })

        self.parking_spots = {}
        frame_height, frame_width = frame.shape[:2]
        annotated_frame = frame.copy()
        fps_label = f"YOLO: {self.inference_fps:.1f} FPS | {self.inference_size}px"
        cv2.rectangle(annotated_frame, (8, 8), (290, 38), (20, 20, 20), -1)
        cv2.putText(
            annotated_frame,
            fps_label,
            (16, 29),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        for zone in self.camera_zones:
            points = [
                (round(point["x"] * (frame_width - 1)), round(point["y"] * (frame_height - 1)))
                for point in zone["points"]
            ]
            polygon = np.array(points, dtype="int32")
            occupied_confidence = 0.0
            for vehicle in vehicles:
                center_x, center_y = vehicle["center"]
                if cv2.pointPolygonTest(
                    polygon,
                    (float(center_x), float(center_y)),
                    False,
                ) >= 0:
                    occupied_confidence = max(occupied_confidence, vehicle["confidence"])

            occupied = occupied_confidence > 0
            status = "occupied" if occupied else "free"
            self.parking_spots[zone["id"]] = {
                "status": status,
                "confidence": occupied_confidence if occupied else 1.0,
            }

            color = (70, 90, 245) if occupied else (80, 200, 120)
            cv2.polylines(annotated_frame, [polygon], True, color, 2, cv2.LINE_AA)
            zone_label = (
                f"{zone['id']}  {status.upper()} {occupied_confidence:.0%}"
                if occupied
                else f"{zone['id']}  LIBRE"
            )
            label_y = max(20, points[0][1] - 8)
            cv2.putText(
                annotated_frame,
                zone_label,
                (points[0][0], label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
                cv2.LINE_AA,
            )

        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle["box"]
            track_id = vehicle["track_id"]
            color = (
                (80, 200, 255)
                if track_id is None
                else (
                    (80, 200, 255),
                    (255, 170, 70),
                    (210, 100, 240),
                    (80, 230, 180),
                )[track_id % 4]
            )
            track_label = f"ID {track_id}" if track_id is not None else "Vehiculo"
            label = (
                f"{vehicle['class_name']} {track_label} "
                f"{vehicle['confidence']:.0%}"
            )
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
            cv2.circle(
                annotated_frame,
                (round(vehicle["center"][0]), round(vehicle["center"][1])),
                4,
                color,
                -1,
            )
            cv2.putText(
                annotated_frame,
                label,
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
                cv2.LINE_AA,
            )

        return annotated_frame
    
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
    print(f"  • imgsz: {detector.inference_size} (DETECTOR_IMAGE_SIZE)")
    if detector.device == 'cuda':
        print(f"  • Precision: FP16 (half)")
    print(f"  • Confidence threshold: 0.5")
    print("\nPresiona Ctrl+C para detener\n")

    detector.detect_from_source(source)
