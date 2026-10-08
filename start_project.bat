@echo off
setlocal

cd /d "%~dp0"

echo ==========================================
echo SmartParking - Inicio de todos los servicios
echo ==========================================
echo.

if not exist "env\Scripts\python.exe" (
    echo.
    echo No se encontro el entorno Python en env\Scripts\python.exe.
    echo Crea/configura el entorno e instala backend\requirements.txt primero.
    pause
    exit /b 1
)

if not exist "models\best.pt" (
    echo No se encontro el modelo models\best.pt.
    pause
    exit /b 1
)

env\Scripts\python.exe -m uvicorn --version >nul 2>nul
if errorlevel 1 (
    echo No se encontro Uvicorn en el entorno env.
    echo Instala primero las dependencias con:
    echo   env\Scripts\python.exe -m pip install -r backend\requirements.txt
    pause
    exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
    echo No se encontro Node.js en PATH.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo Instalando dependencias del frontend...
    pushd frontend
    call npm install
    if errorlevel 1 (
        popd
        echo No se pudieron instalar las dependencias del frontend.
        pause
        exit /b 1
    )
    popd
)

echo.
echo Iniciando backend...
start "SmartParking Backend" /D "%~dp0" cmd /k "env\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

echo Esperando que el backend arranque...
set "BACKEND_READY="
for /L %%i in (1,1,30) do (
    powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
    if not errorlevel 1 (
        set "BACKEND_READY=1"
        goto backend_ready
    )
    timeout /t 1 /nobreak >nul
)

:backend_ready
if not defined BACKEND_READY (
    echo El backend no respondio a tiempo. El detector intentara reconectarse de todos modos.
)

echo Iniciando detector...
start "SmartParking Detector" /D "%~dp0" cmd /k "set BACKEND_URL=http://127.0.0.1:8000&& set CAMERA_STREAM_URL=rtsp://146.83.194.142:1935/share-w5DiM5QUILZ3lyTd70vCnEbt6Y9IkRNG_q9D5pPxYKU&& set DETECTOR_SOURCE=stream&& env\Scripts\python.exe -u scripts\edge_detector.py"

echo Iniciando frontend...
start "SmartParking Frontend" /D "%~dp0frontend" cmd /k "npm run dev -- --host 0.0.0.0"

echo.
echo Servicios iniciados en ventanas separadas:
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:8000
echo Cierra cada ventana con Ctrl+C para detener su servicio.
echo.
pause
