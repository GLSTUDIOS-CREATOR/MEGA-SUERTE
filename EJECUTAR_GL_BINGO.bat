@echo off
setlocal EnableExtensions
title GL Bingo - Ejecutar

REM 1) Ir a la carpeta del proyecto (la misma donde está este .bat)
cd /d "%~dp0"

REM 2) Crear entorno virtual si no existe
if not exist "venv\Scripts\python.exe" (
  echo Creando entorno virtual...
  py -m venv venv
  if errorlevel 1 (
    echo ERROR: No se pudo crear el entorno virtual.
    pause
    exit /b 1
  )
)

REM 3) Activar entorno virtual
call "venv\Scripts\activate"
if errorlevel 1 (
  echo ERROR: No se pudo activar el entorno virtual.
  pause
  exit /b 1
)

REM 4) Actualizar pip e instalar dependencias
python -m pip install --upgrade pip

if exist "requirements.txt" (
  echo Instalando dependencias desde requirements.txt...
  pip install -r requirements.txt
) else (
  echo requirements.txt no existe, instalando base...
  pip install flask flask-login pandas openpyxl requests pillow reportlab "qrcode[pil]" PyPDF2
)

REM 5) DATA_DIR (persistente local)
set "DATA_DIR=%CD%\DATA"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

REM 6) Ejecutar app
echo Iniciando servidor...
python app.py

pause
