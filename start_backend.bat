@echo off
REM SmartParking - Start Backend Script
REM Inicia el servidor FastAPI en el puerto 8000

echo ====================================
echo SmartParking Backend - FastAPI
echo ====================================
echo.

cd /d "%~dp0"

REM Activar entorno virtual
call env\Scripts\activate.bat

REM Instalar dependencias si no existen
echo Verificando dependencias...
pip install -q -r backend\requirements.txt

REM Iniciar backend
echo.
echo Iniciando servidor en http://localhost:8000
echo Presiona Ctrl+C para detener
echo.

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

pause
