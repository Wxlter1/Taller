import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List
from ultralytics import YOLO

class YOLOService:
    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            repo_root = Path(__file__).resolve().parents[1]
            self.model_path = repo_root / model_path

        self.model = YOLO(str(self.model_path))

    def predict_image(self, image_bytes: bytes) -> Dict[str, object]:
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if image is None:
            return {"success": False, "error": "No se pudo decodificar la imagen."}

        resultados = self.model.predict(source=image, conf=0.25, imgsz=640, verbose=False)
        detections = self._build_detections(resultados[0])

        return {
            "success": True,
            "detections": detections,
            "metadata": {"width": int(image.shape[1]), "height": int(image.shape[0])},
        }

    def _build_detections(self, result) -> List[Dict[str, object]]:
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.tolist()
        confidences = boxes.conf.tolist()
        class_ids = boxes.cls.tolist()
        names = result.names

        detections = []
        for idx, box in enumerate(xyxy):
            detections.append({
                "x1": int(box[0]),
                "y1": int(box[1]),
                "x2": int(box[2]),
                "y2": int(box[3]),
                "confidence": float(confidences[idx]),
                "class_id": int(class_ids[idx]),
                "class_name": names[int(class_ids[idx])],
            })

        return detections
