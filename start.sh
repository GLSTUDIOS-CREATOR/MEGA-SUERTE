#!/usr/bin/env bash
set -euo pipefail

echo "==> Boot hook: preparando disco persistente y enlaces…"

BASE="/opt/render/project/src"
cd "$BASE"

# 1) carpetas persistentes
mkdir -p DATA/CAJA DATA/usuarios DATA/REINTEGROS DATA/DB/xml
mkdir -p static/db

# 2) usuarios.xml: si ya existe en DATA lo respetamos. Si no:
if [ ! -f DATA/usuarios/usuarios.xml ]; then
  if [ -f static/db/usuarios.xml ]; then
    echo "Copiando usuarios.xml del repo -> DATA/usuarios/usuarios.xml"
    cp static/db/usuarios.xml DATA/usuarios/usuarios.xml
  else
    echo "Creando usuarios.xml mínimo en DATA/usuarios/usuarios.xml"
    cat > DATA/usuarios/usuarios.xml <<'EOF'
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

# 3) caja.xml: si falta, inicializar con configuración por defecto
if [ ! -f DATA/CAJA/caja.xml ]; then
  echo "Creando DATA/CAJA/caja.xml"
  cat > DATA/CAJA/caja.xml <<EOF
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

# 4) Migrar XML del repo a DATA/DB/xml (solo primera vez)
#    (ignoramos caja.xml y usuarios.xml que ya tienen sus sitios)
shopt -s nullglob
for f in static/db/*.xml; do
  bn="$(basename "$f")"
  if [ "$bn" != "caja.xml" ] && [ "$bn" != "usuarios.xml" ]; then
    if [ ! -f "DATA/DB/xml/$bn" ]; then
      echo "Moviendo $f -> DATA/DB/xml/$bn"
      cp "$f" "DATA/DB/xml/$bn"
    fi
  fi
done
shopt -u nullglob

# 5) Symlinks para que la app siga usando rutas 'static/db/...'
ln -sf ../../DATA/usuarios/usuarios.xml static/db/usuarios.xml
ln -sf ../../DATA/CAJA/caja.xml      static/db/caja.xml

for f in DATA/DB/xml/*.xml; do
  bn="$(basename "$f")"
  ln -sf ../../"$f" "static/db/$bn"
done

echo "==> Resumen:"
echo "   - DATA       : $(ls -la DATA | wc -l) entradas"
echo "   - static/db  : $(ls -la static/db | wc -l) entradas"
echo "   - Caja       : DATA/CAJA/caja.xml -> $(wc -c < DATA/CAJA/caja.xml) bytes"
echo "   - Usuarios   : DATA/usuarios/usuarios.xml -> $(wc -c < DATA/usuarios/usuarios.xml) bytes"

echo "==> Iniciando Gunicorn…"
# Arranca la app (ajusta workers/timeouts si lo necesitas)
exec gunicorn app:app --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 120
