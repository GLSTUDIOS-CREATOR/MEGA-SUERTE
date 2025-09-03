# GL SISTEMA (Bingo + Caja + Sorteos)

Este repositorio contiene tu sistema Flask con módulos de:
- Usuarios y login
- Caja / Contabilidad
- Vendedores y asignación de planillas
- Impresión de boletos (PDF con ReportLab)
- Figuras / Sorteos / Boletín

## Requisitos

- Python 3.11+ (recomendado)
- Pip

```bash
python -V
pip -V
```

## Instalación (local)

```bash
# 1) Crear entorno virtual
python -m venv .venv
# 2) Activar
# Windows:
.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate

# 3) Instalar dependencias
pip install -r requirements.txt

# 4) Ejecutar
python app.py
# Abre: http://127.0.0.1:5000
```

## Fuentes (ReportLab) — *opcional*

Tu código intenta registrar `C:\\Windows\\Fonts\\arial.ttf`. En Linux/Render esa ruta no existe.
Opciones:
1. **Usar fuentes estándar** de ReportLab (Helvetica, Times) → no necesitas TTF.
2. **Incluir TTF** dentro de `static/fonts/` y registrar así:

```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
try:
    pdfmetrics.registerFont(TTFont("Arial", "static/fonts/arial.ttf"))
    FONT_NAME = "Arial"
except Exception:
    FONT_NAME = "Helvetica"  # fallback universal
```

Luego en tu código ReportLab usa `FONT_NAME`.

## Estructura de datos (XML/CSV)

Se validó que las rutas a XML en `app.py` apuntan a `static/` y existen.
Si mueves carpetas, ajusta los `*_DIR` y `*_XML` en la cabecera de `app.py`.

## Subir a GitHub (paso a paso)

> **Nota:** Asegúrate de estar parado en la carpeta `SISTEMA/` (donde está `app.py`).

```bash
git init
git branch -m main
git add .
git commit -m "Primera subida del sistema GL"

# Crear repo en GitHub (web) → copia la URL HTTPS de tu repo, por ej.:
git remote add origin https://github.com/USUARIO/GL_SISTEMA.git
git push -u origin main
```

Si te pide login, usa **GitHub Desktop** o ejecuta:
```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu-email@ejemplo.com"
```

## Despliegue en Render (resumen)

- Crea un **Web Service** nuevo apuntando al repo.
- **Start Command:** `python app.py`
- **Build Command:** `pip install -r requirements.txt`
- Ajusta variables de entorno si usas rutas externas. Como trabajas con `BASE_DIR/static/...`, no necesitas volúmenes.

## Soporte

Si ves error de fuentes en impresión, aplica el bloque de *fallback* arriba.
Si falta algún XML, crea el archivo vacío en `static/...` (ya están incluidos en este paquete).