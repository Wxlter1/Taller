import cv2
import time
import json
import os
import requests
import numpy as np
from ultralytics import YOLO
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import box as ShapelyBox

BASE_DIR = os.path.dirname(__file__)
ZONAS_PATH = os.path.join(BASE_DIR, "zonas.json")
MODEL_PATH = os.path.join(BASE_DIR, "best.pt")
VIDEO_PATH = os.path.join(BASE_DIR, "video_parking2.mp4")
BACKEND_URL = "http://localhost:8000/api/parking/update"

FRAMES_TO_SKIP = 2
COVERAGE_THRESHOLD = 0.25


def enviar_estado_al_backend(estado_plazas):
    payload = {
        "spots": [
            {
                "spot_id": spot_id,
                "status": status,
                "confidence": 1.0,
                "timestamp": time.time(),
            }
            for spot_id, status in estado_plazas.items()
        ]
    }
    try:
        response = requests.post(BACKEND_URL, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"✓ Estado enviado: {len(estado_plazas)} spots", end="\r")
        else:
            print(f"✗ Error backend {response.status_code}", end="\r")
    except requests.exceptions.RequestException:
        print("✗ No se pudo conectar al backend", end="\r")


def calcular_estado_zonas(zonas_guardadas, cajas):
    estado_plazas = {nombre: "free" for nombre in zonas_guardadas.keys()}

    for nombre_plaza, puntos_plaza in zonas_guardadas.items():
        poligono_plaza = ShapelyPolygon(puntos_plaza)
        area_plaza = poligono_plaza.area

        for caja in cajas:
            x1, y1, x2, y2 = caja.xyxy[0].cpu().numpy()
            caja_auto = ShapelyBox(x1, y1, x2, y2)

            if not poligono_plaza.intersects(caja_auto):
                continue

            area_choque = poligono_plaza.intersection(caja_auto).area
            cobertura = area_choque / area_plaza if area_plaza > 0 else 0

            if cobertura > COVERAGE_THRESHOLD:
                estado_plazas[nombre_plaza] = "occupied"
                break

    return estado_plazas


def iniciar_sistema_core():
    
    try:
        with open(ZONAS_PATH, "r", encoding="utf-8") as f:
            zonas_guardadas = json.load(f)
        print(f"Zonas cargadas: {list(zonas_guardadas.keys())}")
    except FileNotFoundError:
        print(f"No se encontró el archivo de zonas: {ZONAS_PATH}")
        return

    try:
        modelo = YOLO(MODEL_PATH)
        print("Modelo YOLO cargado correctamente.")
    except Exception as e:
        print(f"Error al cargar modelo: {e}")
        return

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print("No se pudo abrir el video.")
        return

    estado_historial = {nombre: ["free", "free", "free"] for nombre in zonas_guardadas.keys()}

    while cap.isOpened():
        tiempo_inicio = time.time()
        
        exito, frame = cap.read()
        if not exito:
            print("Video finalizado.")
            break

        for _ in range(FRAMES_TO_SKIP):
            cap.grab()

        frame = cv2.resize(frame, (1024, 768))
        frame_anotado = frame.copy()

        resultados = modelo.predict(source=frame, conf=0.4, imgsz=640, verbose=False)
        cajas = resultados[0].boxes

        estado_plazas = calcular_estado_zonas(zonas_guardadas, cajas)

        for nombre_plaza, historial in estado_historial.items():
            historial.append(estado_plazas[nombre_plaza])
            if historial[-1] == "free" and historial[-2] == "occupied":
                estado_plazas[nombre_plaza] = "leaving"
            elif historial[-1] == "free" and historial[-2] == "leaving":
                estado_plazas[nombre_plaza] = "free"
            elif historial[-1] == "occupied":
                estado_plazas[nombre_plaza] = "occupied"

        enviar_estado_al_backend(estado_plazas)

        for nombre_plaza, puntos_plaza in zonas_guardadas.items():
            contorno = np.array(puntos_plaza, dtype=np.int32).reshape((-1, 1, 2))
            estado = estado_plazas[nombre_plaza]
            color_linea = (0, 255, 0) if estado == "free" else (0, 0, 255) if estado == "occupied" else (0, 165, 255)

            cv2.polylines(frame_anotado, [contorno], isClosed=True, color=color_linea, thickness=3)
            cx_texto = int(sum([p[0] for p in puntos_plaza]) / len(puntos_plaza))
            cy_texto = int(sum([p[1] for p in puntos_plaza]) / len(puntos_plaza))
            cv2.putText(frame_anotado, f"{nombre_plaza}: {estado}", (cx_texto - 35, cy_texto), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_linea, 2)

        tiempo_fin = time.time()
        fps = 1.0 / max(1e-6, (tiempo_fin - tiempo_inicio))

        print(f"Estado: {estado_plazas}")

        cv2.imshow("SmartParking UBB - Motor de Deteccion", frame_anotado)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    iniciar_sistema_core()