#!/usr/bin/env bash
set -euo pipefail

echo "==> Preparando DISCO persistente y enlaces…"

# ------------------------------------------------------------------------------------
# RUTAS
# ------------------------------------------------------------------------------------
BASE="/opt/render/project/src"
DATA_ROOT="/data"                 # <- DISCO PERSISTENTE DE RENDER
cd "$BASE"

# Asegura el esqueleto en el disco
mkdir -p \
  "$DATA_ROOT/logs" \
  "$DATA_ROOT/usuarios" \
  "$DATA_ROOT/CAJA" \
  "$DATA_ROOT/REINTEGROS" \
  "$DATA_ROOT/DB"

# ------------------------------------------------------------------------------------
# LOGS persistentes
# ------------------------------------------------------------------------------------
mkdir -p instance/gl_bingo
rm -rf instance/gl_bingo/logs || true
ln -sfn "$DATA_ROOT/logs" instance/gl_bingo/logs

# Crea impresiones.xml si no existe o está vacío
if [ ! -s "$DATA_ROOT/logs/impresiones.xml" ]; then
  cat > "$DATA_ROOT/logs/impresiones.xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<impresiones></impresiones>
XML
fi

# ------------------------------------------------------------------------------------
# usuarios.xml (persistente)
# ------------------------------------------------------------------------------------
if [ ! -f "$DATA_ROOT/usuarios/usuarios.xml" ]; then
  if [ -f static/db/usuarios.xml ]; then
    echo "Sembrando usuarios.xml desde el repo → /data/usuarios/usuarios.xml"
    cp static/db/usuarios.xml "$DATA_ROOT/usuarios/usuarios.xml"
  else
    echo "Creando usuarios.xml mínimo"
    cat > "$DATA_ROOT/usuarios/usuarios.xml" <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<usuarios>
  <usuario>
    <nombre>ADMIN</nombre>
    <clave>admin</clave>
    <rol>Super Administrador</rol>
    <email>admin@example.com</email>
    <estado>activo</estado>
    <avatar>avatar-male.png</avatar>
  </usuario>
</usuarios>
EOF
  fi
fi

# ------------------------------------------------------------------------------------
# caja.xml (persistente)
# ------------------------------------------------------------------------------------
if [ ! -f "$DATA_ROOT/CAJA/caja.xml" ]; then
  echo "Creando /data/CAJA/caja.xml"
  cat > "$DATA_ROOT/CAJA/caja.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<caja>
  <dia fecha="$(date +%Y-%m-%d)">
    <configuracion>
      <valor_boleto>1.00</valor_boleto>
      <comision_vendedor>0.30</comision_vendedor>
      <comision_extra_meta>0</comision_extra_meta>
      <meta_boletos>0</meta_boletos>
    </configuracion>
  </dia>
</caja>
EOF
fi

# ------------------------------------------------------------------------------------
# Sembrar XMLs de DB al DISCO (SOLO primera vez)
# (Se excluyen usuarios.xml y caja.xml que ya tienen su propia ruta)
# ------------------------------------------------------------------------------------
if [ -z "$(ls -A "$DATA_ROOT/DB" 2>/dev/null)" ]; then
  echo "Sembrando DB XMLs en /data/DB (una sola vez)…"
  shopt -s nullglob
  for f in static/db/*.xml; do
    bn="$(basename "$f")"
    if [ "$bn" != "usuarios.xml" ] && [ "$bn" != "caja.xml" ]; then
      cp -a "$f" "$DATA_ROOT/DB/$bn" || true
    fi
  done
  shopt -u nullglob
fi

# ------------------------------------------------------------------------------------
# Enlaces para que la app vea TODO donde espera
# ------------------------------------------------------------------------------------

# a) static/db como carpeta REAL con symlinks a los XML del DISCO
rm -rf static/db || true
mkdir -p static/db

#    Usuarios y Caja (siempre a persistente)
ln -sfn "$DATA_ROOT/usuarios/usuarios.xml" static/db/usuarios.xml
ln -sfn "$DATA_ROOT/CAJA/caja.xml"       static/db/caja.xml

#    Resto de XMLs (DB)
shopt -s nullglob
for f in "$DATA_ROOT/DB"/*.xml; do
  bn="$(basename "$f")"
  ln -sfn "$DATA_ROOT/DB/$bn" "static/db/$bn"
done
shopt -u nullglob

# b) Compatibilidad con rutas DATA/... usadas por el código
mkdir -p DATA
for d in usuarios CAJA REINTEGROS; do
  rm -rf "DATA/$d" || true
  ln -sfn "$DATA_ROOT/$d" "DATA/$d"
done

# ------------------------------------------------------------------------------------
# Resumen útil en logs
# ------------------------------------------------------------------------------------
echo "==> Resumen:"
ls -ld instance/gl_bingo/logs DATA/usuarios DATA/CAJA DATA/REINTEGROS static/db | cat
echo "Log persistente en: $DATA_ROOT/logs/impresiones.xml"

# ------------------------------------------------------------------------------------
# ARRANCAR GUNICORN con timeout amplio (Planillas puede pesar)
# ------------------------------------------------------------------------------------
echo "==> Iniciando Gunicorn…"
exec gunicorn app:app \
  --bind 0.0.0.0:${PORT:-10000} \
  --workers 1 \
  --timeout 600 \
  --access-logfile - \
  --error-logfile -


