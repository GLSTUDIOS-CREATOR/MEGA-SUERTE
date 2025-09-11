#!/usr/bin/env bash
set -euo pipefail

echo "==> Boot: preparar DISCO (/data) y enlaces…"

BASE="/opt/render/project/src"
DATA="/data"

cd "$BASE"

# 1) Carpetas persistentes en el DISCO
mkdir -p "$DATA"/{logs,usuarios,CAJA,REINTEGROS,DB}
mkdir -p instance

# 2) LOGS persistentes (para impresiones)
mkdir -p instance/gl_bingo
rm -rf instance/gl_bingo/logs || true
ln -sf "$DATA/logs" instance/gl_bingo/logs
[ -f "$DATA/logs/impresiones.xml" ] || echo '<impresiones/>' > "$DATA/logs/impresiones.xml"

# 3) usuarios.xml persistente
if [ ! -f "$DATA/usuarios/usuarios.xml" ]; then
  if [ -f static/db/usuarios.xml ]; then
    cp static/db/usuarios.xml "$DATA/usuarios/usuarios.xml"
  else
    cat > "$DATA/usuarios/usuarios.xml" <<'EOF'
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

# 4) caja.xml persistente
if [ ! -f "$DATA/CAJA/caja.xml" ]; then
  cat > "$DATA/CAJA/caja.xml" <<EOF
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

# 5) Sembrar XML de DB en el DISCO (primera vez)
shopt -s nullglob
for f in static/db/*.xml; do
  bn="$(basename "$f")"
  case "$bn" in
    usuarios.xml|caja.xml) continue ;;
  esac
  if [ ! -f "$DATA/DB/$bn" ]; then
    cp "$f" "$DATA/DB/$bn"
  fi
done
shopt -u nullglob

# 6) Enlaces: que la app vea todo donde espera
rm -rf static/db || true
mkdir -p static/db
ln -sf "$DATA/usuarios/usuarios.xml" static/db/usuarios.xml
ln -sf "$DATA/CAJA/caja.xml"      static/db/caja.xml
for f in "$DATA/DB"/*.xml; do
  bn="$(basename "$f")"
  ln -sf "$DATA/DB/$bn" "static/db/$bn"
done

mkdir -p DATA
for d in usuarios CAJA REINTEGROS; do
  rm -rf "DATA/$d" || true
  ln -sf "$DATA/$d" "DATA/$d"
done

echo "==> Resumen:"
ls -ld instance/gl_bingo/logs DATA/usuarios DATA/CAJA DATA/REINTEGROS static/db | cat
echo "Log persistente en: $DATA/logs/impresiones.xml"

echo "==> Iniciando Gunicorn…"
# Más tolerancia para evitar 500 por timeout en planillas
exec gunicorn app:app \
  --bind 0.0.0.0:${PORT:-10000} \
  --workers 2 \
  --threads 2 \
  --timeout 600 \
  --graceful-timeout 610 \
  --keep-alive 65

