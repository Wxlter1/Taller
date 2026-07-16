import cv2
import json
import os
import time
import requests
import numpy as np
from ultralytics import YOLO
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import box as ShapelyBox

BASE_DIR = os.path.dirname(__file__)
ZONAS_PATH = os.getenv("ZONAS_PATH", os.path.join(BASE_DIR, "zonasubb2.json"))
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "../models/best.pt"))
VIDEO_PATH = os.getenv("VIDEO_PATH", os.path.join(BASE_DIR, "../videos/videoparkingubb2.mp4"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/parking/update")
BACKEND_RESET_URL = BACKEND_URL.rsplit("/", 1)[0] + "/reset"
HEADLESS = os.getenv("HEADLESS", "0").lower() not in {"0", "false", "no"}

FRAMES_TO_SKIP = 2
COVERAGE_THRESHOLD = 0.15
TIEMPO_ESPERA = 3.0
HEARTBEAT_INTERVAL = 5.0

_ultimo_envio_ts = 0.0


def enviar_estado_al_backend(estado_plazas, ultimo_estado_enviado=None):
    global _ultimo_envio_ts

    sin_cambios = ultimo_estado_enviado is not None and estado_plazas == ultimo_estado_enviado
    if sin_cambios and (time.time() - _ultimo_envio_ts) < HEARTBEAT_INTERVAL:
        return ultimo_estado_enviado

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
            _ultimo_envio_ts = time.time()
            print(f"✓ Estado enviado: {len(estado_plazas)} spots", end="\r")
            return estado_plazas.copy()
        print(f"✗ Error backend {response.status_code}", end="\r")
    except requests.exceptions.RequestException:
        print("✗ No se pudo conectar al backend", end="\r")

    return ultimo_estado_enviado


def notificar_apagado_al_backend():
    """Avisa al backend que el detector se apaga para que reinicie el mapa al instante."""
    try:
        requests.post(BACKEND_RESET_URL, timeout=3)
        print("\n✓ Backend notificado: estado reiniciado.")
    except requests.exceptions.RequestException:
        print("\n✗ No se pudo notificar el apagado (el watchdog del backend lo hará).")


def calcular_estado_zonas(zonas_guardadas, cajas):
    estado_plazas = {nombre: False for nombre in zonas_guardadas.keys()}

    for nombre_plaza, puntos_plaza in zonas_guardadas.items():
        poligono_plaza = ShapelyPolygon(puntos_plaza)
        area_plaza = poligono_plaza.area

        for caja in cajas:
            x1, y1, x2, y2 = caja.xyxy[0].cpu().numpy()
            ancho = x2 - x1
            alto = y2 - y1
            hx1 = x1 + (ancho * 0.25)
            hx2 = x2 - (ancho * 0.25)
            hy1 = y1 + (alto * 0.50)
            hy2 = y2 - (alto * 0.15)
            caja_auto = ShapelyBox(hx1, hy1, hx2, hy2)

            if not poligono_plaza.intersects(caja_auto):
                continue

            area_choque = poligono_plaza.intersection(caja_auto).area
            cobertura = area_choque / area_plaza if area_plaza > 0 else 0

            if cobertura > COVERAGE_THRESHOLD:
                estado_plazas[nombre_plaza] = True
                break

    return estado_plazas


def actualizar_estado_plazas(zonas_guardadas, deteccion_frame_actual, estado_oficial, temporizadores, tiempo_actual):
    for nombre_plaza in zonas_guardadas.keys():
        hay_auto_ahora = deteccion_frame_actual[nombre_plaza]
        estado_actual = estado_oficial[nombre_plaza]

        if estado_actual == "free" and hay_auto_ahora:
            if temporizadores[nombre_plaza] is None:
                temporizadores[nombre_plaza] = tiempo_actual
            elif (tiempo_actual - temporizadores[nombre_plaza]) >= TIEMPO_ESPERA:
                estado_oficial[nombre_plaza] = "occupied"
                temporizadores[nombre_plaza] = None

        elif estado_actual == "occupied" and not hay_auto_ahora:
            if temporizadores[nombre_plaza] is None:
                temporizadores[nombre_plaza] = tiempo_actual
                estado_oficial[nombre_plaza] = "leaving"
            elif (tiempo_actual - temporizadores[nombre_plaza]) >= TIEMPO_ESPERA:
                estado_oficial[nombre_plaza] = "free"
                temporizadores[nombre_plaza] = None

        elif estado_actual == "leaving":
            if hay_auto_ahora:
                estado_oficial[nombre_plaza] = "occupied"
                temporizadores[nombre_plaza] = None
            elif temporizadores[nombre_plaza] is not None and (tiempo_actual - temporizadores[nombre_plaza]) >= TIEMPO_ESPERA:
                estado_oficial[nombre_plaza] = "free"
                temporizadores[nombre_plaza] = None

        else:
            temporizadores[nombre_plaza] = None


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

    estado_oficial = {nombre: "free" for nombre in zonas_guardadas.keys()}
    temporizadores = {nombre: None for nombre in zonas_guardadas.keys()}
    ultimo_estado_enviado = None

    try:
        ejecutar_bucle_deteccion(zonas_guardadas, modelo, cap, estado_oficial, temporizadores, ultimo_estado_enviado)
    finally:
        cap.release()
        if not HEADLESS:
            cv2.destroyAllWindows()
        notificar_apagado_al_backend()


def ejecutar_bucle_deteccion(zonas_guardadas, modelo, cap, estado_oficial, temporizadores, ultimo_estado_enviado):
    while cap.isOpened():
        tiempo_inicio = time.time()

        exito, frame = cap.read()
        if not exito:
            print("Video finalizado. Reiniciando...")
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        for _ in range(FRAMES_TO_SKIP):
            cap.grab()

        frame = cv2.resize(frame, (1024, 768))
        frame_anotado = frame.copy()

        resultados = modelo.predict(source=frame, conf=0.4, imgsz=640, verbose=False)
        cajas = resultados[0].boxes

        deteccion_frame_actual = calcular_estado_zonas(zonas_guardadas, cajas)
        tiempo_actual = time.time()
        actualizar_estado_plazas(zonas_guardadas, deteccion_frame_actual, estado_oficial, temporizadores, tiempo_actual)

        estado_para_backend = {
            nombre: estado_oficial[nombre]
            for nombre in zonas_guardadas.keys()
        }
        ultimo_estado_enviado = enviar_estado_al_backend(estado_para_backend, ultimo_estado_enviado)

        if not HEADLESS:
            for nombre_plaza, puntos_plaza in zonas_guardadas.items():
                contorno = np.array(puntos_plaza, dtype=np.int32).reshape((-1, 1, 2))
                estado = estado_oficial[nombre_plaza]

                if estado == "occupied":
                    color_linea = (0, 0, 255)
                elif estado == "leaving":
                    color_linea = (0, 165, 255)
                else:
                    color_linea = (0, 255, 0)

                cv2.polylines(frame_anotado, [contorno], isClosed=True, color=color_linea, thickness=3)
                cx_texto = int(sum([p[0] for p in puntos_plaza]) / len(puntos_plaza))
                cy_texto = int(sum([p[1] for p in puntos_plaza]) / len(puntos_plaza))
                cv2.putText(frame_anotado, f"{nombre_plaza}: {estado}", (cx_texto - 35, cy_texto), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_linea, 2)

                if temporizadores[nombre_plaza] is not None:
                    progreso = min(1.0, (tiempo_actual - temporizadores[nombre_plaza]) / TIEMPO_ESPERA)
                    cv2.putText(frame_anotado, f"... {int(progreso * 100)}%", (cx_texto - 25, cy_texto + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

            for caja in cajas:
                x1, y1, x2, y2 = caja.xyxy[0].cpu().numpy()
                ancho = x2 - x1
                alto = y2 - y1
                hx1 = x1 + (ancho * 0.25)
                hx2 = x2 - (ancho * 0.25)
                hy1 = y1 + (alto * 0.50)
                hy2 = y2 - (alto * 0.15)
                cv2.rectangle(frame_anotado, (int(hx1), int(hy1)), (int(hx2), int(hy2)), (255, 150, 0), 2)

            tiempo_fin = time.time()
            fps = 1.0 / max(1e-6, (tiempo_fin - tiempo_inicio))
            cv2.putText(frame_anotado, f"FPS: {int(fps)}", (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.imshow("SmartParking UBB - Motor de Deteccion", frame_anotado)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            time.sleep(0.001)


if __name__ == "__main__":
    try:
        iniciar_sistema_core()
    except KeyboardInterrupt:
        print("\nDetector detenido por el usuario.")