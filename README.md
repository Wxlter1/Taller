# SmartParking - Sistema de Detección en Tiempo Real

Sistema integral para monitoreo de estacionamientos del Campus Concepción - Universidad del Bío-Bío. 
Utiliza visión computacional (YOLO) en el edge para detección local y un backend que centraliza los datos.

## Arquitectura

### 1. **Edge Computing** (`edge_detector.py`)
- Procesa video/cámara localmente
- Detecta estacionamientos usando YOLO
- Envía solo metadatos (estado: libre, ocupado, liberándose) al backend
- Minimiza ancho de banda

### 2. **Backend FastAPI** (`backend/`)
- API RESTful para recibir actualizaciones de estado
- Almacenamiento en memoria de estado actual
- Estadísticas agregadas (total, libres, ocupados)
- Endpoints:
  - `POST /api/parking/update` - Recibe actualizaciones desde edge
  - `GET /api/parking/status` - Obtiene estado de todos los estacionamientos
  - `GET /api/parking/spot/{spot_id}` - Obtiene estado de un estacionamiento

### 3. **Frontend React** (`frontend/`)
- Interfaz web en tiempo real
- Mapa de estacionamientos con iconos de estado
- Actualización cada 2 segundos
- Controles: pausar/reanudar, estadísticas

## Instalación

### Backend

```powershell
cd d:\BackendFastApi\backend
python -m pip install -r requirements.txt
```

### Frontend

```powershell
cd d:\BackendFastApi\frontend
npm install
```

## Uso

### Iniciar todo el proyecto de una vez

**Windows:** con Python configurado en `env`, las dependencias backend instaladas y Node.js disponible, ejecuta:

```bat
start_project.bat
```

El script abre ventanas independientes para backend, detector y frontend; espera a que el backend responda antes de iniciar el detector. El detector lee la retransmisión RTSP y reintenta la conexión si se interrumpe. El frontend queda en `http://localhost:5173`.

**Servidor Linux administrado por SSH/Termius:** instala Python 3, Node.js y npm en el servidor. Una sola vez, desde la carpeta del proyecto:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && cd ..
chmod +x start_project.sh stop_project.sh
```

Luego inicia backend, detector y frontend con:

```bash
./start_project.sh
```

Abre `http://<IP-del-servidor>:5173`. Los procesos continúan en segundo plano al cerrar Termius; los registros están en `.runtime/`. Para detenerlos de forma segura:

```bash
./stop_project.sh
```

El detector publica los frames recientes en paralelo al análisis YOLO, por lo que una inferencia lenta no debe dejar el video atrasado. Los polígonos de plazas y sus estados se superponen sobre el video en vivo.

**Configurar las fuentes:**
- `CAMERA_STREAM_URL`: dirección RTSP de la cámara (por defecto, la retransmisión configurada).
- `VITE_CAMERA_WATCH_URL`: dirección HTTP que se muestra en el reproductor del frontend.
- `DETECTOR_SOURCE=video`: procesa `videos\videoparkingubb2.mp4` en lugar del stream.
- `DETECTOR_SOURCE=camera`: usa la cámara local del equipo.

El detector puede detenerse con `Ctrl+C`.

**Definir plazas sobre la cámara:**
1. Abre el frontend y espera a que aparezca el video anotado.
2. Pulsa **Marcar plazas** y haz clic en al menos tres esquinas de cada espacio de estacionamiento.
3. Pulsa **Cerrar plaza** para cada polígono y luego **Guardar plazas**.
4. El detector consulta las plazas guardadas automáticamente y dibuja el contorno verde si está libre o rojo si detecta un vehículo dentro.

Las coordenadas quedan guardadas en `backend\camera_zones.json` y se mantienen alineadas con el video. Para que una plaza pase a ocupada, el modelo debe reconocer un vehículo y su centro debe quedar dentro del polígono.

## Estados de Estacionamiento

| Icono | Estado | Significado |
|-------|--------|------------|
| 🟢 | **free** | Libre disponible |
| 🔴 | **occupied** | Ocupado por vehículo |
| 🟡 | **leaving** | Se está liberando (auto saliendo) |

## Flujo de Datos

```
Cámara (RTSP)
    ↓
Edge Detector (YOLO local)
    ↓
POST /api/parking/update (solo metadatos)
    ↓
Backend FastAPI (estado en memoria)
    ↓
SSE /api/parking/stream ──→ Frontend React (mapa y estados)
Cámara (HTTP) ─────────────→ Frontend React (video en vivo)
```

## Ventajas del Sistema

✅ **Bajo ancho de banda**: Solo metadatos, no video continuo
✅ **Tiempo real**: Actualización cada 2 segundos
✅ **Escalable**: Múltiples edge nodes → un backend central
✅ **Resiliente**: Edge continúa funcionando aunque Backend caiga
✅ **Flexible**: Soporta cámara en vivo o archivos de video

## Próximas Mejoras

- [ ] Persistencia en base de datos (PostgreSQL)
- [ ] Análisis predictivo (ML) de ocupación
- [ ] Filtros por zona/sector del campus
- [ ] Historial de ocupación
- [ ] Notificaciones de disponibilidad
- [ ] WebSocket para tiempo real sin polling
- [ ] Dashboard administrativo
- [ ] API para aplicaciones móviles
