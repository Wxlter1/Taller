import cv2
import json
import numpy as np
import os

puntos_actuales = []
zonas_guardadas = {}
contador_plaza = 1
frame_limpio = None

def cargar_historial(archivo_json):
    global zonas_guardadas, contador_plaza
    
    if os.path.exists(archivo_json):
        with open(archivo_json, "r") as f:
            zonas_guardadas = json.load(f)
            
        print(f"Historial cargado: Se encontraron {len(zonas_guardadas)} plazas guardadas.")
        
        if zonas_guardadas:

            numeros = [int(nombre[1:]) for nombre in zonas_guardadas.keys() if nombre.startswith('A') and nombre[1:].isdigit()]
            if numeros:
                contador_plaza = max(numeros) + 1
                print(f"El proximo espacio a mapear será el A{contador_plaza}")
    else:
        print("No se encontró historial previo. Iniciando un mapeo en blanco.")

def manejar_clics(event, x, y, flags, param):
    global puntos_actuales, zonas_guardadas, contador_plaza, frame_limpio
    

    if event == cv2.EVENT_LBUTTONDOWN:
        puntos_actuales.append([x, y])
        

        if len(puntos_actuales) == 4:
            nombre_plaza = f"A{contador_plaza}"
            zonas_guardadas[nombre_plaza] = puntos_actuales.copy()
            print(f"Plaza {nombre_plaza} guardada exitosamente.")
            
            contador_plaza += 1
            puntos_actuales.clear()


    elif event == cv2.EVENT_RBUTTONDOWN:
        plaza_a_borrar = None
        

        for nombre, puntos in zonas_guardadas.items():
            contorno = np.array(puntos, dtype=np.int32)
   
            if cv2.pointPolygonTest(contorno, (x, y), False) >= 0:
                plaza_a_borrar = nombre
                break 
                
        if plaza_a_borrar:
            del zonas_guardadas[plaza_a_borrar]
            print(f"Plaza {plaza_a_borrar} eliminada correctamente.")

def iniciar_mapeador():
    global frame_limpio, puntos_actuales, zonas_guardadas
    
    ruta_video = "./scripts/video_parking2.mp4" 
    archivo_salida = "./scripts/zonas.json"
    
    if not os.path.exists(ruta_video):
        print(f"No se encontró el video '{ruta_video}'.")
        return

    cargar_historial(archivo_salida)

    cap = cv2.VideoCapture(ruta_video)
    exito, frame = cap.read()
    cap.release()

    if not exito:
        print("No se pudo leer el video.")
        return


    frame = cv2.resize(frame, (1024, 768))
    frame_limpio = frame.copy()

    # --- ARREGLO DEL BUG DE OPENCV ---
    # Usamos una variable con un nombre sin espacios para forzar a OpenCV a usar una sola ventana
    ventana = "Mapeador"
    cv2.namedWindow(ventana)
    cv2.setMouseCallback(ventana, manejar_clics)

    print("\ninstrucciones")
    print("CLIC IZQUIERDO: Marca 4 esquinas para crear una plaza.")
    print("CLIC DERECHO: Haz clic dentro de una plaza verde para eliminarla.")
    print("Presiona 'z': Deshacer el ultimo clic suelto.")
    print("Presiona 's': gurdar historial y salir.")
    print("-----------------------------------------\n")

    while True:
        frame_mostrar = frame_limpio.copy()


        for nombre, puntos in zonas_guardadas.items():
            pts = np.array(puntos, np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame_mostrar, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
            
            cx = int(sum([p[0] for p in puntos]) / 4)
            cy = int(sum([p[1] for p in puntos]) / 4)
            cv2.putText(frame_mostrar, nombre, (cx - 15, cy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)


        for i, punto in enumerate(puntos_actuales):
            cv2.circle(frame_mostrar, tuple(punto), 5, (0, 0, 255), -1)
            if i > 0:
                cv2.line(frame_mostrar, tuple(puntos_actuales[i-1]), tuple(punto), (0, 0, 255), 2)

  
        cv2.imshow(ventana, frame_mostrar)

        tecla = cv2.waitKey(20) & 0xFF
        
        if tecla == ord('s'): 
            with open(archivo_salida, "w") as archivo:
                json.dump(zonas_guardadas, archivo, indent=4)
            print(f"\nMapeo completado. Archivo '{archivo_salida}' actualizado con {len(zonas_guardadas)} plazas.")
            break
            
        elif tecla == ord('z'): 
            if len(puntos_actuales) > 0:
                puntos_actuales.pop()
                print("Punto deshecho.")

    cv2.destroyAllWindows()

if __name__ == "__main__":
    iniciar_mapeador()