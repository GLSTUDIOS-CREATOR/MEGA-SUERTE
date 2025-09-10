#!/usr/bin/env bash
set -euo pipefail

echo "==> Preparando DISCO persistente y enlaces…"

BASE="/opt/render/project/src"
cd "$BASE"

DATA_ROOT="/data"   # <-- DISCO de Render (persistente)

# 1) Carpetas persistentes en el DISCO
mkdir -p "$DATA_ROOT/logs" "$DATA_ROOT/usuarios" "$DATA_ROOT/CAJA" "$DATA_ROOT/REINTEGROS" "$DATA_ROOT/DB"

# 2) LOGS persistentes
mkdir -p instance/gl_bingo
rm -rf instance/gl_bingo/logs || true
ln -s "$DATA_ROOT/logs" instance/gl_bingo/logs
[ -f "$DATA_ROOT/logs/impresiones.xml" ] || echo "<impresiones/>" > "$DATA_ROOT/logs/impresiones.xml"

# 3) usuarios.xml (persistente)
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

# 4) caja.xml (persistente)
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

# 5) Sembrar los XML de DB en el DISCO la primera vez
if [ -z "$(ls -A "$DATA_ROOT/DB" 2>/dev/null)" ]; then
  echo "Sembrando DB XMLs en /data/DB (una sola vez)…"
  cp -a static/db/*.xml "$DATA_ROOT/DB" 2>/dev/null || true
fi

# 6) Enlaces para que la app vea todo donde espera:

#    a) static/db como carpeta REAL y dentro symlinks a los XML del DISCO
rm -rf static/db || true
mkdir -p static/db
for f in "$DATA_ROOT/DB"/*.xml; do
  [ -e "$f" ] || continue
  bn="$(basename "$f")"
  ln -sf "$DATA_ROOT/DB/$bn" "static/db/$bn"
done
#    Usuarios y Caja apuntan a sus rutas persistentes
ln -sf "$DATA_ROOT/usuarios/usuarios.xml" static/db/usuarios.xml
ln -sf "$DATA_ROOT/CAJA/caja.xml"      static/db/caja.xml

#    b) Mantener compatibilidad con rutas DATA/… usadas por tu código
for d in usuarios CAJA REINTEGROS; do
  rm -rf "DATA/$d" || true
  ln -s "$DATA_ROOT/$d" "DATA/$d"
done

echo "==> Resumen:"
ls -ld instance/gl_bingo/logs DATA/usuarios DATA/CAJA DATA/REINTEGROS static/db | cat
echo "Log persistente en: $DATA_ROOT/logs/impresiones.xml"

echo "==> Iniciando Gunicorn…"
# Usa el PORT que le da Render; si no está, 10000
exec gunicorn app:app --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 120

