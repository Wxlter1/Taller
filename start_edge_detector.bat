@echo off
REM SmartParking - Start Edge Detector Script
REM Inicia el script de detección de estacionamientos desde video

echo ====================================
echo SmartParking Edge Detector
echo ====================================
echo.

cd /d "%~dp0"

REM Activar entorno virtual
call env\Scripts\activate.bat

REM Verificar que el video existe
if not exist "video_dia.mp4" (
    echo Error: No se encontró video_dia.mp4
    echo Por favor coloca el archivo de video en el directorio raíz
    pause
    exit /b 1
)

REM Verificar que el modelo existe
if not exist "best.pt" (
    echo Error: No se encontró best.pt
    echo Por favor coloca el modelo YOLO en el directorio raíz
    pause
    exit /b 1
)

REM Iniciar edge detector
echo.
echo Iniciando detección de estacionamientos...
echo Asegúrate de que el backend está corriendo en http://localhost:8000
echo Presiona Q en la ventana de video para detener
echo.

python edge_detector.py

pause
