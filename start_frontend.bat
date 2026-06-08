@echo off
REM SmartParking - Start Frontend Script
REM Inicia la interfaz web React

echo ====================================
echo SmartParking Frontend - React
echo ====================================
echo.

cd /d "%~dp0frontend"

REM Verificar node_modules
if not exist "node_modules" (
    echo Instalando dependencias...
    call npm install
)

REM Iniciar frontend
echo.
echo Iniciando servidor en http://localhost:5173
echo Presiona Ctrl+C para detener
echo.

call npm run dev

pause
