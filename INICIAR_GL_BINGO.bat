@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM =========================================================
REM  GL BINGO - INICIAR EN WINDOWS (LOCAL)
REM  - Crea/activa venv
REM  - Instala requirements.txt (si existe)
REM  - Prepara carpetas DATA persistentes (sin symlinks)
REM  - Si faltan, "siembra" XML básicos (usuarios/caja, etc.)
REM  - Arranca el servidor Python
REM =========================================================

cd /d "%~dp0"

echo.
echo =========================================================
echo   GL BINGO - INICIAR (Windows)
echo   Carpeta: %CD%
echo =========================================================
echo.

REM ---------- Detectar Python ----------
set "PY=py"
%PY% -V >nul 2>&1
if errorlevel 1 set "PY=python"
%PY% -V >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No se encontro Python en PATH. Instala Python 3 y vuelve a intentar.
  echo         Tip: Marca "Add python.exe to PATH" al instalar.
  pause
  exit /b 1
)

REM ---------- Crear/activar entorno virtual ----------
if not exist "venv\Scripts\activate.bat" (
  echo [1/5] Creando entorno virtual (venv)...
  %PY% -m venv venv
  if errorlevel 1 goto :FAIL
) else (
  echo [1/5] Entorno virtual ya existe.
)

call "venv\Scripts\activate.bat"
if errorlevel 1 goto :FAIL

echo [2/5] Actualizando pip...
python -m pip install --upgrade pip >nul

if exist "requirements.txt" (
  echo [2/5] Instalando dependencias (requirements.txt)...
  pip install -r requirements.txt
  if errorlevel 1 goto :FAIL
) else (
  echo [2/5] requirements.txt NO encontrado. (Se omite instalacion automatica.)
)

REM ---------- DATA_DIR para persistencia local ----------
set "DATA_DIR=%CD%\DATA"
set "PORT=5000"
set "FLASK_ENV=development"
set "PYTHONUNBUFFERED=1"

echo [3/5] Preparando carpetas en: %DATA_DIR%
for %%d in (DB usuarios CAJA REINTEGROS CONTABILIDAD logs EXPORTS) do (
  if not exist "%DATA_DIR%\%%d" mkdir "%DATA_DIR%\%%d" >nul 2>&1
)

REM ---------- Semillas: usuarios.xml ----------
if not exist "%DATA_DIR%\usuarios\usuarios.xml" (
  echo [3/5] Sembrando usuarios.xml...
  if exist "static\db\usuarios.xml" (
    copy /Y "static\db\usuarios.xml" "%DATA_DIR%\usuarios\usuarios.xml" >nul
  ) else if exist "DATA\usuarios\usuarios.xml" (
    copy /Y "DATA\usuarios\usuarios.xml" "%DATA_DIR%\usuarios\usuarios.xml" >nul
  ) else (
    > "%DATA_DIR%\usuarios\usuarios.xml" (
      echo ^<?xml version="1.0" encoding="utf-8"?^>
      echo ^<usuarios^>
      echo   ^<usuario^>
      echo     ^<nombre^>ADMIN^</nombre^>
      echo     ^<clave^>admin^</clave^>
      echo     ^<rol^>Super Administrador^</rol^>
      echo     ^<email^>admin@example.com^</email^>
      echo     ^<estado^>activo^</estado^>
      echo     ^<avatar^>avatar-male.png^</avatar^>
      echo   ^</usuario^>
      echo ^</usuarios^>
    )
  )
)

REM ---------- Semillas: caja.xml ----------
if not exist "%DATA_DIR%\CAJA\caja.xml" (
  echo [3/5] Sembrando caja.xml...
  if exist "static\CAJA\caja.xml" (
    copy /Y "static\CAJA\caja.xml" "%DATA_DIR%\CAJA\caja.xml" >nul
  ) else if exist "static\db\caja.xml" (
    copy /Y "static\db\caja.xml" "%DATA_DIR%\CAJA\caja.xml" >nul
  ) else if exist "DATA\CAJA\caja.xml" (
    copy /Y "DATA\CAJA\caja.xml" "%DATA_DIR%\CAJA\caja.xml" >nul
  ) else (
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%i"
    > "%DATA_DIR%\CAJA\caja.xml" (
      echo ^<?xml version="1.0" encoding="utf-8"?^>
      echo ^<caja^>
      echo   ^<dia fecha="!TODAY!"^>
      echo     ^<configuracion^>
      echo       ^<valor_boleto^>1.00^</valor_boleto^>
      echo       ^<comision_vendedor^>0.30^</comision_vendedor^>
      echo       ^<comision_extra_meta^>0^</comision_extra_meta^>
      echo       ^<meta_boletos^>0^</meta_boletos^>
      echo     ^</configuracion^>
      echo   ^</dia^>
      echo ^</caja^>
    )
  )
)

REM ---------- Semillas: CONTABILIDAD ----------
for %%f in (bancos.xml gastos.xml sueldos.xml ventas.xml) do (
  if not exist "%DATA_DIR%\CONTABILIDAD\%%f" (
    if exist "static\CONTABILIDAD\%%f" copy /Y "static\CONTABILIDAD\%%f" "%DATA_DIR%\CONTABILIDAD\%%f" >nul
    if exist "DATA\CONTABILIDAD\%%f"   copy /Y "DATA\CONTABILIDAD\%%f"   "%DATA_DIR%\CONTABILIDAD\%%f" >nul
  )
)

REM ---------- Semillas: DB (static\db\*.xml excepto caja/usuarios) ----------
if exist "static\db" (
  echo [3/5] Sembrando DB (static\db\*.xml)...
  for %%X in ("static\db\*.xml") do (
    set "BN=%%~nxX"
    if /I "!BN!"=="caja.xml" (
      REM skip
    ) else if /I "!BN!"=="usuarios.xml" (
      REM skip
    ) else (
      if not exist "%DATA_DIR%\DB\!BN!" copy /Y "%%~fX" "%DATA_DIR%\DB\!BN!" >nul
    )
  )
)

REM ---------- Logs ----------
if not exist "%DATA_DIR%\logs\impresiones.xml" (
  echo ^<impresiones/^> > "%DATA_DIR%\logs\impresiones.xml"
)

echo [4/5] Variables listas:
echo    DATA_DIR=%DATA_DIR%
echo    PORT=%PORT%
echo.

REM ---------- Arranque ----------
echo [5/5] Iniciando servidor...
echo    Abre: http://127.0.0.1:%PORT%
echo.

REM Si tu app usa "if __name__ == '__main__': app.run(...)", esto funciona perfecto:
python app.py

REM Si prefieres Flask CLI, comenta la linea anterior y usa:
REM set FLASK_APP=app.py
REM python -m flask run --host 0.0.0.0 --port %PORT%

goto :EOF

:FAIL
echo.
echo [ERROR] Fallo el arranque. Revisa el mensaje anterior.
pause
exit /b 1
