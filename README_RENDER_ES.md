# Despliegue de GL Bingo (Flask + XML) en Render con Disco Persistente

## ¿Qué incluye este paquete?

- `render.yaml` — Infraestructura como código para Render (servicio web Python, disco persistente y variables de entorno).
- `requirements.txt` — Dependencias mínimas para producción.
- `Procfile` — Comando de arranque para Gunicorn (opcional en Render si usas `startCommand` en render.yaml).
- `app_data_dir_patch.txt` — Bloque de código listo para pegar al inicio de tu `app.py` para usar `DATA_DIR`.

## Pasos rápidos

1. **Agrega estos archivos a la raíz de tu proyecto** (donde está `app.py`).
2. **Pega el contenido de `app_data_dir_patch.txt` dentro de tu `app.py`** (debajo de los imports) y cambia tus rutas de XML para que usen `xml_path(...)`.
3. Crea/actualiza `requirements.txt` con el contenido provisto.
4. Sube el proyecto a GitHub.
5. En Render: New → **Blueprint** → selecciona tu repo con `render.yaml`.
6. Render creará el servicio con un **disco** montado en `/var/data` y la variable `DATA_DIR=/var/data`.
7. Tras el primer deploy, abre **Shell** en Render y copia tus XML iniciales al disco:
   ```bash
   mkdir -p /var/data
   cp -r /opt/render/project/src/data/* /var/data/ || true
   ```

## Notas importantes
- Todo lo que escribas **dentro de `/var/data`** sobrevive a los deploys. Lo que esté **fuera** es efímero.
- En local, `DATA_DIR` apuntará a `./data` automáticamente si no defines la variable de entorno.

¡Éxitos!
