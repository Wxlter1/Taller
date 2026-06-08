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

### 1. Iniciar el Backend

```powershell
cd d:\BackendFastApi
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Iniciar el Edge Detector

En otra terminal (con el entorno activado):

```powershell
cd d:\BackendFastApi
python edge_detector.py
```

El script procesará el video (`video_dia.mp4`) y enviará actualizaciones al backend.

**Alternativas:**
- Cambiar la línea final de `edge_detector.py` para usar cámara en vivo:
  ```python
  detector.detect_from_camera(0)  # 0 = primera cámara
  ```

### 3. Iniciar el Frontend

```powershell
cd d:\BackendFastApi\frontend
npm run dev
```

Abre `http://localhost:5173`

## Estados de Estacionamiento

| Icono | Estado | Significado |
|-------|--------|------------|
| 🟢 | **free** | Libre disponible |
| 🔴 | **occupied** | Ocupado por vehículo |
| 🟡 | **leaving** | Se está liberando (auto saliendo) |

## Flujo de Datos

```
Cámara/Video
    ↓
Edge Detector (YOLO local)
    ↓
POST /api/parking/update (solo metadatos)
    ↓
Backend FastAPI (estado en memoria)
    ↓
GET /api/parking/status (polling cada 2s)
    ↓
Frontend React (visualización mapa)
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
