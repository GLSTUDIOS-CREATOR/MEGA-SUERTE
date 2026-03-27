@echo off
setlocal ENABLEDELAYEDEXPANSION

:: === CONFIGURA TU RUTA DEL REPO ===
set "REPO_DIR=D:\GL STUDIOS\GOLPEDESUERTE.EC"
set "BRANCH=main"

echo.
echo == SUBIR CAMBIOS A GITHUB ==
echo Repo: "%REPO_DIR%"
echo Rama: %BRANCH%
echo.

:: 1) Ir al repo
cd /d "%REPO_DIR%" || (echo [ERROR] No se puede entrar a "%REPO_DIR%" && pause && exit /b 1)

:: 2) Confirmar que git existe
git --version >nul 2>&1 || (echo [ERROR] Git no esta instalado o no esta en PATH && pause && exit /b 1)

:: 3) Ver si hay cambios
for /f "delims=" %%A in ('git status --porcelain') do set CHANGES=1

if defined CHANGES (
    :: 3a) Mensaje de commit (usa argumento o genera uno automático con fecha/hora)
    set "MSG=%*"
    if "%MSG%"=="" set "MSG=Auto: update %DATE% %TIME%"
    echo Haciendo commit con mensaje: "%MSG%"
    git add -A
    git commit -m "%MSG%" || (echo [ERROR] Commit fallido && pause && exit /b 1)
) else (
    echo No hay cambios para commitear. (saltando add/commit)
)

:: 4) Traer lo ultimo del remoto sin crear merge commit
echo Haciendo pull --rebase...
git pull --rebase origin %BRANCH% || (echo [ERROR] Pull --rebase fallo && pause && exit /b 1)

:: 5) Push
echo Subiendo cambios a GitHub...
git push origin %BRANCH% || (echo [ERROR] Push fallido && pause && exit /b 1)

echo.
echo ✅ Listo: cambios actualizados en GitHub (rama %BRANCH%).
pause
exit /b 0
