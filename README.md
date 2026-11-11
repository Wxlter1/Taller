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

**Servidor Linux administrado por SSH/Termius (publicado con HTTPS):** ver la sección [Publicar con HTTPS en el servidor](#publicar-con-https-en-el-servidor).

El detector publica en paralelo los frames ya analizados por YOLO, para que el envío del video no bloquee la inferencia. La retransmisión muestra las cajas de los vehículos, su ID de seguimiento y confianza, además del estado y contorno de cada plaza. Al entrar el centro de un vehículo en una plaza, el detector informa su estado como ocupado al backend; el frontend actualiza el mapa y los estados en vivo.

**Variables sensibles (`.env`):** los enlaces de las cámaras, el dominio y las claves van en el archivo `.env` de la raíz, que **no se sube al repositorio**. La primera vez, copia la plantilla y completa los valores:

```bat
copy .env.example .env
```

El backend, los detectores y `start_project.sh` leen `.env` automáticamente. Si una variable de cámara queda vacía, esa cámara usa solo su video de respaldo.

**Configurar las cámaras (`cameras.json`):** cada cámara corresponde a un estacionamiento del plano y define:
- `id`: identificador corto (`face`, `ac`), el mismo que usa `cameraId` en `frontend/src/campusAreas.js`.
- `stream_url`: retransmisión RTSP/HTTP. Se escribe como referencia a `.env`, por ejemplo `"${CAMERA_FACE_STREAM_URL}"`, para que la dirección real no quede en el repositorio.
- `fallback_video`: video que se reproduce en bucle si la retransmisión no entrega imagen.
- `watch_url`: enlace "Cámara original" (también desde `.env`); solo lo ve el administrador.

Para agregar una cámara: añade su entrada en `cameras.json`, sus variables en `.env` y `.env.example` (esta última sin valores reales) y su área en `campusAreas.js`.

`scripts/run_detectors.py` (lo usan `start_project.bat` y `start_project.sh`) inicia un detector por cámara y lo reinicia si se cae. Cada detector intenta primero la retransmisión; tras 3 intentos sin imagen pasa al video de respaldo y cada 60 s (`STREAM_RETRY_SECONDS`) vuelve a probar la retransmisión. En el panel de cámaras, el administrador ve qué fuente usa cada una.

Para ejecutar un solo detector: `env\Scripts\python.exe -u scripts\edge_detector.py --camera ac`.
- `DETECTOR_SOURCE=video`: usa solo el video de respaldo; `stream`: solo la retransmisión; `camera`: la cámara local del equipo.
- `DETECTOR_IMAGE_SIZE`: resolución de inferencia YOLO; por defecto `320`. Un valor menor suele aumentar los FPS, pero puede reducir la detección de vehículos pequeños o lejanos. El video muestra los FPS de análisis actuales.

El detector puede detenerse con `Ctrl+C`.

**Definir plazas sobre la cámara:**
1. Abre el frontend y espera a que aparezca el video anotado.
2. Pulsa **Marcar plazas** y haz clic en al menos tres esquinas de cada espacio de estacionamiento.
3. Pulsa **Cerrar plaza** para cada polígono y luego **Guardar plazas**.
4. El detector consulta las plazas guardadas automáticamente y dibuja el contorno verde si está libre o rojo si detecta un vehículo dentro.

Las coordenadas quedan guardadas en `backend\camera_zones.json` y se mantienen alineadas con el video. Para que una plaza pase a ocupada, el modelo debe reconocer un vehículo y su centro debe quedar dentro del polígono.

## Publicar con HTTPS en el servidor

En el servidor, [Caddy](https://caddyserver.com) es el único punto de entrada: sirve la página por HTTPS (puerto 443) y reenvía `/api/...` al backend. El backend escucha solo en `127.0.0.1`, por lo que no es accesible desde fuera del servidor.

### Una sola vez

```bash
# 1. Dependencias del sistema (Ubuntu/Debian)
sudo apt install -y python3-venv nodejs npm caddy
sudo systemctl disable --now caddy          # el proyecto inicia su propio Caddy
sudo setcap cap_net_bind_service=+ep "$(command -v caddy)"   # permite usar los puertos 80/443 sin sudo

# 2. Dependencias del proyecto
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && cd ..
chmod +x start_project.sh stop_project.sh

# 3. Cuenta de administrador
.venv/bin/python -m backend.create_admin

# 4. Configuración
cp .env.example .env
nano .env
```

En `.env` (además de los enlaces de las cámaras):

- **Con dominio** (recomendado): crea en tu proveedor de dominio un registro **A** que apunte a la IP del servidor y usa
  ```
  SITE_ADDRESS="smartparking.midominio.cl"
  CADDY_TLS="tu-correo@midominio.cl"
  ```
  Caddy obtiene y renueva solo un certificado gratuito de Let's Encrypt. Requiere que los puertos **80 y 443** del servidor estén abiertos a internet (pídeselo al área de TI si la red de la universidad los bloquea).
- **Solo con IP** (mientras no tengas dominio):
  ```
  SITE_ADDRESS="https://200.1.2.3"
  CADDY_TLS="internal"
  ```
  La conexión va cifrada, pero el navegador mostrará una advertencia de certificado la primera vez.

### Iniciar y detener

```bash
./start_project.sh    # compila el frontend e inicia backend, detector y Caddy
./stop_project.sh
```

Los procesos siguen en segundo plano al cerrar Termius; los registros están en `.runtime/`.

### Seguridad

- **Administrador:** la contraseña se guarda cifrada en `backend/admin.json`; la sesión dura 8 horas.
- **Detector:** el backend genera una clave en `backend/.detector_key` y solo acepta estados de plazas y frames que la incluyan. El detector la lee automáticamente porque corre en el mismo servidor. Si se ejecuta en otro equipo, copia el contenido de ese archivo a la variable `DETECTOR_API_KEY` del detector.
- `admin.json`, `.auth_secret`, `.detector_key` y `.env` no se suben al repositorio.

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
