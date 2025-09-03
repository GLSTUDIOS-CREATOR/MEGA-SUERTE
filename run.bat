@echo off
cd /d "%~dp0"

echo Instalando dependencias...
pip install -r requirements.txt

echo Configurando variables de entorno...
set FLASK_APP=app.py
set FLASK_ENV=development

echo Iniciando servidor Flask en http://127.0.0.1:5000...
flask run

pause
