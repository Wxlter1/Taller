"""
Edge Computing Script - Parking Detection
Detecta estacionamientos en tiempo real para UNA cámara y envía los datos al backend.

Uso:
    python scripts/edge_detector.py --camera face

La cámara se define en cameras.json (raíz del proyecto). Por defecto (modo "auto"):
  1. intenta leer la retransmisión (stream_url);
  2. si no obtiene imagen, reproduce en bucle el video de respaldo (fallback_video);
  3. mientras usa el video, vuelve a probar la retransmisión cada cierto tiempo y,
     si responde, regresa a ella.

Variables opcionales:
  DETECTOR_SOURCE      auto (por defecto) | stream | video | camera (cámara local del equipo)
  MODEL_PATH           modelo YOLO (por defecto models/Det_V2.pt)
  BACKEND_URL          dirección del backend (por defecto http://localhost:8000)
  DETECTOR_IMAGE_SIZE  resolución de inferencia (por defecto 320)
  STREAM_RETRY_SECONDS cada cuánto se vuelve a probar la retransmisión (por defecto 60)
"""
import argparse
import os
import signal
import sys
import threading
import time

import cv2
import numpy as np
import requests
import torch
from ultralytics import YOLO

from detector_auth import detector_headers, reset_cached_key, wait_for_key

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, ROOT_DIR)
from backend.cameras import load_cameras  # noqa: E402

MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(ROOT_DIR, "models", "Det_V2.pt"))
BACKEND_URL_ENV = os.getenv("BACKEND_URL", "http://localhost:8000")
DETECTOR_SOURCE = os.getenv("DETECTOR_SOURCE", "auto").strip().lower()

STREAM_ATTEMPTS = 3            # intentos fallidos seguidos antes de pasar al video de respaldo
STREAM_RETRY_SECONDS = float(os.getenv("STREAM_RETRY_SECONDS", "60"))
STREAM_TIMEOUT_MS = 5000
UPDATE_HEARTBEAT_SECONDS = 2.0  # aunque no haya cambios, se envía el estado cada 2 s

SOURCE_LABELS = {
    "stream": "RETRANSMISION EN VIVO",
    "video": "VIDEO DE RESPALDO",
    "camera": "CAMARA LOCAL",
}


