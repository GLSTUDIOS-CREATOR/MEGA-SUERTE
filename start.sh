#!/usr/bin/env bash
set -euo pipefail

echo "==> Preparando DISCO persistente y enlaces…"

BASE="/opt/render/project/src"
DATA="/data"     # Disco persistente de Render

cd "$BASE"

# 1) Carpetas persistentes en /data
mkdir -p "$DATA/DB" "$DATA/usuarios" "$DATA/CAJA" "$DATA/REINTEGROS" "$DATA/CONTABILIDAD" "$DATA/logs" "$DATA/EXPORTS"

# 2) Semillas (solo si faltan en /data)
# --- usuarios.xml
if [ ! -f "$DATA/usuarios/usuarios.xml" ]; then
  if [ -f static/db/usuarios.xml ]; then
    cp static/db/usuarios.xml "$DATA/usuarios/usuarios.xml"
  elif [ -f DATA/usuarios/usuarios.xml ]; then
    cp DATA/usuarios/usuarios.xml "$DATA/usuarios/usuarios.xml"
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

# --- caja.xml
if [ ! -f "$DATA/CAJA/caja.xml" ]; then
  if [ -f static/CAJA/caja.xml ]; then
    cp static/CAJA/caja.xml "$DATA/CAJA/caja.xml"
  elif [ -f static/db/caja.xml ]; then
    cp static/db/caja.xml "$DATA/CAJA/caja.xml"
  elif [ -f DATA/CAJA/caja.xml ]; then
    cp DATA/CAJA/caja.xml "$DATA/CAJA/caja.xml"
  else
    # Caja mínima
    today="$(date +%Y-%m-%d)"
    cat > "$DATA/CAJA/caja.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<caja>
  <dia fecha="$today">
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
fi

# --- CONTABILIDAD (bancos, gastos, sueldos, ventas)
for f in bancos.xml gastos.xml sueldos.xml ventas.xml; do
  [ -f "$DATA/CONTABILIDAD/$f" ] && continue
  if   [ -f static/CONTABILIDAD/$f ]; then cp static/CONTABILIDAD/$f "$DATA/CONTABILIDAD/$f"
  elif [ -f DATA/CONTABILIDAD/$f   ]; then cp DATA/CONTABILIDAD/$f   "$DATA/CONTABILIDAD/$f"
  fi
done

# --- DB (todos los XML de static/db excepto caja y usuarios)
shopt -s nullglob
for src in static/db/*.xml; do
  bn="$(basename "$src")"
  case "$bn" in
    caja.xml|usuarios.xml) continue ;;
  esac
  [ -f "$DATA/DB/$bn" ] || cp "$src" "$DATA/DB/$bn"
done
shopt -u nullglob

# --- Logs
[ -f "$DATA/logs/impresiones.xml" ] || echo "<impresiones/>" > "$DATA/logs/impresiones.xml"

# ======================= REINTEGROS =======================
# Si hay imágenes en el repo, semillas hacia /data (solo las faltantes)
if [ -d "static/REINTEGROS" ]; then
  shopt -s nullglob
  for f in static/REINTEGROS/*.{png,PNG,jpg,JPG,jpeg,JPEG,webp,WEBP,svg,SVG}; do
    [ -e "$f" ] || continue
    bn="$(basename "$f")"
    [ -f "$DATA/REINTEGROS/$bn" ] || cp "$f" "$DATA/REINTEGROS/$bn"
  done
  shopt -u nullglob
fi

# Enlace para servir siempre desde /data
rm -rf static/REINTEGROS || true
ln -s "$DATA/REINTEGROS" static/REINTEGROS
# ==========================================================

# 3) Enlaces (symlinks) para que la app SIEMPRE escriba en /data

# Logs de la app
mkdir -p instance/gl_bingo
rm -rf instance/gl_bingo/logs || true
ln -s "$DATA/logs" instance/gl_bingo/logs

# static/db como carpeta real con symlinks hacia /data/DB
rm -rf static/db || true
mkdir -p static/db
for src in "$DATA/DB"/*.xml; do
  [ -e "$src" ] || continue
  ln -sf "$src" "static/db/$(basename "$src")"
done
# y apuntamos usuarios & caja a sus rutas persistentes
ln -sf "$DATA/usuarios/usuarios.xml" static/db/usuarios.xml
ln -sf "$DATA/CAJA/caja.xml"       static/db/caja.xml

# static/CONTABILIDAD y static/CAJA hacia /data
rm -rf static/CONTABILIDAD || true
ln -s "$DATA/CONTABILIDAD" static/CONTABILIDAD

rm -rf static/CAJA || true
ln -s "$DATA/CAJA" static/CAJA

# Directorios DATA/… (compatibilidad con tu código)
for d in usuarios CAJA REINTEGROS CONTABILIDAD; do
  rm -rf "DATA/$d" || true
  ln -s "$DATA/$d" "DATA/$d"
done

# (opcional) carpeta de exportaciones
rm -rf static/EXPORTS || true
ln -s "$DATA/EXPORTS" static/EXPORTS

echo "==> Persistencia lista. Iniciando Gunicorn…"
# Timeout alto para generación de planillas pesadas
exec gunicorn app:app --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 1200