class ParkingDetector:
    def __init__(self, camera: dict, source_mode: str, model_path: str = MODEL_PATH,
                 backend_url: str = BACKEND_URL_ENV):
        self.camera = camera
        self.camera_id = camera["id"]
        self.source_mode = source_mode
        self.stream_url = camera["stream_url"]
        video = camera["fallback_video"]
        self.video_path = (video if os.path.isabs(video) else os.path.join(ROOT_DIR, video)) if video else ""

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.log(f"Dispositivo: {self.device.upper()}")
        if self.device == 'cuda':
            self.log(f"GPU: {torch.cuda.get_device_name(0)}")

        self.inference_size = int(os.getenv("DETECTOR_IMAGE_SIZE", "320"))
        if self.inference_size < 32:
            raise ValueError("DETECTOR_IMAGE_SIZE debe ser al menos 32.")

        self.model = YOLO(model_path)
        self.model.to(self.device)
        self.camera_http = requests.Session()

        self.api_base = f"{backend_url.rstrip('/')}/api/cameras/{self.camera_id}"
        self.parking_spots = {}
        self.camera_zones = []
        self.last_zones_refresh = 0.0
        self.latest_frame_lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_id = 0
        self.latest_annotated_frame = None
        self.latest_annotated_frame_id = 0
        self.last_inference_at = None
        self.inference_fps = 0.0
        self.active_source = None
        self.stream_is_back = threading.Event()
        self.last_sent_spots = None
        self.last_sent_at = 0.0

    def log(self, message: str):
        print(f"[{self.camera_id}] {message}", flush=True)

    # ------------------------------------------------------------------
    # Captura de imagen
    # ------------------------------------------------------------------

    def _store_frame(self, frame, source: str):
        frame = self._resize_frame(frame)
        with self.latest_frame_lock:
            self.latest_frame = frame
            self.latest_frame_id += 1
            if self.active_source != source:
                self.active_source = source
                self.log(f"Fuente activa: {SOURCE_LABELS[source]}")

    @staticmethod
    def _open_stream(source):
        backend = cv2.CAP_FFMPEG if isinstance(source, str) else cv2.CAP_ANY
        if isinstance(source, str):
            capture = cv2.VideoCapture(
                source, backend,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, STREAM_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, STREAM_TIMEOUT_MS],
            )
        else:
            capture = cv2.VideoCapture(source, backend)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _read_live(self, source, source_name: str, stop_event) -> bool:
        """Lee una retransmisión o cámara local hasta que se corte. Devuelve True si llegó imagen."""
        got_frames = False
        capture = None
        try:
            capture = self._open_stream(source)
            if not capture.isOpened():
                self.log("No se pudo abrir la retransmisión.")
                return False
            while not stop_event.is_set():
                ret, frame = capture.read()
                if not ret:
                    break
                got_frames = True
                self._store_frame(frame, source_name)
        except Exception as e:
            self.log(f"Error leyendo la retransmisión: {e}")
        finally:
            if capture is not None:
                capture.release()
        return got_frames

    def _play_video(self, stop_event) -> bool:
        """Reproduce el video de respaldo en bucle y a velocidad real (como una cámara).
        Termina si se pide detener o si la retransmisión vuelve a estar disponible."""
        capture = cv2.VideoCapture(self.video_path)
        if not capture.isOpened():
            self.log(f"No se pudo abrir el video de respaldo: {self.video_path}")
            return False
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        frame_interval = 1.0 / fps
        started_at = time.monotonic()
        frame_index = 0
        try:
            while not stop_event.is_set() and not self.stream_is_back.is_set():
                target = started_at + frame_index * frame_interval
                delay = target - time.monotonic()
                if delay > 0:
                    stop_event.wait(delay)
                elif delay < -frame_interval:
                    # Vamos atrasados (p. ej. video 4K en CPU): se saltan frames para no desfasarse.
                    skip = min(int(-delay / frame_interval), 30)
                    for _ in range(skip):
                        capture.grab()
                    frame_index += skip

                ret, frame = capture.read()
                if not ret:
                    # Fin del video: vuelve al inicio.
                    capture.release()
                    capture = cv2.VideoCapture(self.video_path)
                    started_at = time.monotonic()
                    frame_index = 0
                    continue
                frame_index += 1
                self._store_frame(frame, "video")
        finally:
            capture.release()
        return True

    def _probe_stream_periodically(self, stop_event):
        """Mientras se usa el video, prueba la retransmisión cada STREAM_RETRY_SECONDS."""
        while not stop_event.wait(STREAM_RETRY_SECONDS):
            capture = self._open_stream(self.stream_url)
            try:
                ok = capture.isOpened() and capture.read()[0]
            finally:
                capture.release()
            if ok:
                self.log("La retransmisión volvió a estar disponible.")
                self.stream_is_back.set()
                return

    def _capture_loop(self, stop_event):
        if self.source_mode == "camera":
            while not stop_event.is_set():
                self._read_live(0, "camera", stop_event)
                stop_event.wait(2)
            return

        use_stream = self.source_mode in {"auto", "stream"} and bool(self.stream_url)
        can_fallback = self.source_mode in {"auto", "video"} and bool(self.video_path)
        if not use_stream and not can_fallback:
            self.log("La cámara no tiene retransmisión ni video de respaldo configurados en cameras.json.")
            stop_event.set()
            return

        mode = "stream" if use_stream else "video"
        failures = 0
        while not stop_event.is_set():
            if mode == "stream":
                if self._read_live(self.stream_url, "stream", stop_event):
                    failures = 0
                else:
                    failures += 1
                if stop_event.is_set():
                    break
                if can_fallback and failures >= STREAM_ATTEMPTS:
                    self.log("Sin imagen de la retransmisión; se usará el video de respaldo.")
                    mode = "video"
                    continue
                self.log("Retransmisión interrumpida; reconectando en 2 segundos...")
                stop_event.wait(2)
            else:
                self.stream_is_back.clear()
                probe_stop = threading.Event()
                if use_stream:
                    threading.Thread(target=self._probe_stream_periodically, args=(probe_stop,), daemon=True).start()
                opened = self._play_video(stop_event)
                probe_stop.set()
                if self.stream_is_back.is_set():
                    mode = "stream"
                    failures = 0
                elif not opened:
                    stop_event.wait(5)

    # ------------------------------------------------------------------
    # Bucle principal
    # ------------------------------------------------------------------

    def run(self):
        stop_event = threading.Event()
        capture_thread = threading.Thread(target=self._capture_loop, args=(stop_event,), daemon=True)
        publisher_thread = threading.Thread(target=self._publish_latest_frames, args=(stop_event,), daemon=True)
        capture_thread.start()
        publisher_thread.start()

        last_detected_frame_id = 0
        try:
            while not stop_event.is_set():
                with self.latest_frame_lock:
                    frame_id = self.latest_frame_id
                    frame = self.latest_frame.copy() if self.latest_frame is not None else None
                    source = self.active_source

                if frame is None or frame_id == last_detected_frame_id:
                    stop_event.wait(0.01)
                    continue

                last_detected_frame_id = frame_id
                results = self._track_frame(frame)
                self._refresh_camera_zones()
                annotated_frame = self._process_detections(results[0], frame, source)
                with self.latest_frame_lock:
                    self.latest_annotated_frame = annotated_frame
                    self.latest_annotated_frame_id += 1
                self._send_update(source)
        finally:
            stop_event.set()
            capture_thread.join(timeout=2)
            publisher_thread.join(timeout=2)
            self._notify_shutdown()
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

    # ------------------------------------------------------------------
    # Comunicación con el backend
    # ------------------------------------------------------------------

    def _send_camera_frame(self, frame):
        """Publica un frame anotado para el video del administrador."""
        encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not encoded:
            self.log("✗ No se pudo codificar el frame de cámara")
            return
        try:
            response = self.camera_http.post(
                f"{self.api_base}/frame",
                data=buffer.tobytes(),
                headers={"Content-Type": "image/jpeg", **detector_headers()},
                timeout=2,
            )
            if response.status_code == 401:
                reset_cached_key()
                self.log("✗ El backend rechazó la clave del detector al enviar el frame")
            elif response.status_code != 200:
                self.log(f"✗ Error al enviar frame al backend: {response.status_code}")
        except requests.exceptions.RequestException as e:
            self.log(f"✗ Error de conexión al enviar frame: {e}")

    def _publish_latest_frames(self, stop_event):
        """Publica el último frame procesado por YOLO sin bloquear la inferencia."""
        last_frame_id = 0
        while not stop_event.is_set():
            with self.latest_frame_lock:
                frame_id = self.latest_annotated_frame_id
                frame = self.latest_annotated_frame.copy() if self.latest_annotated_frame is not None else None
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
            response = requests.get(f"{self.api_base}/zones", headers=detector_headers(), timeout=3)
            if response.status_code == 401:
                reset_cached_key()
            response.raise_for_status()
            self.camera_zones = response.json()["zones"]
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            self.log(f"✗ No se pudieron actualizar las plazas de cámara: {e}")

    def _send_update(self, source):
        """Envía el estado de las plazas cuando cambia (y como latido cada 2 s)."""
        now = time.time()
        if self.parking_spots == self.last_sent_spots and now - self.last_sent_at < UPDATE_HEARTBEAT_SECONDS:
            return
        spots_data = [
            {"spot_id": spot_id, "status": info["status"], "confidence": info["confidence"], "timestamp": now}
            for spot_id, info in self.parking_spots.items()
        ]
        try:
            response = requests.post(
                f"{self.api_base}/update",
                json={"spots": spots_data, "source": source},
                headers=detector_headers(),
                timeout=5,
            )
            if response.status_code == 401:
                reset_cached_key()
                self.log("✗ El backend rechazó la clave del detector")
            elif response.status_code == 200:
                if self.parking_spots != self.last_sent_spots:
                    free = sum(1 for s in self.parking_spots.values() if s["status"] == "free")
                    self.log(f"✓ Estado enviado: {free} libres de {len(spots_data)}")
                self.last_sent_spots = dict(self.parking_spots)
                self.last_sent_at = now
            else:
                self.log(f"✗ Error al enviar: {response.status_code}")
        except requests.exceptions.RequestException as e:
            self.log(f"✗ Error de conexión: {e}")

    def _notify_shutdown(self):
        try:
            requests.post(f"{self.api_base}/reset", headers=detector_headers(), timeout=3)
        except requests.exceptions.RequestException:
            pass

    # ------------------------------------------------------------------
    # Detección y anotación
    # ------------------------------------------------------------------

    def _process_detections(self, results, frame, source):
        """Calcula la ocupación y anota vehículos, IDs de seguimiento y plazas."""
        boxes = results.boxes
        vehicles = []
        if boxes is not None:
            track_ids = boxes.id
            for index, (box, confidence, class_id) in enumerate(zip(boxes.xyxy, boxes.conf, boxes.cls)):
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

        parking_spots = {}
        frame_height, frame_width = frame.shape[:2]
        annotated_frame = frame.copy()

        header = f"{SOURCE_LABELS.get(source, '')} | YOLO: {self.inference_fps:.1f} FPS | {self.inference_size}px"
        (text_width, _), _ = cv2.getTextSize(header, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        header_color = (80, 200, 120) if source == "stream" else (0, 190, 255)
        cv2.rectangle(annotated_frame, (8, 8), (24 + text_width, 38), (20, 20, 20), -1)
        cv2.putText(annotated_frame, header, (16, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.55, header_color, 2, cv2.LINE_AA)

        for zone in self.camera_zones:
            points = [
                (round(point["x"] * (frame_width - 1)), round(point["y"] * (frame_height - 1)))
                for point in zone["points"]
            ]
            polygon = np.array(points, dtype="int32")
            occupied_confidence = 0.0
            for vehicle in vehicles:
                center_x, center_y = vehicle["center"]
                if cv2.pointPolygonTest(polygon, (float(center_x), float(center_y)), False) >= 0:
                    occupied_confidence = max(occupied_confidence, vehicle["confidence"])

            occupied = occupied_confidence > 0
            status = "occupied" if occupied else "free"
            parking_spots[zone["id"]] = {
                "status": status,
                "confidence": round(occupied_confidence, 3) if occupied else 1.0,
            }

            color = (70, 90, 245) if occupied else (80, 200, 120)
            cv2.polylines(annotated_frame, [polygon], True, color, 2, cv2.LINE_AA)
            zone_label = (
                f"{zone['id']}  {status.upper()} {occupied_confidence:.0%}" if occupied else f"{zone['id']}  LIBRE"
            )
            label_y = max(20, points[0][1] - 8)
            cv2.putText(annotated_frame, zone_label, (points[0][0], label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

        self.parking_spots = parking_spots

        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle["box"]
            track_id = vehicle["track_id"]
            color = (
                (80, 200, 255)
                if track_id is None
                else ((80, 200, 255), (255, 170, 70), (210, 100, 240), (80, 230, 180))[track_id % 4]
            )
            track_label = f"ID {track_id}" if track_id is not None else "Vehiculo"
            label = f"{vehicle['class_name']} {track_label} {vehicle['confidence']:.0%}"
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
            cv2.circle(annotated_frame, (round(vehicle["center"][0]), round(vehicle["center"][1])), 4, color, -1)
            cv2.putText(annotated_frame, label, (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

        return annotated_frame


def _handle_sigterm(_signum, _frame):
    raise KeyboardInterrupt


def main():
    cameras = {camera["id"]: camera for camera in load_cameras()}
    parser = argparse.ArgumentParser(description="Detector de estacionamientos para una cámara.")
    parser.add_argument("--camera", default=os.getenv("CAMERA_ID"),
                        help=f"Id de la cámara en cameras.json ({', '.join(cameras)})")
    args = parser.parse_args()

    camera_id = args.camera or next(iter(cameras))
    if camera_id not in cameras:
        raise SystemExit(f"La cámara '{camera_id}' no existe en cameras.json ({', '.join(cameras)}).")
    if DETECTOR_SOURCE not in {"auto", "stream", "video", "camera"}:
        raise SystemExit("DETECTOR_SOURCE debe ser 'auto', 'stream', 'video' o 'camera'.")

    camera = cameras[camera_id]
    signal.signal(signal.SIGTERM, _handle_sigterm)

    print("\n" + "=" * 50)
    print(f"SmartParking - Edge Detector · {camera['name']} ({camera_id})")
    print("=" * 50)
    wait_for_key()
    detector = ParkingDetector(camera, DETECTOR_SOURCE)
    detector.log(f"Modelo: {MODEL_PATH}")
    detector.log(f"Modo de fuente: {DETECTOR_SOURCE}")
    detector.log(f"Retransmisión: {'configurada' if camera['stream_url'] else 'no configurada'}")
    detector.log(f"Video de respaldo: {camera['fallback_video'] or 'no configurado'}")
    detector.log(f"imgsz: {detector.inference_size} (DETECTOR_IMAGE_SIZE)")
    detector.log("Presiona Ctrl+C para detener")

    try:
        detector.run()
    except KeyboardInterrupt:
        detector.log("Detector detenido.")


if __name__ == "__main__":
    main()
