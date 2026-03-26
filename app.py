# ====== PARCHE DE ARRANQUE (PÉGALO AL INICIO DE app.py) ======
# Evita NameError en 'mm' incluso si el import real aparece más abajo
try:
    from reportlab.lib.units import mm  # import real si está disponible
except Exception:
    # Fallback: 1 mm en puntos (ReportLab trabaja en puntos)
    mm = 2.834645669291339

# Evita NameError en @login_required si Flask-Login no está instalado
try:
    from flask_login import login_required as _login_required
    def login_required(f):
        return _login_required(f)
except Exception:
    # Fallback 'no-op': deja pasar la vista sin exigir login
    def login_required(f):
        return f
# ====== FIN PARCHE DE ARRANQUE ======



import os
import random
import pandas as pd
import qrcode
import xml.etree.ElementTree as ET
from datetime import date, datetime
from io import BytesIO
from flask import Flask, request, render_template, send_file, redirect, url_for, flash, session, Response
# ---- Safe login URL helper (avoids BuildError for missing 'login' endpoint) ----
from flask import url_for as _flask_url_for
from werkzeug.routing import BuildError as _BuildError

def _login_url(**values):
    try:
        return _flask_url_for('login', **values)
    except Exception:
        try:
            return _flask_url_for('_login_demo', **values)
        except Exception:
            return '/_login_demo'
# -------------------------------------------------------------------------------

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.units import mm, cm, inch


app = Flask(__name__)
app.secret_key = 'super_secreto_bingo_2025'


from functools import wraps
from flask import session, redirect, url_for

def require_session(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(_login_url())
        return f(*args, **kwargs)
    return wrapper


# ================== PERMISOS POR USUARIO (PARCHE SEGURO) ==================
MODULOS_PERMISOS = [
    ('dashboard', 'Dashboard', '/dashboard'),
    ('usuarios', 'Usuarios', '/usuarios'),
    ('juego', 'Juego', '/juego'),
    ('contabilidad', 'Contabilidad', '/contabilidad'),
    ('vendedores', 'Vendedores', '/vendedores'),
    ('asignar_planillas', 'Asignar Planillas', '/asignar-planillas'),
    ('impresion', 'Impresión de Boletos', '/impresion'),
    ('cobro', 'Cobro de Caja', '/cobro'),
    ('pago_premios', 'Pago de Premios', '/pago-premios'),
    ('sorteo', 'Sorteo', '/sorteo'),
    ('crear_figuras', 'Crear Figuras', '/crear-figuras'),
    ('escoger_figuras', 'Escoger Figuras', '/escoger-figuras'),
    ('boletin', 'Boletín', '/boletin'),
]
MODULOS_PERMISOS_KEYS = [k for k, _label, _path in MODULOS_PERMISOS]

RUTAS_PERMISOS = {
    '/dashboard': 'dashboard',
    '/api/dashboard/hoy': 'dashboard',
    '/usuarios': 'usuarios',
    '/juego': 'juego',
    '/contabilidad': 'contabilidad',
    '/vendedores': 'vendedores',
    '/asignar-planillas': 'asignar_planillas',
    '/impresion': 'impresion',
    '/cobro': 'cobro',
    '/pago-premios': 'pago_premios',
    '/sorteo': 'sorteo',
    '/crear-figuras': 'crear_figuras',
    '/escoger-figuras': 'escoger_figuras',
    '/boletin': 'boletin',
}

def _perm_norm(v):
    return str(v or '').strip().lower().replace('-', '_').replace(' ', '_')

def _coerce_permisos(value):
    if value is None:
        return list(MODULOS_PERMISOS_KEYS)
    if isinstance(value, (list, tuple, set)):
        raw = [str(v).strip() for v in value if str(v).strip()]
    else:
        txt = str(value or '').strip()
        raw = [p.strip() for p in txt.split(',')] if txt else []
    out, seen = [], set()
    for item in raw:
        key = _perm_norm(item)
        if key in MODULOS_PERMISOS_KEYS and key not in seen:
            out.append(key)
            seen.add(key)
    return out

def usuario_tiene_modulo(modulo):
    return _perm_norm(modulo) in set(_coerce_permisos(session.get('permisos', None)))

def _ruta_inicio_permitida():
    for key, _label, path in MODULOS_PERMISOS:
        if usuario_tiene_modulo(key):
            return path
    return '/logout'

@app.context_processor
def inject_can_helper():
    return {'can': usuario_tiene_modulo}

@app.before_request
def _bloquear_acceso_por_permiso():
    path = (request.path or '/').rstrip('/') or '/'
    if path.startswith('/static') or path in {'/', '/login', '/logout'}:
        return None
    if 'usuario' not in session:
        return None
    for prefix, modulo in sorted(RUTAS_PERMISOS.items(), key=lambda x: len(x[0]), reverse=True):
        if path == prefix or path.startswith(prefix + '/'):
            if not usuario_tiene_modulo(modulo):
                if path.startswith('/api/'):
                    return Response('{"ok": false, "error": "No tienes permiso para este módulo."}', status=403, mimetype='application/json')
                flash('No tienes permiso para entrar a esta sección.', 'error')
                destino = _ruta_inicio_permitida()
                if destino == path:
                    destino = '/logout'
                return redirect(destino)
            break
    return None
# =======================================================================



# ─── ARCHIVOS Y DIRECTORIOS ────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USUARIOS_XML = os.path.join(BASE_DIR, 'usuarios', 'usuarios.xml')
AVATAR_DIR = os.path.join('static', 'avatars')
DATA_DIR = os.path.join(BASE_DIR, "DATA")
REINTEGROS_DIR = os.path.join(DATA_DIR, "REINTEGROS")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REINTEGROS_DIR, exist_ok=True)
# ==== PERSISTENCIA (Render / Local) ====
import os, shutil

# 1) Usar DATA_DIR de entorno si existe; si no, ./DATA local
DATA_DIR = os.environ.get("DATA_DIR") or ("/data" if os.path.isdir("/data") else os.path.join(BASE_DIR, "DATA"))
os.makedirs(DATA_DIR, exist_ok=True)

# Helpers
def _persist(*rel):
    """Ruta dentro de DATA_DIR (crea la carpeta si no existe)."""
    path = os.path.join(DATA_DIR, *rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

def _seed(src_rel, dst_abs):
    """
    Copia archivo inicial del repo → persistente, solo si NO existe.
    Ej.: _seed('static/db/caja.xml', CAJA_XML)
    """
    src_abs = os.path.join(BASE_DIR, src_rel)
    if not os.path.exists(dst_abs) and os.path.exists(src_abs):
        shutil.copy2(src_abs, dst_abs)

# 2) Reasignar rutas de XML “vivos” a DATA_DIR (persistente)
#    Usamos los mismos nombres de variables que usa tu app.
USUARIOS_XML            = _persist('usuarios', 'usuarios.xml')

CAJA_XML                = _persist('static', 'db', 'caja.xml')
ASIGNACIONES_XML        = _persist('static', 'db', 'asignaciones.xml')
PAGOS_PREMIOS_XML       = _persist('static', 'db', 'pagos_premios.xml')
RESULTADOS_SORTEO_XML   = _persist('static', 'db', 'resultados_sorteo.xml')
SORTEOS_XML             = _persist('static', 'db', 'sorteos.xml')
SPINNERS_XML            = _persist('static', 'db', 'spinners.xml')
VMIX_REINTEGRO_XML      = _persist('static', 'db', 'vmix_reintegro.xml')
VMIX_SPINNERS_XML       = _persist('static', 'db', 'vmix_spinners.xml')
VMIX_VENDEDORES_XML     = _persist('static', 'db', 'vmix_vendedores.xml')
VMIX_VENTAS_XML         = _persist('static', 'db', 'vmix_ventas.xml')
VENDEDORES_XML          = _persist('static', 'db', 'vendedores.xml')
DATOS_FIGURAS_XML         = _persist('static', 'db', 'datos_figuras.xml')
FIGURAS_FECHA_XML         = _persist('static', 'db', 'figuras_por_fecha.xml')
FIGURAS_DEL_DIA_XML       = _persist('static', 'db', 'figuras_del_dia.xml')

LOGS_CAJA_XML           = _persist('static', 'LOGS', 'caja.xml')
LOGS_IMPRESIONES_XML    = _persist('static', 'LOGS', 'impresiones.xml')

CONTAB_BANCOS_XML       = _persist('static', 'CONTABILIDAD', 'bancos.xml')
CONTAB_GASTOS_XML       = _persist('static', 'CONTABILIDAD', 'gastos.xml')
CONTAB_SUELDOS_XML      = _persist('static', 'CONTABILIDAD', 'sueldos.xml')
CONTAB_VENTAS_XML       = _persist('static', 'CONTABILIDAD', 'ventas.xml')

# 3) Sembrar contenido inicial (solo primera vez)
for src, dst in [
    ('usuarios/usuarios.xml',               USUARIOS_XML),
    ('static/db/caja.xml',                  CAJA_XML),
    ('static/db/asignaciones.xml',          ASIGNACIONES_XML),
    ('static/db/pagos_premios.xml',         PAGOS_PREMIOS_XML),
    ('static/db/resultados_sorteo.xml',     RESULTADOS_SORTEO_XML),
    ('static/db/sorteos.xml',               SORTEOS_XML),
    ('static/db/spinners.xml',              SPINNERS_XML),
    ('static/db/vmix_reintegro.xml',        VMIX_REINTEGRO_XML),
    ('static/db/vmix_spinners.xml',         VMIX_SPINNERS_XML),
    ('static/db/vmix_vendedores.xml',       VMIX_VENDEDORES_XML),
    ('static/db/vmix_ventas.xml',           VMIX_VENTAS_XML),
    ('static/db/vendedores.xml',           VENDEDORES_XML),
    ('static/db/datos_figuras.xml',          DATOS_FIGURAS_XML),
    ('static/db/figuras_por_fecha.xml',      FIGURAS_FECHA_XML),
    ('DATA/static/db/figuras_del_dia.xml',   FIGURAS_DEL_DIA_XML),
    ('static/LOGS/caja.xml',                LOGS_CAJA_XML),
    ('static/LOGS/impresiones.xml',         LOGS_IMPRESIONES_XML),
    ('static/CONTABILIDAD/bancos.xml',      CONTAB_BANCOS_XML),
    ('static/CONTABILIDAD/gastos.xml',      CONTAB_GASTOS_XML),
    ('static/CONTABILIDAD/sueldos.xml',     CONTAB_SUELDOS_XML),
    ('static/CONTABILIDAD/ventas.xml',      CONTAB_VENTAS_XML),
]:
    _seed(src, dst)

# (Opcional) Escritura atómica (más seguro ante cortes)
def write_text_atomic(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

# Copiar un XML persistente a /static/db (compatibilidad con URLs antiguas y vMix)
def _mirror_db_to_public(persist_abs: str):
    try:
        if not persist_abs or not os.path.exists(persist_abs):
            return
        public_dir = os.path.join(BASE_DIR, "static", "db")
        os.makedirs(public_dir, exist_ok=True)
        shutil.copy2(persist_abs, os.path.join(public_dir, os.path.basename(persist_abs)))
    except Exception as e:
        print(f"[WARN] Mirror static/db falló para {persist_abs}: {e}")

# Asegurar que estos XML queden visibles también en /static/db al iniciar
for _p in [locals().get("CAJA_XML"), locals().get("ASIGNACIONES_XML"), locals().get("VENDEDORES_XML"), locals().get("DATOS_FIGURAS_XML"), locals().get("FIGURAS_FECHA_XML"), locals().get("FIGURAS_DEL_DIA_XML")]:
    if _p:
        _mirror_db_to_public(_p)

# ==== FIN PERSISTENCIA ====

# ==== ENLAZAR CARPETAS DEL REPO -> DISCO PERSISTENTE (/data) ====
import os, shutil

PERSIST_ROOT = DATA_DIR
os.makedirs(PERSIST_ROOT, exist_ok=True)

def _bind_dir(repo_rel):
    """
    Enlaza (opcionalmente) carpetas del repo hacia PERSIST_ROOT.

    ⚠️ Importante: **NO borra** carpetas del repo. Antes se hacía un rmtree() y,
    si el symlink fallaba (muy común en Windows), al reiniciar se perdían datos.

    - Siempre crea la carpeta persistente.
    - "Siembra" archivos del repo → persistente solo si persistente está vacío.
    - En Linux/Mac intenta reemplazar la carpeta del repo por un symlink de forma SEGURA
      (primero crea el link, luego hace swap con backup). En Windows no lo intenta.
    """
    repo_abs    = os.path.join(BASE_DIR, repo_rel)
    persist_abs = os.path.join(PERSIST_ROOT, repo_rel)
    os.makedirs(persist_abs, exist_ok=True)

    # Sembrar (solo primera vez)
    try:
        if os.path.isdir(repo_abs) and os.path.isdir(persist_abs) and not os.listdir(persist_abs):
            for name in os.listdir(repo_abs):
                src = os.path.join(repo_abs, name)
                dst = os.path.join(persist_abs, name)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
    except Exception as e:
        print("Seed warning:", repo_rel, e)

    # Symlink seguro (solo POSIX). Se puede desactivar con ENABLE_SYMLINK_BIND=0
    if os.name == "nt" or os.environ.get("ENABLE_SYMLINK_BIND", "1") == "0":
        return

    try:
        if os.path.islink(repo_abs):
            return

        # Crea primero un symlink temporal; si falla, no tocamos nada
        tmp_link = repo_abs + ".__linktmp__"
        if os.path.lexists(tmp_link):
            try:
                if os.path.islink(tmp_link) or os.path.isfile(tmp_link):
                    os.unlink(tmp_link)
                else:
                    shutil.rmtree(tmp_link)
            except Exception:
                pass

        os.makedirs(os.path.dirname(repo_abs), exist_ok=True)
        os.symlink(persist_abs, tmp_link, target_is_directory=True)

        # Swap seguro: mueve carpeta actual a backup y pone el symlink en su lugar
        if os.path.exists(repo_abs):
            import time
            backup = repo_abs + f".__backup__{int(time.time())}"
            os.rename(repo_abs, backup)

        os.rename(tmp_link, repo_abs)

    except Exception as e:
        # Si algo falla, intentamos limpiar el tmp_link
        try:
            if os.path.lexists(tmp_link):
                if os.path.islink(tmp_link) or os.path.isfile(tmp_link):
                    os.unlink(tmp_link)
                else:
                    shutil.rmtree(tmp_link)
        except Exception:
            pass
        print("Bind warning:", repo_rel, e)


# Enlazar carpetas que CAMBIAN en runtime


_bind_dir("usuarios")
_bind_dir(os.path.join("static", "db"))
_bind_dir(os.path.join("static", "LOGS"))
_bind_dir(os.path.join("static", "CONTABILIDAD"))
# ==== FIN ENLACE PERSISTENTE ====


ROLES = [
    ('superadmin', 'Super Administrador'),
    ('admin', 'Administrador'),
    ('socio', 'Socio'),
    ('cobrador', 'Cobrador'),
    ('jugador', 'Jugador'),
    ('impresion', 'Impresión'),
]

# ─── UTILIDADES XML ────────────────────────
def leer_usuarios():
    if not os.path.exists(USUARIOS_XML):
        return []
    tree = ET.parse(USUARIOS_XML)
    root = tree.getroot()
    usuarios = []
    for elem in root.findall('usuario'):
        permisos_elem = elem.find('permisos')
        permisos_raw = None if permisos_elem is None else (permisos_elem.text or '')
        usuarios.append({
            'nombre': elem.findtext('nombre', ''),
            'clave': elem.findtext('clave', ''),
            'rol': elem.findtext('rol', ''),
            'email': elem.findtext('email', ''),
            'estado': elem.findtext('estado', 'activo'),
            'avatar': elem.findtext('avatar', 'avatar-male.png') or 'avatar-male.png',
            'permisos': _coerce_permisos(permisos_raw)
        })
    return usuarios

def guardar_usuarios(usuarios):
    root = ET.Element('usuarios')
    for u in usuarios:
        user_elem = ET.SubElement(root, 'usuario')
        ET.SubElement(user_elem, 'nombre').text = u.get('nombre', '')
        ET.SubElement(user_elem, 'clave').text = u.get('clave', '')
        ET.SubElement(user_elem, 'rol').text = u.get('rol', '')
        ET.SubElement(user_elem, 'email').text = u.get('email', '')
        ET.SubElement(user_elem, 'estado').text = u.get('estado', 'activo')
        ET.SubElement(user_elem, 'avatar').text = u.get('avatar', 'avatar-male.png')
        ET.SubElement(user_elem, 'permisos').text = ','.join(_coerce_permisos(u.get('permisos', None)))
    tree = ET.ElementTree(root)
    tree.write(USUARIOS_XML, encoding='utf-8', xml_declaration=True)

def obtener_usuario(nombre):
    usuarios = leer_usuarios()
    for u in usuarios:
        if u['nombre'] == nombre:
            return u
    return None

def eliminar_usuario(nombre):
    usuarios = leer_usuarios()
    usuarios = [u for u in usuarios if u['nombre'] != nombre]
    guardar_usuarios(usuarios)

# ─── LOGIN Y DASHBOARD ─────────────────────
@app.route('/login', methods=['GET', 'POST'])
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        usuarios = leer_usuarios()
        user = next((u for u in usuarios if u['nombre'] == usuario and u['clave'] == clave and u['estado'] == 'activo'), None)
        if user:
            session['usuario'] = user['nombre']
            session['rol'] = user['rol']
            session['avatar'] = user.get('avatar', 'avatar-male.png')
            session['permisos'] = list(user.get('permisos', _coerce_permisos(None)))
            return redirect(_ruta_inicio_permitida())
        else:
            flash('Usuario o clave incorrectos o usuario inactivo', 'error')
    return render_template('login.html')



# ===================== DASHBOARD (HOY) =====================
# Bloque auto-contenido. Si tu app ya define constantes o helpers
# (p.ej. CAJA_XML, get_configuracion_dia, _iter_impresiones) se usan tal cual.
# No rompe nada existente.

import os
import xml.etree.ElementTree as ET
from datetime import date, datetime
from flask import render_template, jsonify, request, session, redirect, url_for

# --- Rutas/archivos (respetamos existentes si ya están definidos) -------------
CAJA_XML              = globals().get('CAJA_XML',              _persist('static', 'db', 'caja.xml'))
VENDEDORES_XML        = globals().get('VENDEDORES_XML',        _persist('static', 'db', 'vendedores.xml'))
ASIGNACIONES_XML      = globals().get('ASIGNACIONES_XML',      _persist('static', 'db', 'asignaciones.xml'))
IMPRESION_LOG         = globals().get('IMPRESION_LOG',         _persist('static', 'IMPRESION', 'log.xml'))
BOLETOS_POR_PLANILLA  = int(globals().get('BOLETOS_POR_PLANILLA', 20))

# --- Helpers seguros -----------------------------------------------------------
def _parse_or_none(path):
    try:
        if not os.path.exists(path):
            return None, None
        t = ET.parse(path)
        return t, t.getroot()
    except ET.ParseError:
        return None, None

def _leer_xml_seguro(path, root_tag='root'):
    """Crea el XML vacío si no existe para evitar errores en primeras ejecuciones."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ET.ElementTree(ET.Element(root_tag)).write(path, encoding='utf-8', xml_declaration=True)
    t = ET.parse(path)
    return t, t.getroot()

def _vendor_map():
    """Devuelve {seudonimo: 'Nombre Apellido (Seud)'} para etiquetas lindas."""
    out = {}
    t, r = _parse_or_none(VENDEDORES_XML)
    if r is None:
        return out
    for v in r.findall('vendedor'):
        nom  = (v.findtext('nombre') or '').strip()
        ape  = (v.findtext('apellido') or '').strip()
        seud = (v.findtext('seudonimo') or '').strip()
        if seud:
            etiqueta = (nom + ' ' + ape).strip() or seud
            out[seud] = f"{etiqueta} ({seud})"
    return out

# ---------------- IMPRESOS / PLANILLAS IMPRESAS (tolerante al formato) --------
def _impresos_y_planillas_del_dia(fecha_iso):
    """
    Devuelve (boletos_impresos, planillas_impresas) del día.
    Soporta:
      - Iterador global _iter_impresiones() si existe (chequea tipo='boletos')
      - IMPRESION/log.xml con campos: fecha_sorteo|fecha|fecha_impresion y
        total_boletos|boletos|cantidad y/o total_planillas|planillas|cantidad_planillas
    """
    total_boletos = 0
    total_planillas = 0

    # Opción 1: usar helper existente
    if '_iter_impresiones' in globals():
        try:
            for n in globals()['_iter_impresiones']():
                tipo = (n.get('tipo') or '').strip().lower()
                f = (n.findtext('fecha_sorteo') or n.findtext('fecha') or n.findtext('fecha_impresion') or '').strip()
                if f != fecha_iso:
                    continue
                # si hay entrada de tipo Boletos
                if tipo and tipo != 'boletos':
                    continue
                # boletos
                for tag in ('total_boletos','boletos','cantidad'):
                    txt = n.findtext(tag)
                    if txt:
                        try: total_boletos += int(float(txt))
                        except: pass
                        break
                # planillas
                for tag in ('total_planillas','planillas','cantidad_planillas'):
                    txt = n.findtext(tag)
                    if txt:
                        try: total_planillas += int(float(txt))
                        except: pass
                        break
            # si no venían planillas en el log, derivamos por boletos // tamaño
            if total_planillas == 0 and BOLETOS_POR_PLANILLA > 0:
                total_planillas = total_boletos // BOLETOS_POR_PLANILLA
            return total_boletos, total_planillas
        except Exception:
            pass

    # Opción 2: leer log.xml directamente (sin helper)
    t, r = _parse_or_none(IMPRESION_LOG)
    if r is None:
        return 0, 0
    # buscar cualquier nodo que tenga los campos esperados
    for nodo in r.iter():
        # fecha
        f = None
        for ft in ('fecha_sorteo', 'fecha', 'fecha_impresion'):
            try:
                f = nodo.findtext(ft)
                if f: f = f.strip()
            except: f = None
            if f: break
        # fecha por atributo
        if not f:
            f = (getattr(nodo, 'get', lambda *_: '')('fecha') or '').strip()
        if f != fecha_iso:
            continue

        # si hay tipo y no es boletos, saltamos
        tipo = (getattr(nodo, 'get', lambda *_: '')('tipo') or '').strip().lower()
        if tipo and tipo != 'boletos':
            continue

        # boletos
        ok_boletos = False
        for tag in ('total_boletos','boletos','cantidad'):
            try:
                v = nodo.findtext(tag)
                if v:
                    total_boletos += int(float(v))
                    ok_boletos = True
                    break
            except: pass

        # planillas
        ok_pl = False
        for tag in ('total_planillas','planillas','cantidad_planillas'):
            try:
                v = nodo.findtext(tag)
                if v:
                    total_planillas += int(float(v))
                    ok_pl = True
                    break
            except: pass

        # si no hubo tag de planillas pero sí de boletos, derivar
        if not ok_pl and ok_boletos and BOLETOS_POR_PLANILLA > 0:
            total_planillas += int(total_boletos // BOLETOS_POR_PLANILLA)

    # normalizar
    if total_planillas == 0 and BOLETOS_POR_PLANILLA > 0:
        total_planillas = total_boletos // BOLETOS_POR_PLANILLA

    return int(total_boletos), int(total_planillas)

# ---------------- ASIGNACIONES (planillas asignadas) --------------------------
def _asignaciones_de_dia(fecha_iso):
    """Cuenta planillas asignadas y boletos entregados del día (asignaciones.xml)."""
    planillas = 0
    t, r = _parse_or_none(ASIGNACIONES_XML)
    if r is None:
        return 0, 0
    d = r.find(f"./dia[@fecha='{fecha_iso}']")
    if d is None:
        return 0, 0
    for v in d.findall('vendedor'):
        planillas += len(v.findall('planilla'))
    entregados = planillas * BOLETOS_POR_PLANILLA
    return planillas, entregados

# ---------------- CONFIGURACIÓN DEL DÍA (valor, comisión, meta) ----------------
def _config_del_dia(fecha_iso):
    """Obtiene configuración del día. Usa get_configuracion_dia si ya existe."""
    if 'get_configuracion_dia' in globals():
        try:
            return globals()['get_configuracion_dia'](fecha_iso)
        except Exception:
            pass
    # Fallback: leer de CAJA_XML
    _, root = _leer_xml_seguro(CAJA_XML, 'caja')
    dia = root.find(f"./dia[@fecha='{fecha_iso}']")
    if dia is None:
        return {"valor_boleto": 0.0, "comision_vendedor": 0.0, "comision_extra_meta": 0.0, "meta_boletos": 0}
    cfg = dia.find('configuracion')
    def ffloat(x, d=0.0):
        try: return float(x)
        except: return d
    def fint(x, d=0):
        try: return int(x)
        except: return d
    return {
        "valor_boleto": ffloat(cfg.findtext('valor_boleto', '0') if cfg is not None else '0'),
        "comision_vendedor": ffloat(cfg.findtext('comision_vendedor', '0') if cfg is not None else '0'),
        "comision_extra_meta": ffloat(cfg.findtext('comision_extra_meta', '0') if cfg is not None else '0'),
        "meta_boletos": fint(cfg.findtext('meta_boletos', '0') if cfg is not None else '0'),
    }

# ---------------- COBROS PAGADOS DEL DÍA (dos estructuras soportadas) ----------
def _iter_cobros_pagados(fecha_iso):
    """
    Itera cobros 'pagados' del día. Soporta dos estructuras en CAJA_XML:

      a) <dia fecha="..."><cobros>
           <cobro seudonimo="..." vendidos=".." devueltos=".."
                 transferencia=".." efectivo=".." pagado="1"/>
         </cobros></dia>

      b) <dia fecha="..."><vendedor>...<vendidos>..</vendidos>
             <devueltos>..</devueltos><transferencia>..</transferencia>
             <efectivo>..</efectivo><pagado>true</pagado>...</vendedor>
    """
    _, root = _leer_xml_seguro(CAJA_XML, 'caja')
    dia = root.find(f"./dia[@fecha='{fecha_iso}']")
    if dia is None:
        return

    # (a) estructura nueva
    cobros = dia.find('cobros')
    if cobros is not None and list(cobros.findall('cobro')):
        for c in cobros.findall('cobro'):
            seud = (c.attrib.get('seudonimo') or '').strip() or '—'
            pag  = (c.attrib.get('pagado') or c.attrib.get('pago') or '0')
            pag  = str(pag).strip().lower() in ('1', 'true', 'si', 'sí')
            if not pag:
                continue
            def I(attr, d=0):
                try: return int(float(c.attrib.get(attr, d) or d))
                except: return int(d)
            def F(attr, d=0.0):
                try: return float(c.attrib.get(attr, d) or d)
                except: return float(d)
            yield {
                "seudonimo": seud,
                "vendidos":  I('vendidos', 0),
                "devueltos": I('devueltos', 0),
                "transferencia": F('transferencia', 0.0),
                "efectivo": F('efectivo', 0.0),
            }
        return

    # (b) estructura antigua
    for v in dia.findall('vendedor'):
        ptxt = (v.findtext('pagado') or v.attrib.get('pagado') or '').strip().lower()
        if ptxt not in ('true', '1', 'si', 'sí'):
            continue
        seud = (v.findtext('seudonimo') or v.attrib.get('seudonimo') or '').strip() or '—'
        def I(tag, d=0):
            try: return int(v.findtext(tag) or d)
            except: return d
        def F(tag, d=0.0):
            try: return float(v.findtext(tag) or d)
            except: return d
        yield {
            "seudonimo": seud,
            "vendidos":  I('vendidos', 0),
            "devueltos": I('devueltos', 0),
            "transferencia": F('transferencia', 0.0),
            "efectivo": F('efectivo', 0.0),
        }

# ---------------- Composición de datos del Dashboard ---------------------------
def _dashboard_data(fecha_iso):
    cfg = _config_del_dia(fecha_iso)
    valor    = float(cfg.get('valor_boleto') or 0)
    base_pct = float(cfg.get('comision_vendedor') or 0)
    extra_pct= float(cfg.get('comision_extra_meta') or 0)
    meta     = int(cfg.get('meta_boletos') or 0)

    etiquetas_vendedores = _vendor_map()

    # Cobros pagados del día
    vendedores_det = []
    tot_vend = tot_dev = 0
    tot_ing = tot_gan_vend = tot_gan_emp = 0.0
    tot_e = tot_t = 0.0

    for c in _iter_cobros_pagados(fecha_iso) or []:
        vendidos  = int(c['vendidos'] or 0)
        devueltos = int(c['devueltos'] or 0)
        pct = base_pct + (extra_pct if (meta > 0 and vendidos >= meta) else 0)
        total_venta = vendidos * valor
        gan_v = total_venta * pct / 100.0
        gan_e = total_venta - gan_v

        seud = c['seudonimo']
        etiqueta = etiquetas_vendedores.get(seud, seud)

        vendedores_det.append({
            "vendedor": etiqueta,
            "seudonimo": seud,
            "vendidos": vendidos,
            "devueltos": devueltos,
            "total_venta": round(total_venta, 2),
            "gan_vendedor": round(gan_v, 2),
            "gan_empresa": round(gan_e, 2),
        })

        tot_vend += vendidos
        tot_dev  += devueltos
        tot_ing  += total_venta
        tot_gan_vend += gan_v
        tot_gan_emp  += gan_e
        tot_e  += float(c.get('efectivo') or 0)
        tot_t  += float(c.get('transferencia') or 0)

    # Impresos y planillas impresas
    boletos_impresos, planillas_impresas = _impresos_y_planillas_del_dia(fecha_iso)

    # Asignadas
    planillas_asignadas, _entregados = _asignaciones_de_dia(fecha_iso)
    planillas_blanco = max(int(planillas_impresas) - int(planillas_asignadas), 0)

    return {
        "fecha": fecha_iso,
        "boletos_impresos": int(boletos_impresos),
        "vendidos_total": int(tot_vend),
        "devueltos_total": int(tot_dev),
        "ingresos_brutos": round(tot_ing, 2),
        "ganancia_vendedores": round(tot_gan_vend, 2),
        "ganancia_empresa": round(tot_gan_emp, 2),
        "efectivo": round(tot_e, 2),
        "transferencia": round(tot_t, 2),
        "planillas_impresas": int(planillas_impresas),
        "planillas_asignadas": int(planillas_asignadas),
        "planillas_blanco": int(planillas_blanco),
        "vendedores": vendedores_det,
        "config": {
            "valor_boleto": valor,
            "comision_vendedor": base_pct,
            "comision_extra_meta": extra_pct,
            "meta_boletos": meta
        }
    }

# --- Rutas --------------------------------------------------------------------
@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(_login_url())
    return render_template(
        'dashboard.html',
        usuario=session.get('usuario',''),
        rol=session.get('rol',''),
        avatar=session.get('avatar','avatar-male.png')
    )

@app.get('/api/dashboard/hoy')
def api_dashboard_hoy():
    f = (request.args.get('fecha') or date.today().isoformat()).strip()
    try:
        datetime.fromisoformat(f)
    except Exception:
        f = date.today().isoformat()
    data = _dashboard_data(f)
    return jsonify({"ok": True, **data})



@app.route('/logout')
def logout():
    session.clear()
    return redirect(_login_url())

# ─── SECCIÓN DE USUARIOS ──────────────────
@app.route('/usuarios')
def usuarios():
    if 'usuario' not in session:
        return redirect(_login_url())
    lista_usuarios = leer_usuarios()
    roles = [r[1] for r in ROLES]
    return render_template(
        'usuarios.html',
        usuarios=lista_usuarios,
        roles=roles,
        modulos_permisos=MODULOS_PERMISOS,
        usuario=session['usuario'],
        rol=session['rol'],
        avatar=session.get('avatar', 'avatar-male.png')
    )

@app.route('/usuarios/guardar', methods=['POST'])
def guardar_usuario():
    nombre = request.form['username']
    clave = request.form['password']
    rol   = request.form['rol']
    email = request.form.get('email', '')
    avatar_filename = request.form.get('avatar_select', 'avatar-male.png')
    permisos = _coerce_permisos(request.form.getlist('permisos'))
    estado = 'activo'

    usuarios = leer_usuarios()
    existe = False
    for u in usuarios:
        if u['nombre'] == nombre:
            u['clave'] = clave
            u['rol'] = rol
            u['email'] = email
            u['avatar'] = avatar_filename
            u['permisos'] = permisos
            u['estado'] = estado
            existe = True
            break
    if not existe:
        usuarios.append({
            'nombre': nombre,
            'clave': clave,
            'rol': rol,
            'email': email,
            'avatar': avatar_filename,
            'permisos': permisos,
            'estado': estado
        })
    guardar_usuarios(usuarios)
    flash('Usuario guardado correctamente', 'success')
    return redirect(url_for('usuarios'))

@app.route('/usuarios/editar/<nombre>', methods=['GET', 'POST'])
def editar_usuario(nombre):
    if 'usuario' not in session:
        return redirect(_login_url())
    user = obtener_usuario(nombre)
    if not user:
        flash(f'Usuario "{nombre}" no encontrado', 'error')
        return redirect(url_for('usuarios'))
    roles = [r[1] for r in ROLES]
    if request.method == 'POST':
        user['clave'] = request.form['password']
        user['rol'] = request.form['rol']
        user['email'] = request.form.get('email', '')
        user['avatar'] = request.form.get('avatar_select', user.get('avatar', 'avatar-male.png'))
        user['permisos'] = _coerce_permisos(request.form.getlist('permisos'))
        usuarios = leer_usuarios()
        for u in usuarios:
            if u['nombre'] == nombre:
                u.update(user)
                break
        guardar_usuarios(usuarios)
        if session.get('usuario') == nombre:
            session['permisos'] = list(user.get('permisos', _coerce_permisos(None)))
        flash('Usuario editado correctamente', 'success')
        return redirect(url_for('usuarios'))
    return render_template(
        'usuarios_editar.html',
        user=user,
        roles=[r[1] for r in ROLES],
        modulos_permisos=MODULOS_PERMISOS,
        usuario=session['usuario'],
        rol=session['rol'],
        avatar=session.get('avatar', 'avatar-male.png')
    )

######__________________impresiones _________________________________####
######__________________impresiones _________________________________####
######__________________impresiones _________________________________####
######__________________impresiones _________________________________####




# -*- coding: utf-8 -*-
######__________________impresiones _________________________________####

import os, random, csv, math, shutil, unicodedata, json
from io import BytesIO, StringIO
from datetime import datetime, date
from threading import RLock  # RLock para evitar deadlocks reentrantes

import pandas as pd
from flask import (
    Flask, request, send_file, render_template, redirect,
    url_for, flash, jsonify, session
)
from markupsafe import Markup
from PyPDF2 import PdfMerger

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import qrcode
import xml.etree.ElementTree as ET

# ================== FALLBACKS APP/SESSION ==================
try:
    app  # noqa
except NameError:
    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = "glbingo-secret"
    app.config["JSON_AS_ASCII"] = False

try:
    require_session  # noqa
except NameError:
    def require_session(fn):
        def _wrap(*a, **k):  # aquí validarías sesión/rol real
            return fn(*a, **k)
        _wrap.__name__ = fn.__name__
        return _wrap

# ---------- utilidades ----------
def _to_int(v, default=0):
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _to_float(v, default=0.0):
    try:
        return float(str(v).strip().replace(',', '.'))
    except Exception:
        return default

def _read_df_for_series(archivo: str) -> pd.DataFrame:
    """Lee XLSX o CSV como texto; busca la serie en rutas robustas."""
    path = _resolve_series_path(archivo)
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
    return pd.read_excel(path, dtype=str).fillna("")

def fecha_ddmmyyyy(fecha_iso: str) -> str:
    try:
        return datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return fecha_iso

def format_money(valor) -> str:
    try:
        v = float(str(valor).replace(",", "."))
    except Exception:
        return f"${valor}"
    if abs(v - 1.0) < 1e-9:
        return "$1"
    if v < 1.0:
        s = f"{v:.2f}".replace(".", ",")
        return f"{s} ctvs"
    if abs(v - int(v)) < 1e-9:
        return f"${int(v)}"
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"${s}"

def _send_bytesio(buf: BytesIO, filename: str, mimetype: str = None):
    """Compat: Flask 1.x (attachment_filename) y 2.x (download_name)."""
    try:
        return send_file(buf, download_name=filename, as_attachment=True, mimetype=mimetype)
    except TypeError:
        return send_file(buf, attachment_filename=filename, as_attachment=True, mimetype=mimetype)

# ─── CONFIG PDFs ──────────────────────────────
BLEED    = 5 * mm
w, h     = A4
OFFSET_X = -20
OFFSET_Y = 5

# ─── RUTAS ────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR     = os.path.join(BASE_DIR, "static")
DATA_DIR       = globals().get("DATA_DIR") or os.path.join(BASE_DIR, "DATA")
REINTEGROS_DIR = os.path.join(DATA_DIR, "REINTEGROS")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REINTEGROS_DIR, exist_ok=True)

# Persistencia REAL en DATA_DIR/static/LOGS
LOGS_DIR = os.path.join(DATA_DIR, "static", "LOGS")
os.makedirs(LOGS_DIR, exist_ok=True)

# Migración inicial desde rutas antiguas
OLD_LOGS_DIR = os.path.join(STATIC_DIR, "LOGS")
old_xml = os.path.join(OLD_LOGS_DIR, "impresiones.xml")

IMPRESIONES_XML = globals().get(
    "LOGS_IMPRESIONES_XML",
    os.path.join(LOGS_DIR, "impresiones.xml")
)

if os.path.exists(old_xml) and not os.path.exists(IMPRESIONES_XML):
    try:
        shutil.copy2(old_xml, IMPRESIONES_XML)
        print("[MIGRATION] impresiones.xml migrado a:", IMPRESIONES_XML)
    except Exception as e:
        print("[WARN] Migración de impresiones.xml falló:", e)

# ─── Fuentes ──────────────────────────────────
ULTRA_BLACK_FONT = "Helvetica-Bold"
for fname in [
    "Montserrat-ExtraBold.ttf",
    "Inter-Black.ttf",
    "Poppins-Black.ttf",
    "ArchivoBlack-Regular.ttf",
    "Anton-Regular.ttf",
]:
    fpath = os.path.join(STATIC_DIR, "fonts", fname)
    if os.path.exists(fpath):
        try:
            pdfmetrics.registerFont(TTFont("UltraBlackLocal", fpath))
            ULTRA_BLACK_FONT = "UltraBlackLocal"
            break
        except Exception:
            pass

# ─── LAYOUT ───────────────────────────────────
MARGEN_IZQ     = 20
MARGEN_SUP     = 60
ESPACIO_X      = 140
ESPACIO_Y      = 115
COLUMNAS       = 2
FILAS          = 4

SIZE_NUM       = 23
SIZE_INFO      = 12
SIZE_ID_BIG    = 18
REINTEGRO_W    = 41
REINTEGRO_H    = 41

DELTA_Y_FILA_3 = 2
DELTA_Y_FILA_4 = 5

SERIE_MAP = {
    "Srs_ib1.xlsx":    "V",
    "Srs_ib2.xlsx":    "+",
    "Srs_ib3.xlsx":    "&",
    "Srs_Manila.xlsx": "M",
    "Srs_ib1.csv":     "V",
    "Srs_ib2.csv":     "+",
    "Srs_ib3.csv":     "&",
    "Srs_Manila.csv":  "M",
}


SERIE_MAP_CANON = {str(k).strip().lower(): v for k, v in SERIE_MAP.items()}

def _serie_key(nombre: str) -> str:
    try:
        return os.path.basename(str(nombre or "")).strip().lower()
    except Exception:
        return str(nombre or "").strip().lower()

def _serie_label(nombre: str) -> str:
    base = os.path.basename(str(nombre or "")).strip()
    return SERIE_MAP_CANON.get(_serie_key(base), base or str(nombre or "").strip())

def _series_search_dirs():
    dirs = []
    candidatos = [
        DATA_DIR,
        os.path.join(DATA_DIR, "data"),
        os.path.join(DATA_DIR, "DATA"),
        os.path.join(DATA_DIR, "static", "data"),
        os.path.join(BASE_DIR, "DATA"),
        os.path.join(BASE_DIR, "data"),
        os.path.join(BASE_DIR, "static", "data"),
    ]
    for d in candidatos:
        try:
            if d and os.path.isdir(d) and d not in dirs:
                dirs.append(d)
        except Exception:
            pass
    return dirs

def _list_series_files():
    permitidas = (".xlsx", ".csv")
    encontrados = {}

    for carpeta in _series_search_dirs():
        try:
            for nombre in os.listdir(carpeta):
                full = os.path.join(carpeta, nombre)
                if not os.path.isfile(full):
                    continue
                if not nombre.lower().endswith(permitidas):
                    continue

                key = _serie_key(nombre)
                if key not in encontrados:
                    encontrados[key] = os.path.basename(nombre)
        except Exception:
            continue

    orden = {
        "srs_ib1.xlsx": 1, "srs_ib1.csv": 1,
        "srs_ib2.xlsx": 2, "srs_ib2.csv": 2,
        "srs_ib3.xlsx": 3, "srs_ib3.csv": 3,
        "srs_manila.xlsx": 4, "srs_manila.csv": 4,
    }

    return sorted(
        encontrados.values(),
        key=lambda n: (orden.get(_serie_key(n), 999), _serie_key(n))
    )

def _resolve_series_path(archivo: str) -> str:
    raw = str(archivo or "").strip()
    if not raw:
        raise FileNotFoundError("Nombre de serie vacío")

    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw

    basename = os.path.basename(raw)

    # 1) exacto en directorios candidatos
    for carpeta in _series_search_dirs():
        for nombre in (raw, basename):
            try:
                ruta = os.path.join(carpeta, nombre)
            except Exception:
                continue
            if os.path.isfile(ruta):
                return ruta

    # 2) búsqueda case-insensitive por basename
    lower = basename.lower()
    for carpeta in _series_search_dirs():
        try:
            for nombre in os.listdir(carpeta):
                if nombre.lower() == lower and os.path.isfile(os.path.join(carpeta, nombre)):
                    return os.path.join(carpeta, nombre)
        except Exception:
            continue

    buscadas = ", ".join(_series_search_dirs()) or "(sin carpetas candidatas)"
    raise FileNotFoundError(f"No existe el archivo de serie: {archivo}. Busqué en: {buscadas}")

# ── OFFSETS EN CÓDIGO (boleto 0…7) ──
per_cell_offsets = {
    0: {"grid_x": -80, "grid_y": 20,  "info_x": 5,   "info_y": 25,  "rein_x":  225, "rein_y": 30},
    1: {"grid_x": -155, "grid_y": 20,  "info_x": -60, "info_y": 25,  "rein_x": 140, "rein_y": 30},
    2: {"grid_x": -80, "grid_y": 75,  "info_x": 5,   "info_y": 80,  "rein_x":  225, "rein_y":-25},
    3: {"grid_x": -155, "grid_y": 75,  "info_x": -60, "info_y": 80,  "rein_x": 140, "rein_y":-25},
    4: {"grid_x": -80, "grid_y": 133, "info_x": 5,   "info_y": 143, "rein_x":  225, "rein_y":-85},
    5: {"grid_x": -155, "grid_y": 133, "info_x": -60, "info_y": 143, "rein_x": 140, "rein_y":-85},
    6: {"grid_x": -80, "grid_y": 195, "info_x": 5,   "info_y": 200, "rein_x":  225, "rein_y":-145},
    7: {"grid_x": -155, "grid_y": 195, "info_x": -60, "info_y": 200, "rein_x": 140, "rein_y":-145},
}



bonus_cell_offsets = {
    0: {"offset_x": -10, "offset_y": -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
    1: {"offset_x": -5, "offset_y":  -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
    2: {"offset_x": -10, "offset_y": -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
    3: {"offset_x": -5, "offset_y":  -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
    4: {"offset_x": -10, "offset_y": -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
    5: {"offset_x": -5, "offset_y":  -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
    6: {"offset_x": -10, "offset_y": -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
    7: {"offset_x": -5, "offset_y":  -20, "scale": 150, "font_size": 9.0, "gap": 5, "slot_w": 10},
}


# ===== BONUS por boleto: usa SIEMPRE los offsets definidos en código =====
def _bonus_style_for_ticket(ticket_pos: int, ui_style: dict | None = None):
    """
    Combina el layout fijo por boleto (bonus_cell_offsets) con los ajustes globales
    que vengan del formulario.

    - bonus_cell_offsets manda por boleto y ya no queda "muerto".
    - scale (%) del diccionario en código sí afecta tamaño real del bonus.
    - Los valores del formulario se aplican como ajuste fino sin romper el layout.
    """
    ui_style = ui_style or {}
    base = bonus_cell_offsets.get(ticket_pos, {}) or {}

    def _clamp(v, lo, hi, default):
        try:
            v = float(v)
        except Exception:
            v = float(default)
        return max(lo, min(hi, v))

    scale_pct = _clamp(base.get('scale', 100.0), 10.0, 400.0, 100.0) / 100.0

    # Base del código por boleto
    code_offset_x = _clamp(base.get('offset_x', 0.0), -120.0, 120.0, 0.0)
    code_offset_y = _clamp(base.get('offset_y', 0.0), -120.0, 120.0, 0.0)
    code_font     = _clamp(base.get('font_size', 9.0), 6.0, 24.0, 9.0) * scale_pct
    code_gap      = _clamp(base.get('gap', 3.5), 0.0, 25.0, 3.5) * scale_pct
    code_slot_w   = _clamp(base.get('slot_w', 8.5), 4.0, 30.0, 8.5) * scale_pct

    # Ajuste fino desde UI/formulario respecto a la base actual del sistema
    ui_offset_x = _clamp(ui_style.get('offset_x', 0.0), -120.0, 120.0, 0.0)
    ui_offset_y = _clamp(ui_style.get('offset_y', 0.0), -120.0, 120.0, 0.0)
    ui_font_adj = _clamp(ui_style.get('font_size', 9.0), 6.0, 24.0, 9.0) - 9.0
    ui_gap_adj  = _clamp(ui_style.get('gap', 3.5), 0.0, 25.0, 3.5) - 3.5
    ui_slot_adj = _clamp(ui_style.get('slot_w', 8.5), 4.0, 30.0, 8.5) - 8.5

    merged = {
        'offset_x': _clamp(code_offset_x + ui_offset_x, -120.0, 120.0, 0.0),
        'offset_y': _clamp(code_offset_y + ui_offset_y, -120.0, 120.0, 0.0),
        'font_size': _clamp(code_font + ui_font_adj, 6.0, 24.0, code_font),
        'gap': _clamp(code_gap + ui_gap_adj, 0.0, 25.0, code_gap),
        'slot_w': _clamp(code_slot_w + ui_slot_adj, 4.0, 30.0, code_slot_w),
        'scale': round(scale_pct * 100.0, 2),
    }
    return merged

# ================== LOGS XML ==================
_LOG_LOCK = RLock()  # RLock para evitar deadlocks

def _ensure_logs_file():
    canon = globals().get("IMPRESIONES_XML") or _persist("static", "LOGS", "impresiones.xml")
    os.makedirs(os.path.dirname(canon), exist_ok=True)

    if os.path.exists(canon) and os.path.getsize(canon) > 32:
        return

    candidatos = [
        canon,
        os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "logs", "impresiones.xml"),
        os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "static", "db", "impresiones.xml"),
        os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "DB", "impresiones.xml"),
        os.path.join(BASE_DIR, "static", "LOGS", "impresiones.xml"),
        os.path.join(BASE_DIR, "static", "db", "impresiones.xml"),
    ]

    mejor = None
    mejor_size = -1
    for p in candidatos:
        try:
            if p and os.path.exists(p):
                sz = os.path.getsize(p)
                if sz > mejor_size:
                    mejor = p
                    mejor_size = sz
        except Exception:
            pass

    if mejor and os.path.abspath(mejor) != os.path.abspath(canon) and mejor_size > 32:
        import shutil
        shutil.copy2(mejor, canon)
        return

    root = ET.Element('impresiones')
    tree = ET.ElementTree(root)
    tmp_path = canon + ".tmp"
    tree.write(tmp_path, encoding='utf-8', xml_declaration=True)
    os.replace(tmp_path, canon)


def _read_logs_root():
    _ensure_logs_file()
    tree = ET.parse(IMPRESIONES_XML)
    return tree, tree.getroot()

def _write_logs_tree(tree):
    canon = globals().get("IMPRESIONES_XML") or _persist("static", "LOGS", "impresiones.xml")
    os.makedirs(os.path.dirname(canon), exist_ok=True)

    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass

    tmp_path = canon + ".tmp"
    tree.write(tmp_path, encoding='utf-8', xml_declaration=True)
    os.replace(tmp_path, canon)

    mirrors = [
        os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "logs", "impresiones.xml"),
        os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "static", "db", "impresiones.xml"),
        os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "DB", "impresiones.xml"),
    ]

    import shutil
    for p in mirrors:
        try:
            if os.path.abspath(p) == os.path.abspath(canon):
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)
            shutil.copy2(canon, p)
        except Exception:
            pass


def _get_next_id(root):
    mx = 0
    for n in root.findall('impresion'):
        try:
            mx = max(mx, int(n.get('id') or 0))
        except Exception:
            pass
    return mx + 1

def _ensure_log_ids():
    with _LOG_LOCK:
        tree, root = _read_logs_root()
        changed = False
        next_id = _get_next_id(root)
        for n in root.findall('impresion'):
            if not (n.get('id') or '').isdigit():
                n.set('id', str(next_id)); next_id += 1; changed = True
        if changed:
            _write_logs_tree(tree)

def _iter_impresiones():
    _ensure_log_ids()
    _, root = _read_logs_root()
    for n in root.findall('impresion'):
        yield n

def _series_impresas_en_fecha(fecha_yyyy_mm_dd):
    s = set()
    for imp in _iter_impresiones():
        if (imp.get('tipo') or '').lower() != 'boletos':
            continue
        if (imp.findtext('fecha_sorteo') or '') != fecha_yyyy_mm_dd:
            continue
        s.add(imp.get('serie_archivo') or '')
    return s

# === columnas para BONUS en la tabla simple (CSV/HTML logs)===
_LOG_COLS = [
    "id","fecha_hora","usuario","tipo","serie_archivo","desde","hasta",
    "valor","telefono","fecha_sorteo","reintegro_especial",
    "cant_reintegro_especial","incluir_aleatorio",
    "fecha_planilla","total_boletos","total_planillas",
    "excedente","lote",
    # bonus:
    "bonus_enabled","bonus_code","bonus_numbers","bonus_winners"
]

def _append_log_impresion_boletos(
    *, usuario, serie_archivo, desde, hasta, fecha_sorteo, total_boletos,
    valor, telefono, reintegro_especial, cant_reintegro_especial,
    incluir_aleatorio, excedente=0, lote='',
    # paquete bonus opcional
    bonus_payload: dict | None = None
) -> int:
    """Devuelve el id (int) del log creado."""
    with _LOG_LOCK:
        tree, root = _read_logs_root()
        _ensure_log_ids()
        next_id = _get_next_id(root)
        elem = ET.Element('impresion', attrib={
            'id'           : str(next_id),
            'fecha_hora'   : datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'usuario'      : str(usuario or ''),
            'tipo'         : 'boletos',
            'serie_archivo': str(serie_archivo or ''),
            'desde'        : str(desde or ''),
            'hasta'        : str(hasta or '')
        })
        def add(tag, val):
            c = ET.SubElement(elem, tag); c.text = '' if val is None else str(val)

        add('valor', valor)
        add('telefono', telefono)
        add('fecha_sorteo', fecha_sorteo)
        add('reintegro_especial', reintegro_especial)
        add('cant_reintegro_especial', cant_reintegro_especial)
        add('incluir_aleatorio', '1' if incluir_aleatorio else '0')
        add('total_boletos', total_boletos)
        try:
            tp = int(math.ceil(int(total_boletos) / 20.0))
        except Exception:
            tp = ''
        add('total_planillas', tp)
        add('excedente', '1' if excedente else '0')
        add('lote', lote)

        # Bloque BONUS dentro del XML (estructurado)
        if bonus_payload:
            add('bonus_enabled', '1')
            add('bonus_code', bonus_payload.get('code',''))
            add('bonus_numbers', ','.join(map(str, bonus_payload.get('numbers',[]))))
            # vista compacta:
            bw = bonus_payload.get('winners', {})
            parts = []
            for k in [5,4,3,2,1]:
                ids = bw.get(str(k), [])
                parts.append(f"{k}:[{','.join(map(str,ids))}]")
            add('bonus_winners', ';'.join(parts))

            bx = ET.SubElement(elem, 'bonus')
            bx.set('code', bonus_payload.get('code',''))
            bx.set('feasible', '1' if bonus_payload.get('feasible', True) else '0')
            ET.SubElement(bx, 'numbers').text = ','.join(map(str, bonus_payload.get('numbers',[])))
            req = bonus_payload.get('requested', {})
            ET.SubElement(bx, 'requested').text = json.dumps(req, ensure_ascii=False)
            win = bonus_payload.get('winners', {})
            for k in ['5','4','3','2','1']:
                ET.SubElement(bx, f"k{k}").text = ','.join(map(str, win.get(k, [])))
            sh = bonus_payload.get('shortages', {})
            if sh:
                ET.SubElement(bx, 'shortages').text = json.dumps(sh, ensure_ascii=False)

        root.append(elem)
        _write_logs_tree(tree)
        return next_id

def _append_log_impresion_planilla(
    *, usuario, serie_archivo, desde, hasta, fecha_planilla,
    lote_text='', excedente=0
):
    """Registra UNA sola fila por impresión de planillas (rango completo)."""
    with _LOG_LOCK:
        tree, root = _read_logs_root()
        _ensure_log_ids()
        next_id = _get_next_id(root)
        elem = ET.Element('impresion', attrib={
            'id'           : str(next_id),
            'fecha_hora'   : datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'usuario'      : str(usuario or ''),
            'tipo'         : 'planilla',
            'serie_archivo': str(serie_archivo or ''),
            'desde'        : str(desde or ''),
            'hasta'        : str(hasta or '')
        })
        def add(tag, val):
            c = ET.SubElement(elem, tag); c.text = '' if val is None else str(val)
        add('fecha_planilla', fecha_planilla)
        add('excedente', '1' if excedente else '0')
        add('lote', lote_text)
        try:
            total_b = int(hasta) - int(desde) + 1
        except Exception:
            total_b = ''
        add('total_boletos', total_b)
        try:
            tp = int(math.ceil(int(total_b) / 20.0)) if total_b != '' else ''
        except Exception:
            tp = ''
        add('total_planillas', tp)
        root.append(elem)
        _write_logs_tree(tree)

def _delete_log_by_id(log_id: str) -> bool:
    with _LOG_LOCK:
        tree, root = _read_logs_root()
        nodo = None
        for n in root.findall('impresion'):
            if (n.get('id') or '') == str(log_id):
                nodo = n; break
        if nodo is None:
            return False
        root.remove(nodo)
        _write_logs_tree(tree)
        return True

def get_printed_ids_for_day(fecha_yyyy_mm_dd, serie_archivo):
    printed = set()
    for imp in _iter_impresiones():
        if (imp.get('tipo') or '').lower() != 'boletos':
            continue
        if (imp.get('serie_archivo') or '') != serie_archivo:
            continue
        if (imp.findtext('fecha_sorteo') or '') != fecha_yyyy_mm_dd:
            continue
        try:
            d = int(imp.get('desde') or '0'); h = int(imp.get('hasta') or '-1')
        except Exception:
            continue
        if h >= d:
            for n in range(d, h + 1):
                printed.add(str(n))
    return printed

# ---------- Permisos ----------
def _normalize(s: str) -> str:
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return s.replace('-', ' ').replace('_', ' ').strip().lower()

def _is_superadmin() -> bool:
    rol_raw = session.get('rol') or ''
    rol_n = _normalize(rol_raw)
    if rol_n in {'superadmin', 'super administrador', 'superadministrador'}:
        return True
    perms = session.get('permisos') or []
    try:
        perms_l = {_normalize(str(p)) for p in perms}
    except Exception:
        perms_l = set()
    if any(p in perms_l for p in {'superadmin', 'super administrador', 'superadministrador', 'delete logs', 'logs delete'}):
        return True
    usuario = (session.get('usuario') or '').strip().upper()
    if usuario == 'GLSTUDIOS':
        return True
    return False

if os.getenv('GLBINGO_DEBUG_SUPER') == '1':
    @app.route('/debug/make-superadmin')
    def _debug_make_superadmin():
        session['rol'] = 'Super Administrador'
        u = session.get('usuario') or 'GLSTUDIOS'
        session['usuario'] = u
        flash('Sesión marcada como SUPERADMIN (modo debug).', 'success')
        return redirect(url_for('impresion'))

def _current_session_user_record():
    usuario = (session.get('usuario') or '').strip()
    if not usuario:
        return None
    usuario_n = _normalize(usuario)
    try:
        for u in leer_usuarios():
            nombre_u = (u.get('nombre') or '').strip()
            if nombre_u == usuario or _normalize(nombre_u) == usuario_n:
                return u
    except Exception:
        return None
    return None

def _is_admin_like() -> bool:
    rol_n = _normalize(session.get('rol') or '')
    return rol_n in {'administrador', 'admin', 'super administrador', 'superadministrador', 'superadmin'}

def _is_player_like() -> bool:
    rol_n = _normalize(session.get('rol') or '')
    return rol_n in {'jugador', 'player'}

def _sorteo_scope_allowed(scope: str) -> bool:
    scope = (scope or '').strip().lower()
    if scope == 'bonus_history':
        return _is_superadmin()
    if scope == 'programar_tablas':
        return _is_superadmin() or _is_admin_like() or _is_player_like()
    return False

def _verify_scope_password(scope: str, clave: str):
    if not _sorteo_scope_allowed(scope):
        return False, 'No tienes permiso para esta sección.'
    user = _current_session_user_record()
    if not user:
        return False, 'No se pudo validar la sesión actual.'
    clave_ok = str(user.get('clave') or '')
    if not clave_ok:
        return False, 'Tu usuario no tiene clave registrada.'
    if str(clave or '').strip() != str(clave_ok).strip():
        return False, 'Clave incorrecta.'
    return True, ''

def _backup_diario():
    try:
        if os.path.exists(IMPRESIONES_XML):
            ymd = datetime.now().strftime("%Y%m%d")
            bkp = os.path.join(LOGS_DIR, f"impresiones_{ymd}.bak.xml")
            if not os.path.exists(bkp):
                shutil.copy2(IMPRESIONES_XML, bkp)
    except Exception as e:
        print("[WARN] Backup diario falló:", e)
_backup_diario()

# ─── Endpoints logs (+ UI borrar para superadmin) ───────────
def _get_log_rows():
    rows = []
    for n in _iter_impresiones():
        d = dict(n.attrib)
        for ch in n:
            d[ch.tag] = ch.text or ''
        for k in _LOG_COLS:
            d.setdefault(k, "")
        rows.append(d)
    rows.sort(key=lambda x: x.get('fecha_hora', ''))
    return rows

@app.route('/logs-impresion')
@require_session
def logs_impresion_v2():
    rows = _get_log_rows()
    is_super = _is_superadmin()
    head_cells = _LOG_COLS + (["acciones"] if is_super else [])
    head = ''.join(f'<th style="padding:6px;border:1px solid #ccc;background:#f5f5f5">{c}</th>' for c in head_cells)
    trs = []
    for r in rows:
        tds = ''.join(f'<td style="padding:6px;border:1px solid #eee">{r.get(c,"")}</td>' for c in _LOG_COLS)
        if is_super:
            btn = (f'<td style="padding:6px;border:1px solid #eee">'
                   f'<button onclick="delLog({r.get("id","")})" '
                   f'style="padding:6px 10px;background:#d9534f;color:#fff;border:none;border-radius:4px;cursor:pointer">'
                   f'Eliminar</button></td>')
            tds += btn
        trs.append(f'<tr>{tds}</tr>')
    body = ''.join(trs)
    html = f"""
    <html>
    <head><meta charset="utf-8"><title>Logs de Impresión</title></head>
    <body style="font-family:Arial,Helvetica,sans-serif">
      <h2>Logs de Impresión</h2>
      <p>
        <a href="/logs-impresion.csv">Descargar CSV</a> &nbsp;|&nbsp;
        <a href="/logs-impresion.json">Ver JSON</a>
      </p>
      <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;min-width:1400px">
        <thead><tr>{head}</tr></thead>
        <tbody>{body}</tbody>
      </table>

      <script>
        async function delLog(id) {{
          if (!id) return alert("ID inválido");
          if (!confirm("¿Eliminar el registro " + id + "? Esta acción no se puede deshacer.")) return;
          try {{
            const res = await fetch('/logs-impresion/delete', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              credentials: 'same-origin',
              body: JSON.stringify({{ id: String(id) }})
            }});
            if (res.ok) {{
              location.reload();
            }} else {{
              const j = await res.json().catch(() => ({{}}));
              alert("No se pudo eliminar: " + (j.error || res.status));
            }}
          }} catch (e) {{
            alert("Error de red: " + e);
          }}
        }}
      </script>
    </body>
    </html>
    """
    return html

@app.route('/logs-impresion.csv')
@require_session
def logs_impresion_csv_v2():
    rows = _get_log_rows()
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=_LOG_COLS)
    writer.writeheader()
    writer.writerows(rows)
    csv_data = buf.getvalue()
    buf.close()
    return (
        csv_data, 200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=logs_impresion.csv",
        },
    )

@app.route('/logs-impresion.json')
@require_session
def logs_impresion_json_v2():
    rows = _get_log_rows()
    return jsonify(rows=rows, count=len(rows))

@app.route('/logs-impresion/delete', methods=['POST'])
@require_session
def logs_impresion_delete():
    if not _is_superadmin():
        return jsonify(ok=False, error='forbidden'), 403
    log_id = (request.json or {}).get('id') if request.is_json else request.form.get('id')
    if not log_id:
        return jsonify(ok=False, error='missing id'), 400
    ok = _delete_log_by_id(str(log_id))
    return (jsonify(ok=True) if ok else (jsonify(ok=False, error='not found'), 404))

# ================== GENERADORES PDF ==================
def _try_draw_qr_on_canvas(c, data, x, y, size):
    try:
        from qrcode.constants import ERROR_CORRECT_M
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=1,
            border=4
        )
        qr.add_data(str(data))
        qr.make(fit=True)

        matrix = qr.get_matrix()
        rows = len(matrix)
        cols = len(matrix[0]) if rows else 0
        total = max(rows, cols)
        if total <= 0:
            return False

        size = max(float(size), 1.0)
        module = size / float(total)
        qr_size = module * total
        ox = x + (size - qr_size) / 2.0
        oy = y + (size - qr_size) / 2.0

        c.saveState()
        c.setFillColorRGB(1, 1, 1)
        c.rect(ox, oy, qr_size, qr_size, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)

        for r, row in enumerate(matrix):
            py = oy + (total - 1 - r) * module
            run_start = None
            for col, bit in enumerate(row + [False]):
                if bit and run_start is None:
                    run_start = col
                elif not bit and run_start is not None:
                    c.rect(ox + run_start * module, py, (col - run_start) * module, module, stroke=0, fill=1)
                    run_start = None

        c.restoreState()
        return True
    except Exception:
        c.setFillGray(0.95)
        c.rect(x, y, size, size, stroke=0, fill=1)
        c.setFillGray(0.0)
        c.setFont("Helvetica", 6)
        c.drawCentredString(x + size/2, y + size/2 - 3, "QR")
        return False


def _safe_draw_image(c, path_or_buf, x, y, w_, h_):
    try:
        if isinstance(path_or_buf, (str, bytes)):
            if isinstance(path_or_buf, str) and not os.path.exists(path_or_buf):
                return False
            c.drawImage(ImageReader(path_or_buf), x, y, w_, h_, mask="auto")
            return True
        else:
            c.drawImage(ImageReader(path_or_buf), x, y, w_, h_, mask="auto")
            return True
    except Exception:
        return False

# ---- Dibujo de la franja BONUS (5 cuadros bajo el reintegro)----
def _draw_bonus_franja(c: canvas.Canvas, x_left: float, y_top_rein: float, numbers: list[int], style: dict | None = None):
    """
    x_left, y_top_rein: esquina superior-izquierda del área del reintegro ya dibujado.
    Dibuja debajo los 5 números BONUS (sin bordes), con ajustes opcionales de posición/tamaño.

    style (opcional):
      - offset_x: mueve horizontal (+ derecha / - izquierda)
      - offset_y: mueve vertical   (+ sube / - baja)
      - slot_w  : ancho de cada número ("alargar")
      - gap     : separación entre números
      - font_size: tamaño del número
    """
    if not numbers:
        return

    style = style or {}
    slot_w   = max(4.0, min(30.0, _to_float(style.get('slot_w', 8.5), 8.5)))
    gap      = max(0.0, min(25.0, _to_float(style.get('gap', 3.5), 3.5)))
    offset_x = max(-120.0, min(120.0, _to_float(style.get('offset_x', 0.0), 0.0)))
    offset_y = max(-120.0, min(120.0, _to_float(style.get('offset_y', 0.0), 0.0)))
    font_sz  = max(6.0, min(24.0, _to_float(style.get('font_size', 9.0), 9.0)))

    # Altura lógica (aunque no haya bordes) para centrar texto y separar etiqueta BONUS
    slot_h = max(8.5, font_sz + 1.5)
    label_font = max(7.0, min(18.0, font_sz - 0.5))

    total_w = 5 * slot_w + 4 * gap
    x0 = x_left + (REINTEGRO_W - total_w) / 2.0 + offset_x
    y0 = (y_top_rein - REINTEGRO_H - 10) + offset_y  # base bajo reintegro + ajuste

    # Etiqueta "BONUS"
    c.setFont("Helvetica-Bold", label_font)
    # Se elimina solo la etiqueta visible del BONUS en el boleto, sin mover números ni alterar el resto

    # Solo números (sin bordes)
    c.setFont("Helvetica-Bold", font_sz)
    baseline_adj = font_sz * 0.34
    for idx, n in enumerate(numbers[:5]):
        xi = x0 + idx * (slot_w + gap)
        yi = y0
        c.drawCentredString(xi + slot_w/2.0, yi + slot_h/2.0 - baseline_adj, str(n))

def generar_pdf_boletos_excel(
    ids, registros, valor, telefono,
    nombre, reintegro_especial,
    cant_especial, reintegros,
    incluir_aleatorio, fecha_sorteo,
    # puedes pasar un set global o una lista por boleto
    bonus_numbers_global: list[int] | None = None,
    bonus_numbers_per_ticket: list[list[int]] | None = None,
    qr_public_base: str | None = None,
    bonus_style: dict | None = None,
):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.translate(OFFSET_X, OFFSET_Y)

    fecha_num = fecha_ddmmyyyy(fecha_sorteo)
    precio_str = format_money(valor)

    N = len(registros)
    esp_idx = random.sample(range(N), min(N, cant_especial)) if reintegro_especial else []
    ale_idx = [i for i in range(N) if i not in esp_idx] if incluir_aleatorio else []

    for start in range(0, N, FILAS * COLUMNAS):
        page = registros[start:start + FILAS * COLUMNAS]

        for i, row in enumerate(page):
            pos = start + i
            col = i % COLUMNAS
            fil = i // COLUMNAS

            ancho_b = (w + 2 * MARGEN_IZQ - ESPACIO_X * (COLUMNAS - 1)) / COLUMNAS
            alto_b  = (h + 2 * MARGEN_SUP - ESPACIO_Y * (FILAS   - 1)) / FILAS
            x0 = MARGEN_IZQ + col * (ancho_b + ESPACIO_X)
            y0 = h - MARGEN_SUP - fil * (alto_b + ESPACIO_Y)
            if fil == 2: y0 -= DELTA_Y_FILA_3
            if fil == 3: y0 -= DELTA_Y_FILA_4

            size = min(ancho_b, alto_b) / 5
            offs = per_cell_offsets[i]

            # Rejilla 5×5 y QR en N3
            bx0 = x0 + ancho_b - size * 5 + offs['grid_x']
            by0 = y0 + offs['grid_y']
            c.setFont('Helvetica-Bold', SIZE_NUM)
            for r in range(5):
                for j, letra in enumerate('bingo'):
                    cx = bx0 + j * size
                    cy = by0 - r * size
                    if letra == 'n' and r == 2:
                        qr_data = f"{ids[pos]}|{fecha_sorteo}"
                        try:
                            if qr_public_base:
                                qr_data = _qr_ticket_url_compact(
                                    base_url=qr_public_base,
                                    serie_archivo=nombre,
                                    boleto_id=str(ids[pos]),
                                    fecha_iso=fecha_sorteo
                                )
                        except Exception:
                            pass
                        _try_draw_qr_on_canvas(c, qr_data, cx + 2, cy + 2, size - 4)
                    else:
                        v = str(row.get(f"{letra}{r+1}", "-"))
                        c.drawCentredString(cx + size / 2, cy + size * 0.28, v)

            # Texto inferior: ID grande + fecha + valor
            boleto_text = f"{ids[pos]}{SERIE_MAP.get(nombre, nombre)}"
            x_info = x0 + offs['info_x']
            y_info = y0 - size * 5 + offs['info_y']

            c.setFont(ULTRA_BLACK_FONT, SIZE_ID_BIG)
            c.drawString(x_info, y_info, boleto_text)

            dx_id = c.stringWidth(boleto_text, ULTRA_BLACK_FONT, SIZE_ID_BIG) + 4
            c.setFont('Helvetica', SIZE_INFO)
            fecha_str = f"| {fecha_num} | "
            c.drawString(x_info + dx_id, y_info, fecha_str)

            dx_fecha = c.stringWidth(fecha_str, 'Helvetica', SIZE_INFO)
            c.setFont('Helvetica-Bold', SIZE_INFO)
            c.drawString(x_info + dx_id + dx_fecha, y_info, precio_str)

            # Reintegro seguro
            img = None
            if pos in esp_idx and reintegro_especial:
                img = reintegro_especial
            elif pos in ale_idx and reintegros:
                others = [r for r in reintegros if r != reintegro_especial]
                img = random.choice(others) if others else None

            rein_x = x0 + offs['rein_x']
            rein_y_top = y0 - offs['rein_y']  # Y superior

            if img:
                path_img = os.path.join(REINTEGROS_DIR, img)
                _safe_draw_image(c, path_img, rein_x, rein_y_top, REINTEGRO_W, REINTEGRO_H)

            # ---- BONUS debajo del reintegro ----
            bn = None
            if bonus_numbers_per_ticket and pos < len(bonus_numbers_per_ticket):
                bn = bonus_numbers_per_ticket[pos]
            elif bonus_numbers_global:
                bn = bonus_numbers_global
            if bn:
                ticket_bonus_style = _bonus_style_for_ticket(i, bonus_style)
                _draw_bonus_franja(c, rein_x, rein_y_top, bn, style=ticket_bonus_style)

        c.showPage()
        c.translate(OFFSET_X, OFFSET_Y)

    c.save()
    buf.seek(0)
    return buf

def generar_pdf_planilla(ids, serie_archivo, vendedor, fecha, inicio, fin, serie_map, num_planilla=None, qr_public_base=None):
    LOGO_PATH = os.path.join("static", "golpe_suerte_logo.png")
    LOGO_LEFT_PAD        = 0.1
    DATE_GAP_AFTER_LOGO  = 1
    DATE_WIDTH_FACTOR    = 0.78
    DATE_MIN_WIDTH       = 220
    QR_SIZE_HDR          = 56

    PN_W, PN_H = 54, 22

    dt = datetime.strptime(fecha, "%Y-%m-%d")
    dias   = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    meses  = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}
    formatted_date = f"{dias[dt.weekday()]}, {dt.day} de {meses[dt.month]} del {dt.year}"
    fecha_limpia   = dt.strftime("%Y%m%d")
    serie_letra    = serie_map.get(serie_archivo, "")

    left_desde  = inicio
    left_hasta  = min(inicio + 19, fin)
    right_desde = inicio + 20
    right_hasta = min(inicio + 39, fin)
    full_desde  = inicio
    full_hasta  = min(inicio + 39, fin)

    def qr_cadena(tipo, desde, hasta, serie, planilla_num):
        txt_fallback = f"SORTEO{fecha_limpia}{tipo}A{desde}A{hasta}{serie}"
        try:
            if qr_public_base:
                return _qr_planilla_url(qr_public_base, serie_archivo, fecha, desde, hasta, planilla_num)
        except Exception:
            pass
        return txt_fallback

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    ancho, alto = landscape(A4)

    M_LEFT, M_RIGHT, M_BOTTOM = 12, 20, 20
    GUTTER        = 28
    HEADER_H      = 86
    QR_SIZE_HDR          = 56
    QR_SIZE_CENTER= min(GUTTER + 30, 50)

    HALF_W  = (ancho - M_LEFT - M_RIGHT - GUTTER) / 2
    TOP_Y   = alto - HEADER_H - 10
    BOT_Y   = M_BOTTOM
    AVAIL_H = TOP_Y - BOT_Y

    NUM_ROWS = 21
    ROW_H    = AVAIL_H / NUM_ROWS

    X_L = M_LEFT
    X_R = M_LEFT + HALF_W + GUTTER
    TABLE_W  = HALF_W - 20
    PAD      = 10

    FB = "Helvetica-Bold"

    left_index  = (left_desde  - 1) // 20 + 1
    right_index = (right_desde - 1) // 20 + 1

    def draw_header(x0, sheet_num, tipo, desde, hasta):
        from reportlab.lib import colors
        c.setFillColorRGB(0.92, 0.92, 0.92)
        c.rect(x0, alto - HEADER_H, HALF_W, HEADER_H, fill=1, stroke=0)
        c.setFillColor(colors.black)
        try:
            img = ImageReader(LOGO_PATH)
            ow, oh = img.getSize()
            max_logo_w = HALF_W * 0.25
            max_logo_h = HEADER_H - 10
            dw = max_logo_w
            dh = dw * oh / ow
            if dh > max_logo_h:
                dh = max_logo_h
                dw = dh * ow / oh
            logo_x = x0 + LOGO_LEFT_PAD
            logo_y = alto - HEADER_H + (HEADER_H - dh) / 2
            c.drawImage(img, logo_x, logo_y, width=dw, height=dh, mask="auto")
        except Exception:
            logo_x = x0 + LOGO_LEFT_PAD
            dw = 0

        gap = DATE_GAP_AFTER_LOGO
        right_reserved = 6 + QR_SIZE_HDR + 6 + PN_W + 6
        avail_for_date = HALF_W - ((logo_x - x0) + dw + gap + right_reserved)
        date_w = max(DATE_MIN_WIDTH, min(avail_for_date, HALF_W * DATE_WIDTH_FACTOR))
        date_h_top, date_h_bot = 26, 26
        space = 6
        total_h = date_h_top + space + date_h_bot
        bx = logo_x + dw + gap
        by = alto - HEADER_H + (HEADER_H - total_h) / 2

        c.setLineWidth(1.5)
        c.setFillGray(1.0)
        c.roundRect(bx, by + date_h_bot + space, date_w, date_h_top, 4, stroke=1, fill=1)
        c.roundRect(bx, by,                     date_w, date_h_bot, 4, stroke=1, fill=1)
        c.setFillGray(0.0)
        c.setFont(FB, 10)
        c.drawCentredString(bx + date_w/2, by + date_h_bot/2 - 4, formatted_date)

        data_qr = qr_cadena(tipo, desde, hasta, serie_letra, sheet_num)
        qx = x0 + HALF_W - QR_SIZE_HDR - 4
        qy = alto - HEADER_H + (HEADER_H - QR_SIZE_HDR) / 2
        _try_draw_qr_on_canvas(c, data_qr, qx, qy, QR_SIZE_HDR)

        px = qx + (QR_SIZE_HDR - PN_W) / 2
        py = qy - PN_H - 2
        c.setFillGray(1.0)
        c.roundRect(px, py, PN_W, PN_H, 6, stroke=0, fill=1)
        c.setFillGray(0.0)
        c.setFont("Helvetica-Bold", 15)
        c.drawCentredString(px + PN_W/2, py + PN_H/2 - 4, str(sheet_num))

    draw_header(X_L, left_index,  "L1", left_desde,  left_hasta)
    draw_header(X_R, right_index, "L2", right_desde, right_hasta)

    c.setLineWidth(2)
    c.line(X_R, TOP_Y, X_R, BOT_Y)

    fecha_limpia = dt.strftime("%Y%m%d")
    if qr_public_base:
        data_full = _qr_planilla_url(qr_public_base, serie_archivo, fecha, full_desde, full_hasta, "R")
    else:
        data_full = f"SORTEO{fecha_limpia}RGA{full_desde}A{full_hasta}{serie_letra}"
    cx = X_R - (GUTTER/2) - (QR_SIZE_CENTER/2)
    cy = BOT_Y + (AVAIL_H/2) - (QR_SIZE_CENTER/2)
    _try_draw_qr_on_canvas(c, data_full, cx, cy, QR_SIZE_CENTER)

    left_data = [["Boleto / Nombres Apellidos", ""]]
    for i in range(20):
        n = inicio + i
        left_data.append([str(n) if n <= fin else "", ""])

    right_data = [["Boleto / Nombres Apellidos", ""]]
    for i in range(20):
        n = inicio + 20 + i
        right_data.append([str(n) if n <= fin else "", ""])

    header_y = TOP_Y - ROW_H
    c.setLineWidth(1.5)
    c.roundRect(X_L + PAD, header_y, TABLE_W, ROW_H, 4, stroke=1, fill=0)
    c.roundRect(X_R + PAD, header_y, TABLE_W, ROW_H, 4, stroke=1, fill=0)

    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    style = TableStyle([
        ("SPAN",        (0,0),(1,0)),
        ("FONT",        (0,0),(1,0), "Helvetica-Bold", 10),
        ("ALIGN",       (0,0),(1,0), "CENTER"),
        ("FONT",        (0,1),(0,-1), "Helvetica-Bold", 12),
        ("FONT",        (1,1),(1,-1), "Helvetica", 8),
        ("VALIGN",      (0,0),(-1,-1), "MIDDLE"),
        ("INNERGRID",   (0,0),(-1,-1), 1, colors.black),
        ("BOX",         (0,0),(-1,-1), 2, colors.black),
        ("LEFTPADDING", (0,0),(-1,-1), 3),
        ("RIGHTPADDING",(0,0),(-1,-1), 3),
    ])

    tblL = Table(left_data,  colWidths=[40, TABLE_W-40], rowHeights=[ROW_H]*21)
    tblL.setStyle(style); tblL.wrapOn(c,0,0); tblL.drawOn(c, X_L+PAD, BOT_Y)

    tblR = Table(right_data, colWidths=[40, TABLE_W-40], rowHeights=[ROW_H]*21)
    tblR.setStyle(style); tblR.wrapOn(c,0,0); tblR.drawOn(c, X_R+PAD, BOT_Y)

    c.save()
    buffer.seek(0)
    return buffer


# ===================== QR BOLETOS / PLANILLAS (Público + vMix) =====================
QR_REGISTROS_XML     = _persist('static', 'db', 'qr_registros.xml')
VMIX_QR_CLIENTES_XML = _persist('static', 'db', 'vmix_qr_clientes.xml')

def _qr_ensure_xml(path, root_tag):
    try:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            root = ET.Element(root_tag)
            ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
            try:
                _mirror_db_to_public(path)
            except Exception:
                pass
        else:
            ET.parse(path)
    except Exception:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        root = ET.Element(root_tag)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        try:
            _mirror_db_to_public(path)
        except Exception:
            pass

_qr_ensure_xml(QR_REGISTROS_XML, "registros_qr")
_qr_ensure_xml(VMIX_QR_CLIENTES_XML, "clientes_qr")

def _qr_public_base_url():
    env_url = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env_url:
        return env_url
    try:
        return request.url_root.rstrip("/")
    except Exception:
        return ""

def _qr_sign_payload(parts):
    import hmac, hashlib
    secret = str(app.secret_key or "gl_bingo_secret").encode("utf-8")
    msg = "|".join([str(p or "") for p in parts]).encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:16]

def _qr_fecha_compacta(fecha_iso: str) -> str:
    try:
        dt = datetime.strptime(str(fecha_iso), "%Y-%m-%d")
        return dt.strftime("%y%m%d")
    except Exception:
        return str(fecha_iso or "").replace("-", "")


def _qr_fecha_expandida(fecha_compacta: str) -> str:
    raw = str(fecha_compacta or "").strip()
    if len(raw) == 6 and raw.isdigit():
        try:
            dt = datetime.strptime(raw, "%y%m%d")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return raw
    return raw


def _qr_serie_token(serie_archivo: str) -> str:
    serie = _serie_key(serie_archivo)
    mapa = {
        "srs_ib1.xlsx": "1",
        "srs_ib2.xlsx": "2",
        "srs_ib3.xlsx": "3",
        "srs_manila.xlsx": "M",
        "srs_ib1.csv": "1",
        "srs_ib2.csv": "2",
        "srs_ib3.csv": "3",
        "srs_manila.csv": "M",
    }
    return mapa.get(serie, os.path.basename(str(serie_archivo or "")).strip() or str(serie_archivo or "").strip())


def _qr_serie_from_token(token: str) -> str:
    tk = str(token or "").strip()
    candidatos = {
        "1": ["Srs_ib1.xlsx", "Srs_ib1.csv"],
        "2": ["Srs_ib2.xlsx", "Srs_ib2.csv"],
        "3": ["Srs_ib3.xlsx", "Srs_ib3.csv"],
        "M": ["Srs_Manila.xlsx", "Srs_Manila.csv"],
    }
    if tk in candidatos:
        for nombre in candidatos[tk]:
            try:
                _resolve_series_path(nombre)
                return nombre
            except Exception:
                continue
        return candidatos[tk][0]
    return tk


def _qr_ticket_url_compact(base_url: str, serie_archivo: str, boleto_id: str, fecha_iso: str) -> str:
    from urllib.parse import urlencode
    st = _qr_serie_token(serie_archivo)
    fc = _qr_fecha_compacta(fecha_iso)
    sig = _qr_sign_payload([serie_archivo, boleto_id, fecha_iso, "T"])[:10]
    qs = urlencode({
        "s": st,
        "b": str(boleto_id),
        "f": fc,
        "k": sig,
    })
    return f"{base_url}/q/t?{qs}"


def _qr_ticket_sig_ok_compact(serie_token, boleto, fecha_compacta, sig) -> bool:
    serie = _qr_serie_from_token(serie_token)
    fecha = _qr_fecha_expandida(fecha_compacta)
    expected = _qr_sign_payload([serie, boleto, fecha, "T"])[:10]
    return str(sig or "") == expected


def _qr_ticket_url(base_url: str, serie_archivo: str, boleto_id: str, fecha_iso: str) -> str:
    from urllib.parse import urlencode
    sig = _qr_sign_payload([serie_archivo, boleto_id, fecha_iso, "T"])
    qs = urlencode({
        "serie": serie_archivo,
        "boleto": str(boleto_id),
        "fecha": fecha_iso,
        "sig": sig
    })
    return f"{base_url}/qr/boleto?{qs}"

def _qr_planilla_url(base_url: str, serie_archivo: str, fecha_iso: str, desde: int, hasta: int, planilla_num) -> str:
    from urllib.parse import urlencode
    sig = _qr_sign_payload([serie_archivo, str(desde), str(hasta), fecha_iso, str(planilla_num), "P"])
    qs = urlencode({
        "serie": serie_archivo,
        "fecha": fecha_iso,
        "desde": int(desde),
        "hasta": int(hasta),
        "planilla": str(planilla_num),
        "sig": sig
    })
    return f"{base_url}/qr/planilla?{qs}"

def _qr_ticket_sig_ok(serie, boleto, fecha, sig) -> bool:
    expected = _qr_sign_payload([serie, boleto, fecha, "T"])
    return str(sig or "") == expected

def _qr_planilla_sig_ok(serie, desde, hasta, fecha, planilla, sig) -> bool:
    expected = _qr_sign_payload([serie, str(desde), str(hasta), fecha, str(planilla), "P"])
    return str(sig or "") == expected

def _qr_resolver_vendedor_por_boleto(fecha_iso: str, serie_archivo: str, boleto_id: str):
    try:
        df = _read_df_for_series(serie_archivo)
        id_col = df.columns[0]
        all_ids = [str(x).strip() for x in df[id_col].astype(str).tolist()]
        boleto_id = str(boleto_id).strip()
        if boleto_id not in all_ids:
            return {"vendedor": "", "planilla": "", "index": None}
        idx0 = all_ids.index(boleto_id)
        idx1 = idx0 + 1
        planilla_num = str(((idx1 - 1) // int(BOLETOS_POR_PLANILLA or 20)) + 1)

        if not os.path.exists(ASIGNACIONES_XML):
            return {"vendedor": "", "planilla": planilla_num, "index": idx1}

        root = ET.parse(ASIGNACIONES_XML).getroot()
        dia = None
        for d in root.findall("dia"):
            if (d.attrib.get("fecha") or "").strip() == str(fecha_iso).strip():
                dia = d
                break
        if dia is None:
            return {"vendedor": "", "planilla": planilla_num, "index": idx1}

        for vend in dia.findall("vendedor"):
            seud = (vend.attrib.get("seudonimo") or "").strip()
            nom  = (vend.attrib.get("nombre") or "").strip()
            ape  = (vend.attrib.get("apellido") or "").strip()
            for p in vend.findall("planilla"):
                if (p.attrib.get("serie") or "").strip() == str(serie_archivo).strip() and \
                   (p.attrib.get("numero") or "").strip() == planilla_num:
                    vendedor_txt = seud or f"{nom} {ape}".strip()
                    return {"vendedor": vendedor_txt, "planilla": planilla_num, "index": idx1}

        return {"vendedor": "", "planilla": planilla_num, "index": idx1}
    except Exception:
        return {"vendedor": "", "planilla": "", "index": None}

def _qr_guardar_registro_ticket(fecha_iso, serie_archivo, boleto_id, cliente_nombre, sector, celular, vendedor, planilla):
    _qr_ensure_xml(QR_REGISTROS_XML, "registros_qr")
    tree = ET.parse(QR_REGISTROS_XML)
    root = tree.getroot()

    key = f"{fecha_iso}|{serie_archivo}|{boleto_id}"
    node = None
    for r in root.findall("registro"):
        if (r.attrib.get("key") or "") == key:
            node = r
            break

    if node is None:
        node = ET.SubElement(root, "registro", {"key": key})

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    node.set("fecha_sorteo", str(fecha_iso))
    node.set("serie", str(serie_archivo))
    node.set("boleto", str(boleto_id))
    node.set("cliente_nombre", (cliente_nombre or "").strip())
    node.set("sector", (sector or "").strip())
    node.set("celular", (celular or "").strip())
    node.set("vendedor", (vendedor or "").strip())
    node.set("planilla", (planilla or "").strip())
    node.set("scan_at", now_str)

    tree.write(QR_REGISTROS_XML, encoding="utf-8", xml_declaration=True)
    try:
        _mirror_db_to_public(QR_REGISTROS_XML)
    except Exception:
        pass

    _qr_refrescar_vmix_clientes(fecha_iso)

def _qr_buscar_registro_ticket(fecha_iso, serie_archivo, boleto_id):
    try:
        _qr_ensure_xml(QR_REGISTROS_XML, "registros_qr")
        root = ET.parse(QR_REGISTROS_XML).getroot()
        key = f"{fecha_iso}|{serie_archivo}|{boleto_id}"
        for r in root.findall("registro"):
            if (r.attrib.get("key") or "") == key:
                return {
                    "cliente_nombre": r.attrib.get("cliente_nombre", ""),
                    "sector": r.attrib.get("sector", ""),
                    "celular": r.attrib.get("celular", ""),
                    "vendedor": r.attrib.get("vendedor", ""),
                    "planilla": r.attrib.get("planilla", ""),
                    "scan_at": r.attrib.get("scan_at", ""),
                }
    except Exception:
        pass
    return None

def _qr_refrescar_vmix_clientes(fecha_iso=None):
    try:
        _qr_ensure_xml(QR_REGISTROS_XML, "registros_qr")
        src_root = ET.parse(QR_REGISTROS_XML).getroot()

        regs = []
        for r in src_root.findall("registro"):
            regs.append({
                "fecha_sorteo": r.attrib.get("fecha_sorteo", ""),
                "serie": r.attrib.get("serie", ""),
                "boleto": r.attrib.get("boleto", ""),
                "cliente_nombre": r.attrib.get("cliente_nombre", ""),
                "sector": r.attrib.get("sector", ""),
                "celular": r.attrib.get("celular", ""),
                "vendedor": r.attrib.get("vendedor", ""),
                "planilla": r.attrib.get("planilla", ""),
                "scan_at": r.attrib.get("scan_at", "")
            })

        if fecha_iso:
            regs = [x for x in regs if x["fecha_sorteo"] == str(fecha_iso)]

        regs.sort(key=lambda x: x.get("scan_at", ""), reverse=True)

        root = ET.Element("clientes_qr")
        ult = regs[0] if regs else {}
        ET.SubElement(root, "ultimo", {
            "fecha_sorteo": ult.get("fecha_sorteo", ""),
            "serie": ult.get("serie", ""),
            "boleto": ult.get("boleto", ""),
            "cliente_nombre": ult.get("cliente_nombre", ""),
            "sector": ult.get("sector", ""),
            "celular": ult.get("celular", ""),
            "vendedor": ult.get("vendedor", ""),
            "planilla": ult.get("planilla", ""),
            "scan_at": ult.get("scan_at", "")
        })

        lista = ET.SubElement(root, "lista")
        for i, r in enumerate(regs[:30], start=1):
            ET.SubElement(lista, "cliente", {"idx": str(i), **{k: str(v or "") for k, v in r.items()}})

        ET.ElementTree(root).write(VMIX_QR_CLIENTES_XML, encoding="utf-8", xml_declaration=True)
        try:
            _mirror_db_to_public(VMIX_QR_CLIENTES_XML)
        except Exception:
            pass
    except Exception as e:
        print("[WARN] _qr_refrescar_vmix_clientes:", e)

def _qr_sorteo_bloqueado_para_registro(fecha_iso: str) -> bool:
    """
    Devuelve True si ya hay resultados cargados para el sorteo y el QR debe quedar solo en modo consulta.
    """
    try:
        resultados = _cargar_resultados(fecha_iso) or {}
        items = resultados.get("items") or []
        extras = resultados.get("extras") or {}

        # Si ya hay figuras ganadoras cargadas, se bloquea registro
        if items:
            return True

        # Si hay extras con contenido real (comodín, gran bonus, etc.), también se bloquea
        if isinstance(extras, dict):
            for v in extras.values():
                if isinstance(v, dict):
                    if any(str(x or "").strip() for x in v.values()):
                        return True
                elif isinstance(v, list):
                    if any(str(x or "").strip() for x in v):
                        return True
                else:
                    if str(v or "").strip():
                        return True

        return False
    except Exception as e:
        print('[WARN] _qr_sorteo_bloqueado_para_registro:', e)
        return False

def _qr_premios_de_boleto(fecha_iso: str, serie_archivo: str, boleto_id: str):
    out = {"tiene_premio": False, "figuras": [], "extras": []}
    try:
        resultados = _cargar_resultados(fecha_iso) or {"items": [], "extras": {}}
        suf = SERIE_MAP.get(serie_archivo, serie_archivo)
        boleto_publico = f"{boleto_id}{suf}"

        for item in (resultados.get("items") or []):
            figura = (item.get("figura") or "").strip()
            for g in (item.get("ganadores") or []):
                b = str(g.get("boleto") or "").strip()
                if b in (str(boleto_id), boleto_publico):
                    out["figuras"].append({
                        "figura": figura,
                        "premio": float(g.get("premio") or 0),
                        "vendedor": g.get("vendedor", ""),
                        "nombre": g.get("nombre", ""),
                        "sector": g.get("sector", "")
                    })

        com = (resultados.get("extras") or {}).get("comodin") or {}
        com_boletos = str(com.get("boletos") or "").strip()
        if com_boletos:
            tokens = [t.strip() for t in com_boletos.replace(";", ",").split(",") if t.strip()]
            if str(boleto_id) in tokens or boleto_publico in tokens:
                out["extras"].append({"tipo": "comodin", "texto": com.get("texto", "")})

        # Hook opcional para spinners si luego guardas ganadores spinner por boleto en resultados/otro XML
        out["tiene_premio"] = bool(out["figuras"] or out["extras"])
        return out
    except Exception:
        return out

@app.route("/q/t", methods=["GET", "POST"])
def qr_boleto_publico_compacto():
    from flask import redirect, request
    serie_token = (request.values.get("s") or "").strip()
    boleto = (request.values.get("b") or "").strip()
    fecha_compacta = (request.values.get("f") or "").strip()
    sig = (request.values.get("k") or "").strip()

    if not serie_token or not boleto or not fecha_compacta or not _qr_ticket_sig_ok_compact(serie_token, boleto, fecha_compacta, sig):
        return "QR inválido o alterado.", 400

    serie = _qr_serie_from_token(serie_token)
    fecha = _qr_fecha_expandida(fecha_compacta)
    from urllib.parse import urlencode
    qs = urlencode({"serie": serie, "boleto": boleto, "fecha": fecha, "sig": _qr_sign_payload([serie, boleto, fecha, "T"] )})
    target = f"/qr/boleto?{qs}"
    if request.method == "POST":
        return redirect(target, code=307)
    return redirect(target)


@app.route("/qr/boleto", methods=["GET", "POST"])
def qr_boleto_publico():
    from flask import render_template_string
    serie = (request.values.get("serie") or "").strip()
    boleto = (request.values.get("boleto") or "").strip()
    fecha = (request.values.get("fecha") or "").strip()
    sig = (request.values.get("sig") or "").strip()

    if not serie or not boleto or not fecha or not _qr_ticket_sig_ok(serie, boleto, fecha, sig):
        return "QR inválido o alterado.", 400

    vend_info = _qr_resolver_vendedor_por_boleto(fecha, serie, boleto)
    vendedor = vend_info.get("vendedor", "")
    planilla = vend_info.get("planilla", "")

    reg = _qr_buscar_registro_ticket(fecha, serie, boleto) or {}
    premios = _qr_premios_de_boleto(fecha, serie, boleto)
    sorteo_finalizado = _qr_sorteo_bloqueado_para_registro(fecha)
    vendido = bool((reg.get("cliente_nombre") or "").strip())

    msg = ""
    if request.method == "POST":
        if sorteo_finalizado:
            msg = "⛔ El sorteo ya finalizó. Este QR ahora es solo de consulta."
        else:
            cliente_nombre = (request.form.get("cliente_nombre") or "").strip()
            sector = (request.form.get("sector") or "").strip()
            celular = (request.form.get("celular") or "").strip()
            if cliente_nombre:
                _qr_guardar_registro_ticket(
                    fecha_iso=fecha,
                    serie_archivo=serie,
                    boleto_id=boleto,
                    cliente_nombre=cliente_nombre,
                    sector=sector,
                    celular=celular,
                    vendedor=vendedor,
                    planilla=planilla
                )
                reg = _qr_buscar_registro_ticket(fecha, serie, boleto) or {}
                vendido = bool((reg.get("cliente_nombre") or "").strip())
                msg = "✅ Registro guardado correctamente."
            else:
                msg = "⚠️ Escribe tu nombre o cábala para registrar el boleto."

    suf = SERIE_MAP.get(serie, serie)
    boleto_publico = f"{boleto}{suf}"

    # Etiquetas de premio para vista cliente
    premios_labels = []
    try:
        for f in (premios.get("figuras") or []):
            nombre_fig = str(f.get("figura") or "Figura").strip()
            val = float(f.get("premio") or 0)
            if val > 0:
                premios_labels.append(f"{nombre_fig} (${val:.2f})")
            else:
                premios_labels.append(nombre_fig)
        for e in (premios.get("extras") or []):
            tipo = str(e.get("tipo") or "extra").strip().lower()
            texto = str(e.get("texto") or "").strip()
            if tipo == 'comodin':
                premios_labels.append('Reintegro' + (f" - {texto}" if texto else ""))
            elif tipo in ('spinner','spinners','golpe de suerte'):
                premios_labels.append('Golpe de Suerte' + (f" - {texto}" if texto else ""))
            else:
                premios_labels.append(tipo.title() + (f" - {texto}" if texto else ""))
    except Exception:
        premios_labels = []

    premio_principal = premios_labels[0] if premios_labels else '-'
    premio_tiene = bool(premios_labels)
    premio_color = '#1d4ed8' if premio_tiene else '#6b7280'

    # Mostrar serie limpia para cliente
    serie_cliente = str(serie).replace('.csv','').replace('.xlsx','')

    html = """
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Boleto {{ boleto_publico }}</title>
      <style>
        *{box-sizing:border-box}
        body{margin:0;font-family:Inter,Arial,sans-serif;background:#eef2f7;color:#1f2937}
        .wrap{max-width:480px;margin:0 auto;min-height:100vh;background:#eef2f7}
        .hero{background:linear-gradient(180deg,#ffcc00 0%, #ff5a00 42%, #942ad6 100%);color:#fff;padding:22px 18px 26px;border-bottom-left-radius:36px;border-bottom-right-radius:36px;box-shadow:0 10px 30px rgba(0,0,0,.12)}
        .logo{display:flex;justify-content:center;align-items:center;margin-bottom:10px}
        .logo img{max-width:190px;max-height:80px;object-fit:contain;display:block}
        .logo-text{font-size:34px;font-weight:900;letter-spacing:.5px;text-align:center;text-shadow:0 2px 8px rgba(0,0,0,.25)}
        .sub{font-size:14px;text-align:center;opacity:.95;margin-top:2px}
        .hero-grid{margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:12px}
        .hero-item{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.35);backdrop-filter:blur(6px);border-radius:12px;padding:10px 12px;text-align:center}
        .hero-item .k{font-size:12px;opacity:.9}
        .hero-item .v{font-size:20px;font-weight:800;line-height:1.1}
        .panel{background:#eef2f7;margin-top:-16px;border-top-left-radius:28px;border-top-right-radius:28px;padding:14px 14px 20px;min-height:50vh}
        .card{background:#fff;border-radius:16px;padding:14px;box-shadow:0 4px 14px rgba(15,23,42,.08);margin-bottom:12px;border:1px solid #e4eaf3}
        .row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 2px;border-bottom:1px solid #e8edf5}
        .row:last-child{border-bottom:none}
        .l{display:flex;align-items:center;gap:10px;color:#6b7280;font-weight:600}
        .ico{width:22px;height:22px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;background:#f3f4f6;color:#6b7280;font-size:13px}
        .rv{font-weight:800;color:#111827}
        .rv.blue{color:#3349d0}
        .muted{color:#6b7280;font-size:12px}
        .split{border-top:1px solid #d6dbe6;margin:10px 0}
        .chips{display:flex;gap:8px;flex-wrap:wrap}
        .chip{border-radius:999px;padding:6px 10px;font-weight:700;font-size:12px;border:1px solid}
        .chip.ok{background:#ecfdf3;color:#027a48;border-color:#a6f4c5}
        .chip.no{background:#fff1f2;color:#b42318;border-color:#f3b3b3}
        .chip.mode{background:#eef4ff;color:#1d4ed8;border-color:#bfd3ff}
        .chip.mode2{background:#f3f4f6;color:#4b5563;border-color:#d1d5db}
        .title2{font-size:13px;color:#4b5563;font-weight:800;text-transform:uppercase;letter-spacing:.4px;margin-bottom:8px}
        .msg{padding:10px 12px;border-radius:12px;font-weight:700;font-size:13px;margin-bottom:8px}
        .msg.ok{background:#ecfdf3;border:1px solid #a6f4c5;color:#027a48}
        .msg.warn{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412}
        .msg.err{background:#fff1f2;border:1px solid #fecdd3;color:#b42318}
        .formbox{background:#fff;border-radius:18px;padding:16px;box-shadow:0 4px 14px rgba(15,23,42,.08);border:1px solid #e4eaf3}
        .field{width:100%;height:42px;border-radius:999px;border:1px solid #d4dbe7;background:#f8fafc;text-align:center;font-size:15px;padding:0 14px;margin:0 0 10px;color:#111827}
        .field::placeholder{color:#9aa4b2}
        .btn{width:100%;height:42px;border:none;border-radius:999px;background:linear-gradient(90deg,#7c3aed,#a855f7);color:#fff;font-size:15px;font-weight:800;cursor:pointer;box-shadow:0 6px 14px rgba(124,58,237,.28)}
        .btn:active{transform:translateY(1px)}
        .help{font-size:12px;color:#64748b;text-align:center;margin-top:8px}
        .pillline{display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border:1px solid #e5e7eb;border-radius:12px;background:#f8fafc;margin-bottom:8px}
        .premios-list{display:grid;gap:6px;margin-top:8px}
        .premio-item{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:8px 10px;font-size:13px}
        .center{text-align:center}
        .small-note{font-size:11px;color:#64748b}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="hero">
          <div class="logo">
            <img src="/static/golpe_suerte_logo.png" alt="logo" onerror="if(!this.dataset.fallback){this.dataset.fallback=1;this.src='/static/data/logo_qr_cliente.png';}else{this.style.display='none'; this.nextElementSibling.style.display='block';}">
            <div class="logo-text" style="display:none;">SHOW FAMILIAR</div>
          </div>
          <div class="sub">{{ 'Consulta tu boleto' if sorteo_finalizado else 'Registra tu boleto antes del sorteo' }}</div>
          <div class="hero-grid">
            <div class="hero-item">
              <div class="k">Fecha</div>
              <div class="v" style="font-size:16px">{{ fecha }}</div>
            </div>
            <div class="hero-item">
              <div class="k">Boleto</div>
              <div class="v">{{ boleto_publico }}</div>
            </div>
          </div>
        </div>

        <div class="panel">
          {% if msg %}
            <div class="msg {% if '✅' in msg %}ok{% elif '⛔' in msg %}err{% else %}warn{% endif %}">{{ msg }}</div>
          {% endif %}

          <div class="card">
            <div class="chips" style="margin-bottom:10px;">
              <span class="chip {{ 'ok' if vendido else 'no' }}">{{ 'VENDIDO' if vendido else 'NO REGISTRADO' }}</span>
              {% if sorteo_finalizado %}
                <span class="chip mode2">Modo consulta</span>
              {% else %}
                <span class="chip mode">Registro abierto</span>
              {% endif %}
            </div>
          </div>

          {% if not sorteo_finalizado %}
            <div class="formbox">
              <div class="title2 center">Bienvenido</div>
              <div class="muted center" style="margin-bottom:10px">Registra tu boleto con nombre/cábala y sector o barrio.</div>
              <form method="post">
                <input type="hidden" name="serie" value="{{ serie }}">
                <input type="hidden" name="boleto" value="{{ boleto }}">
                <input type="hidden" name="fecha" value="{{ fecha }}">
                <input type="hidden" name="sig" value="{{ sig }}">

                <input class="field" name="cliente_nombre" value="{{ reg.get('cliente_nombre','') }}" placeholder="Nombre o Cábala" required>
                <input class="field" name="celular" value="{{ reg.get('celular','') }}" placeholder="Teléfono">
                <input class="field" name="sector" value="{{ reg.get('sector','') }}" placeholder="Barrio o Sector">
                <button class="btn" type="submit">Registrar</button>
              </form>
              <div class="help">Puedes corregir los datos escaneando otra vez este mismo QR antes del sorteo.</div>
            </div>
          {% else %}
            <div class="card">
              <div class="title2">Resultado del boleto</div>
              <div class="row">
                <div class="l"><span class="ico">💵</span>Premio</div>
                <div class="rv" style="color:{{ premio_color }}">{{ premio_principal }}</div>
              </div>
              <div class="row">
                <div class="l"><span class="ico">🎟️</span>Boleto</div>
                <div class="rv blue">{{ boleto_publico }}</div>
              </div>
              <div class="row">
                <div class="l"><span class="ico">🎲</span>Sorteo</div>
                <div class="rv blue">{{ fecha }}</div>
              </div>
              <div class="row">
                <div class="l"><span class="ico">🧾</span>Venta</div>
                <div class="rv">{{ 'Registrado' if vendido else 'No registrado' }}</div>
              </div>
              <div class="row">
                <div class="l"><span class="ico">🎁</span>Premios especiales</div>
                <div class="rv">{{ 'Sí' if premio_tiene else 'No' }}</div>
              </div>

              {% if vendido %}
                <div class="split"></div>
                <div class="muted" style="font-weight:700;color:#475467;">Cliente: {{ reg.get('cliente_nombre','—') }}</div>
                <div class="muted">Teléfono: {{ reg.get('celular','—') }}</div>
                <div class="muted">Barrio/Sector: {{ reg.get('sector','—') }}</div>
              {% endif %}

              {% if premio_tiene %}
                <div class="split"></div>
                <div class="title2" style="margin-bottom:6px">Detalle de premios</div>
                <div class="premios-list">
                  {% for p in premios_labels %}
                    <div class="premio-item">🏆 {{ p }}</div>
                  {% endfor %}
                </div>
              {% else %}
                <div class="split"></div>
                <div class="center small-note">Este boleto no tiene ganador registrado.</div>
              {% endif %}
            </div>
          {% endif %}

          {% if sorteo_finalizado and not vendido %}
            <div class="card">
              <div class="title2">Estado de venta</div>
              <div class="msg err" style="margin:0">Este boleto no tiene registro de cliente. Se muestra como NO VENDIDO / NO REGISTRADO.</div>
            </div>
          {% endif %}
        </div>
      </div>
    </body>
    </html>
    """
    return render_template_string(
        html,
        msg=msg,
        serie=serie,
        boleto=boleto,
        fecha=fecha,
        sig=sig,
        vendedor=vendedor,
        planilla=planilla,
        reg=reg,
        premios=premios,
        premios_labels=premios_labels,
        premio_principal=premio_principal,
        premio_tiene=premio_tiene,
        premio_color=premio_color,
        boleto_publico=boleto_publico,
        serie_cliente=serie_cliente,
        sorteo_finalizado=sorteo_finalizado,
        vendido=vendido,
    )

@app.route("/qr/planilla")
def qr_planilla_publica():
    from flask import render_template_string
    serie = (request.args.get("serie") or "").strip()
    fecha = (request.args.get("fecha") or "").strip()
    desde = (request.args.get("desde") or "").strip()
    hasta = (request.args.get("hasta") or "").strip()
    planilla = (request.args.get("planilla") or "").strip()
    sig = (request.args.get("sig") or "").strip()

    try:
        d_int = int(desde); h_int = int(hasta)
    except Exception:
        return "Parámetros inválidos.", 400

    if not _qr_planilla_sig_ok(serie, d_int, h_int, fecha, planilla, sig):
        return "QR de planilla inválido.", 400

    vendedor_txt = ""
    try:
        if os.path.exists(ASIGNACIONES_XML):
            root = ET.parse(ASIGNACIONES_XML).getroot()
            dia = None
            for d in root.findall("dia"):
                if (d.attrib.get("fecha") or "") == fecha:
                    dia = d
                    break
            if dia is not None:
                for v in dia.findall("vendedor"):
                    for p in v.findall("planilla"):
                        if (p.attrib.get("serie") or "") == serie and (p.attrib.get("numero") or "") == str(planilla):
                            vendedor_txt = (v.attrib.get("seudonimo") or "").strip() or \
                                           f"{(v.attrib.get('nombre') or '').strip()} {(v.attrib.get('apellido') or '').strip()}".strip()
                            break
    except Exception:
        pass

    html = """
    <!doctype html>
    <html lang="es"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Planilla {{planilla}}</title>
      <style>
        body{font-family:Arial;background:#f4f6fb;padding:12px}
        .card{max-width:760px;margin:auto;background:#fff;border-radius:14px;padding:16px;box-shadow:0 6px 18px rgba(0,0,0,.08)}
        .row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
        .pill{background:#f2f5fb;border:1px solid #dce5f2;border-radius:10px;padding:8px}
      </style>
    </head><body>
      <div class="card">
        <h2>📋 Planilla {{planilla}}</h2>
        <div class="row">
          <div class="pill"><b>Fecha:</b> {{fecha}}</div>
          <div class="pill"><b>Serie:</b> {{serie}}</div>
          <div class="pill"><b>Rango:</b> {{desde}} - {{hasta}}</div>
          <div class="pill"><b>Vendedor:</b> {{vendedor or 'Sin asignar aún'}}</div>
        </div>
        <p style="margin-top:12px">Esta planilla pertenece al rango de boletos indicado. Puedes usar este QR para control rápido del vendedor/cobro.</p>
      </div>
    </body></html>
    """
    return render_template_string(html, serie=serie, fecha=fecha, desde=d_int, hasta=h_int, planilla=planilla, vendedor=vendedor_txt)


# =============== BONUS: utilidades ===================

def _bonus_assign_by_number(ids: list[str], base_numbers: list[int], quotas: dict[int, int]):
    """
    Asigna franjas BONUS por número específico.
    base_numbers: lista de números (1..75) escogidos para el BONUS del día.
    quotas: dict {numero: cantidad_de_ganadores} -> cuántos boletos deberán incluir ese número en su franja.
    Reglas:
      - Los boletos asignados a un número b reciben 5 números que incluyen b.
      - El resto de boletos recibe 5 números que evitan todos los base_numbers.
    Devuelve: {"per_ticket": {idx:[..5..]}, "by_number": {"14":[ID,...]}, "feasible":bool, "shortages":{num:faltantes}}
    """
    import random
    rng_all = set(range(1, 76))
    base_set = set(int(n) for n in base_numbers if 1 <= int(n) <= 75)
    quotas = {int(k): max(0, int(v)) for k, v in quotas.items() if int(k) in base_set}

    libres = list(range(len(ids)))
    per_ticket = {}
    by_number = {}
    shortages = {}
    feasible = True

    def vec_con_b(b: int):
        pool = list((rng_all - base_set) - {b})
        if len(pool) < 4:
            pool = list(rng_all - {b})
        extra = set(random.sample(pool, 4))
        vec = sorted(set([b]) | extra)
        while len(vec) < 5:
            x = random.choice(list(rng_all - set(vec)))
            vec.append(x)
            vec = sorted(set(vec))
        return vec[:5]

    def vec_sin_bases():
        pool = list(rng_all - base_set)
        if len(pool) < 5:
            pool = list(rng_all)
        vec = sorted(set(random.sample(pool, 5)))
        while len(vec) < 5:
            x = random.choice(list(rng_all - set(vec)))
            vec.append(x)
            vec = sorted(set(vec))
        # reemplaza bases si se colaron
        for i,n in enumerate(list(vec)):
            if n in base_set:
                repl = list((rng_all - set(vec)) - base_set) or list(rng_all - set(vec))
                if repl:
                    vec[i] = random.choice(repl)
        return sorted(vec)

    for b in base_numbers:
        q = int(quotas.get(int(b), 0))
        if q <= 0:
            continue
        if len(libres) < q:
            feasible = False
            shortages[int(b)] = q - len(libres)
            q = len(libres)
        elegidos = random.sample(libres, q) if q > 0 else []
        by_number[str(int(b))] = [ids[i] for i in elegidos]
        for i in elegidos:
            per_ticket[i] = vec_con_b(int(b))
        libres = [i for i in libres if i not in elegidos]

    for i in libres:
        per_ticket[i] = vec_sin_bases()

    return {
        "per_ticket": per_ticket,
        "by_number": by_number,
        "feasible": feasible,
        "shortages": shortages
    }


def _row_numbers_as_set(row: dict) -> set[int]:
    """
    Toma una fila (registro) con claves b1..b5, i1..i5, n1..n5, g1..g5, o1..o5 y devuelve un set de ints válidos.
    Ignora vacíos o no-numéricos. (Incluye N3 aunque visualmente sea QR).
    """
    nums = set()
    for letra in 'bingo':
        for r in range(1,6):
            key = f"{letra}{r}"
            v = str(row.get(key,"")).strip()
            if not v:
                continue
            try:
                n = int(v)
                if 1 <= n <= 75:
                    nums.add(n)
            except Exception:
                continue
    return nums

def _bonus_try_assign(registros: list[dict], ids: list[str], requested: dict[str,int], max_iters: int = 3000):
    """
    (Modo antiguo - set global aleatorio). Se mantiene por compatibilidad.
    """
    tickets = [_row_numbers_as_set(r) for r in registros]

    best = None
    req = {int(k): max(0, int(v)) for k,v in requested.items() if str(k) in {'1','2','3','4','5'}}

    for _ in range(max_iters):
        bonus = set(random.sample(range(1,76), 5))
        matches = [len(s & bonus) for s in tickets]

        pool = {k: [i for i, m in enumerate(matches) if m == k] for k in range(6)}  # 0..5
        winners = {}
        feasible = True
        shortages = {}
        satisfied = 0
        for k in [5,4,3,2,1]:
            want = req.get(k, 0)
            candidates = pool.get(k, [])
            if want <= 0:
                winners[str(k)] = []
                continue
            if len(candidates) >= want:
                chosen = random.sample(candidates, want)
                winners[str(k)] = [ids[i] for i in chosen]
                satisfied += want
            else:
                feasible = False
                winners[str(k)] = [ids[i] for i in candidates]
                satisfied += len(candidates)
                shortages[k] = want - len(candidates)

        result = {
            "numbers": sorted(list(bonus)),
            "winners": winners,
            "feasible": feasible,
            "shortages": shortages,
            "score": satisfied
        }
        if feasible:
            return result
        if (best is None) or (result["score"] > best["score"]):
            best = result

    return best or {
        "numbers": [],
        "winners": {str(k): [] for k in [5,4,3,2,1]},
        "feasible": False,
        "shortages": {k: requested.get(str(k),0) for k in [5,4,3,2,1]},
        "score": 0
    }

# ====== NUEVO: Asignación POR BOLETO (cuando NO hay bonus global ingresado por el usuario) ======
def _bonus_assign_per_ticket(registros: list[dict], ids: list[str], requested: dict[str,int]):
    """
    Genera números BONUS distintos por boleto cumpliendo el conteo solicitado
    de ganadores por coincidencias exactas k=5..1. Si sobran boletos, se asigna k=0.
    Retorna:
      {
        "per_ticket": [[5 nums], ...]  # alineado a 'ids'
        "winners": {"5":[ids], ...},
        "feasible": True/False,
        "shortages": {k: faltantes}
      }
    """
    N = len(registros)
    rng_all = set(range(1, 76))
    ticket_sets = [_row_numbers_as_set(r) for r in registros]

    per_ticket = [None] * N
    remaining = list(range(N))
    random.shuffle(remaining)

    winners = {str(k): [] for k in [5,4,3,2,1]}
    shortages = {}
    feasible = True
    used_sets = set()  # para evitar duplicados exactos

    def build_set(S, k):
        # k de S, 5-k fuera de S
        A = set(random.sample(list(S), k)) if k > 0 else set()
        pool_out = list(rng_all - S - A)
        B = set(random.sample(pool_out, 5 - k)) if 5 - k > 0 else set()
        return tuple(sorted(A | B))

    # Asigna exactamente los requeridos por categoría
    for k in [5,4,3,2,1]:
        want = max(0, int(requested.get(str(k), 0)))
        if want == 0:
            continue
        # candidatos que todavía no se usaron y tienen al menos k números
        cands = [i for i in remaining if len(ticket_sets[i]) >= k]
        if len(cands) < want:
            feasible = False
            shortages[k] = want - len(cands)
            want = len(cands)
        chosen = random.sample(cands, want)
        for i in chosen:
            # intenta evitar repetir exactamente el mismo set
            tries = 0
            s = build_set(ticket_sets[i], k)
            while s in used_sets and tries < 10:
                s = build_set(ticket_sets[i], k)
                tries += 1
            used_sets.add(s)
            per_ticket[i] = list(s)
            winners[str(k)].append(ids[i])
        remaining = [i for i in remaining if i not in chosen]

    # El resto con k=0 (cero coincidencias), igualmente variados
    for i in remaining:
        tries = 0
        s = build_set(ticket_sets[i], 0)
        while s in used_sets and tries < 10:
            s = build_set(ticket_sets[i], 0)
            tries += 1
        used_sets.add(s)
        per_ticket[i] = list(s)

    return {
        "per_ticket": per_ticket,
        "winners": winners,
        "feasible": feasible,
        "shortages": shortages
    }

# ====== NUEVO: Asignación desde BONUS GLOBAL con EXACTO k aciertos por boleto ======
def _bonus_assign_from_global(registros: list[dict], ids: list[str], global_numbers: list[int], requested: dict[str,int]):
    """
    Usa un set BONUS GLOBAL de 5 números (p.ej., [25,44,10,8,12]) y reparte ganadores.
    Para cada categoría k=5..1:
      - Elige boletos candidatos.
      - Genera para ese boleto una franja BONUS de 5 números que contenga EXACTAMENTE k
        números del BONUS global que estén también en el boleto, y (5-k) 'distractores'
        que NO estén en el boleto (ni en el set global) para NO completar 5 aciertos.
    Devuelve:
      {
        "per_ticket": [[5 nums], ...]  # alineado a 'ids'
        "winners": {"5":[ids], ...},
        "feasible": True/False,
        "shortages": {k: faltantes}
      }
    """
    # Normaliza y valida BONUS:
    try:
        B = [int(x) for x in global_numbers]
    except Exception:
        B = []
    B = [n for n in B if 1 <= n <= 75]
    if len(set(B)) != 5:
        # BONUS inválido
        return {
            "per_ticket": [[None]*5 for _ in registros],
            "winners": {str(k): [] for k in [5,4,3,2,1]},
            "feasible": False,
            "shortages": {"bonus_numbers": "Se requieren 5 números únicos entre 1..75"}
        }

    Bset = set(B)
    N = len(registros)
    ticket_sets = [_row_numbers_as_set(r) for r in registros]

    per_ticket = [None] * N
    remaining = list(range(N))
    random.shuffle(remaining)

    winners = {str(k): [] for k in [5,4,3,2,1]}
    shortages = {}
    feasible = True
    used_vectors = set()

    rng_all = set(range(1, 76))

    def build_vector_for_ticket(i, k):
        """
        Devuelve una tupla de 5 números para el boleto i con EXACTAMENTE k aciertos:
        - k números tomados de (B ∩ ticket_i)
        - (5-k) distractores tomados de números que NO están en el boleto y NO están en B.
        Evita repetir exactamente la misma tupla en muchos boletos.
        """
        S = ticket_sets[i]
        common = list(Bset & S)
        if len(common) < k:
            return None
        # Elige k comunes
        A = set(random.sample(common, k)) if k > 0 else set()
        # Pool de distractores: fuera del boleto y fuera del BONUS global
        pool_out = list(rng_all - S - Bset - A)
        if len(pool_out) < (5 - k):
            # si faltan, relajamos: permitimos fuera del boleto aunque estén en Bset,
            # pero intentando NO sumar más aciertos (ya excluimos S)
            pool_out = list(rng_all - S - A)
        if len(pool_out) < (5 - k):
            return None
        B_extra = set(random.sample(pool_out, 5 - k))
        vec = tuple(sorted(A | B_extra))
        return vec

    # Asigna categorías 5→1
    for k in [5,4,3,2,1]:
        want = max(0, int(requested.get(str(k), 0)))
        if want == 0:
            continue
        # Candidatos: aún no asignados y con al menos k coincidencias posibles con B
        cands = [i for i in remaining if len(ticket_sets[i] & Bset) >= k]
        if len(cands) < want:
            feasible = False
            shortages[k] = want - len(cands)
            want = len(cands)
        if want <= 0:
            continue
        chosen = random.sample(cands, want)
        for i in chosen:
            tries = 0
            vec = build_vector_for_ticket(i, k)
            while (vec is None or vec in used_vectors) and tries < 20:
                vec = build_vector_for_ticket(i, k)
                tries += 1
            if vec is None:
                feasible = False
                shortages[k] = shortages.get(k, 0) + 1
                continue
            used_vectors.add(vec)
            per_ticket[i] = list(vec)
            winners[str(k)].append(ids[i])
        remaining = [i for i in remaining if i not in chosen]

    # El resto (no ganadores): si B choca con el boleto, armamos 0 aciertos
    for i in remaining:
        S = ticket_sets[i]
        if len(Bset & S) == 0:
            vec = B[:]  # puede mostrarse tal cual (0 aciertos reales)
        else:
            pool_out = list(rng_all - S - Bset)
            if len(pool_out) < 5:
                pool_out = list(rng_all - S)
            vec = random.sample(pool_out, 5)
        per_ticket[i] = list(sorted(vec))

    return {
        "per_ticket": per_ticket,
        "winners": winners,
        "feasible": feasible,
        "shortages": shortages
    }

def _bonus_assign_global_positional(ids: list[str], global_numbers: list[int], requested: dict[str,int]):
    """
    Asigna BONUS con patrón posicional (de izquierda a derecha):
      - k=5: repite los 5 números exactos.
      - k=4: cambia SOLO el 1ro (izquierda), mantiene 2..5.
      - k=3: cambia los 2 primeros, mantiene 3..5.
      - k=2: cambia los 3 primeros, mantiene 4..5.
      - k=1: cambia los 4 primeros, mantiene solo el último.
    El resto de boletos queda con 0 aciertos (ningún número del BONUS global).

    Devuelve:
      {
        "per_ticket": [[5 nums], ...],
        "winners": {"5":[ids], ...},
        "feasible": bool,
        "shortages": {k: faltantes}
      }
    """
    try:
        B = [int(x) for x in global_numbers]
    except Exception:
        B = []
    B = [n for n in B if 1 <= n <= 75]
    # conservar orden y unicidad
    seen = set(); B = [x for x in B if not (x in seen or seen.add(x))]
    if len(B) != 5:
        return {
            "per_ticket": [[None]*5 for _ in ids],
            "winners": {str(k): [] for k in [5,4,3,2,1]},
            "feasible": False,
            "shortages": {"bonus_numbers": "Se requieren 5 números únicos entre 1..75"}
        }

    N = len(ids)
    per_ticket = [None] * N
    remaining = list(range(N))
    random.shuffle(remaining)

    winners = {str(k): [] for k in [5,4,3,2,1]}
    shortages = {}
    feasible = True
    rng_all = set(range(1, 76))
    Bset = set(B)

    def _make_vec(k: int):
        """Construye vector de 5 con exactamente k aciertos por posición (izq→der)."""
        if k < 0: k = 0
        if k > 5: k = 5
        vec = list(B)
        change_count = 5 - k  # cambia desde la izquierda
        if change_count <= 0:
            return vec[:]

        # Reemplazos NO pertenecen al BONUS global para conservar exactitud de aciertos
        pool = list(rng_all - Bset)
        if len(pool) < change_count:
            return None
        repl = random.sample(pool, change_count)
        for idx in range(change_count):
            vec[idx] = repl[idx]

        # Seguridad: unicidad total por si acaso
        if len(set(vec)) != 5:
            usados = set()
            for i, n in enumerate(vec):
                if n in usados:
                    libres = list((rng_all - set(vec)) - Bset) or list(rng_all - set(vec))
                    if not libres:
                        return None
                    vec[i] = random.choice(libres)
                usados.add(vec[i])
        return vec

    # Asignar ganadores 5→1
    for k in [5,4,3,2,1]:
        want = max(0, int(requested.get(str(k), 0)))
        if want == 0:
            continue
        if len(remaining) < want:
            feasible = False
            shortages[k] = want - len(remaining)
            want = len(remaining)
        if want <= 0:
            continue
        chosen = random.sample(remaining, want)
        for i in chosen:
            vec = _make_vec(k)
            if vec is None:
                feasible = False
                shortages[k] = shortages.get(k, 0) + 1
                continue
            per_ticket[i] = vec
            winners[str(k)].append(ids[i])
        remaining = [i for i in remaining if i not in chosen]

    # Restantes con 0 aciertos: 5 números fuera del BONUS global
    for i in remaining:
        pool = list(rng_all - Bset)
        if len(pool) < 5:
            pool = list(rng_all)
        per_ticket[i] = random.sample(pool, 5)

    return {
        "per_ticket": per_ticket,
        "winners": winners,
        "feasible": feasible,
        "shortages": shortages
    }

def _save_bonus_json(log_id: int, payload: dict):
    try:
        path = os.path.join(LOGS_DIR, f"bonus_{log_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[WARN] No se pudo escribir bonus json:", e)


def _bonus_build_ticket_history(ids: list[str], per_ticket: list[list[int]] | None, global_numbers: list[int] | None = None):
    """
    Construye historial detallado por boleto para auditar el BONUS.
    Guarda el vector mostrado en la franja BONUS por boleto y, si existe BONUS global,
    calcula coincidencias por posición (izq->der) y por valor.
    """
    rows = []
    try:
        B = [int(x) for x in (global_numbers or [])]
    except Exception:
        B = []
    B = [n for n in B if 1 <= n <= 75][:5]
    Bset = set(B)

    per_ticket = per_ticket or []
    for i, bid in enumerate(ids or []):
        vec_raw = per_ticket[i] if i < len(per_ticket) else None
        try:
            vec = [int(x) for x in (vec_raw or [])]
        except Exception:
            vec = []

        row = {
            "boleto": str(bid),
            "bonus_boleto": vec,
        }

        if len(B) == 5 and len(vec) == 5:
            pos_eq = sum(1 for a, b in zip(vec, B) if int(a) == int(b))
            num_eq = len(set(vec) & Bset)
            changed = [idx + 1 for idx, (a, b) in enumerate(zip(vec, B)) if int(a) != int(b)]
            row.update({
                "coincidencias_posicion": pos_eq,
                "coincidencias_numeros": num_eq,
                "cambian_posiciones": changed,
            })
        rows.append(row)

    return rows

# ============== /impresion =================
@app.route('/impresion', methods=['GET', 'POST'])
@require_session
def impresion():
    files = _list_series_files()
    series     = [(f, _serie_label(f)) for f in files]
    reintegros = sorted(f for f in os.listdir(REINTEGROS_DIR)
                        if f.lower().endswith('.png')) if os.path.exists(REINTEGROS_DIR) else []
    fecha_hoy  = date.today().strftime('%Y-%m-%d')

    if request.method != 'POST':
        bonus_base_default = {
            'offset_x': 0.0,
            'offset_y': 0.0,
            'font_size': 9.0,
            'gap': 3.5,
            'slot_w': 8.5,
        }
        return render_template(
            'impresion_boletos_excel.html',
            series=series, reintegros=reintegros, fecha_hoy=fecha_hoy,
            bonus_defaults=bonus_cell_offsets,
            bonus_base_default=bonus_base_default,
            username=session.get('usuario',''),
            usuario=session.get('usuario',''),
            rol=session.get('rol',''),
            avatar=session.get('avatar','avatar-male.png'),
            permisos=session.get('permisos', [])
        )

    form_type = (request.form.get('form_type') or '').strip().lower()

    # ---- BOLETOS ----
    if form_type == 'boletos':
        serie_archivo = (request.form.get('serie_archivo') or '').strip()
        start         = (request.form.get('serie_inicio') or '').strip()
        end           = (request.form.get('serie_fin') or '').strip()
        valor         = (request.form.get('valor') or '1.00').strip()
        telefono      = (request.form.get('telefono') or '').strip()
        fecha_str     = (request.form.get('fecha_sorteo') or fecha_hoy).strip()
        rein_esp      = (request.form.get('reintegro_especial') or '').strip()
        cntesp        = _to_int(request.form.get('cant_reintegro_especial'), 0)
        incA_raw      = (request.form.get('incluir_aleatorio') or '1').strip().lower()
        incA          = incA_raw in ('1', 'true', 'on', 'si', 'sí')

        # === BONUS: lectura del formulario
        bonus_enabled = (request.form.get('bonus_enabled') or '').lower() in ('1','true','on','si','sí')
        b5 = _to_int(request.form.get('bonus_k5'), 0)
        b4 = _to_int(request.form.get('bonus_k4'), 0)
        b3 = _to_int(request.form.get('bonus_k3'), 0)
        b2 = _to_int(request.form.get('bonus_k2'), 0)
        b1 = _to_int(request.form.get('bonus_k1'), 0)
        requested_counts = {'5': b5, '4': b4, '3': b3, '2': b2, '1': b1}

        # Ajustes visuales del BONUS (posición/tamaño/separación)
        bonus_style = {
            'offset_x': max(-120.0, min(120.0, _to_float(request.form.get('bonus_move_x'), 0.0))),
            'offset_y': max(-120.0, min(120.0, _to_float(request.form.get('bonus_move_y'), 0.0))),
            'font_size': max(6.0, min(24.0, _to_float(request.form.get('bonus_num_size'), 9.0))),
            'gap': max(0.0, min(25.0, _to_float(request.form.get('bonus_num_gap'), 3.5))),
            'slot_w': max(4.0, min(30.0, _to_float(request.form.get('bonus_num_width'), 8.5))),
        }

        # cuotas por NÚMERO (bonus_q1..bonus_q5 alineadas a bonus_n1..bonus_n5)
        quotas_by_number = {}
        for idx in [1,2,3,4,5]:
            nv = request.form.get(f'bonus_n{idx}')
            qv = request.form.get(f'bonus_q{idx}')
            try:
                nvi = int(str(nv).strip()) if nv not in (None, '') else None
                qvi = int(str(qv).strip()) if qv not in (None, '') else 0
            except Exception:
                nvi, qvi = None, 0
            if nvi is not None and 1 <= nvi <= 75 and qvi > 0:
                quotas_by_number[nvi] = qvi

        # BONUS GLOBAL (opcional): bonus_n1..bonus_n5
        bonus_n_inputs = []
        for k in [1,2,3,4,5]:
            v = request.form.get(f'bonus_n{k}')
            if v is not None and str(v).strip() != '':
                try:
                    bonus_n_inputs.append(int(str(v).strip()))
                except Exception:
                    pass

        if not serie_archivo:
            flash('Selecciona una serie para imprimir boletos.', 'warning')
            return redirect(url_for('impresion'))

        series_prev = _series_impresas_en_fecha(fecha_str)
        if series_prev and (serie_archivo not in series_prev):
            otra = ', '.join(sorted(series_prev))
            flash(f"Ya se imprimieron boletos para {fecha_str} con la serie: {otra}. "
                  f"No se permite imprimir el mismo día con otra serie.", 'danger')
            return redirect(url_for('impresion'))

        try:
            df = _read_df_for_series(serie_archivo)
        except Exception as e:
            flash(str(e), 'danger'); return redirect(url_for('impresion'))

        id_col  = df.columns[0]
        all_ids = df[id_col].astype(str).tolist()
        if not all_ids:
            flash('La serie seleccionada no contiene datos.', 'danger')
            return redirect(url_for('impresion'))

        if not start:
            start = all_ids[0]
        if not end:
            end = start

        if start not in all_ids:
            flash(f'Boleto inicial “{start}” no existe en la serie.', 'danger'); return redirect(url_for('impresion'))
        if end not in all_ids:
            flash(f'Boleto final “{end}” no existe en la serie.', 'danger'); return redirect(url_for('impresion'))

        s_idx = all_ids.index(start)
        e_idx = all_ids.index(end) + 1
        if e_idx <= s_idx:
            e_idx = s_idx + 1

        ids       = all_ids[s_idx:e_idx]
        registros = df.iloc[s_idx:e_idx].to_dict('records')

        # === BONUS: cálculo y log preparado
        bonus_payload = None
        bonus_numbers_global = None
        bonus_numbers_per_ticket = None
        if bonus_enabled:
            # === MODO POR NÚMERO (si existen quotas bonus_qN en el formulario) ===
            if quotas_by_number:
                base_nums = [n for n in bonus_n_inputs if 1 <= n <= 75]
                base_nums = list(dict.fromkeys(base_nums))[:5]
                # Si no vinieron 5 números, completamos aleatorio para tener BONUS global visible
                if len(base_nums) < 5:
                    pool = [n for n in range(1,76) if n not in set(base_nums)]
                    random.shuffle(pool)
                    base_nums.extend(pool[:(5-len(base_nums))])
                assign_num = _bonus_assign_by_number(ids, base_nums, quotas_by_number)
                bonus_numbers_per_ticket = assign_num["per_ticket"]
                bonus_payload = {
                    "enabled": True,
                    "mode": "per_number",
                    "code": f"BNS-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{random.randint(1000,9999)}",
                    "numbers": base_nums,
                    "requested": quotas_by_number,
                    "winners_by_number": assign_num.get("by_number", {}),
                    "feasible": assign_num.get("feasible", True),
                    "shortages": assign_num.get("shortages", {}),
                    "pattern": "left_to_right",
                    "layout": bonus_style
                }
                if not assign_num.get("feasible", True):
                    flash("BONUS por número: algunas cuotas no pudieron cubrirse completamente; se asignó lo máximo posible.", "warning")

            # === MODO GLOBAL POSICIONAL (nuevo comportamiento solicitado) ===
            else:
                # Si el usuario no envía los 5 números, el sistema los genera al azar
                base_global = [n for n in bonus_n_inputs if 1 <= n <= 75]
                # orden y unicidad
                seen_bg = set(); base_global = [x for x in base_global if not (x in seen_bg or seen_bg.add(x))]
                if len(base_global) < 5:
                    pool = [n for n in range(1,76) if n not in set(base_global)]
                    random.shuffle(pool)
                    base_global.extend(pool[:(5-len(base_global))])
                elif len(base_global) > 5:
                    base_global = base_global[:5]

                assign_glob = _bonus_assign_global_positional(ids, base_global, requested_counts)
                bonus_numbers_per_ticket = assign_glob["per_ticket"]
                bonus_payload = {
                    "enabled": True,
                    "mode": "global_positional",
                    "code": f"BNS-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{random.randint(1000,9999)}",
                    "numbers": base_global,
                    "requested": requested_counts,
                    "winners": assign_glob["winners"],
                    "feasible": assign_glob["feasible"],
                    "shortages": assign_glob.get("shortages", {}),
                    "pattern": "left_to_right",
                    "layout": bonus_style
                }
                if not assign_glob["feasible"]:
                    flash("BONUS: no fue posible cumplir exactamente todas las cantidades solicitadas; se asignó lo máximo posible.", "warning")

        try:
            log_id = _append_log_impresion_boletos(
                usuario=session.get('usuario', ''),
                serie_archivo=serie_archivo,
                desde=start, hasta=end,
                fecha_sorteo=fecha_str,
                total_boletos=len(ids),
                valor=valor, telefono=telefono,
                reintegro_especial=rein_esp,
                cant_reintegro_especial=cntesp,
                incluir_aleatorio=incA,
                bonus_payload=bonus_payload
            )
        except Exception as e:
            print('[WARN] No se pudo escribir en impresiones.xml (boletos):', e)
            log_id = None

        # Guarda JSON del informe BONUS (si aplica)
        if bonus_payload and log_id:
            try:
                bonus_payload_out = dict(bonus_payload)
                bonus_payload_out["log_id"] = log_id
                bonus_payload_out["serie_archivo"] = serie_archivo
                bonus_payload_out["desde"] = start
                bonus_payload_out["hasta"] = end
                bonus_payload_out["fecha_sorteo"] = fecha_str
                bonus_payload_out["tickets_detalle"] = _bonus_build_ticket_history(
                    ids,
                    bonus_numbers_per_ticket or [],
                    bonus_payload.get("numbers", [])
                )
                _save_bonus_json(log_id, bonus_payload_out)
                # Link al HTML con el resultado del BONUS
                flash(Markup(
                    f"BONUS asignado | Informe ID {log_id}. "
                    f"<a href='{url_for('bonus_informe_html', log_id=log_id)}' target='_blank'>Ver BONUS</a>"
                ), "success")
            except Exception as e:
                print("[WARN] No se pudo guardar JSON BONUS:", e)

        rein_list = sorted(f for f in os.listdir(REINTEGROS_DIR) if f.lower().endswith('.png')) if os.path.exists(REINTEGROS_DIR) else []
        qr_base = _qr_public_base_url()
        buf_b = generar_pdf_boletos_excel(
            ids, registros, valor, telefono,
            serie_archivo, rein_esp, cntesp,
            rein_list, incA, fecha_str,
            bonus_numbers_global=bonus_numbers_global,
            bonus_numbers_per_ticket=bonus_numbers_per_ticket,
            qr_public_base=qr_base,
            bonus_style=bonus_style
        )
        return _send_bytesio(buf_b, 'boletos_bingo.pdf', 'application/pdf')

    # ---- PLANILLA ----
    if form_type == 'planilla':
        archivo = (request.form.get('serie_archivo_planilla') or '').strip()
        inicio  = _to_int(request.form.get('planilla_inicio'), 0)
        fin     = _to_int(request.form.get('planilla_fin'), 0)
        fecha_p = (request.form.get('fecha_planilla') or fecha_hoy).strip()

        if not archivo or inicio <= 0 or fin < inicio:
            flash('Completa serie e inicio/fin válidos para la planilla.', 'warning')
            return redirect(url_for('impresion'))

        try:
            df2 = _read_df_for_series(archivo)
        except Exception as e:
            flash(str(e), 'danger'); return redirect(url_for('impresion'))

        id_col  = df2.columns[0]
        all_ids = df2[id_col].astype(str).tolist()
        if not all_ids:
            flash('La serie seleccionada no contiene datos.', 'danger'); return redirect(url_for('impresion'))

        inicio = max(1, inicio)
        fin    = min(len(all_ids), fin)

        qr_base = _qr_public_base_url()
        merger = PdfMerger()
        try:
            chunk  = 40
            total  = fin - inicio + 1
            for off in range(0, total, chunk):
                page_start = inicio + off
                page_end   = min(page_start + chunk - 1, fin)
                sub_ids    = all_ids[page_start-1:page_end]

                buf = generar_pdf_planilla(
                    sub_ids, archivo, session.get('usuario',''),
                    fecha_p, page_start, page_end, SERIE_MAP,
                    qr_public_base=qr_base
                )
                merger.append(buf)

            salida = BytesIO()
            merger.write(salida)
            merger.close()
            salida.seek(0)
        finally:
            try:
                merger.close()
            except Exception:
                pass

        try:
            _append_log_impresion_planilla(
                usuario=session.get('usuario',''),
                serie_archivo=archivo,
                desde=inicio, hasta=fin,
                fecha_planilla=fecha_p,
                lote_text=f"{inicio}-{fin}",
                excedente=1 if ((fin - inicio + 1) % 20) != 0 else 0
            )
        except Exception as e:
            print('[WARN] No se pudo escribir en impresiones.xml (planilla-range):', e)

        return _send_bytesio(salida, f'planilla_{inicio}_a_{fin}.pdf', 'application/pdf')

    flash('Formulario no reconocido.', 'warning')
    return redirect(url_for('impresion'))

# ============== ZIP (boletos + planilla) =================
def _crear_zip_boletos_planilla(nombre_serie, start, end, valor, telefono, fecha_str,
                                rein_esp, cnt_esp, incA):
    series_prev = _series_impresas_en_fecha(fecha_str)
    if series_prev and (nombre_serie not in series_prev):
        otra = ', '.join(sorted(series_prev))
        flash(f"Ya se imprimieron boletos para {fecha_str} con la serie: {otra}. "
              f"No se permite imprimir el mismo día con otra serie.", 'danger')
        return redirect(url_for('impresion'))

    try:
        df = _read_df_for_series(nombre_serie)
    except Exception as e:
        flash(str(e), 'danger'); return redirect(url_for('impresion'))

    all_ids = df[df.columns[0]].astype(str).tolist()
    if not all_ids:
        flash('La serie no contiene datos.', 'danger'); return redirect(url_for('impresion'))

    if not start:
        start = all_ids[0]
    if not end:
        end = start

    if start not in all_ids:
        flash(f'Boleto inicial “{start}” no existe.', 'danger'); return redirect(url_for('impresion'))
    if end not in all_ids:
        flash(f'Boleto final “{end}” no existe.', 'danger'); return redirect(url_for('impresion'))

    s_idx = all_ids.index(start)
    e_idx = all_ids.index(end) + 1
    if e_idx <= s_idx:
        e_idx = s_idx + 1

    ids = all_ids[s_idx:e_idx]
    registros = df.iloc[s_idx:e_idx].to_dict('records')

    rein_list = []
    if os.path.exists(REINTEGROS_DIR):
        rein_list = sorted(f for f in os.listdir(REINTEGROS_DIR) if f.lower().endswith('.png'))

    # ZIP (sin cálculo de BONUS en este atajo; se imprimen sin franja BONUS)
    qr_base = _qr_public_base_url()
    buf_boletos = generar_pdf_boletos_excel(
        ids, registros, valor, telefono,
        nombre_serie, rein_esp, cnt_esp,
        rein_list, incA, fecha_str,
        bonus_numbers_global=None,
        bonus_numbers_per_ticket=None,
        qr_public_base=qr_base,
        bonus_style=None
    )
    buf_planilla = generar_pdf_planilla(
        ids, nombre_serie, "Vendedor", fecha_str,
        int(start), int(end), SERIE_MAP,
        qr_public_base=qr_base
    )

    try:
        _append_log_impresion_boletos(
            usuario=session.get('usuario',''),
            serie_archivo=nombre_serie,
            desde=start, hasta=end,
            fecha_sorteo=fecha_str,
            total_boletos=len(ids),
            valor=valor, telefono=telefono,
            reintegro_especial=rein_esp,
            cant_reintegro_especial=cnt_esp,
            incluir_aleatorio=incA,
        )
        _append_log_impresion_planilla(
            usuario=session.get('usuario',''),
            serie_archivo=nombre_serie,
            desde=int(start), hasta=int(end),
            fecha_planilla=fecha_str,
            lote_text=f"{start}-{end}", excedente=0
        )
    except Exception as e:
        print('[WARN] No se pudo escribir en impresiones.xml (zip):', e)

    from zipfile import ZipFile
    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, 'w') as zipf:
        zipf.writestr('boletos.pdf', buf_boletos.getvalue())
        zipf.writestr('planilla.pdf', buf_planilla.getvalue())
    zip_buffer.seek(0)

    resp = _send_bytesio(zip_buffer, "GLSTUDIOS_BOLETOS_PLANILLA.zip", "application/zip")
    try:
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    except Exception:
        pass
    return resp

@app.route('/descargar_zip', methods=['POST'])
@require_session
def descargar_zip():
    nombre_serie = (request.form.get('serie_archivo') or '').strip()
    start        = (request.form.get('serie_inicio') or '').strip()
    end          = (request.form.get('serie_fin') or '').strip()
    valor        = (request.form.get('valor') or '1.00').strip()
    telefono     = (request.form.get('telefono') or '').strip()
    fecha_str    = (request.form.get('fecha_sorteo') or date.today().isoformat()).strip()
    rein_esp     = (request.form.get('reintegro_especial') or '').strip()
    cnt_esp      = _to_int(request.form.get('cant_reintegro_especial'), 0)
    incA         = (request.form.get('incluir_aleatorio') or '1').strip().lower() in ('1','true','on','si','sí')

    if not nombre_serie:
        flash('Selecciona una serie.', 'warning'); return redirect(url_for('impresion'))

    return _crear_zip_boletos_planilla(nombre_serie, start, end, valor, telefono, fecha_str,
                                       rein_esp, cnt_esp, incA)

@app.route('/impresion_zip', methods=['GET', 'POST'])
@require_session
def impresion_zip():
    if request.method == 'GET':
        nombre_serie = (request.args.get('serie') or '').strip()
        start        = (request.args.get('desde') or '').strip()
        end          = (request.args.get('hasta') or '').strip()
        valor        = (request.args.get('valor') or '1.00').strip()
        telefono     = ''
        fecha_str    = (request.args.get('fecha') or date.today().isoformat()).strip()
        rein_esp     = (request.args.get('reintegro') or '').strip()
        cnt_esp      = _to_int(request.args.get('cant'), 0)
        incA         = (request.args.get('aleatorio') or '1').strip().lower() in ('1','true','on','si','sí')

        if not nombre_serie:
            flash('Selecciona una serie.', 'warning'); return redirect(url_for('impresion'))

        return _crear_zip_boletos_planilla(nombre_serie, start, end, valor, telefono, fecha_str,
                                           rein_esp, cnt_esp, incA)
    return descargar_zip()

# ===== Endpoint para ver el informe BONUS de una impresión =====
@app.route('/impresion/bonus-informe/<int:log_id>.json')
@require_session
def bonus_informe(log_id: int):
    path = os.path.join(LOGS_DIR, f"bonus_{log_id}.json")
    if not os.path.exists(path):
        return jsonify(ok=False, error="informe no encontrado"), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(ok=True, informe=data)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

# ===== VISTA HTML del BONUS =====
@app.route('/impresion/bonus-informe/<int:log_id>')
@require_session
def bonus_informe_html(log_id: int):
    path = os.path.join(LOGS_DIR, f"bonus_{log_id}.json")
    if not os.path.exists(path):
        return f"<h3 style='font-family:Arial'>No existe informe BONUS {log_id}</h3>", 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"<h3 style='font-family:Arial'>Error leyendo informe: {e}</h3>", 500

    winners = data.get("winners", {})
    requested = data.get("requested", {})
    feasible = data.get("feasible", True)
    shortages = data.get("shortages", {})
    nums = data.get("numbers", [])
    tickets_detalle = data.get("tickets_detalle", []) or []

    rows = []
    for k in [5,4,3,2,1]:
        want = int(requested.get(str(k), 0) or 0)
        got = len(winners.get(str(k), []))
        ids_str = ", ".join(map(str, winners.get(str(k), [])))
        rows.append(f"<tr><td>{k}</td><td>{want}</td><td>{got}</td><td style='max-width:800px;white-space:normal'>{ids_str}</td></tr>")

    base = f"<p><b>Bonus Global:</b> {', '.join(map(str, nums))}</p>" if nums else "<p><b>Bonus por boleto (no global).</b></p>"

    det_rows = []
    for r in tickets_detalle:
        bid = r.get("boleto", "")
        vec = ", ".join(map(str, r.get("bonus_boleto", []) or []))
        cp = r.get("coincidencias_posicion", "")
        cn = r.get("coincidencias_numeros", "")
        ch = r.get("cambian_posiciones", []) or []
        ch_txt = ", ".join(map(str, ch)) if ch else "-"
        det_rows.append(
            f"<tr><td>{bid}</td><td>{vec}</td><td>{cp}</td><td>{cn}</td><td>{ch_txt}</td></tr>"
        )

    detalle_html = ""
    if det_rows:
        detalle_html = (
            "<h3>Historial por boleto (verificación BONUS)</h3>"
            "<table>"
            "<tr><th>ID boleto</th><th>Franja BONUS del boleto</th><th>Coincidencias por posición</th><th>Coincidencias por número</th><th>Posiciones que cambian</th></tr>"
            + "".join(det_rows) +
            "</table>"
        )

    return f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <title>Informe BONUS #{log_id}</title>
        <style>
          body {{ font-family: Arial, Helvetica, sans-serif; margin: 24px; }}
          table {{ border-collapse: collapse; width: 100%; max-width: 1200px; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; }}
          th {{ background: #f3f3f3; }}
          .pill {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#eee; margin-left:10px; font-size:12px; }}
        </style>
      </head>
      <body>
        <h2>Informe BONUS #{log_id}
          <span class="pill">{'FACTIBLE' if feasible else 'NO FACTIBLE'}</span>
        </h2>
        {base}
        <p><b>Código:</b> {data.get('code','')}</p>
        <table>
          <tr><th>Coincidencias</th><th>Solicitados</th><th>Asignados</th><th>Boletos ganadores (IDs)</th></tr>
          {''.join(rows)}
        </table>
        { (lambda wins_by: (
            "<h3>Ganadores por número</h3><table><tr><th>Número</th><th>Boletos</th></tr>" +
            "".join(f"<tr><td>{k}</td><td>{', '.join(v)}</td></tr>" for k,v in wins_by.items()) +
            "</table>"
            ) if wins_by else ""
          )(data.get('winners_by_number', {})) }
        {detalle_html}
        {"<p style='color:#b00'><b>Faltantes:</b> " + ", ".join(f"{k}:{v}" for k,v in shortages.items()) + "</p>" if shortages else ""}
      </body>
    </html>
    """





# ================== MAIN ==================





# ============== OTROS ==============
@app.route('/usuarios/eliminar/<nombre>', methods=['POST'])
def eliminar_usuario_route(nombre):
    if 'usuario' not in session:
        return redirect(_login_url())
    eliminar_usuario(nombre)   # función existente en tu app
    flash('Usuario eliminado correctamente', 'success')
    return redirect(url_for('usuarios'))




#vendedores seccion de listas #




VENDEDORES_XML = _persist('static', 'db', 'vendedores.xml')
ASIGNACIONES_XML = _persist('static', 'db', 'asignaciones.xml')
BOLETOS_POR_PLANILLA = 20  # 20 boletos por planilla (A4 = 2 planillas = 40 boletos)

# ----------- FUNCIONES PARA VENDEDORES -----------

# ============================================================
#  RUTAS Y CONSTANTES (tus líneas originales, no se tocan)
# ============================================================
VENDEDORES_XML = _persist('static', 'db', 'vendedores.xml')
ASIGNACIONES_XML = _persist('static', 'db', 'asignaciones.xml')
BOLETOS_POR_PLANILLA = 20  # 20 boletos por planilla (A4 = 2 planillas = 40 boletos)

# ----------- FUNCIONES PARA VENDEDORES -----------
# (mantengo tu reasignación exacta, como la tienes)
VENDEDORES_XML = globals().get('VENDEDORES_XML', _persist('static', 'db', 'vendedores.xml'))


# ============================================================
#  UTILIDADES SEGURAS (nuevas)
# ============================================================
def _ensure_xml(path: str, root_tag: str = 'vendedores'):
    """
    Garantiza que exista el archivo XML y su carpeta.
    Si no existe, lo crea con la etiqueta raíz indicada.
    """
    carpeta = os.path.dirname(path)
    if carpeta and not os.path.exists(carpeta):
        os.makedirs(carpeta, exist_ok=True)
    if not os.path.exists(path):
        root = ET.Element(root_tag)
        tree = ET.ElementTree(root)
        tree.write(path, encoding='utf-8', xml_declaration=True)
    _mirror_persist_static_to_public(path)


def _read_tree_with_root(path: str, root_tag: str = 'vendedores'):
    """
    Asegura el XML y devuelve (tree, root) listos para usar.
    """
    _ensure_xml(path, root_tag)
    tree = ET.parse(path)
    root = tree.getroot()
    # Si el root no coincide (por si se creó con otro tag), lo normalizamos
    if root.tag != root_tag:
        new_root = ET.Element(root_tag)
        for child in list(root):
            new_root.append(child)
        tree._setroot(new_root)
        root = new_root
    return tree, root


def _vendor_commission_info_from_node(v):
    try:
        mode = ((v.findtext('modo_comision') or 'normal').strip().lower())
    except Exception:
        mode = 'normal'
    try:
        manual = float(str(v.findtext('comision_manual') or '0').replace(',', '.').strip() or 0)
    except Exception:
        manual = 0.0
    manual = max(0.0, min(100.0, manual))
    if mode != 'manual' or manual <= 0:
        mode = 'normal'
        manual = 0.0
    return {
        'modo_comision': mode,
        'comision_manual': round(manual, 2),
    }


def _indent_tree_if_possible(tree: ET.ElementTree):
    """
    Intenta indentar (Python 3.9+) para que el XML quede legible.
    """
    try:
        ET.indent(tree, space="  ", level=0)  # type: ignore[attr-defined]
    except Exception:
        pass


def _write_xml_atomic(tree: ET.ElementTree, path: str):
    """
    Escritura atómica: escribe a .tmp y luego reemplaza.
    Evita corrupciones si el proceso se interrumpe.
    """
    tmp = f"{path}.tmp"
    _indent_tree_if_possible(tree)
    tree.write(tmp, encoding='utf-8', xml_declaration=True)
    os.replace(tmp, path)


# ============================================================
#  CRUD DE VENDEDORES (robusto; respeta tu API)
# ============================================================


def cargar_vendedores_xml():
    vendedores = []
    # Lee de forma segura (crea el archivo si no existe)
    tree, root = _read_tree_with_root(VENDEDORES_XML, 'vendedores')

    for idx, v in enumerate(root.findall('vendedor')):
        info_com = _vendor_commission_info_from_node(v)
        vendedores.append({
            'id': idx,  # mantener índice para editar/eliminar
            'nombre'  : (v.findtext('nombre') or '').strip(),
            'apellido': (v.findtext('apellido') or '').strip(),
            'seudonimo': (v.findtext('seudonimo') or '').strip(),
            'modo_comision': info_com['modo_comision'],
            'comision_manual': info_com['comision_manual'],
        })
    return vendedores


def guardar_vendedor(nombre, apellido, seudonimo, modo_comision='normal', comision_manual=0.0):
    # Normaliza strings
    nombre = (nombre or '').strip()
    apellido = (apellido or '').strip()
    seudonimo = (seudonimo or '').strip()
    modo = 'manual' if str(modo_comision or '').strip().lower() == 'manual' else 'normal'
    try:
        manual = float(str(comision_manual or 0).replace(',', '.').strip() or 0)
    except Exception:
        manual = 0.0
    manual = max(0.0, min(100.0, manual))
    if modo != 'manual' or manual <= 0:
        modo = 'normal'
        manual = 0.0

    tree, root = _read_tree_with_root(VENDEDORES_XML, 'vendedores')

    # Agrega nuevo <vendedor>
    v = ET.SubElement(root, 'vendedor')
    ET.SubElement(v, 'nombre').text = nombre
    ET.SubElement(v, 'apellido').text = apellido
    ET.SubElement(v, 'seudonimo').text = seudonimo
    ET.SubElement(v, 'modo_comision').text = modo
    ET.SubElement(v, 'comision_manual').text = f"{manual:.2f}"

    _write_xml_atomic(tree, VENDEDORES_XML)


def editar_vendedor(idx, nombre, apellido, seudonimo, modo_comision=None, comision_manual=None):
    nombre = (nombre or '').strip()
    apellido = (apellido or '').strip()
    seudonimo = (seudonimo or '').strip()

    tree, root = _read_tree_with_root(VENDEDORES_XML, 'vendedores')
    vendedores = root.findall('vendedor')

    if 0 <= idx < len(vendedores):
        v = vendedores[idx]

        def _set(tag, val):
            el = v.find(tag)
            if el is None:
                el = ET.SubElement(v, tag)
            el.text = val

        _set('nombre', nombre)
        _set('apellido', apellido)
        _set('seudonimo', seudonimo)

        if modo_comision is not None or comision_manual is not None:
            modo = 'manual' if str(modo_comision or '').strip().lower() == 'manual' else 'normal'
            try:
                manual = float(str(comision_manual or 0).replace(',', '.').strip() or 0)
            except Exception:
                manual = 0.0
            manual = max(0.0, min(100.0, manual))
            if modo != 'manual' or manual <= 0:
                modo = 'normal'
                manual = 0.0
            _set('modo_comision', modo)
            _set('comision_manual', f"{manual:.2f}")

        _write_xml_atomic(tree, VENDEDORES_XML)


def eliminar_vendedor(idx):
    tree, root = _read_tree_with_root(VENDEDORES_XML, 'vendedores')
    vendedores = root.findall('vendedor')

    if 0 <= idx < len(vendedores):
        root.remove(vendedores[idx])
        _write_xml_atomic(tree, VENDEDORES_XML)


# ============================================================
#  ENDPOINT /vendedores (idéntico en comportamiento)
# ============================================================
@app.route('/vendedores', methods=['GET', 'POST'])
def vendedores():
    if request.method == 'POST':
        if 'editar' in request.form:
            idx = int(request.form['id'])
            nombre = request.form['nombre'].strip()
            apellido = request.form['apellido'].strip()
            seudonimo = request.form['seudonimo'].strip()
            editar_vendedor(idx, nombre, apellido, seudonimo)
            flash("Vendedor editado correctamente.", "success")

        elif 'eliminar' in request.form:
            idx = int(request.form['id'])
            eliminar_vendedor(idx)
            flash("Vendedor eliminado.", "info")

        else:
            nombre = request.form['nombre'].strip()
            apellido = request.form['apellido'].strip()
            seudonimo = request.form['seudonimo'].strip()
            if nombre and apellido and seudonimo:
                guardar_vendedor(nombre, apellido, seudonimo)
                flash("¡Vendedor agregado!", "success")
            else:
                flash("Todos los campos son obligatorios.", "danger")

        return redirect(url_for('vendedores'))

    # GET: cargar y renderizar
    vendedores_list = cargar_vendedores_xml()
    return render_template(
        'vendedores.html',
        vendedores=vendedores_list,
        usuario=session.get('usuario', ''),
        rol=session.get('rol', ''),
        avatar=session.get('avatar', 'avatar-male.png')
    )


@app.post('/api/vendedores/comision/<seudonimo>')
def api_vendedor_comision_guardar(seudonimo):
    if 'usuario' not in session:
        return jsonify(ok=False, error='no-auth'), 401
    if not _is_superadmin():
        return jsonify(ok=False, error='solo-superadmin'), 403

    seudonimo = (seudonimo or '').strip()
    if not seudonimo:
        return jsonify(ok=False, error='Seudónimo inválido'), 400

    data = request.get_json(force=True) or {}
    modo = 'manual' if str(data.get('modo_comision') or '').strip().lower() == 'manual' else 'normal'
    try:
        manual = float(str(data.get('comision_manual') or '0').replace(',', '.').strip() or 0)
    except Exception:
        manual = 0.0
    manual = max(0.0, min(100.0, manual))
    if modo != 'manual' or manual <= 0:
        modo = 'normal'
        manual = 0.0

    tree, root = _read_tree_with_root(VENDEDORES_XML, 'vendedores')
    nodo = None
    for v in root.findall('vendedor'):
        if (v.findtext('seudonimo') or '').strip() == seudonimo:
            nodo = v
            break
    if nodo is None:
        return jsonify(ok=False, error='Vendedor no encontrado'), 404

    def _set(tag, val):
        el = nodo.find(tag)
        if el is None:
            el = ET.SubElement(nodo, tag)
        el.text = val

    _set('modo_comision', modo)
    _set('comision_manual', f"{manual:.2f}")
    _write_xml_atomic(tree, VENDEDORES_XML)

    return jsonify(ok=True, seudonimo=seudonimo, modo_comision=modo, comision_manual=round(manual, 2))


# ----------- FUNCIONES PARA ASIGNACIONES -----------


import os
import re
import xml.etree.ElementTree as ET
from datetime import date
from flask import render_template, request, jsonify, session, redirect, url_for

# === Archivos base ===
VENDEDORES_XML       = globals().get('VENDEDORES_XML',       _persist('static', 'db', 'vendedores.xml'))
ASIGNACIONES_XML     = globals().get('ASIGNACIONES_XML',     _persist('static', 'db', 'asignaciones.xml'))
IMPRESIONES_XML      = globals().get('IMPRESIONES_XML',      _persist('static', 'LOGS', 'impresiones.xml'))  # ← LOG de impresión  # ← LOG de impresión
BOLETOS_POR_PLANILLA = int(globals().get('BOLETOS_POR_PLANILLA', 20))
PLANILLAS_POR_HOJA_A4 = int(globals().get('PLANILLAS_POR_HOJA_A4', 2))

os.makedirs(os.path.dirname(ASIGNACIONES_XML), exist_ok=True)
os.makedirs(os.path.dirname(IMPRESIONES_XML), exist_ok=True)
if not os.path.exists(ASIGNACIONES_XML):
    ET.ElementTree(ET.Element('asignaciones')).write(ASIGNACIONES_XML, encoding='utf-8', xml_declaration=True)
if not os.path.exists(IMPRESIONES_XML):
    ET.ElementTree(ET.Element('impresiones')).write(IMPRESIONES_XML, encoding='utf-8', xml_declaration=True)

# === Helpers XML generales ===
def _parse_or_none(path):
    try:
        if not os.path.exists(path):
            return None, None
        t = ET.parse(path)
        return t, t.getroot()
    except ET.ParseError:
        return None, None



def cargar_vendedores():
    vendedores = []
    t, r = _parse_or_none(VENDEDORES_XML)
    if r is None:
        return vendedores
    for v in r.findall('vendedor'):
        info_com = _vendor_commission_info_from_node(v)
        vendedores.append({
            'nombre': (v.findtext('nombre') or ""),
            'apellido': (v.findtext('apellido') or ""),
            'seudonimo': (v.findtext('seudonimo') or ""),
            'modo_comision': info_com['modo_comision'],
            'comision_manual': info_com['comision_manual'],
        })
    return vendedores


def leer_asignaciones():
    t, r = _parse_or_none(ASIGNACIONES_XML)
    if r is None:
        t = ET.ElementTree(ET.Element('asignaciones'))
        r = t.getroot()
        t.write(ASIGNACIONES_XML, encoding='utf-8', xml_declaration=True)
    return t, r

def guardar_asignaciones(tree: ET.ElementTree):
    """Guarda asignaciones en forma segura (escritura atómica) y espeja a /static/db."""
    try:
        _write_xml_atomic(tree, ASIGNACIONES_XML)
    except Exception:
        # fallback: escritura directa (último recurso)
        try:
            ET.indent(tree, space="  ", level=0)  # type: ignore[attr-defined]
        except Exception:
            pass
        tree.write(ASIGNACIONES_XML, encoding='utf-8', xml_declaration=True)
    try:
        _mirror_db_to_public(ASIGNACIONES_XML)
    except Exception:
        pass

# === Rangos / parse de planillas ===
def calcular_rango(planilla, boletos_por_planilla=BOLETOS_POR_PLANILLA):
    inicio = (int(planilla)-1)*boletos_por_planilla + 1
    fin = int(planilla)*boletos_por_planilla
    return f"{inicio}-{fin}"

def parsear_planillas_input(planillas_raw):
    planillas = set()
    planillas_raw = planillas_raw or ""
    # soporta: "1,2", "1-3", "PL03, PL04", "1/2/3"
    piezas = re.split(r'[,\/\s]+', planillas_raw.strip())
    for parte in piezas:
        parte = parte.strip()
        if not parte:
            continue
        # soportar rango "3-7"
        if '-' in parte:
            a, b = parte.split('-', 1)
            a = a.replace('PL', '').replace('pl', '').lstrip('0') or '0'
            b = b.replace('PL', '').replace('pl', '').lstrip('0') or '0'
            if a.isdigit() and b.isdigit():
                a, b = int(a), int(b)
                if a > 0 and b >= a:
                    for x in range(a, b+1):
                        planillas.add(str(x))
            continue
        # número simple
        p = parte.replace('PL', '').replace('pl', '').lstrip('0') or '0'
        if p.isdigit() and int(p) > 0:
            planillas.add(str(int(p)))
    return sorted(planillas, key=lambda x: int(x))

# === LOG de impresiones: series impresas y total impresas por serie+fecha ===
def _imp_root():
    t, r = _parse_or_none(IMPRESIONES_XML)
    if r is None:
        t = ET.ElementTree(ET.Element('impresiones'))
        r = t.getroot()
        t.write(IMPRESIONES_XML, encoding='utf-8', xml_declaration=True)
    return t, r

def series_impresas_en_fecha(fecha_iso):
    """Series (archivo) que tienen registros de 'boletos' en esa fecha."""
    _, r = _imp_root()
    s = set()
    for n in r.findall('impresion'):
        if (n.get('tipo') or '').lower() != 'boletos':
            continue
        if (n.findtext('fecha_sorteo') or '').strip() != fecha_iso:
            continue
        serie = (n.get('serie_archivo') or '').strip()
        if serie:
            s.add(serie)
    return sorted(s)


def fechas_impresas_disponibles():
    _, r = _imp_root()
    fechas = set()
    for n in r.findall('impresion'):
        if (n.get('tipo') or '').lower() != 'boletos':
            continue
        f = (n.findtext('fecha_sorteo') or '').strip()
        if f:
            fechas.add(f)
    return sorted(fechas)

def total_boletos_impresos_por_serie_fecha(serie_archivo, fecha_iso):
    """Suma lógicamente todos los 'total_boletos' para esa serie y fecha."""
    _, r = _imp_root()
    total = 0
    for n in r.findall('impresion'):
        if (n.get('tipo') or '').lower() != 'boletos':
            continue
        if (n.get('serie_archivo') or '') != serie_archivo:
            continue
        if (n.findtext('fecha_sorteo') or '').strip() != fecha_iso:
            continue
        try:
            total += int(float(n.findtext('total_boletos') or '0'))
        except Exception:
            pass
    return int(total)

def planillas_impresas_por_serie_fecha(serie_archivo, fecha_iso):
    tot_boletos = total_boletos_impresos_por_serie_fecha(serie_archivo, fecha_iso)
    return tot_boletos // BOLETOS_POR_PLANILLA

# === Utilidades de lectura/armado de la tabla para el template ===
def _to_int_safe(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def _compactar_numeros(nums):
    """Convierte [1,2,3,6,7] -> '1-3,6-7'"""
    vals = sorted({n for n in (nums or []) if isinstance(n, int) and n > 0})
    if not vals:
        return ""
    bloques = []
    ini = prev = vals[0]
    for n in vals[1:]:
        if n == prev + 1:
            prev = n
            continue
        bloques.append(f"{ini}-{prev}" if ini != prev else str(ini))
        ini = prev = n
    bloques.append(f"{ini}-{prev}" if ini != prev else str(ini))
    return ", ".join(bloques)


def _nums_asignados_serie(root, fecha, serie_archivo):
    nums = set()
    if not serie_archivo:
        return nums
    dia = root.find(f"./dia[@fecha='{fecha}']")
    if dia is None:
        return nums
    for v in dia.findall('vendedor'):
        for p in v.findall('planilla'):
            if (p.attrib.get('serie') or '') != serie_archivo:
                continue
            n = _to_int_safe(p.attrib.get('numero', ''))
            if n:
                nums.add(n)
    return nums


def _planillas_disponibles_info(root, fecha, serie_archivo, impresas_serie):
    impresas_serie = int(impresas_serie or 0)
    if not serie_archivo or impresas_serie <= 0:
        return {
            'total': 0,
            'rangos': '',
            'lista': [],
            'truncado': False,
            'sugeridos': []
        }

    asignadas = _nums_asignados_serie(root, fecha, serie_archivo)
    libres = [n for n in range(1, impresas_serie + 1) if n not in asignadas]

    # Ranges rápidos sugeridos (primer bloque de 5/10 disponibles consecutivos, si existe)
    sugeridos = []
    if libres:
        primeros_5 = libres[:5]
        primeros_10 = libres[:10]
        if primeros_5:
            sugeridos.append(_compactar_numeros(primeros_5))
        if len(primeros_10) > len(primeros_5):
            sug10 = _compactar_numeros(primeros_10)
            if sug10 not in sugeridos:
                sugeridos.append(sug10)

    return {
        'total': len(libres),
        'rangos': _compactar_numeros(libres),
        'lista': [str(n) for n in libres[:140]],  # render rápido
        'truncado': len(libres) > 140,
        'sugeridos': [s for s in sugeridos if s]
    }


def _armar_asignaciones_mostrar(root, fecha, serie_filtro=''):
    """Arma lista para template, filtrando por serie si aplica y agregando resumen por vendedor."""
    asignaciones_mostrar = []
    dia = root.find(f"./dia[@fecha='{fecha}']")
    if dia is None:
        return asignaciones_mostrar

    for v in dia.findall('vendedor'):
        planillas = []
        for p in v.findall('planilla'):
            serie_p = p.attrib.get('serie', '') or ''
            if serie_filtro and serie_p != serie_filtro:
                continue
            planillas.append({
                'numero': p.attrib.get('numero', ''),
                'rango': p.attrib.get('rango', ''),
                'serie': serie_p,
            })

        if serie_filtro and not planillas:
            continue

        # Orden numérico de planillas
        def _ord(item):
            n = _to_int_safe(item.get('numero', ''))
            return (n is None, n if n is not None else 999999, str(item.get('numero', '')))

        planillas.sort(key=_ord)
        nums_v = [n for n in (_to_int_safe(p.get('numero')) for p in planillas) if n]

        asignaciones_mostrar.append({
            'nombre': v.attrib.get('nombre', ''),
            'apellido': v.attrib.get('apellido', ''),
            'seudonimo': v.attrib.get('seudonimo', ''),
            'planillas': planillas,
            'total_planillas': len(planillas),
            'rango_resumen': _compactar_numeros(nums_v),
        })

    asignaciones_mostrar.sort(key=lambda x: ((x.get('seudonimo') or '').lower(), (x.get('nombre') or '').lower(), (x.get('apellido') or '').lower()))
    return asignaciones_mostrar


def _contar_asignadas_serie(root, fecha, serie_archivo):
    """Cantidad de planillas asignadas para ese día + serie."""
    cnt = 0
    dia = root.find(f"./dia[@fecha='{fecha}']")
    if dia is None:
        return 0
    for v in dia.findall('vendedor'):
        for p in v.findall('planilla'):
            if (p.attrib.get('serie') or '') == serie_archivo:
                cnt += 1
    return cnt

# === Rutas ===
@app.route('/asignar-planillas', methods=['GET', 'POST'])
def asignar_planillas():
    # (opcional) proteger por sesión
    if 'usuario' not in session:
        return redirect(_login_url())

    vendedores = cargar_vendedores()
    tree, root = leer_asignaciones()
    fecha_hoy = date.today().isoformat()

    # Filtros por querystring
    fecha_seleccionada = (request.args.get('fecha') or fecha_hoy).strip()
    series_dia = series_impresas_en_fecha(fecha_seleccionada)
    serie_param = (request.args.get('serie') or (series_dia[0] if series_dia else '')).strip()

    if request.method == 'POST':
        # Campos requeridos
        vendedor_val   = request.form.get('vendedor', '')
        planillas_raw  = request.form.get('planillas', '')
        fecha_form     = request.form.get('fecha', fecha_hoy).strip()
        serie_archivo  = request.form.get('serie_archivo', '').strip()  # ← NUEVO

        if not vendedor_val or not planillas_raw or not fecha_form or not serie_archivo:
            return jsonify(ok=False, error="Todos los campos son obligatorios (vendedor, planillas, fecha y serie).")

        # Verificar que la serie tenga impresión registrada ese día
        impresas_serie = planillas_impresas_por_serie_fecha(serie_archivo, fecha_form)
        if impresas_serie <= 0:
            return jsonify(ok=False, error=f"No hay impresión registrada para la serie “{serie_archivo}” en la fecha {fecha_form}.")

        # Parsear vendedor
        try:
            nombre, apellido, seudonimo = vendedor_val.split('|')
        except Exception:
            return jsonify(ok=False, error="Selecciona un vendedor válido.")

        # Planillas solicitadas
        planillas = parsear_planillas_input(planillas_raw)
        if not planillas:
            return jsonify(ok=False, error="No se detectó ninguna planilla válida.")

        # Validar que estén dentro del rango IMPRESO para esa serie/fecha
        max_pl = impresas_serie  # 1..max_pl
        no_impresas = [p for p in planillas if int(p) < 1 or int(p) > max_pl]
        if no_impresas:
            return jsonify(
                ok=False,
                error=f"Estas planillas NO fueron impresas para la serie “{serie_archivo}” ({fecha_form}): {', '.join(no_impresas)}. "
                      f"Permitidas: 1–{max_pl}."
            )

        # Asegurar nodo día y vendedor
        tree, root = leer_asignaciones()
        dia = root.find(f"./dia[@fecha='{fecha_form}']")
        if dia is None:
            dia = ET.SubElement(root, 'dia', fecha=fecha_form)

        vendedor_node = None
        for v in dia.findall('vendedor'):
            if (v.attrib.get('nombre') == nombre and
                v.attrib.get('apellido') == apellido and
                v.attrib.get('seudonimo') == seudonimo):
                vendedor_node = v
                break
        if vendedor_node is None:
            vendedor_node = ET.SubElement(dia, 'vendedor', nombre=nombre, apellido=apellido, seudonimo=seudonimo)

        # Validar duplicadas contra otros vendedores (por SERIE+numero)
        asignadas_otro = set()
        for v in dia.findall('vendedor'):
            for p in v.findall('planilla'):
                serie_p = p.attrib.get('serie', '')
                if not serie_p:  # antiguas sin serie → las ignoramos en el cruce “por serie”
                    continue
                asignadas_otro.add((serie_p, p.attrib.get('numero', '')))

        ya_en_este = set(p.attrib.get('numero', '') for p in vendedor_node.findall('planilla') if p.attrib.get('serie') == serie_archivo)
        duplicadas = [p for p in planillas if (serie_archivo, p) in asignadas_otro and p not in ya_en_este]
        if duplicadas:
            return jsonify(ok=False, error=f"Las planillas {', '.join(duplicadas)} ya están asignadas a otro vendedor para la serie {serie_archivo}.")

        # Insertar nuevas (evitando repetir en el mismo vendedor)
        for p in planillas:
            if p in ya_en_este:
                continue
            rango = calcular_rango(p, BOLETOS_POR_PLANILLA)
            ET.SubElement(
                vendedor_node, 'planilla',
                numero=p, rango=rango, serie=serie_archivo, fecha_impresion=fecha_form
            )
        guardar_asignaciones(tree)

        # Preparar tabla actualizada + contadores por serie
        asignadas_serie = _contar_asignadas_serie(root, fecha_form, serie_archivo)
        blanco_serie = max(impresas_serie - asignadas_serie, 0)
        planillas_disponibles = _planillas_disponibles_info(root, fecha_form, serie_archivo, impresas_serie)
        asignaciones_mostrar = _armar_asignaciones_mostrar(root, fecha_form, serie_archivo)
        tbody_html = render_template(
            'tabla_asignaciones.html',
            vendedores=vendedores,
            asignaciones_mostrar=asignaciones_mostrar,
            fecha_seleccionada=fecha_form,
            serie_seleccionada=serie_archivo,
            impresas_serie=impresas_serie,
            asignadas_serie=asignadas_serie,
            blanco_serie=blanco_serie,
            planillas_disponibles=planillas_disponibles,
            boletos_por_planilla=BOLETOS_POR_PLANILLA
        )

        return jsonify(ok=True,
                       tbody=tbody_html,
                       contadores={
                           "impresas_serie": impresas_serie,
                           "asignadas_serie": asignadas_serie,
                           "blanco_serie": blanco_serie
                       })

    # GET: pintar página
    impresas_serie = planillas_impresas_por_serie_fecha(serie_param, fecha_seleccionada) if serie_param else 0
    asignadas_serie = _contar_asignadas_serie(root, fecha_seleccionada, serie_param) if serie_param else 0
    blanco_serie = max(impresas_serie - asignadas_serie, 0)
    planillas_disponibles = _planillas_disponibles_info(root, fecha_seleccionada, serie_param, impresas_serie)
    asignaciones_mostrar = _armar_asignaciones_mostrar(root, fecha_seleccionada, serie_param)

    # Asegurar que también aparezcan en el combo los vendedores que ya tienen
    # planillas asignadas (por si el XML de vendedores no los carga).
    existentes = {f"{(v.get('nombre','')).strip()}|{(v.get('apellido','')).strip()}|{(v.get('seudonimo','')).strip()}" for v in vendedores}
    for a in asignaciones_mostrar:
        key = f"{(a.get('nombre','')).strip()}|{(a.get('apellido','')).strip()}|{(a.get('seudonimo','')).strip()}"
        if key not in existentes:
            vendedores.append({
                'nombre': a.get('nombre', ''),
                'apellido': a.get('apellido', ''),
                'seudonimo': a.get('seudonimo', '')
            })
            existentes.add(key)

    return render_template(
        'asignar_planillas.html',
        vendedores=vendedores,
        fecha_hoy=fecha_hoy,
        fechas_disponibles=sorted(set(
            [d.attrib['fecha'] for d in root.findall('dia')]
            + fechas_impresas_disponibles()
            + [fecha_hoy, fecha_seleccionada]
        )),
        fecha_seleccionada=fecha_seleccionada,
        series_impresas=series_dia,           # ← para el combo de serie
        serie_seleccionada=serie_param,
        impresas_serie=impresas_serie,
        asignadas_serie=asignadas_serie,
        blanco_serie=blanco_serie,
        planillas_disponibles=planillas_disponibles,
        asignaciones_mostrar=asignaciones_mostrar,
        boletos_por_planilla=BOLETOS_POR_PLANILLA
    )

@app.route('/eliminar_planilla', methods=['POST'])
def eliminar_planilla():
    data = request.get_json(force=True) or {}
    fecha = data.get('fecha', '')
    nombre = data.get('nombre', '')
    apellido = data.get('apellido', '')
    seudonimo = data.get('seudonimo', '')
    numero_planilla = data.get('numero', '')
    serie_archivo = data.get('serie', '')  # NUEVO

    tree, root = leer_asignaciones()
    dia = root.find(f"./dia[@fecha='{fecha}']")
    ok = False

    if dia is not None:
        for v in dia.findall('vendedor'):
            if v.attrib.get('nombre') == nombre and v.attrib.get('apellido') == apellido and v.attrib.get('seudonimo') == seudonimo:
                for p in v.findall('planilla'):
                    if p.attrib.get('numero') == numero_planilla and (p.attrib.get('serie') or '') == serie_archivo:
                        v.remove(p)
                        ok = True
                        break
                if len(v.findall('planilla')) == 0:
                    dia.remove(v)
                break
        if len(dia.findall('vendedor')) == 0:
            root.remove(dia)
        guardar_asignaciones(tree)
    # Tabla actualizada + contadores por serie
    vendedores = cargar_vendedores()

    # Recalcular counters por serie+fecha
    impresas_serie = planillas_impresas_por_serie_fecha(serie_archivo, fecha) if serie_archivo else 0
    asignadas_serie = _contar_asignadas_serie(root, fecha, serie_archivo) if serie_archivo else 0
    blanco_serie = max(impresas_serie - asignadas_serie, 0)
    planillas_disponibles = _planillas_disponibles_info(root, fecha, serie_archivo, impresas_serie)

    tbody_html = render_template(
        'tabla_asignaciones.html',
        vendedores=vendedores,
        asignaciones_mostrar=_armar_asignaciones_mostrar(root, fecha, serie_archivo),
        fecha_seleccionada=fecha,
        serie_seleccionada=serie_archivo,
        impresas_serie=impresas_serie,
        asignadas_serie=asignadas_serie,
        blanco_serie=blanco_serie,
        planillas_disponibles=planillas_disponibles,
        boletos_por_planilla=BOLETOS_POR_PLANILLA
    )

    return jsonify(ok=ok,
                   tbody=tbody_html,
                   contadores={
                       "impresas_serie": impresas_serie,
                       "asignadas_serie": asignadas_serie,
                       "blanco_serie": blanco_serie
                   })


# ─── COBROS en CAJA_XML ─────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# COBRO DE CAJA (backend para templates/cobro.html)
# ─────────────────────────────────────────────────────────────────────────────
import os
import io
import xml.etree.ElementTree as ET
from datetime import date, datetime
from types import SimpleNamespace

from flask import (
    Flask, request, render_template, redirect,
    url_for, session, jsonify, Response, render_template_string, current_app
)

# ────────────────────────────────────────────────────────────────────────────
# APP BÁSICA (autónoma). Si ya tienes tu app principal, puedes ignorar esto
# y copiar SOLO las funciones/rutas más abajo a tu proyecto.
# ────────────────────────────────────────────────────────────────────────────

app.secret_key = os.environ.get("SECRET_KEY", "glbingo-dev-key")

# ─── RUTAS/ARCHIVOS base usados por COBRO ───────────────────────────────────
CAJA_XML = globals().get('CAJA_XML', _persist('static', 'db', 'caja.xml'))
os.makedirs(os.path.dirname(CAJA_XML), exist_ok=True)
if not os.path.exists(CAJA_XML):
    ET.ElementTree(ET.Element('caja')).write(CAJA_XML, encoding='utf-8', xml_declaration=True)

# Si estos símbolos no existen en este módulo, los definimos aquí
if 'VENDEDORES_XML' not in globals():
    VENDEDORES_XML = _persist('static', 'db', 'vendedores.xml')
if 'ASIGNACIONES_XML' not in globals():
    ASIGNACIONES_XML = _persist('static', 'db', 'asignaciones.xml')
if 'BOLETOS_POR_PLANILLA' not in globals():
    BOLETOS_POR_PLANILLA = 20

# ─── HELPERS XML ────────────────────────────────────────────────────────────
def _leer_xml(path: str):
    """Abre un XML; si no existe lo crea con raíz = nombre de archivo."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        root_name = os.path.splitext(os.path.basename(path))[0]
        ET.ElementTree(ET.Element(root_name)).write(path, encoding='utf-8', xml_declaration=True)
    tree = ET.parse(path)
    return tree, tree.getroot()

def _guardar_xml(tree: ET.ElementTree, path: str):
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(path, encoding='utf-8', xml_declaration=True)
    _mirror_persist_static_to_public(path)

def _get_dia(root: ET.Element, fecha_str: str) -> ET.Element:
    """Obtiene/crea <dia fecha='YYYY-MM-DD'> en CAJA_XML."""
    dia = root.find(f"./dia[@fecha='{fecha_str}']")
    if dia is None:
        dia = ET.SubElement(root, 'dia', fecha=fecha_str)
    return dia

# ─── CONFIGURACIÓN DEL DÍA ──────────────────────────────────────────────────
def get_configuracion_dia(fecha_str: str):
    t, r = _leer_xml(CAJA_XML)
    dia = _get_dia(r, fecha_str)
    cfg = dia.find('configuracion')
    if cfg is None:
        cfg = ET.SubElement(dia, 'configuracion')

    defaults = {
        'valor_boleto': "0.50",
        'comision_vendedor': "30.0",
        'comision_extra_meta': "5.0",
        'meta_boletos': "60",
    }

    changed = False
    for tag, dv in defaults.items():
        node = cfg.find(tag)
        if node is None:
            node = ET.SubElement(cfg, tag)
            node.text = dv
            changed = True
        elif node.text is None or str(node.text).strip() == "":
            node.text = dv
            changed = True

    if changed:
        _guardar_xml(t, CAJA_XML)

    def ffloat(x, d=0.0):
        try: return float(str(x).replace(",", "."))
        except: return d

    def fint(x, d=0):
        try: return int(float(str(x).replace(",", ".")))
        except: return d

    return {
        "valor_boleto": ffloat(cfg.findtext('valor_boleto', '0')),
        "comision_vendedor": ffloat(cfg.findtext('comision_vendedor', '0')),
        "comision_extra_meta": ffloat(cfg.findtext('comision_extra_meta', '0')),
        "meta_boletos": fint(cfg.findtext('meta_boletos', '0')),
    }

def set_configuracion_dia(fecha_str: str, data: dict):
    t, r = _leer_xml(CAJA_XML)
    dia = _get_dia(r, fecha_str)
    cfg = dia.find('configuracion')
    if cfg is None:
        cfg = ET.SubElement(dia, 'configuracion')

    for k in ("valor_boleto", "comision_vendedor", "comision_extra_meta", "meta_boletos"):
        node = cfg.find(k)
        if node is None:
            node = ET.SubElement(cfg, k)
        node.text = str(data.get(k, node.text or "0"))

    _guardar_xml(t, CAJA_XML)

# ─── VENDEDORES y ASIGNACIONES (lectura) ────────────────────────────────────


def _cargar_vendedores_base():
    """Devuelve dict por seudónimo con datos base y comisión manual opcional."""
    vendedores = {}
    if os.path.exists(VENDEDORES_XML):
        _, r = _leer_xml(VENDEDORES_XML)
        for v in r.findall('vendedor'):
            seud = (v.findtext('seudonimo', '') or '').strip()
            if seud:
                info_com = _vendor_commission_info_from_node(v)
                vendedores[seud] = {
                    "nombre":   (v.findtext('nombre', '') or '').strip(),
                    "apellido": (v.findtext('apellido', '') or '').strip(),
                    "seudonimo": seud,
                    "modo_comision": info_com["modo_comision"],
                    "comision_manual": info_com["comision_manual"],
                }
    return vendedores

def _cargar_asignaciones_por_fecha(fecha_str: str):
    """Devuelve dict por seudónimo: {'planillas':[...], 'boletos_entregados': int}"""
    data = {}
    if not os.path.exists(ASIGNACIONES_XML):
        return data
    _, r = _leer_xml(ASIGNACIONES_XML)
    dia = r.find(f"./dia[@fecha='{fecha_str}']")
    if dia is None:
        return data
    for v in dia.findall('vendedor'):
        seud = (v.attrib.get('seudonimo', '') or '').strip()
        plans = [p.attrib.get('numero', '') for p in v.findall('planilla')]
        plans = [p for p in plans if p]
        entregados = len(plans) * int(BOLETOS_POR_PLANILLA)
        data[seud] = {"planillas": plans, "boletos_entregados": entregados}
    return data

# ─── COBROS en CAJA_XML ─────────────────────────────────────────────────────
def _get_cobros_node(dia: ET.Element) -> ET.Element:
    node = dia.find('cobros')
    if node is None:
        node = ET.SubElement(dia, 'cobros')
    return node

def _safe_int_local(v, d=0):
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except Exception:
        return d

def _safe_float_local(v, d=0.0):
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return d

def _cobro_qr_parse_payload(qr_text: str, fecha_esperada: str | None = None):
    """Parsea el texto del QR (URL firmada o formato legado) y devuelve datos del boleto."""
    from urllib.parse import urlparse, parse_qs

    raw = str(qr_text or "").strip()
    if not raw:
        raise ValueError("QR vacío")

    if "?" in raw or "qr/boleto" in raw:
        try:
            u = urlparse(raw)
            qs = parse_qs(u.query or "")
        except Exception:
            qs = {}
        serie = (qs.get("serie", [""])[0] or "").strip()
        boleto = (qs.get("boleto", [""])[0] or "").strip()
        fecha = (qs.get("fecha", [""])[0] or "").strip()
        sig = (qs.get("sig", [""])[0] or "").strip()
        if serie and boleto and fecha:
            if sig and ('_qr_ticket_sig_ok' in globals()) and not _qr_ticket_sig_ok(serie, boleto, fecha, sig):
                raise ValueError("Firma QR inválida")
            if fecha_esperada and fecha != str(fecha_esperada):
                raise ValueError(f"El QR corresponde a la fecha {fecha}, no a {fecha_esperada}")
            try:
                boleto_norm = str(int(float(boleto)))
            except Exception:
                boleto_norm = boleto
            return {"serie": serie, "boleto": boleto_norm, "fecha": fecha, "sig": sig, "raw": raw}

    if "|" in raw:
        parts = [p.strip() for p in raw.split("|") if str(p).strip()]
        if len(parts) >= 2:
            boleto, fecha = parts[0], parts[1]
            if fecha_esperada and fecha != str(fecha_esperada):
                raise ValueError(f"El QR corresponde a la fecha {fecha}, no a {fecha_esperada}")
            imp = get_impresiones_info(fecha)
            serie = str(imp.get("serie_detectada") or "").strip()
            if not serie:
                raise ValueError("No se pudo detectar la serie del día para validar este QR")
            try:
                boleto_norm = str(int(float(boleto)))
            except Exception:
                boleto_norm = boleto
            return {"serie": serie, "boleto": boleto_norm, "fecha": fecha, "sig": "", "raw": raw}

    raise ValueError("QR no reconocido. Escanea el QR completo del boleto")


def _cobro_qr_info_ticket_para_vendedor(fecha: str, seudonimo: str, qr_text: str):
    data = _cobro_qr_parse_payload(qr_text, fecha_esperada=fecha)
    serie = str(data.get("serie") or "").strip()
    boleto = str(data.get("boleto") or "").strip()
    if not serie or not boleto:
        raise ValueError("QR sin serie o boleto")

    asign = _cargar_asignaciones_por_fecha(fecha)
    info_asig = asign.get(seudonimo)
    if not info_asig:
        raise ValueError(f"No hay planillas asignadas para '{seudonimo}' en {fecha}")

    idx_num, planilla_num = _parse_ticket_id(boleto)
    if idx_num is None:
        raise ValueError("No se pudo interpretar el número de boleto del QR")

    res = _qr_resolver_vendedor_por_boleto(fecha, serie, boleto)
    if not isinstance(res, dict) or not res.get("ok"):
        raise ValueError(res.get("error") if isinstance(res, dict) else "No se pudo validar el QR")

    ok_rango = False
    det = None
    if os.path.exists(ASIGNACIONES_XML):
        _, r_as = _leer_xml(ASIGNACIONES_XML)
        dia = r_as.find(f"./dia[@fecha='{fecha}']")
        if dia is not None:
            vnode = dia.find(f"./vendedor[@seudonimo='{seudonimo}']")
            if vnode is not None:
                for p in vnode.findall('planilla'):
                    pnum = (p.attrib.get('numero') or '').strip()
                    pserie = (p.attrib.get('serie') or '').strip()
                    d = _safe_int_local(p.attrib.get('desde', 0), 0)
                    h = _safe_int_local(p.attrib.get('hasta', 0), 0)
                    if pserie == serie and d <= idx_num <= h:
                        ok_rango = True
                        det = {"planilla": pnum, "desde": d, "hasta": h}
                        break
    if not ok_rango:
        raise ValueError(f"El boleto {boleto} ({serie}) no pertenece a {seudonimo} en {fecha}")

    return {
        "fecha": fecha,
        "serie": serie,
        "boleto": boleto,
        "idx": idx_num,
        "planilla": str((det or {}).get("planilla") or planilla_num or ""),
        "raw": data.get("raw") or qr_text,
    }


def _cobro_qr_normalizar_lista(fecha: str, seudonimo: str, items):
    out = []
    seen = set()
    if not isinstance(items, list):
        return out

    for it in items:
        if isinstance(it, dict):
            raw = str(it.get('raw') or '').strip()
            serie = str(it.get('serie') or '').strip()
            boleto = str(it.get('boleto') or '').strip()
            if raw:
                info = _cobro_qr_info_ticket_para_vendedor(fecha, seudonimo, raw)
            else:
                if not (serie and boleto):
                    continue
                info = _cobro_qr_info_ticket_para_vendedor(fecha, seudonimo, f"https://local/qr/boleto?serie={serie}&boleto={boleto}&fecha={fecha}")
        else:
            raw = str(it or '').strip()
            if not raw:
                continue
            info = _cobro_qr_info_ticket_para_vendedor(fecha, seudonimo, raw)

        key = (str(info.get('serie') or '').upper(), str(info.get('boleto') or ''))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            'serie': str(info.get('serie') or ''),
            'boleto': str(info.get('boleto') or ''),
            'idx': str(info.get('idx') or ''),
            'planilla': str(info.get('planilla') or ''),
            'raw': str(info.get('raw') or ''),
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
    out.sort(key=lambda x: _safe_int_local(x.get('idx', 0), 0))
    return out



def _calc_cobro_detalle(vendidos: int, cfg: dict, vendor_override: dict | None = None):
    vendidos = max(0, int(vendidos or 0))
    valor = max(0.0, _safe_float_local(cfg.get("valor_boleto"), 0.0))
    pct_base = max(0.0, min(100.0, _safe_float_local(cfg.get("comision_vendedor"), 0.0)))
    pct_extra = max(0.0, min(100.0, _safe_float_local(cfg.get("comision_extra_meta"), 0.0)))
    meta = max(0, _safe_int_local(cfg.get("meta_boletos"), 0))

    ov = vendor_override if isinstance(vendor_override, dict) else (cfg if isinstance(cfg, dict) else {})
    modo_comision = str((ov.get("modo_comision") or ov.get("_modo_comision") or "normal")).strip().lower()
    comision_manual = max(0.0, min(100.0, _safe_float_local(ov.get("comision_manual", ov.get("_comision_manual", 0)), 0.0)))

    if modo_comision == "manual" and comision_manual > 0:
        pct = comision_manual
    else:
        modo_comision = "normal"
        comision_manual = 0.0
        pct = pct_base + (pct_extra if (meta > 0 and vendidos >= meta) else 0.0)

    pct = max(0.0, min(100.0, pct))

    total_venta = round(vendidos * valor, 2)
    gan_vendedor = round(total_venta * pct / 100.0, 2)
    a_pagar_caja = round(total_venta - gan_vendedor, 2)

    return {
        "valor_boleto": round(valor, 4),
        "comision_vendedor": round(pct_base, 4),
        "comision_extra_meta": round(pct_extra, 4),
        "meta_boletos": meta,
        "modo_comision": modo_comision,
        "comision_manual": round(comision_manual, 4),
        "pct_aplicado": round(pct, 4),
        "valor_total_venta": total_venta,
        "gan_vendedor": gan_vendedor,
        "a_pagar_caja": a_pagar_caja,
    }

def _leer_cobros(fecha_str: str):
    """Dict por seudónimo con cobros guardados."""
    _, r = _leer_xml(CAJA_XML)
    dia = _get_dia(r, fecha_str)
    cobros = _get_cobros_node(dia)
    out = {}
    for c in cobros.findall('cobro'):
        seud = c.attrib.get('seudonimo', '')
        out[seud] = {
            "devueltos":     _safe_int_local(c.attrib.get('devueltos', 0)),
            "vendidos":      _safe_int_local(c.attrib.get('vendidos', 0)),
            "total_pagar":   round(_safe_float_local(c.attrib.get('total_pagar', 0), 0.0), 2),  # pago recibido (contabilidad)
            "transferencia": round(_safe_float_local(c.attrib.get('transferencia', 0), 0.0), 2),
            "efectivo":      round(_safe_float_local(c.attrib.get('efectivo', 0), 0.0), 2),
            "pagado":        c.attrib.get('pagado', '0') == '1',
            "fecha_hora":    c.attrib.get('fecha_hora', ''),
            # snapshot de configuración
            "valor_boleto": _safe_float_local(c.attrib.get('valor_boleto', 0), 0.0),
            "comision_vendedor": _safe_float_local(c.attrib.get('comision_vendedor', 0), 0.0),
            "comision_extra_meta": _safe_float_local(c.attrib.get('comision_extra_meta', 0), 0.0),
            "meta_boletos": _safe_int_local(c.attrib.get('meta_boletos', 0), 0),
            "modo_comision": (c.attrib.get('modo_comision', 'normal') or 'normal'),
            "comision_manual": _safe_float_local(c.attrib.get('comision_manual', 0), 0.0),
            # montos calculados guardados (si existen)
            "pct_aplicado": _safe_float_local(c.attrib.get('pct_aplicado', ''), None),
            "valor_total_venta": _safe_float_local(c.attrib.get('valor_total_venta', ''), None),
            "gan_vendedor": _safe_float_local(c.attrib.get('gan_vendedor', ''), None),
            "a_pagar_caja": _safe_float_local(c.attrib.get('a_pagar_caja', ''), None),
            "vuelto": _safe_float_local(c.attrib.get('vuelto', ''), None),
            "modo_devolucion": c.attrib.get('modo_devolucion', 'manual'),
            "boletos_devueltos_qr": [],
        }
        qrn = c.find("boletos_devueltos_qr")
        if qrn is not None:
            lst = []
            for b in qrn.findall("boleto"):
                lst.append({
                    "serie": (b.attrib.get("serie") or ""),
                    "boleto": (b.attrib.get("numero") or ""),
                    "idx": (b.attrib.get("idx") or ""),
                    "planilla": (b.attrib.get("planilla") or ""),
                    "ts": (b.attrib.get("ts") or ""),
                })
            out[seud]["boletos_devueltos_qr"] = lst
            out[seud]["devueltos_qr_count"] = len(lst)
    return out

def _upsert_cobro(fecha_str: str, seudonimo: str, datos: dict):
    """Crea/actualiza un <cobro> dentro del día indicado.

    Guarda también metadatos para auditoría:
      - creado_por / creado_rol / creado_ip / creado_en (solo si no existían)
      - actualizado_por / actualizado_ip / actualizado_en (siempre)
      - snapshot de configuración (si viene en datos)
    """
    t, r = _leer_xml(CAJA_XML)
    dia = _get_dia(r, fecha_str)
    cobros = _get_cobros_node(dia)
    node = cobros.find(f"./cobro[@seudonimo='{seudonimo}']")
    if node is None:
        node = ET.SubElement(cobros, 'cobro', seudonimo=seudonimo)

    now = datetime.now()
    if not node.get("id"):
        node.set("id", f"{fecha_str}__{seudonimo}")

    node.set('devueltos',     str(int(datos.get('devueltos', 0))))
    node.set('vendidos',      str(int(datos.get('vendidos', 0))))
    node.set('total_pagar',   f"{float(datos.get('total_pagar', 0)):.2f}")  # pago recibido
    node.set('transferencia', f"{float(datos.get('transferencia', 0)):.2f}")
    node.set('efectivo',      f"{float(datos.get('efectivo', 0)):.2f}")
    node.set('pagado',        '1' if datos.get('pagado', True) else '0')
    node.set('fecha_hora',    datos.get('fecha_hora', now.strftime('%Y-%m-%d %H:%M:%S')))

    # Snapshot + montos guardados (para mantener consistencia histórica)
    for k in (
        "valor_boleto", "comision_vendedor", "comision_extra_meta", "meta_boletos",
        "modo_comision", "comision_manual",
        "pct_aplicado", "valor_total_venta", "gan_vendedor", "a_pagar_caja", "vuelto"
    ):
        if k in datos and datos.get(k) is not None:
            v = datos.get(k)
            if isinstance(v, float):
                # meta_boletos no debería caer aquí, pero por seguridad:
                node.set(k, f"{v:.2f}" if k != "pct_aplicado" else f"{v:.4f}")
            else:
                node.set(k, str(v))

    if not node.get("creado_en"):
        node.set("creado_en", datos.get("creado_en") or now.isoformat(timespec="seconds"))
    if not node.get("creado_por"):
        node.set("creado_por", datos.get("creado_por") or (session.get("usuario") if session else "") or "")
    if not node.get("creado_rol"):
        node.set("creado_rol", datos.get("creado_rol") or (session.get("rol") if session else "") or "")
    if not node.get("creado_ip"):
        node.set("creado_ip", datos.get("creado_ip") or (request.remote_addr if request else "") or "")

    node.set("actualizado_en", now.isoformat(timespec="seconds"))
    node.set("actualizado_por", (session.get("usuario") if session else "") or (datos.get("creado_por") or ""))
    node.set("actualizado_ip", (request.remote_addr if request else "") or "")

    if "modo_devolucion" in datos:
        node.set("modo_devolucion", str(datos.get("modo_devolucion") or "manual"))

    if "boletos_devueltos_qr" in datos:
        qn = node.find("boletos_devueltos_qr")
        if qn is None:
            qn = ET.SubElement(node, "boletos_devueltos_qr")
        qn.attrib["total"] = str(len(datos.get("boletos_devueltos_qr") or []))
        qn.attrib["actualizado_en"] = now.strftime('%Y-%m-%d %H:%M:%S')
        for oldb in list(qn):
            qn.remove(oldb)
        for it in (datos.get("boletos_devueltos_qr") or []):
            if not isinstance(it, dict):
                continue
            ET.SubElement(qn, "boleto", {
                "serie": str(it.get("serie") or ""),
                "numero": str(it.get("boleto") or ""),
                "idx": str(it.get("idx") or ""),
                "planilla": str(it.get("planilla") or ""),
                "ts": str(it.get("ts") or now.strftime('%Y-%m-%d %H:%M:%S')),
            })

    _guardar_xml(t, CAJA_XML)

# ─── AGREGADORES DE TOTALES (para la tabla de “Pagados”) ────────────────────
def _agregar_totales_pagados(lista_vendedores, config):
    tot = {"planillas":0, "entregados":0, "devueltos":0, "vendidos":0,
           "total":0.0, "gan_vendedor":0.0, "a_pagar_caja":0.0, "pago":0.0}

    for v in lista_vendedores:
        if not v.get('pagado'):
            continue

        tot["planillas"]  += len(v.get('planillas', []))
        tot["entregados"] += int(v.get('boletos_entregados', 0) or 0)
        tot["devueltos"]  += int(v.get('boletos_devueltos', 0) or 0)
        tot["vendidos"]   += int(v.get('boletos_vendidos', 0) or 0)

        total_venta = _safe_float_local(v.get("total_venta_calc"), None)
        gan_v = _safe_float_local(v.get("gan_vendedor_calc"), None)
        caja = _safe_float_local(v.get("a_pagar_caja_calc"), None)

        if total_venta is None or gan_v is None or caja is None:
            detalle = _calc_cobro_detalle(v.get('boletos_vendidos', 0), config)
            total_venta = detalle["valor_total_venta"]
            gan_v = detalle["gan_vendedor"]
            caja = detalle["a_pagar_caja"]

        pago = round(_safe_float_local(v.get("transferencia", 0.0)) + _safe_float_local(v.get("efectivo", 0.0)), 2)

        tot["total"]        += float(total_venta)
        tot["gan_vendedor"] += float(gan_v)
        tot["a_pagar_caja"] += float(caja)
        tot["pago"]         += pago

    for k in ("total","gan_vendedor","a_pagar_caja","pago"):
        tot[k] = round(tot[k], 2)
    return tot

# ─── VISTA PRINCIPAL /cobro (con ?fecha=YYYY-MM-DD) ─────────────────────────
@app.route('/cobro', methods=['GET'])
def cobro():
    if 'usuario' not in session:
        return redirect(_login_url())

    fecha_actual = (request.args.get('fecha') or date.today().isoformat()).strip()

    config = get_configuracion_dia(fecha_actual)
    base   = _cargar_vendedores_base()
    asign  = _cargar_asignaciones_por_fecha(fecha_actual)
    cobros = _leer_cobros(fecha_actual)

    vendedores_ui = []
    ordered_seuds = list(asign.keys()) + [s for s in cobros.keys() if s not in asign]

    for seud in ordered_seuds:
        info = asign.get(seud, {})
        base_info  = base.get(seud, {"nombre":"", "apellido":"", "seudonimo":seud})
        planillas  = info.get('planillas', [])
        entregados = int(info.get('boletos_entregados', 0) or 0)

        c = cobros.get(seud, {})
        devueltos = int(c.get('devueltos', 0) or 0)
        vendidos_guardado = int(c.get('vendidos', 0) or 0)

        # Si el cobro existe pero ya no hay asignación visible, preserva consistencia visual
        if entregados <= 0 and (devueltos > 0 or vendidos_guardado > 0):
            entregados = devueltos + vendidos_guardado

        devueltos = max(0, min(devueltos, entregados))
        vendidos  = vendidos_guardado if vendidos_guardado > 0 else max(entregados - devueltos, 0)
        pagado    = bool(c.get('pagado', False))

        cfg_row = dict(config)
        if c:
            # usa snapshot si existe (mantiene histórico aunque cambies configuración del día)
            if c.get("valor_boleto") not in (None, 0, 0.0):
                cfg_row["valor_boleto"] = c.get("valor_boleto")
            if c.get("comision_vendedor") is not None:
                cfg_row["comision_vendedor"] = c.get("comision_vendedor")
            if c.get("comision_extra_meta") is not None:
                cfg_row["comision_extra_meta"] = c.get("comision_extra_meta")
            if c.get("meta_boletos") is not None:
                cfg_row["meta_boletos"] = c.get("meta_boletos")
            if str(c.get("modo_comision") or 'normal').strip().lower() == 'manual' and float(c.get("comision_manual") or 0) > 0:
                cfg_row["modo_comision"] = 'manual'
                cfg_row["comision_manual"] = float(c.get("comision_manual") or 0)
        else:
            if str(base_info.get("modo_comision") or 'normal').strip().lower() == 'manual' and float(base_info.get("comision_manual") or 0) > 0:
                cfg_row["modo_comision"] = 'manual'
                cfg_row["comision_manual"] = float(base_info.get("comision_manual") or 0)

        detalle = _calc_cobro_detalle(vendidos, cfg_row)

        total_venta_calc = c.get("valor_total_venta") if c.get("valor_total_venta") is not None else detalle["valor_total_venta"]
        pct_aplicado_calc = c.get("pct_aplicado") if c.get("pct_aplicado") is not None else detalle["pct_aplicado"]
        gan_vendedor_calc = c.get("gan_vendedor") if c.get("gan_vendedor") is not None else detalle["gan_vendedor"]
        a_pagar_caja_calc = c.get("a_pagar_caja") if c.get("a_pagar_caja") is not None else detalle["a_pagar_caja"]

        transferencia = round(_safe_float_local(c.get('transferencia', 0.0), 0.0), 2)
        efectivo = round(_safe_float_local(c.get('efectivo', 0.0), 0.0), 2)
        pago_calc = round(transferencia + efectivo, 2)
        vuelto_calc = c.get("vuelto") if c.get("vuelto") is not None else round(pago_calc - a_pagar_caja_calc, 2)

        vendedores_ui.append({
            "nombre_completo": (base_info.get('nombre','') + " " + base_info.get('apellido','')).strip() or seud,
            "seudonimo": seud,
            "planillas": planillas,
            "boletos_entregados": entregados,
            "boletos_devueltos":  devueltos,
            "boletos_vendidos":   vendidos,
            "transferencia": transferencia,
            "efectivo":      efectivo,
            "pagado":        pagado,

            # Detalle ya calculado (para evitar inconsistencias en plantilla)
            "valor_boleto_aplicado": float(cfg_row.get("valor_boleto", 0.0) or 0.0),
            "modo_comision": str((cfg_row.get('modo_comision') or 'normal')).strip().lower(),
            "comision_manual": round(float(cfg_row.get('comision_manual', 0.0) or 0.0), 2),
            "pct_aplicado": round(float(pct_aplicado_calc or 0.0), 2),
            "total_venta_calc": round(float(total_venta_calc or 0.0), 2),
            "gan_vendedor_calc": round(float(gan_vendedor_calc or 0.0), 2),
            "a_pagar_caja_calc": round(float(a_pagar_caja_calc or 0.0), 2),
            "pago_calc": pago_calc,
            "vuelto_calc": round(float(vuelto_calc or 0.0), 2),
        })

    paid_totals = _agregar_totales_pagados(vendedores_ui, config)

    return render_template(
        'cobro.html',
        username=session.get('usuario', 'admin'),
        avatar=session.get('avatar', 'avatar-male.png'),
        config=config,
        fecha_actual=fecha_actual,
        vendedores=vendedores_ui,
        paid_totals=paid_totals,
        can_edit_vendor_commission=_is_superadmin(),
        user_role=session.get('rol', '')
    )


# ─── ALIAS DE COMPATIBILIDAD (evita 404 en enlaces antiguos) ────────────────
@app.route('/cobro-caja', methods=['GET'])
@app.route('/caja-cobro', methods=['GET'])
@app.route('/cobro_caja', methods=['GET'])
def cobro_alias_compat():
    # Redirige conservando la fecha u otros query params para no romper accesos viejos
    params = request.args.to_dict(flat=True)
    return redirect(url_for('cobro', **params))

# ─── GUARDAR CONFIGURACIÓN DEL DÍA ──────────────────────────────────────────
@app.route('/guardar_configuracion_caja', methods=['POST'])
def guardar_configuracion_caja():
    try:
        data = request.get_json(force=True) or {}
        fecha_actual = (data.get('fecha') or request.args.get('fecha') or date.today().isoformat()).strip()

        valor_boleto = _safe_float_local(data.get('valor_boleto', 0), 0.0)
        comision_vendedor = _safe_float_local(data.get('comision_vendedor', 0), 0.0)
        comision_extra_meta = _safe_float_local(data.get('comision_extra_meta', 0), 0.0)
        meta_boletos = _safe_int_local(data.get('meta_boletos', 0), 0)

        if valor_boleto <= 0:
            return jsonify(ok=False, error="El valor del boleto debe ser mayor que 0."), 400
        if comision_vendedor < 0 or comision_vendedor > 100:
            return jsonify(ok=False, error="La comisión base debe estar entre 0% y 100%."), 400
        if comision_extra_meta < 0 or comision_extra_meta > 100:
            return jsonify(ok=False, error="La comisión extra debe estar entre 0% y 100%."), 400
        if (comision_vendedor + comision_extra_meta) > 100:
            return jsonify(ok=False, error="La comisión total (base + extra) no puede superar 100%."), 400
        if meta_boletos < 0:
            return jsonify(ok=False, error="La meta de boletos no puede ser negativa."), 400

        payload = {
            "valor_boleto": round(valor_boleto, 2),
            "comision_vendedor": round(comision_vendedor, 2),
            "comision_extra_meta": round(comision_extra_meta, 2),
            "meta_boletos": meta_boletos,
        }
        set_configuracion_dia(fecha_actual, payload)
        return jsonify(ok=True, config=payload)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

# ─── GUARDAR COBRO DE UN VENDEDOR ───────────────────────────────────────────
@app.route('/api/cobro/qr/validar', methods=['POST'])
def api_cobro_qr_validar():
    try:
        j = request.get_json(force=True) or {}
        fecha = (j.get('fecha') or date.today().isoformat()).strip()
        seudonimo = (j.get('seudonimo') or '').strip()
        qr_text = (j.get('qr_text') or '').strip()
        if not seudonimo:
            return jsonify(ok=False, error='Falta seudónimo del vendedor'), 400
        info = _cobro_qr_info_ticket_para_vendedor(fecha, seudonimo, qr_text)
        return jsonify(ok=True, item=info)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@app.route('/guardar_cobro/<seudonimo>', methods=['POST'])
def guardar_cobro(seudonimo):
    try:
        j = request.get_json(force=True) or {}
        fecha_actual = (j.get('fecha') or request.args.get('fecha') or date.today().isoformat()).strip()

        asign = _cargar_asignaciones_por_fecha(fecha_actual)
        info_asig = asign.get(seudonimo)
        if not info_asig:
            return jsonify(ok=False, error=f"No hay planillas asignadas para '{seudonimo}' en la fecha {fecha_actual}."), 400

        entregados = int(info_asig.get('boletos_entregados', 0) or 0)

        qr_items_in = j.get('boletos_devueltos_qr') if isinstance(j.get('boletos_devueltos_qr'), list) else None
        qr_items = []
        modo_devolucion = 'manual'
        if qr_items_in is not None:
            qr_items = _cobro_qr_normalizar_lista(fecha_actual, seudonimo, qr_items_in)
            devueltos = len(qr_items)
            modo_devolucion = 'qr'
        else:
            devueltos = _safe_int_local(j.get('boletos_devueltos', 0), 0)

        if devueltos < 0:
            return jsonify(ok=False, error="Los devueltos no pueden ser negativos."), 400
        if devueltos > entregados:
            return jsonify(ok=False, error=f"Devueltos ({devueltos}) no puede ser mayor que entregados ({entregados})."), 400

        vendidos = max(entregados - devueltos, 0)

        transferencia = round(_safe_float_local(j.get('transferencia', 0), 0.0), 2)
        efectivo = round(_safe_float_local(j.get('efectivo', 0), 0.0), 2)
        if transferencia < 0 or efectivo < 0:
            return jsonify(ok=False, error="Transferencia y efectivo no pueden ser negativos."), 400

        base_vendedores = _cargar_vendedores_base()
        vendor_info = base_vendedores.get(seudonimo, {})
        cfg = dict(get_configuracion_dia(fecha_actual))
        if str(vendor_info.get('modo_comision') or 'normal').strip().lower() == 'manual' and float(vendor_info.get('comision_manual') or 0) > 0:
            cfg['modo_comision'] = 'manual'
            cfg['comision_manual'] = float(vendor_info.get('comision_manual') or 0)
        detalle = _calc_cobro_detalle(vendidos, cfg)

        a_pagar_caja = detalle["a_pagar_caja"]
        pago_recibido = round(transferencia + efectivo, 2)
        vuelto = round(pago_recibido - a_pagar_caja, 2)

        if pago_recibido + 0.009 < a_pagar_caja:
            faltante = round(a_pagar_caja - pago_recibido, 2)
            return jsonify(ok=False, error=f"Pago insuficiente. Faltan ${faltante:.2f} para completar el cobro."), 400

        _upsert_cobro(
            fecha_actual,
            seudonimo,
            {
                "devueltos": devueltos,
                "vendidos": vendidos,
                "total_pagar": pago_recibido,   # pago recibido (contabilidad)
                "transferencia": transferencia,
                "efectivo": efectivo,
                "pagado": True,

                # Snapshot de configuración + montos finales
                "valor_boleto": detalle["valor_boleto"],
                "comision_vendedor": detalle["comision_vendedor"],
                "comision_extra_meta": detalle["comision_extra_meta"],
                "meta_boletos": detalle["meta_boletos"],
                "modo_comision": detalle["modo_comision"],
                "comision_manual": detalle["comision_manual"],
                "pct_aplicado": detalle["pct_aplicado"],
                "valor_total_venta": detalle["valor_total_venta"],
                "gan_vendedor": detalle["gan_vendedor"],
                "a_pagar_caja": detalle["a_pagar_caja"],
                "vuelto": vuelto,

                # Auditoría
                "creado_por": session.get("usuario", ""),
                "creado_rol": session.get("rol", ""),
                "creado_ip": request.remote_addr or "",
                "creado_en": datetime.now().isoformat(timespec="seconds"),
                "modo_devolucion": modo_devolucion,
                "boletos_devueltos_qr": qr_items,
            }
        )

        try:
            if qr_items_in is not None and '_sorteo_upsert_boletos_no_vendidos_qr' in globals():
                _sorteo_upsert_boletos_no_vendidos_qr(fecha_actual, seudonimo, qr_items)
        except Exception:
            pass

        return jsonify(
            ok=True,
            cobro={
                "seudonimo": seudonimo,
                "entregados": entregados,
                "devueltos": devueltos,
                "vendidos": vendidos,
                "transferencia": transferencia,
                "efectivo": efectivo,
                "pago": pago_recibido,
                "modo_comision": detalle["modo_comision"],
                "comision_manual": round(detalle["comision_manual"], 2),
                "pct_aplicado": round(detalle["pct_aplicado"], 2),
                "total_venta": round(detalle["valor_total_venta"], 2),
                "gan_vendedor": round(detalle["gan_vendedor"], 2),
                "a_pagar_caja": round(detalle["a_pagar_caja"], 2),
                "vuelto": vuelto,
                "modo_devolucion": modo_devolucion,
                "devueltos_qr": len(qr_items) if isinstance(qr_items, list) else 0,
            }
        )
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400



@app.get('/cobro/recibo/<seudonimo>.pdf')
def cobro_recibo_pdf(seudonimo):
    if 'usuario' not in session:
        return redirect(_login_url())

    fecha_actual = (request.args.get('fecha') or date.today().isoformat()).strip()
    base = _cargar_vendedores_base().get(seudonimo, {"nombre":"", "apellido":"", "seudonimo": seudonimo})
    asign = _cargar_asignaciones_por_fecha(fecha_actual).get(seudonimo, {})
    cobros = _leer_cobros(fecha_actual)
    c = cobros.get(seudonimo)
    if not c:
        return Response('Cobro no encontrado', 404, mimetype='text/plain')

    entregados = int(asign.get('boletos_entregados', 0) or 0)
    devueltos = int(c.get('devueltos', 0) or 0)
    vendidos = int(c.get('vendidos', 0) or 0)
    planillas = asign.get('planillas', []) or []
    nombre = (str(base.get('nombre','')) + ' ' + str(base.get('apellido',''))).strip() or seudonimo
    modo_comision = str(c.get('modo_comision') or 'normal').strip().lower()
    com_manual = float(c.get('comision_manual') or 0)

    detalle = {
        'valor_boleto': float(c.get('valor_boleto') or 0),
        'pct_aplicado': float(c.get('pct_aplicado') or 0),
        'valor_total_venta': float(c.get('valor_total_venta') or 0),
        'gan_vendedor': float(c.get('gan_vendedor') or 0),
        'a_pagar_caja': float(c.get('a_pagar_caja') or 0),
    }

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 35

    pdf.setTitle(f"cobro_{fecha_actual}_{seudonimo}")
    pdf.setFont('Helvetica-Bold', 18)
    pdf.drawString(35, y, 'Comprobante de Cobro de Caja')
    y -= 18
    pdf.setFont('Helvetica', 10)
    pdf.drawString(35, y, f'Fecha: {fecha_actual}')
    pdf.drawRightString(w - 35, y, f'Generado por: {session.get("usuario", "") or "Sistema"}')

    y -= 22
    pdf.roundRect(30, y-92, w-60, 88, 10, stroke=1, fill=0)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(40, y-16, f'Vendedor: {nombre}')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(40, y-34, f'Seudónimo: {seudonimo}')
    pdf.drawString(40, y-50, f'Planillas: {", ".join(planillas) if planillas else "—"}')
    pdf.drawString(40, y-66, f'Modo comisión: {'Manual' if modo_comision == 'manual' and com_manual > 0 else 'Normal del día'}')
    if modo_comision == 'manual' and com_manual > 0:
        pdf.drawString(250, y-66, f'Comisión manual: {com_manual:.2f}%')
    y -= 110

    rows = [
        ('Boletos entregados', str(entregados)),
        ('Boletos devueltos', str(devueltos)),
        ('Boletos vendidos', str(vendidos)),
        ('Valor total venta', f"${detalle['valor_total_venta']:.2f}"),
        ('% comisión aplicado', f"{detalle['pct_aplicado']:.2f}%"),
        ('Ganancia vendedor', f"${detalle['gan_vendedor']:.2f}"),
        ('A pagar caja', f"${detalle['a_pagar_caja']:.2f}"),
        ('Transferencia', f"${float(c.get('transferencia') or 0):.2f}"),
        ('Efectivo', f"${float(c.get('efectivo') or 0):.2f}"),
        ('Pago recibido', f"${float(c.get('total_pagar') or 0):.2f}"),
        ('Vuelto', f"${float(c.get('vuelto') or 0):.2f}"),
    ]
    tbl = Table(rows, colWidths=[170, 150])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EEF2FF')),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('GRID', (0,0), (-1,-1), .5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    tw, th = tbl.wrapOn(pdf, w-70, h)
    tbl.drawOn(pdf, 35, y-th)
    y = y - th - 22

    pdf.setFont('Helvetica', 9)
    pdf.setFillColor(colors.HexColor('#334155'))
    pdf.drawString(35, max(24, y), 'Documento generado por GL Bingo. Este comprobante resume el cobro liquidado para el vendedor en la fecha indicada.')
    pdf.showPage()
    pdf.save()
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'cobro_{fecha_actual}_{seudonimo}.pdf')

# ─── RUTAS DE APOYO (no interfieren con tu app) ─────────────────────────────
@app.route("/_login_demo")
def _login_demo():
    """Login de prueba para esta demo autónoma."""
    session['usuario'] = 'Administrador'
    session['avatar'] = 'avatar-male.png'
    return redirect(url_for('cobro'))

@app.route("/cobro_ping")
def cobro_ping():
    return "COBRO PING OK"

@app.route("/cobro_raw")
def cobro_raw():
    tpl_dir = current_app.jinja_loader.searchpath[0] if hasattr(current_app, "jinja_loader") else "templates"
    path = os.path.join(tpl_dir, "cobro.html")
    if not os.path.exists(path):
        return Response(f"NO EXISTE: {path}", 404, mimetype="text/plain")
    with io.open(path, "r", encoding="utf-8") as f:
        data = f.read()
    return Response(data, 200, mimetype="text/plain; charset=utf-8")

@app.route("/cobro_inline")
def cobro_inline():
    html = """
    <!doctype html><meta charset="utf-8">
    <title>Inline Cobro</title>
    <div style="padding:24px;font:16px/1.4 system-ui;background:#f5f7fb">
      <h1>Inline OK</h1>
      <p>Si ves esto, Flask está renderizando. El problema estaría en la plantilla o su ubicación.</p>
      <a href="/_login_demo">Entrar (demo)</a> · <a href="/cobro">/cobro</a>
    </div>
    """
    return render_template_string(html)

@app.after_request
def _debug_banner(resp):
    """Inserta un banner discreto si /cobro devuelve HTML."""
    try:
        if request.path == "/cobro" and resp.content_type and resp.content_type.startswith("text/html"):
            body = resp.get_data(as_text=True) or ""
            if "<!-- COBRO DEBUG BANNER -->" not in body:
                banner = '<!-- COBRO DEBUG BANNER --><div style="position:fixed;z-index:99999;top:8px;left:8px;background:#000;color:#fff;padding:6px 10px;border-radius:6px;font:700 12px system-ui">COBRO render</div>'
                resp.set_data(banner + body)
    except Exception:
        pass
    return resp

# ─── MAIN ───────────────────────────────────────────────────────────────────
if False and __name__ == "__main__":  # DESHABILITADO (evita arrancar antes de cargar rutas)
    # Crea carpetas mínimas de ejemplo
    os.makedirs(os.path.dirname(VENDEDORES_XML), exist_ok=True)
    os.makedirs(os.path.dirname(ASIGNACIONES_XML), exist_ok=True)
    # Inicia
    app.run(host="127.0.0.1", port=5000, debug=False)


    
#FIN DE COBRO DE CAJA#







@app.route('/_debug_routes')
def _debug_routes():
    # lista todas las rutas registradas en este proceso
    return '<br>'.join(sorted(rule.rule for rule in app.url_map.iter_rules()))


#crear figuras #




# ─────────────────────────────────────────────────────────────
# FIGURAS · Crear, editar y listar (BINGO americano)
# ORDEN requerido (por FILAS, arriba→abajo):
#   Fila1: B1 I1 N1 G1 O1
#   Fila2: B2 I2 N2 G2 O2
#   ...
#   Fila5: B5 I5 N5 G5 O5
#
# XML: static/db/datos_figuras.xml  (guarda color + pos="B1"...)
# Rutas:
#   /figuras/crear        (crear/editar figuras)
#   /crear-figuras        (alias)
#   /escoger-figuras      (selector con tablero)
#   /figuras/seleccion    (POST opcional desde selector)
#   /api/figuras/orden    (diagnóstico del orden vigente)
# ─────────────────────────────────────────────────────────────
import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from flask import (
    render_template, request, redirect, url_for, flash, session,
    current_app, jsonify
)

# Si tu app ya tiene "app", exponemos current_app en templates
if "app" in globals():
    @app.context_processor
    def inject_current_app():
        return dict(current_app=current_app)

# Rutas absolutas
try:
    BASE_DIR
except NameError:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FIGURAS_XML = globals().get("DATOS_FIGURAS_XML") or os.path.join(globals().get("DATA_DIR", BASE_DIR), "static", "db", "datos_figuras.xml")
os.makedirs(os.path.dirname(FIGURAS_XML), exist_ok=True)

# ============ ORDENES ============
def row_order():
    """
    Orden NUEVO por FILAS (lo que pides):
    B1 I1 N1 G1 O1, B2 I2 N2 G2 O2, …, B5 I5 N5 G5 O5
    """
    letters = ["B", "I", "N", "G", "O"]
    out = []
    for r in range(1, 6):          # filas 1..5
        for L in letters:          # columnas B I N G O
            out.append(f"{L}{r}")
    return out                     # 25

def legacy_column_order():
    """
    Orden anterior por COLUMNAS (lo que NO quieres):
    B1 B2 B3 B4 B5, I1 I2 …, N1 N2 …, G1 …, O1 …
    """
    out = []
    for L in ["B", "I", "N", "G", "O"]:
        for r in range(1, 6):
            out.append(f"{L}{r}")
    return out

NEW_ORDER = row_order()
OLD_ORDER = legacy_column_order()

# ============ XML helpers ============
def _write_empty_figuras():
    root = ET.Element("figuras")
    ET.ElementTree(root).write(FIGURAS_XML, encoding="utf-8", xml_declaration=True)
    _mirror_db_to_public(FIGURAS_XML)

def _ensure_figuras_root():
    if not os.path.exists(FIGURAS_XML):
        _write_empty_figuras()
        return
    try:
        ET.parse(FIGURAS_XML)
    except ET.ParseError:
        _write_empty_figuras()

def _load_tree():
    _ensure_figuras_root()
    return ET.parse(FIGURAS_XML)

def _find_figura(root, nombre_busqueda: str):
    nb = (nombre_busqueda or "").strip().lower()
    for f in root.findall("figura"):
        if f.attrib.get("nombre","").strip().lower() == nb:
            return f
    return None

def _celda_map_by_pos(fig_nodo):
    """Devuelve dict {pos: color} para una figura (pos= B1..O5)."""
    d = {}
    for cel in fig_nodo.findall("celda"):
        pos = (cel.attrib.get("pos") or "").strip()
        col = (cel.attrib.get("color") or "#FFFFFF").strip().upper()
        if pos:
            d[pos] = col
    return d

def _figure_pos_sequence(fig_nodo):
    """Secuencia de pos tal como está en el XML (idx 1..25)."""
    seq = []
    for i in range(1, 26):
        cel = fig_nodo.find(f'celda[@idx="{i}"]')
        seq.append(None if cel is None else (cel.attrib.get("pos") or "").strip())
    return seq

def _needs_migration(fig_nodo):
    """Detecta si la figura quedó guardada en el orden viejo por columnas."""
    seq = _figure_pos_sequence(fig_nodo)
    # comparar suficiente prefijo para no fallar con figuras cortas
    return seq[:10] == OLD_ORDER[:10]

def _rewrite_celdas(fig_nodo, pos_to_color, new_order):
    """Reescribe celdas con new_order; fuerza N3 en blanco."""
    # Limpiar celdas actuales
    for cel in list(fig_nodo.findall("celda")):
        fig_nodo.remove(cel)
    # Forzar centro libre
    pos_to_color = dict(pos_to_color)
    pos_to_color["N3"] = "#FFFFFF"
    # Escribir con nuevo orden (idx 1..25)
    for idx, pos in enumerate(new_order, start=1):
        ET.SubElement(fig_nodo, "celda", {
            "idx": str(idx),
            "color": (pos_to_color.get(pos, "#FFFFFF") or "#FFFFFF").upper(),
            "pos": pos
        })

def migrate_figuras_xml_to_row_order():
    """
    Migra figuras desde el orden por COLUMNAS al orden por FILAS.
    Mantiene colores; N3 queda blanco.
    """
    tree = _load_tree()
    root = tree.getroot()
    changed = False
    for fig in root.findall("figura"):
        if _needs_migration(fig):
            mapping = _celda_map_by_pos(fig)
            _rewrite_celdas(fig, mapping, NEW_ORDER)
            changed = True
    if changed:
        try:
            ET.indent(tree, space="  ", level=0)
        except Exception:
            pass
        tree.write(FIGURAS_XML, encoding="utf-8", xml_declaration=True)
    _mirror_db_to_public(FIGURAS_XML)

# Ejecutar migración al importar el módulo
try:
    migrate_figuras_xml_to_row_order()
except Exception as _e:
    print("[WARN] Migración de figuras no aplicada:", _e)

# ============ Persistencia ============
def guardar_figura_en_xml(nombre, celdas_hex, descripcion="", pos_codes=None):
    """
    Guarda (crea/reemplaza) una figura:
      - celdas_hex: lista de 25 colores "#RRGGBB"
      - pos_codes : lista de 25 códigos pos (B1..O5). Si NO viene, usamos NEW_ORDER (por FILAS).
      - N3 SIEMPRE en blanco.
    """
    if len(celdas_hex) != 25:
        raise ValueError("La cuadrícula debe tener 25 celdas.")

    tree = _load_tree()
    root = tree.getroot()

    existente = _find_figura(root, nombre)
    if existente is not None:
        root.remove(existente)

    pos = list(pos_codes) if (pos_codes and len(pos_codes) == 25) else NEW_ORDER[:]
    colores = [str(c or "").strip().upper() for c in celdas_hex]

    # Centro gratis N3 blanco
    try:
        n3_idx = pos.index("N3")
        colores[n3_idx] = "#FFFFFF"
    except ValueError:
        pass

    nodo = ET.SubElement(root, "figura", {
        "nombre": (nombre or "").strip(),
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "centro_bloqueado": "1"
    })

    if (descripcion or "").strip():
        ET.SubElement(nodo, "descripcion").text = descripcion.strip()

    for i, color in enumerate(colores, start=1):
        ET.SubElement(nodo, "celda", {
            "idx": str(i),
            "color": color,
            "pos": pos[i-1]
        })

    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(FIGURAS_XML, encoding="utf-8", xml_declaration=True)
    _mirror_db_to_public(FIGURAS_XML)

def cargar_figura_por_nombre(nombre: str):
    tree = _load_tree()
    root = tree.getroot()
    nodo = _find_figura(root, nombre)
    if nodo is None:
        return None

    desc = ""
    nd = nodo.find("descripcion")
    if nd is not None and (nd.text or "").strip():
        desc = nd.text.strip()

    colores, pos = [], []
    for i in range(1, 26):
        cel = nodo.find(f'celda[@idx="{i}"]')
        if cel is None:
            colores.append("#FFFFFF")
            pos.append(NEW_ORDER[i-1])
        else:
            colores.append((cel.attrib.get("color") or "#FFFFFF").upper())
            pos.append(cel.attrib.get("pos", NEW_ORDER[i-1]))

    # N3 blanco
    try:
        n3_idx = pos.index("N3")
        colores[n3_idx] = "#FFFFFF"
    except ValueError:
        pass

    return {
        "nombre": nodo.attrib.get("nombre",""),
        "fecha": nodo.attrib.get("fecha",""),
        "centro_bloqueado": True,
        "descripcion": desc,
        "colores": colores,
        "pos": pos
    }

def cargar_todas_figuras():
    tree = _load_tree()
    root = tree.getroot()
    figs = []
    for f in root.findall("figura"):
        nombre = f.attrib.get("nombre","")
        fecha = f.attrib.get("fecha","")
        desc = ""
        nd = f.find("descripcion")
        if nd is not None and (nd.text or "").strip():
            desc = nd.text.strip()

        colores, pos = [], []
        for i in range(1, 26):
            cel = f.find(f'celda[@idx="{i}"]')
            if cel is None:
                colores.append("#FFFFFF")
                pos.append(NEW_ORDER[i-1])
            else:
                colores.append((cel.attrib.get("color") or "#FFFFFF").upper())
                pos.append(cel.attrib.get("pos", NEW_ORDER[i-1]))

        # N3 blanco
        try:
            n3_idx = pos.index("N3")
            colores[n3_idx] = "#FFFFFF"
        except ValueError:
            pass

        figs.append({
            "nombre": nombre,
            "fecha": fecha,
            "descripcion": desc,
            "colores": colores,
            "pos": pos
        })

    figs.sort(key=lambda x: x["nombre"].lower())
    return figs

# ============ Rutas (Flask) ============
@app.route("/figuras/crear", methods=["GET", "POST"])
def figuras_crear():
    # Protege si hay login en tu app
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(_login_url())

    figura_cargada = None
    nombre_cargar = (request.args.get("nombre") or "").strip()
    if nombre_cargar:
        figura_cargada = cargar_figura_por_nombre(nombre_cargar)

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = (request.form.get("descripcion") or "").strip()
        grid_raw = (request.form.get("grid") or "").strip()      # "25 colores separados por coma"
        pos_raw  = (request.form.get("grid_pos") or "").strip()  # opcional, 25 POS separados por coma

        colores = [c.strip().upper() for c in grid_raw.split(",") if c.strip()]
        pos_codes = [p.strip() for p in pos_raw.split(",") if p.strip()] if pos_raw else None

        if not nombre:
            flash("El nombre de la figura es obligatorio.", "warning")
            return redirect(url_for("figuras_crear", nombre=nombre))

        if len(colores) != 25:
            flash("La cuadrícula enviada es inválida (deben ser 25 celdas).", "danger")
            return redirect(url_for("figuras_crear", nombre=nombre))

        if pos_codes is not None and len(pos_codes) != 25:
            flash("grid_pos inválido. Debe traer 25 posiciones (B1..O5).", "danger")
            return redirect(url_for("figuras_crear", nombre=nombre))

        try:
            guardar_figura_en_xml(nombre, colores, descripcion, pos_codes)
            flash(f"Figura '{nombre}' guardada correctamente.", "success")
            return redirect(url_for("figuras_crear", nombre=nombre))
        except Exception as e:
            flash(f"Error al guardar la figura: {e}", "danger")
            return redirect(url_for("figuras_crear"))

    return render_template("figuras_crear.html", figura=figura_cargada)

@app.route("/crear-figuras", methods=["GET", "POST"])
def crear_figuras_alias():
    return figuras_crear()

@app.route("/escoger-figuras-legacy", methods=["GET"])
def escoger_figuras():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(_login_url())
    try:
        return redirect(url_for("escoger_figuras_view", **request.args.to_dict(flat=True)))
    except Exception:
        return render_template("escoger_figuras.html")

@app.route("/figuras/seleccion", methods=["POST"])
def figuras_seleccion():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(_login_url())
    raw = request.form.get("seleccion","")
    seleccion = []
    if raw:
        try:
            seleccion = json.loads(raw)
            if not isinstance(seleccion, list):
                seleccion = []
        except Exception:
            seleccion = [s.strip() for s in raw.split(",") if s.strip()]
    session["seleccion_figuras"] = seleccion
    flash(f"Seleccionadas: {', '.join(seleccion) if seleccion else 'ninguna'}", "success")
    return redirect(url_for("escoger_figuras"))

@app.get("/api/figuras/orden")
def api_figuras_orden():
    """Para que el front valide rápidamente el orden del backend."""
    return jsonify({
        "order": NEW_ORDER,              # B1 I1 N1 G1 O1, B2 I2 ...
        "legacy_column_order": OLD_ORDER # B1 B2 B3 B4 B5, I1 I2 ...
    })





# ─────────────────────────────────────────────────────────────
# ESCOGER FIGURAS POR FECHA (con VALOR por figura)
# Archivo: static/db/figuras_por_fecha.xml
# Rutas:
#   GET  /escoger-figuras
#   POST /escoger-figuras/guardar
#   GET  /api/figuras-por-fecha
# ─────────────────────────────────────────────────────────────
import os, re, json, xml.etree.ElementTree as ET
from flask import render_template, request, redirect, url_for, flash, session, current_app, jsonify

FIGURAS_FECHA_XML = globals().get("FIGURAS_FECHA_XML") or os.path.join(globals().get("DATA_DIR", BASE_DIR), "static", "db", "figuras_por_fecha.xml")
os.makedirs(os.path.dirname(FIGURAS_FECHA_XML), exist_ok=True)

def _ensure_agenda_root():
    if not os.path.exists(FIGURAS_FECHA_XML):
        ET.ElementTree(ET.Element("agenda")).write(FIGURAS_FECHA_XML, encoding="utf-8", xml_declaration=True)
        _mirror_db_to_public(FIGURAS_FECHA_XML)
        return
    try:
        ET.parse(FIGURAS_FECHA_XML)
    except ET.ParseError:
        ET.ElementTree(ET.Element("agenda")).write(FIGURAS_FECHA_XML, encoding="utf-8", xml_declaration=True)
        _mirror_db_to_public(FIGURAS_FECHA_XML)

def _load_agenda_tree():
    _ensure_agenda_root()
    return ET.parse(FIGURAS_FECHA_XML)

def _find_dia(root, fecha_iso: str):
    for d in root.findall("dia"):
        if d.attrib.get("fecha") == fecha_iso:
            return d
    return None

def _is_fecha_iso(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (s or "").strip()))

def _norm_items(items):
    """
    items puede venir como:
      ["LLENA 1","PIRAMIDE 5"]  o  [{"nombre":"LLENA 1","valor":2.5}, ...]
    Devuelve lista normalizada: [{"nombre":str, "valor":float>=0}, ...] sin duplicados.
    """
    clean, seen = [], set()
    for x in (items or []):
        if isinstance(x, dict):
            nombre = str(x.get("nombre","")).strip()
            valor = x.get("valor", 0)
        else:
            nombre = str(x).strip()
            valor = 0
        if not nombre:
            continue
        key = nombre.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            v = float(valor)
        except Exception:
            v = 0.0
        if v < 0:
            v = 0.0
        clean.append({"nombre": nombre, "valor": round(v, 2)})
    return clean

def guardar_figuras_para_fecha(fecha_iso: str, items):
    if not _is_fecha_iso(fecha_iso):
        raise ValueError("Fecha inválida. Usa YYYY-MM-DD.")
    lista = _norm_items(items)

    tree = _load_agenda_tree()
    root = tree.getroot()
    dia = _find_dia(root, fecha_iso)
    if dia is not None:
        root.remove(dia)

    dia = ET.SubElement(root, "dia", {"fecha": fecha_iso})
    for it in lista:
        ET.SubElement(dia, "fig", {
            "nombre": it["nombre"],
            "valor": f'{it["valor"]:.2f}'
        })
    tree.write(FIGURAS_FECHA_XML, encoding="utf-8", xml_declaration=True)
    _mirror_db_to_public(FIGURAS_FECHA_XML)

def cargar_figuras_de_fecha(fecha_iso: str):
    """
    Devuelve lista de objetos: [{"nombre":"X","valor":2.5}, ...]
    (Si en XML no hay 'valor', devuelve 0.0)
    """
    if not _is_fecha_iso(fecha_iso):
        return []
    tree = _load_agenda_tree()
    root = tree.getroot()
    dia = _find_dia(root, fecha_iso)
    if dia is None:
        return []
    out = []
    for f in dia.findall("fig"):
        nombre = (f.attrib.get("nombre","") or "").strip()
        try:
            valor = float(f.attrib.get("valor","0") or 0)
        except Exception:
            valor = 0.0
        out.append({"nombre": nombre, "valor": round(max(valor, 0.0), 2)})
    return out

# ---------- RUTAS ----------

# Vista (solo GET)
@app.route("/escoger-figuras", methods=["GET"])
def escoger_figuras_view():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(_login_url())
    fecha_q = (request.args.get("fecha") or "").strip()
    preseleccion = cargar_figuras_de_fecha(fecha_q) if fecha_q else []
    return render_template("escoger_figuras.html",
                           fecha_inicial=fecha_q,
                           preseleccion=preseleccion)

# Guardar (solo POST)
@app.route("/escoger-figuras/guardar", methods=["POST"])
def escoger_figuras_guardar():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(_login_url())

    fecha = (request.form.get("fecha") or "").strip()
    raw   = (request.form.get("seleccion") or "").strip()

    items = []
    if raw:
        try:
            data = json.loads(raw)
            # data puede ser lista de strings o de objetos
            if isinstance(data, list):
                items = data
        except Exception:
            # compat: CSV -> solo nombres
            items = [s.strip() for s in raw.split(",") if s.strip()]

    try:
        guardar_figuras_para_fecha(fecha, items)
        flash(f"Figuras guardadas para {fecha}.", "success")
    except Exception as e:
        flash(f"Error al guardar: {e}", "danger")

    return redirect(url_for("escoger_figuras_view", fecha=fecha))

# API auxiliar (GET)
@app.route("/api/figuras-por-fecha", methods=["GET"])
def api_figuras_por_fecha():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    fecha = (request.args.get("fecha") or "").strip()
    lista = cargar_figuras_de_fecha(fecha) if _is_fecha_iso(fecha) else []
    return jsonify({"ok": True, "fecha": fecha, "figuras": lista})

# -*- coding: utf-8 -*-







#BOLETIN#


import os, re, json, math, unicodedata, xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

# ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader  # tamaño real del logo

# ------------------ App ------------------
try:
    app  # noqa: F821
except NameError:

    app.secret_key = "dev"

# ------------------ Ajustes visuales ------------------
FIG_BLOCK_SCALE       = 0.99  # escala global de las figuras
FIG_FIXED_COLS        = 8     # columnas por fila para figuras (auto si None)
LOGO_SCALE_DEFAULT    = 1.30  # escala del logo (1.0 = normal)

# ------------------ Paths ------------------
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR   = globals().get("DATA_DIR") or os.path.join(BASE_DIR, "DATA")
DB_DIR     = globals().get("DB_DIR_PERSIST") or os.path.join(DATA_DIR, "static", "db")
IMG_DIR    = os.path.join(STATIC_DIR, "img")
FONTS_DIR  = os.path.join(STATIC_DIR, "fonts")
LOGS_DIR   = globals().get("LOGS_DIR") or os.path.join(DATA_DIR, "static", "LOGS")

for p in (DB_DIR, IMG_DIR, FONTS_DIR, LOGS_DIR):
    os.makedirs(p, exist_ok=True)

# XMLs base
FIGURAS_FECHA_XML  = globals().get("FIGURAS_FECHA_XML", os.path.join(DB_DIR, "figuras_por_fecha.xml"))
DATOS_FIGURAS_XML  = globals().get("DATOS_FIGURAS_XML", os.path.join(DB_DIR, "datos_figuras.xml"))
RESULTADOS_XML     = globals().get("RESULTADOS_SORTEO_XML", os.path.join(DB_DIR, "resultados_sorteo.xml"))

# Layout JSON (diseñador)
LAYOUT_JSON = globals().get("BOLETIN_LAYOUT_JSON", _persist("static", "db", "boletin_layout.json"))

# ------------------ Helpers ------------------
def _is_fecha_iso(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (s or "").strip()))

def _money(v):
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return "$0.00"

def _money_header(v):
    try:
        return f"${int(round(float(v))):,}".replace(",", ",")
    except Exception:
        return "$0"

def _safe_text(s, font_name):
    s = "" if s is None else str(s)
    if font_name != "Helvetica":
        return s
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

def _es_largo(fecha_iso: str) -> str:
    meses = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    dias  = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    d = datetime.fromisoformat(fecha_iso).date()
    return f"{dias[d.weekday()].upper()}, {d.day} DE {meses[d.month-1].upper()} DE {d.year}"

def _es_corta(fecha_iso: str) -> str:
    meses = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    dias  = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    d = datetime.fromisoformat(fecha_iso).date()
    return f"{dias[d.weekday()]}, {d.day} de {meses[d.month-1]} de {d.year}"

def _ensure_xml(path, root_name):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ET.ElementTree(ET.Element(root_name)).write(path, encoding="utf-8", xml_declaration=True)
        return
    try:
        ET.parse(path)
    except ET.ParseError:
        ET.ElementTree(ET.Element(root_name)).write(path, encoding="utf-8", xml_declaration=True)

# ------------------ Agenda / Figuras por fecha ------------------
def _figuras_de_fecha(fecha_iso):
    if not _is_fecha_iso(fecha_iso):
        return []
    _ensure_xml(FIGURAS_FECHA_XML, "agenda")
    root = ET.parse(FIGURAS_FECHA_XML).getroot()
    for d in root.findall("dia"):
        if d.attrib.get("fecha") == fecha_iso:
            out = []
            for f in d.findall("fig"):
                nom = (f.attrib.get("nombre") or "").strip()
                try:
                    val = float(f.attrib.get("valor") or 0.0)
                except Exception:
                    val = 0.0
                if nom:
                    out.append({"nombre": nom, "valor": val})
            return out
    return []


def _siguiente_fecha_con_figuras(fecha_base_iso: str) -> str:
    """
    Devuelve la siguiente fecha REAL programada en figuras_por_fecha.xml.
    Si no existe una fecha posterior, mantiene compatibilidad devolviendo
    el día calendario siguiente a fecha_base_iso.
    """
    base = (fecha_base_iso or "").strip()
    if not _is_fecha_iso(base):
        base = date.today().isoformat()

    try:
        base_date = datetime.fromisoformat(base).date()
    except Exception:
        base_date = date.today()
        base = base_date.isoformat()

    candidatas = []
    try:
        _ensure_xml(FIGURAS_FECHA_XML, "agenda")
        root = ET.parse(FIGURAS_FECHA_XML).getroot()
        for d in root.findall("dia"):
            fecha_txt = (d.attrib.get("fecha") or "").strip()
            if not _is_fecha_iso(fecha_txt):
                continue
            try:
                fecha_d = datetime.fromisoformat(fecha_txt).date()
            except Exception:
                continue
            if fecha_d > base_date:
                candidatas.append(fecha_d)
    except Exception:
        candidatas = []

    if candidatas:
        return min(candidatas).isoformat()

    return (base_date + timedelta(days=1)).isoformat()

# ------------------ Formas 5x5 ------------------
def _load_shapes():
    shapes = {}
    if not os.path.exists(DATOS_FIGURAS_XML):
        return shapes
    try:
        root = ET.parse(DATOS_FIGURAS_XML).getroot()
    except ET.ParseError:
        return shapes
    for n in root.findall("figura"):
        nombre = (n.attrib.get("nombre", "") or "").strip()
        if not nombre:
            continue
        arr = [False] * 25
        for i in range(1, 26):
            cel = n.find(f'celda[@idx="{i}"]')
            if cel is not None:
                col = (cel.attrib.get("color", "#FFFFFF") or "").upper()
                arr[i - 1] = (col == "#FF0000")
        arr[12] = False  # centro libre
        shapes[nombre.strip().lower()] = arr
    return shapes

# ------------------ Resultados (XML) ------------------
# ===================== BOLETÍN: RUTAS ROBUSTAS (LOCAL/RENDER) =====================
# Objetivo:
#  - Guardar/leer resultados SIEMPRE desde una ruta consistente
#  - Escribir en DATA_DIR/static/db (persistente) y también "espejar" en BASE_DIR/static/db (para que lo veas en tu carpeta)
#  - Si no existe día en resultados_sorteo.xml, devolver estructura basada en figuras programadas (no deja el PDF en blanco)

def _boletin_data_dir():
    base = os.environ.get("DATA_DIR")
    if base:
        return base
    # Render suele montar /data; en local usamos ./DATA
    return "/data" if os.path.isdir("/data") else os.path.join(BASE_DIR, "DATA")

def _boletin_db_dirs():
    data_dir = _boletin_data_dir()
    db_persist = os.path.join(data_dir, "static", "db")
    db_public  = os.path.join(BASE_DIR, "static", "db")
    return db_persist, db_public

def _boletin_resultados_paths():
    db_persist, db_public = _boletin_db_dirs()
    return os.path.join(db_persist, "resultados_sorteo.xml"), os.path.join(db_public, "resultados_sorteo.xml")

def _boletin_pick_resultados_xml():
    p, pub = _boletin_resultados_paths()
    # Si existe el persistente y tiene contenido, úsalo
    try:
        if os.path.exists(p) and os.path.getsize(p) > 50:
            return p
    except Exception:
        pass
    # Si no, usa el público
    return pub

def _boletin_seed_resultados():
    p, pub = _boletin_resultados_paths()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.makedirs(os.path.dirname(pub), exist_ok=True)
        # si no existe persistente, copia desde public si existe
        if (not os.path.exists(p)) and os.path.exists(pub):
            shutil.copy2(pub, p)
    except Exception:
        pass

def _boletin_write_resultados_xml(xml_bytes: bytes):
    p, pub = _boletin_resultados_paths()
    for dst in (p, pub):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(xml_bytes)
        except Exception:
            pass

# Asegura que exista al menos el archivo base
try:
    _boletin_seed_resultados()
except Exception:
    pass

def _cargar_resultados(fecha_iso):
    # Siempre devolver estructura (para que el PDF no salga vacío)
    data = {"items": [], "extras": {"comodin": {}, "gran_bonus": {}}}
    if not _is_fecha_iso(fecha_iso):
        return data

    # 1) Base: figuras programadas del día (aunque no haya ganadores todavía)
    try:
        agenda_hoy = _figuras_de_fecha(fecha_iso) or []
        # Mantener orden de agenda
        for f in agenda_hoy:
            nom = (f.get("nombre") or f.get("figura") or "").strip()
            if nom:
                data["items"].append({"figura": nom, "ganadores": []})
    except Exception:
        agenda_hoy = []

    # 2) Leer resultados guardados (si existen)
    try:
        _boletin_seed_resultados()
        path = _boletin_pick_resultados_xml()
        _ensure_xml(path, "resultados")
        root = ET.parse(path).getroot()
        dia = None
        for d in root.findall("dia"):
            if d.attrib.get("fecha") == fecha_iso:
                dia = d
                break

        # Si existe el día, mezclar ganadores/extras
        if dia is not None:
            # Mapa para reemplazar ganadores en la agenda
            idx_map = { (it.get("figura") or "").strip().lower(): i for i, it in enumerate(data["items"]) }
            for f in dia.findall("fig"):
                nom = (f.attrib.get("nombre", "") or "").strip()
                if not nom:
                    continue
                gs = []
                for g in f.findall("ganador"):
                    try:
                        prem = float(g.attrib.get("premio") or 0.0)
                    except Exception:
                        prem = 0.0
                    gs.append({
                        "boleto": g.attrib.get("boleto", ""),
                        "nombre": g.attrib.get("nombre", ""),
                        "vendedor": g.attrib.get("vendedor", ""),
                        "sector": g.attrib.get("sector", ""),
                        "premio": prem
                    })
                key = nom.lower()
                if key in idx_map:
                    data["items"][idx_map[key]]["ganadores"] = gs
                else:
                    data["items"].append({"figura": nom, "ganadores": gs})

            com = dia.find("comodin")
            if com is not None:
                data["extras"]["comodin"] = {
                    "boletos": com.attrib.get("boletos", ""),
                    "texto": com.attrib.get("texto", "")
                }
            bon = dia.find("granbonus")
            if bon is not None:
                nums = [n.strip() for n in (bon.attrib.get("numeros", "")).split(",") if n.strip()]
                data["extras"]["gran_bonus"] = {
                    "numeros": nums,
                    "texto": bon.attrib.get("texto", "")
                }
    except Exception:
        pass

    # 3) Mezclar ganadores detectados del juego (ganadores.json) si existen y aún no están
    try:
        # GANADORES_JSON suele estar en DB_DIR; si existe esta variable, úsala
        gj_path = None
        try:
            gj_path = GANADORES_JSON
        except Exception:
            pass
        if gj_path and os.path.exists(gj_path):
            gj = _safe_json_read(gj_path) or {}
            stack = gj.get(str(fecha_iso)) or []
            if isinstance(stack, list) and stack:
                idx_map = { (it.get("figura") or "").strip().lower(): i for i, it in enumerate(data["items"]) }
                for w in stack:
                    fig = (w.get("figura") or w.get("nombre_figura") or "").strip()
                    if not fig:
                        continue
                    key = fig.lower()
                    if key not in idx_map:
                        data["items"].append({"figura": fig, "ganadores": []})
                        idx_map[key] = len(data["items"]) - 1
                    # Si el detector ya trae tabla/boleto/vendedor/planilla, lo dejamos como texto si no existe en XML
                    # Nota: esto NO reemplaza lo que guardaste manualmente; solo llena si está vacío
                    if not data["items"][idx_map[key]]["ganadores"]:
                        # Crear entrada mínima para que el PDF muestre algo
                        b = str(w.get("boleto") or w.get("tabla") or "").strip()
                        vend = str(w.get("vendedor") or "").strip()
                        pl = str(w.get("planilla") or w.get("rango") or w.get("sector") or "").strip()
                        data["items"][idx_map[key]]["ganadores"] = [{
                            "boleto": b,
                            "nombre": str(w.get("nota") or w.get("nombre") or "").strip(),
                            "vendedor": vend,
                            "sector": pl,
                            "premio": float(w.get("premio") or 0.0) if str(w.get("premio") or "").strip() else 0.0
                        }]
    except Exception:
        pass

    return data

    for f in dia.findall("fig"):
        nom = f.attrib.get("nombre", "")
        gs = []
        for g in f.findall("ganador"):
            try:
                prem = float(g.attrib.get("premio") or 0.0)
            except Exception:
                prem = 0.0
            gs.append({
                "boleto": g.attrib.get("boleto", ""),
                "nombre": g.attrib.get("nombre", ""),
                "vendedor": g.attrib.get("vendedor", ""),
                "sector": g.attrib.get("sector", ""),
                "premio": prem
            })
        data["items"].append({"figura": nom, "ganadores": gs})

    com = dia.find("comodin")
    if com is not None:
        data["extras"]["comodin"] = {
            "boletos": com.attrib.get("boletos", ""),
            "texto": com.attrib.get("texto", "")
        }
    bon = dia.find("granbonus")
    if bon is not None:
        nums = [n.strip() for n in (bon.attrib.get("numeros", "")).split(",") if n.strip()]
        data["extras"]["gran_bonus"] = {
            "numeros": nums,
            "texto": bon.attrib.get("texto", "")
        }
    return data

def _guardar_resultados(fecha_iso, resultados, extras=None):
    if not _is_fecha_iso(fecha_iso):
        raise ValueError("Fecha inválida")

    _boletin_seed_resultados()
    path = _boletin_pick_resultados_xml()

    _ensure_xml(path, "resultados")
    tree = ET.parse(path)
    root = tree.getroot()

    # reemplazar el día completo para esa fecha
    for d in root.findall("dia"):
        if d.attrib.get("fecha") == fecha_iso:
            root.remove(d)
            break

    dia = ET.SubElement(root, "dia", {"fecha": fecha_iso})

    for item in (resultados or []):
        nom = (item.get("figura") or "").strip()
        if not nom:
            continue
        fig = ET.SubElement(dia, "fig", {"nombre": nom})
        for g in (item.get("ganadores") or []):
            try:
                prem = float(g.get("premio") or 0.0)
            except Exception:
                prem = 0.0
            ET.SubElement(fig, "ganador", {
                "boleto": (g.get("boleto") or "").strip(),
                "nombre": (g.get("nombre") or "").strip(),
                "vendedor": (g.get("vendedor") or "").strip(),
                "sector": (g.get("sector") or "").strip(),
                "premio": f"{prem:.2f}"
            })

    if extras:
        com = extras.get("comodin") or {}
        bon = extras.get("gran_bonus") or {}
        if com:
            ET.SubElement(dia, "comodin", {
                "boletos": (com.get("boletos") or "").strip(),
                "texto": (com.get("texto") or "").strip()
            })
        if bon:
            nums = bon.get("numeros")
            if isinstance(nums, (list, tuple)):
                nums = ",".join(str(x) for x in nums)
            ET.SubElement(dia, "granbonus", {
                "numeros": (nums or "").strip(),
                "texto": (bon.get("texto") or "").strip()
            })

    # escribir y espejar en ambas rutas (persistente + static/db)
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    _boletin_write_resultados_xml(xml_bytes)

def _sync_resultados_from_juego(fecha_iso, ganadores):
    """
    Mantiene resultados_sorteo.xml sincronizado con los ganadores reales del juego.
    Esto hace que Boletín y Pago de Premios lean la misma base, sin perder los extras
    (comodín / gran bonus) y conservando nombres manuales si ya existían.
    """
    try:
        if not _is_fecha_iso(fecha_iso):
            return False

        actual = _cargar_resultados(fecha_iso) or {"items": [], "extras": {"comodin": {}, "gran_bonus": {}}}
        items_actuales = list(actual.get("items") or [])
        extras = dict(actual.get("extras") or {})

        prev_map = {}
        for item in items_actuales:
            figura = str(item.get("figura") or "").strip()
            if not figura:
                continue
            fkey = figura.lower()
            for g in (item.get("ganadores") or []):
                boleto = _norm_tabla_id(g.get("boleto") or "")
                if not boleto:
                    continue
                prev_map[(fkey, boleto)] = {
                    "nombre": str(g.get("nombre") or "").strip(),
                    "vendedor": str(g.get("vendedor") or "").strip(),
                    "sector": str(g.get("sector") or "").strip(),
                    "premio": _safe_float(g.get("premio"))
                }

        grouped = defaultdict(list)
        order = []
        seen = set()
        for w in (ganadores or []):
            if not isinstance(w, dict):
                continue
            figura = str(w.get("figura") or w.get("nombre_figura") or "").strip()
            if not figura:
                continue
            fkey = figura.lower()
            if fkey not in seen:
                seen.add(fkey)
                order.append(figura)

            boleto = _norm_tabla_id(w.get("boleto") or w.get("tabla") or "")
            prev = prev_map.get((fkey, boleto), {}) if boleto else {}

            premio_raw = w.get("premio")
            if premio_raw in (None, ""):
                premio_raw = w.get("valor")

            grouped[fkey].append({
                "boleto": boleto,
                "nombre": str(prev.get("nombre") or w.get("nombre") or w.get("nota") or "").strip(),
                "vendedor": str(w.get("vendedor") or prev.get("vendedor") or "").strip(),
                "sector": str(w.get("sector") or w.get("planilla") or w.get("rango") or prev.get("sector") or "").strip(),
                "premio": _safe_float(premio_raw)
            })

        nuevos_items = []
        usados = set()
        for item in items_actuales:
            figura = str(item.get("figura") or "").strip()
            if not figura:
                continue
            fkey = figura.lower()
            nuevos_items.append({"figura": figura, "ganadores": grouped.get(fkey, [])})
            usados.add(fkey)

        for figura in order:
            fkey = figura.lower()
            if fkey in usados:
                continue
            nuevos_items.append({"figura": figura, "ganadores": grouped.get(fkey, [])})

        _guardar_resultados(fecha_iso, nuevos_items, extras)
        return True
    except Exception:
        return False

def _resultado_meta_para_ganador(fecha_iso, figura, boleto):
    """
    Resuelve metadatos editables del ganador (nombre/premio) y de planilla
    (vendedor/sector) para mantener UI + XML de vMix en concordancia.
    """
    figura_s = str(figura or "").strip()
    boleto_s = _norm_tabla_id(boleto or "")
    meta = {
        "nombre": "",
        "premio": 0.0,
        "vendedor": "",
        "sector": "",
    }

    try:
        actual = _cargar_resultados(fecha_iso) or {"items": []}
        for item in (actual.get("items") or []):
            if str(item.get("figura") or "").strip().lower() != figura_s.lower():
                continue
            for g in (item.get("ganadores") or []):
                if _norm_tabla_id(g.get("boleto") or "") != boleto_s:
                    continue
                meta["nombre"] = str(g.get("nombre") or "").strip()
                meta["premio"] = _safe_float(g.get("premio"), 0.0)
                meta["vendedor"] = str(g.get("vendedor") or "").strip()
                meta["sector"] = str(g.get("sector") or "").strip()
                raise StopIteration
    except StopIteration:
        pass
    except Exception:
        pass

    try:
        info = buscar_info_por_boleto(fecha_iso, boleto_s) or {}
    except Exception:
        info = {}

    if not str(meta.get("vendedor") or "").strip():
        meta["vendedor"] = str(info.get("vendedor") or "").strip()
    if not str(meta.get("sector") or "").strip():
        meta["sector"] = str(info.get("planilla") or info.get("rango") or info.get("sector") or "").strip()

    meta["boleto"] = boleto_s
    meta["figura"] = figura_s
    return meta

# ------------------ Reintegro desde LOGS ------------------
def _find_image_case_insensitive(dirs, filename):
    base = (filename or "").strip()
    if not base:
        return None
    cands = [base]
    if "." not in base:
        cands += [base + ext for ext in (".png",".jpg",".jpeg",".webp",".gif")]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            files = os.listdir(d)
        except Exception:
            files = []
        lowers = [f.lower() for f in files]
        for cand in cands:
            if cand.lower() in lowers:
                return os.path.join(d, files[lowers.index(cand.lower())])
        bases = {os.path.splitext(f)[0].lower(): f for f in files}
        key = os.path.splitext(base)[0].lower()
        if key in bases:
            return os.path.join(d, bases[key])
    return None

def _reintegro_from_log_for_date(fecha_iso):
    log_path = os.path.join(LOGS_DIR, "impresiones.xml")
    if not os.path.exists(log_path):
        for alt in (os.path.join(DB_DIR, "impresiones.xml"), os.path.join(BASE_DIR, "impresiones.xml")):
            if os.path.exists(alt):
                log_path = alt
                break
        else:
            return {"archivo": None, "imagen": None, "cantidad": None, "fecha": None}

    try:
        root = ET.parse(log_path).getroot()
    except ET.ParseError:
        return {"archivo": None, "imagen": None, "cantidad": None, "fecha": None}

    records = []
    for imp in root.findall("impresion"):
        fs = (imp.findtext("fecha_sorteo") or imp.findtext("fecha") or "").strip()
        rein = (imp.findtext("reintegro_especial") or imp.findtext("reintegro") or "").strip()
        cant = (imp.findtext("cantidad_reintegro_especial") or imp.findtext("cant_reintegro_especial") or "").strip()
        if rein:
            records.append((fs, rein, cant))

    chosen = None
    for item in reversed(records):
        if _is_fecha_iso(fecha_iso) and item[0] == fecha_iso:
            chosen = item
            break
    if chosen is None and records:
        chosen = records[-1]

    if chosen is None:
        return {"archivo": None, "imagen": None, "cantidad": None, "fecha": None}

    nombre_archivo = chosen[1]
    dirs = [
        os.path.join(STATIC_DIR, "REINTEGROS"),
        os.path.join(STATIC_DIR, "reintegros"),
        os.path.join(IMG_DIR, "reintegros"),
    ]
    img = _find_image_case_insensitive(dirs, nombre_archivo)
    return {"archivo": nombre_archivo, "imagen": img, "cantidad": chosen[2], "fecha": chosen[0]}

# ------------------ Layout JSON ------------------
def _read_json(path, default_obj):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_obj, f, ensure_ascii=False, indent=2)
        return default_obj
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_obj

def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# --- Auto-fit para que entren todas las figuras en A4 ---
def _default_layout(figs, scale=1.0, fixed_cols=None):
    W, H = A4
    n = max(1, len(figs))

    header_h = 120
    top_y = header_h + 1
    bottom_reserved = 1
    avail_h = max(120.0, H - top_y - bottom_reserved)

    margin_x = 10
    gap_x = 5
    gap_row = 5
    extra_v = 22 + 8 + 18

    best = None
    if fixed_cols:
        cols = max(1, min(int(fixed_cols), n))
        rows = math.ceil(n / cols)
        size_w = (W - 2*margin_x - (cols-1)*gap_x) / cols
        size_h = (avail_h - (rows-1)*gap_row - rows*extra_v) / rows
        size = min(size_w, size_h)
        best = (size, cols, rows)
    else:
        for cols in range(14, 3, -1):
            rows = math.ceil(n / cols)
            size_w = (W - 2 * margin_x - (cols - 1) * gap_x) / cols
            size_h = (avail_h - (rows - 1) * gap_row - rows * extra_v) / rows
            size = min(size_w, size_h)
            if size <= 28:
                continue
            if best is None or size > best[0]:
                best = (size, cols, rows)

    if best is None:
        size, cols, rows = 72, min(n, 8), math.ceil(n / min(n, 8))
    else:
        size, cols, rows = best

    size *= float(scale)

    positions = {}
    x0 = margin_x
    y0 = top_y
    for i, f in enumerate(figs):
        col = i % cols
        row = i // cols
        x = x0 + col * (size + gap_x)
        y = y0 + row * (size + gap_row + extra_v)
        positions[f["nombre"]] = {"x": float(x), "y": float(y), "size": float(size)}

    return {
        "logo":  {"x": 12, "y": 8, "w": 420, "h": 110},
        "title": {"x": 220, "y": 32, "size": 18, "align": "left"},
        "total": {"x": W - 22, "y": 24, "size": 56, "align": "right"},
        "figs": positions
    }

def _layout_for(fecha_base, figs, scale=1.0, force_autofit=False, fixed_cols=None):
    data = _read_json(LAYOUT_JSON, {"default": {}})
    if fecha_base in data and not force_autofit:
        return data[fecha_base]
    return _default_layout(figs, scale=scale, fixed_cols=fixed_cols)

# ------------------ PDF helpers (dibujo) ------------------
def _register_font():
    try:
        for p in [
            os.path.join(FONTS_DIR, "DejaVuSans.ttf"),
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]:
            if os.path.exists(p):
                pdfmetrics.registerFont(TTFont("GLTTF", p))
                return "GLTTF"
    except Exception:
        pass
    return "Helvetica"

def _chip(c, x, y_top, w, txt, font, bg="#1F58FF", fs=10):
    h = 18
    y = y_top - h
    c.setFillColor(colors.HexColor(bg)); c.roundRect(x, y, w, h, 6, 0, 1)
    c.setFillColor(colors.white); c.setFont(font, fs); c.drawCentredString(x + w/2, y + 4, txt)

def _bar(c, x, y_base, w, txt, font, bg="#173A9E", fs=10):
    h = 18
    y = y_base - h
    c.setFillColor(colors.HexColor(bg)); c.roundRect(x, y, w, h, 6, 0, 1)
    c.setFillColor(colors.white); c.setFont(font, fs); c.drawCentredString(x + w/2, y + 4, txt)

def _draw_star(c, cx, cy, r_outer, r_inner, color_hex="#FF0000"):
    pts = []
    for i in range(10):
        ang = math.radians(-90 + i * 36)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    p = c.beginPath()
    p.moveTo(pts[0][0], pts[0][1])
    for (px, py) in pts[1:]:
        p.lineTo(px, py)
    p.close()
    c.setFillColor(colors.HexColor(color_hex))
    c.drawPath(p, fill=1, stroke=0)

def _grid5(c, x, y_top, size, mask):
    cell = (size - 4) / 5.0
    for r in range(5):
        for col in range(5):
            idx = r*5 + col
            on  = bool(mask[idx]) if mask else False
            px  = x + col*(cell+1)
            py  = y_top - (r+1)*(cell+1)
            c.setFillColor(colors.HexColor("#1F58FF") if on else colors.HexColor("#E8EEFF"))
            c.rect(px, py, cell, cell, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor("#27418B"))
    c.rect(x-1, y_top-(5*(cell+1))-1, 5*(cell+1)-1, 5*(cell+1)-1, stroke=1, fill=0)
    cx = x + 2*(cell+1) + cell/2.0
    cy = y_top - (3*(cell+1)) + cell/2.0
    _draw_star(c, cx, cy, r_outer=cell*0.42, r_inner=cell*0.20, color_hex="#FF0000")

def _draw_ultrablack(c, text, x, y, size, font):
    c.setFont(font, size)
    c.setFillColor(colors.black)
    for dx, dy in [(0,0),(0.25,0),(0,-0.25),(0.25,-0.25),(0.15,-0.15),(-0.15,-0.15)]:
        c.drawRightString(x+dx, y+dy, text)

# --------- Helpers de SPINNERS (Extras) ----------
def _sanitize_spinner_list(values):
    """Filtra placeholders como 0000 y deja solo spinners realmente lanzados."""
    out = []
    seen = set()
    for raw in (values or []):
        s = str(raw or "").strip()
        if not s:
            continue
        s = re.sub(r"\D", "", s)
        if not s:
            continue
        s = s[:4].zfill(4)
        if s in {"0000", "000", "00", "0"}:
            continue
        if int(s) <= 0:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[:20]


def _parse_spinners(extras: dict):
    """
    Lee extras y extrae lista de spinners (hasta 20) y el valor por spinner.
    Busca en:
      - extras['spinners'] -> {'numeros': '...', 'valor'/'texto': '...'}
      - fallback: extras['comodin'] -> usa 'boletos' como numeros y 'texto' como valor
    """
    extras = extras or {}
    block = extras.get("spinners") or extras.get("spinner") or {}
    if not block:
        block = extras.get("comodin") or {}

    raw_nums = (block.get("numeros") or (block.get("boletos") or "")).strip()
    raw_val  = (block.get("valor") or (block.get("texto") or "")).strip()

    tokens = re.findall(r"\d{1,4}", raw_nums)
    nums = _sanitize_spinner_list(tokens)

    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", raw_val)
    valor = None
    if m:
        try:
            valor = float(m.group(1).replace(",", "."))
        except Exception:
            valor = None

    return {"nums": nums, "valor": valor, "texto": raw_val}


def _parse_bonus(extras: dict):
    """Lee GRAN BONUS / BONUS desde resultados para el PDF."""
    extras = extras or {}
    block = extras.get("gran_bonus") or extras.get("granbonus") or extras.get("bonus") or {}
    raw_nums = block.get("numeros") or block.get("numbers") or ""
    if isinstance(raw_nums, (list, tuple)):
        nums = [str(x).strip() for x in raw_nums if str(x).strip()]
    else:
        nums = [n.strip() for n in re.findall(r"\d{1,2}", str(raw_nums)) if n.strip()]
    nums = nums[:10]
    raw_text = (block.get("texto") or block.get("valor") or "").strip()
    return {"nums": nums, "texto": raw_text}

def _bonus_from_sources_for_date(fecha_iso: str, extras: dict | None = None):
    """Resuelve BONUS para PDF desde resultados y, si falta, desde historial bonus_*.json."""
    data = _parse_bonus(extras or {})
    if data.get("nums") or data.get("texto"):
        return data
    try:
        items = _bonus_history_items_for_date(fecha_iso) if "_bonus_history_items_for_date" in globals() else []
    except Exception:
        items = []
    if items:
        src = items[0] or {}
        nums = [str(x).strip() for x in (src.get("numbers") or []) if str(x).strip()][:10]
        req = src.get("requested") or {}
        win = src.get("winners") or {}
        resumen = []
        for k in (5,4,3,2,1):
            rk = str(k)
            rv = int(req.get(rk, 0) or 0)
            wv = int(win.get(rk, 0) or 0)
            if rv or wv:
                resumen.append(f"{k}A:{wv}/{rv}")
        texto = " · ".join(resumen) if resumen else (src.get("serie_archivo") or "")
        return {"nums": nums, "texto": texto}
    return {"nums": [], "texto": ""}


def _spinners_from_sources_for_date(fecha_iso: str, extras: dict | None = None):
    """Resuelve SPINNERS para PDF desde resultados y, si falta, desde el XML/histórico del sorteo."""
    data = _parse_spinners(extras or {})
    if data.get("nums"):
        return data
    nums = []
    try:
        if "_load_spinners_for_fecha" in globals():
            nums = [str(x).strip() for x in (_load_spinners_for_fecha(fecha_iso) or []) if str(x).strip()]
    except Exception:
        nums = []
    nums = _sanitize_spinner_list(nums)
    return {"nums": nums, "valor": data.get("valor"), "texto": data.get("texto") or ""}


def _reintegro_from_sources_for_date(fecha_iso: str):
    """Resuelve reintegro e imagen para PDF usando LOGS y fallback a configuración del sorteo."""
    data = _reintegro_from_log_for_date(fecha_iso)
    if data.get("imagen") or data.get("archivo"):
        return data

    nombre = ""
    try:
        if "get_impresiones_info" in globals():
            imp = get_impresiones_info(fecha_iso) or {}
            nombre = str(imp.get("reintegro_dia") or imp.get("reintegro") or "").strip()
    except Exception:
        nombre = ""

    if not nombre:
        try:
            if "_get_sorteo_activo_info" in globals() and (fecha_iso == (_get_sorteo_fecha() if "_get_sorteo_fecha" in globals() else fecha_iso)):
                info = _get_sorteo_activo_info() or {}
                nombre = str(info.get("reintegro") or info.get("reintegro_dia") or "").strip()
        except Exception:
            pass

    if not nombre:
        return data

    # Intentar resolver con helper del módulo de juego si existe
    try:
        if "_resolve_reintegro_media" in globals():
            meta = _resolve_reintegro_media(nombre) or {}
            ruta = meta.get("ruta") or ""
            if ruta and os.path.exists(ruta):
                return {"archivo": nombre, "imagen": ruta, "cantidad": None, "fecha": fecha_iso}
    except Exception:
        pass

    dirs = []
    for cand in (
        globals().get("REINTEGRO_MEDIA_DIR"),
        globals().get("REINTEGROS_MEDIA_DIR"),
        os.path.join(STATIC_DIR, "REINTEGRO"),
        os.path.join(STATIC_DIR, "REINTEGROS"),
        os.path.join(STATIC_DIR, "reintegro"),
        os.path.join(STATIC_DIR, "reintegros"),
        os.path.join(IMG_DIR, "reintegros"),
        os.path.join(IMG_DIR, "REINTEGROS"),
    ):
        if cand and cand not in dirs:
            dirs.append(cand)
    img = _find_image_case_insensitive(dirs, nombre)
    return {"archivo": nombre, "imagen": img, "cantidad": None, "fecha": fecha_iso}


def _draw_spinners_card(c, x, y, w, h, nums, valor, font):
    """Tarjeta SPINNERS con mejor estética y solo números realmente jugados."""
    nums = _sanitize_spinner_list(nums)

    c.setFillColor(colors.HexColor("#FFFFFF"))
    c.setStrokeColor(colors.HexColor("#CBD5F1"))
    c.roundRect(x, y, w, h, 10, stroke=1, fill=1)

    header_h = 22
    c.setFillColor(colors.HexColor("#243C94"))
    c.roundRect(x, y + h - header_h, w, header_h, 10, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(font, 10)
    c.drawCentredString(x + w/2, y + h - 15, "SPINNERS JUGADOS")

    pad = 10
    inner_x = x + pad
    inner_w = w - 2 * pad
    top_y = y + h - header_h - 12

    if valor is not None:
        badge_w = min(88, inner_w * 0.34)
        c.setFillColor(colors.HexColor("#E8F3FF"))
        c.setStrokeColor(colors.HexColor("#BFDBFE"))
        c.roundRect(inner_x, top_y - 4, badge_w, 16, 7, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#1D4ED8"))
        c.setFont(font, 8)
        c.drawCentredString(inner_x + badge_w/2, top_y + 1, f"C/U {_money(valor)}")

    if not nums:
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont(font, 10)
        c.drawCentredString(x + w/2, y + h/2 - 8, "SIN SPINNERS JUGADOS")
        return

    title_gap = 18 if valor is not None else 6
    body_top = y + h - header_h - title_gap
    body_h = max(32, body_top - y - 10)

    spinner_gap = 10
    row_gap = 8
    box_gap = 2.5
    pill_pad_x = 6
    pill_pad_y = 5

    n = len(nums)
    best = None
    max_per_row = min(n, 6)
    for per_row in range(max_per_row, 0, -1):
        rows = math.ceil(n / per_row)
        max_box_w = ((inner_w - (per_row - 1) * spinner_gap) / per_row - 2 * pill_pad_x - 3 * box_gap) / 4.0
        max_box_h = ((body_h - (rows - 1) * row_gap) / rows - 2 * pill_pad_y)
        box = min(max_box_w, max_box_h, 15)
        if box >= 8.5:
            if best is None or box > best[0]:
                best = (box, per_row, rows)

    if best is None:
        best = (8.5, min(n, 4), math.ceil(n / max(1, min(n, 4))))

    box, per_row, rows = best
    pill_h = 2 * pill_pad_y + box
    pill_w = 2 * pill_pad_x + 4 * box + 3 * box_gap
    fs = max(8.0, min(11.0, box * 0.72))

    idx = 0
    grid_top = y + 10 + body_h - pill_h
    for r in range(rows):
        remaining = n - idx
        count = min(per_row, remaining)
        row_w = count * pill_w + (count - 1) * spinner_gap
        start_x = inner_x + max(0, (inner_w - row_w) / 2.0)
        y_row = grid_top - r * (pill_h + row_gap)

        for j in range(count):
            cur_x = start_x + j * (pill_w + spinner_gap)

            c.setFillColor(colors.HexColor("#EEF4FF"))
            c.setStrokeColor(colors.HexColor("#BFD0FF"))
            c.roundRect(cur_x, y_row, pill_w, pill_h, 7, stroke=1, fill=1)

            s = re.sub(r"\D", "", str(nums[idx]))[:4].rjust(4, "0")
            xx = cur_x + pill_pad_x
            yy = y_row + pill_pad_y
            for ch in s:
                c.setFillColor(colors.white)
                c.setStrokeColor(colors.HexColor("#8FA8FF"))
                c.roundRect(xx, yy, box, box, 2.8, stroke=1, fill=1)
                c.setFillColor(colors.HexColor("#14213D"))
                c.setFont(font, fs)
                tx = xx + (box - pdfmetrics.stringWidth(ch, font, fs)) / 2.0
                ty = yy + (box - fs) / 2.0 + 0.2
                c.drawString(tx, ty, ch)
                xx += box + box_gap

            idx += 1
            if idx >= n:
                break


def _draw_bonus_card(c, x, y, w, h, nums, texto, font):
    """Tarjeta elegante para BONUS / GRAN BONUS."""
    c.setFillColor(colors.HexColor("#FFF7D6"))
    c.setStrokeColor(colors.HexColor("#E7B91E"))
    c.roundRect(x, y, w, h, 10, stroke=1, fill=1)

    pad = 10
    header_h = 20
    c.setFillColor(colors.HexColor("#D4A414"))
    c.roundRect(x, y + h - header_h, w, header_h, 10, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(font, 10)
    c.drawCentredString(x + w/2, y + h - 14, "BONUS")

    nums = [str(n).zfill(2) for n in (nums or []) if str(n).strip()][:10]
    if texto:
        c.setFillColor(colors.HexColor("#6B7280"))
        c.setFont(font, 7.6)
        txt = _fit_text_one_line(c, str(texto), font, 7.6, w - 2*pad)
        c.drawCentredString(x + w/2, y + h - header_h - 10, txt)

    body_top = y + h - header_h - (14 if texto else 8)
    body_h = max(24, body_top - y - 8)

    if not nums:
        c.setFillColor(colors.HexColor("#9CA3AF"))
        c.setFont(font, 10)
        c.drawCentredString(x + w/2, y + body_h/2, "SIN BONUS")
        return

    cols = 5 if len(nums) > 5 else max(1, len(nums))
    rows = int(math.ceil(len(nums) / float(cols)))
    gap_x = 8
    gap_y = 8
    inner_w = w - 2 * pad
    inner_h = body_h - 10
    ball = min((inner_w - (cols - 1) * gap_x) / cols, (inner_h - (rows - 1) * gap_y) / rows, 28)
    ball = max(18, ball)
    total_grid_w = cols * ball + (cols - 1) * gap_x
    total_grid_h = rows * ball + (rows - 1) * gap_y
    start_x = x + pad + max(0, (inner_w - total_grid_w) / 2)
    start_y = y + 8 + max(0, (inner_h - total_grid_h) / 2) + (rows - 1) * (ball + gap_y)

    for i, n in enumerate(nums):
        col = i % cols
        row = i // cols
        bx = start_x + col * (ball + gap_x)
        by = start_y - row * (ball + gap_y)
        c.setFillColor(colors.HexColor("#FACC15"))
        c.setStrokeColor(colors.HexColor("#B7791F"))
        c.circle(bx + ball/2, by + ball/2, ball/2, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#1F2937"))
        fs = max(8, min(12, ball * 0.40))
        c.setFont(font, fs)
        tw = pdfmetrics.stringWidth(n, font, fs)
        c.drawString(bx + (ball - tw)/2, by + (ball - fs)/2 + 1, n)


def _fit_text_one_line(c, txt, font, size, max_w):
    txt = _safe_text(txt or "", font)
    if pdfmetrics.stringWidth(txt, font, size) <= max_w:
        return txt
    base = txt
    while base and pdfmetrics.stringWidth(base + "...", font, size) > max_w:
        base = base[:-1]
    return (base + "...") if base else ""


# ------------------ Rutas Flask ------------------

@app.get("/api/figuras-manana")
def api_figuras_manana():
    base = (request.args.get("fecha") or date.today().isoformat()).strip()
    if not _is_fecha_iso(base):
        base = date.today().isoformat()
    fecha_objetivo = _siguiente_fecha_con_figuras(base)
    figs = _figuras_de_fecha(fecha_objetivo)
    total = sum((f.get("valor") or 0.0) for f in figs)
    return jsonify({"ok": True, "fecha": fecha_objetivo, "figuras": figs, "total": total})

@app.get("/api/resultados")
def api_resultados():
    fecha = (request.args.get("fecha") or date.today().isoformat()).strip()
    if not _is_fecha_iso(fecha):
        fecha = date.today().isoformat()
    return jsonify({"ok": True, **_cargar_resultados(fecha)})

@app.post("/boletin/guardar")
def boletin_guardar():
    fecha = (request.form.get("fecha") or "").strip()
    raw = (request.form.get("resultados") or "").strip()
    raw_extras = (request.form.get("extras") or "").strip()
    resultados = []
    extras = None
    if raw:
        try:
            tmp = json.loads(raw)
            if isinstance(tmp, list):
                resultados = tmp
        except Exception:
            pass
    if raw_extras:
        try:
            tmp = json.loads(raw_extras)
            if isinstance(tmp, dict):
                extras = tmp
        except Exception:
            pass
    try:
        _guardar_resultados(fecha, resultados, extras)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/resultados/upsert-ganador")
@app.post("/api/resultados/upsert_ganador")
def api_resultados_upsert_ganador():
    """
    Guarda/actualiza un ganador puntual desde el modal del juego.
    Esto evita el error "Respuesta inválida" cuando el botón Guardar boletín
    intenta escribir directamente sobre resultados_sorteo.xml.
    """
    try:
        fecha = (request.values.get("fecha") or "").strip()
        if not _is_fecha_iso(fecha):
            try:
                fecha = _get_sorteo_fecha()
            except Exception:
                fecha = date.today().isoformat()
        if not _is_fecha_iso(fecha):
            fecha = date.today().isoformat()

        payload = request.get_json(silent=True) or {}
        figura = str(request.values.get("figura") or payload.get("figura") or "").strip()
        boleto = _norm_tabla_id(request.values.get("boleto") or payload.get("boleto") or "")
        nombre = str(request.values.get("nombre") or payload.get("nombre") or "").strip()
        premio = _safe_float(
            request.values.get("premio") if request.values.get("premio") is not None else payload.get("premio"),
            0.0,
        )

        if not figura or not boleto:
            return jsonify({"ok": False, "msg": "Falta figura o boleto."}), 400

        actual = _cargar_resultados(fecha) or {"items": [], "extras": {"comodin": {}, "gran_bonus": {}}}
        items = list(actual.get("items") or [])
        extras = dict(actual.get("extras") or {})

        item = None
        for it in items:
            if str(it.get("figura") or "").strip().lower() == figura.lower():
                item = it
                break
        if item is None:
            item = {"figura": figura, "ganadores": []}
            items.append(item)

        ganadores = list(item.get("ganadores") or [])
        ganador = None
        for g in ganadores:
            if _norm_tabla_id(g.get("boleto") or "") == boleto:
                ganador = g
                break
        if ganador is None:
            ganador = {
                "boleto": boleto,
                "nombre": "",
                "vendedor": "",
                "sector": "",
                "premio": 0.0,
            }
            ganadores.append(ganador)
            item["ganadores"] = ganadores

        ganador["boleto"] = boleto
        ganador["nombre"] = nombre
        ganador["premio"] = round(float(premio or 0.0), 2)

        # Completa vendedor/sector desde asignación de planillas, pero sin pisar lo ya guardado.
        try:
            info_boleto = buscar_info_por_boleto(fecha, boleto) or {}
        except Exception:
            info_boleto = {}
        vendedor_resuelto = str(info_boleto.get("vendedor") or "").strip()
        sector_resuelto = str(
            info_boleto.get("planilla")
            or info_boleto.get("rango")
            or info_boleto.get("sector")
            or ""
        ).strip()

        ganador["vendedor"] = vendedor_resuelto or str(ganador.get("vendedor") or "").strip()
        ganador["sector"] = sector_resuelto or str(ganador.get("sector") or "").strip()

        _guardar_resultados(fecha, items, extras)

        try:
            data_g = _safe_json_read(GANADORES_JSON) or {}
            raw_g = data_g.get(str(fecha), []) or []
            enriquecidos = []
            for ww in raw_g:
                if not isinstance(ww, dict):
                    continue
                item_w = dict(ww)
                try:
                    item_w["figura"] = _tl_semantic_name(
                        str(item_w.get("figura") or item_w.get("nombre_figura") or ""),
                        str(item_w.get("fig_code") or "")
                    )
                except Exception:
                    pass
                enriquecidos.append(item_w)
            _sync_resultados_from_juego(str(fecha), enriquecidos)
            try:
                ultimo_xml = 0
                if os.path.exists(GANADORES_XML):
                    rg = ET.parse(GANADORES_XML).getroot()
                    ultimo_xml = _safe_int(rg.attrib.get("ultimo_marcado"), 0)
                elif os.path.exists(GANADORES_XML_PUBLIC):
                    rg = ET.parse(GANADORES_XML_PUBLIC).getroot()
                    ultimo_xml = _safe_int(rg.attrib.get("ultimo_marcado"), 0)
            except Exception:
                ultimo_xml = 0
            _write_ganadores_xml(str(fecha), ultimo_xml, enriquecidos)
        except Exception:
            pass

        return jsonify({"ok": True, "fecha": fecha, "ganador": ganador})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"No se pudo guardar ganador: {e}"}), 500

@app.get("/api/boletin-layout/get")
def api_layout_get():
    fecha = (request.args.get("fecha") or date.today().isoformat()).strip()
    if not _is_fecha_iso(fecha):
        fecha = date.today().isoformat()
    fecha_objetivo = _siguiente_fecha_con_figuras(fecha)
    figs = _figuras_de_fecha(fecha_objetivo)
    lay  = _layout_for(fecha, figs, scale=FIG_BLOCK_SCALE, fixed_cols=FIG_FIXED_COLS)
    return jsonify({"ok": True, "fecha": fecha_objetivo, "layout": lay, "figuras": figs})

@app.post("/api/boletin-layout/save")
def api_layout_save():
    payload = request.get_json(force=True, silent=True) or {}
    fecha = (payload.get("fecha") or date.today().isoformat()).strip()
    if not _is_fecha_iso(fecha):
        fecha = date.today().isoformat()
    lay = payload.get("layout") or {}
    data = _read_json(LAYOUT_JSON, {"default": {}})
    data[fecha] = lay
    _write_json(LAYOUT_JSON, data)
    return jsonify({"ok": True})

@app.get("/")
def home():
    return redirect(url_for("boletin_view"))

@app.get("/boletin")
def boletin_view():
    q = (request.args.get("fecha") or date.today().isoformat()).strip()
    if not _is_fecha_iso(q):
        q = date.today().isoformat()
    try:
        return render_template("boletin.html", fecha_inicial=q)
    except Exception:
        pdf_url = url_for("boletin_pdf", fecha=q)
        return f'''
        <html><body style="font-family:Arial, sans-serif; background:#0b1324; color:#e5e7eb;">
            <div style="max-width:920px;margin:40px auto;padding:16px;background:#111827;border-radius:12px;">
                <h2>Boletín</h2>
                <p>Fecha seleccionada: {q}</p>
                <p><a style="background:#10b981;color:#fff;padding:8px 12px;border-radius:8px;text-decoration:none"
                      href="{pdf_url}" target="_blank">Ver PDF</a></p>
            </div>
        </body></html>
        '''

# ------------------ PDF principal ------------------
@app.get("/boletin/pdf")
def boletin_pdf():
    try:
        fecha = (request.args.get("fecha") or date.today().isoformat()).strip()
        if not _is_fecha_iso(fecha):
            fecha = date.today().isoformat()

        qscale = request.args.get("scale")
        qcols  = request.args.get("cols")
        fixed_cols = int(qcols) if qcols else (FIG_FIXED_COLS or None)
        if qscale is None:
            scale = FIG_BLOCK_SCALE
            force_autofit = False
        else:
            try:
                scale = float(qscale)
            except Exception:
                scale = FIG_BLOCK_SCALE
            scale = max(0.5, min(1.2, scale))
            force_autofit = True

        def _float_arg(name, default):
            v = request.args.get(name)
            if v is None:
                return default
            try:
                return float(v)
            except Exception:
                return default

        LOGO_SCALE = max(0.5, min(2.0, _float_arg("logo_scale", LOGO_SCALE_DEFAULT)))
        REIN_SCALE = max(0.5, min(1.8, _float_arg("rein_scale", 1.10)))
        SPIN_SCALE = max(0.5, min(1.8, _float_arg("spin_scale", 1.10)))
        BONUS_SCALE = max(0.5, min(1.8, _float_arg("bonus_scale", 1.08)))

        fecha_objetivo = _siguiente_fecha_con_figuras(fecha)
        figs_manana  = _figuras_de_fecha(fecha_objetivo)
        total_manana = sum((f.get("valor") or 0.0) for f in figs_manana)
        resultados   = _cargar_resultados(fecha)
        shapes       = _load_shapes()
        layout       = _layout_for(fecha, figs_manana, scale=scale, force_autofit=force_autofit, fixed_cols=fixed_cols)

        extras = resultados.get("extras") or {}
        rein_log   = _reintegro_from_sources_for_date(fecha)
        sp_data    = _spinners_from_sources_for_date(fecha, extras)
        bonus_data = _bonus_from_sources_for_date(fecha, extras)

        default_figs_pos = _default_layout(figs_manana, scale=scale, fixed_cols=fixed_cols)["figs"]
        layout.setdefault("figs", {})
        for f in figs_manana:
            n = f["nombre"]
            if n not in layout["figs"]:
                layout["figs"][n] = default_figs_pos.get(n, {"x": 50, "y": 148, "size": 96})

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        W, H = A4
        FONT = _register_font()
        T = lambda s: _safe_text(s, FONT)

        # ---------- Header ----------
        header_h = 120
        c.setFillColor(colors.HexColor("#E7B91E"))
        c.rect(0, H - header_h, W, header_h, 0, 1)

        logo_candidates = [
            os.path.join(BASE_DIR, "static", "golpe_suerte_logo.png"),
            os.path.join(IMG_DIR, "logo.png"),
            os.path.join(IMG_DIR, "golpe_suerte_logo.png"),
            os.path.join(BASE_DIR, "static", "img", "logo.png"),
        ]
        logo = next((p for p in logo_candidates if os.path.exists(p)), None)
        L = layout.get("logo", {"x": 12, "y": 8, "w": 420, "h": 110})
        if logo:
            img = ImageReader(logo)
            iw, ih = img.getSize()
            s = min(L["w"]/iw, L["h"]/ih) * float(LOGO_SCALE)
            draw_w = iw * s
            draw_h = ih * s
            if draw_w > L["w"] or draw_h > L["h"]:
                f = min(L["w"]/draw_w, L["h"]/draw_h, 1.0)
                draw_w *= f
                draw_h *= f
            c.drawImage(img, L["x"], H - (L["y"] + draw_h), width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")

        # Título y fecha con mejor estética
        date_card_w = 150
        date_card_h = 28
        date_card_x = (W - date_card_w) / 2.0
        date_card_y = H - 68
        c.setFillColor(colors.HexColor("#0F2A7A"))
        c.setStrokeColor(colors.HexColor("#E5EDFF"))
        c.roundRect(date_card_x, date_card_y, date_card_w, date_card_h, 10, stroke=1, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT, 18)
        c.drawCentredString(W/2, H - 34, T("JUEGO DEL DIA"))
        c.setFont(FONT, 11)
        c.drawCentredString(W/2, date_card_y + 9, T(_es_largo(fecha_objetivo).capitalize()))

        TL = layout.get("total", {"x": W - 22, "y": 24, "size": 56, "align": "right"})
        c.setFillColor(colors.white)
        c.setFont(FONT, 11)
        c.drawRightString(W - 18, H - 22, T("PREMIO TOTAL"))
        amount = T(_money_header(total_manana))
        _draw_ultrablack(c, amount, TL.get("x", W - 22), H - (TL.get("y", 24) + TL.get("size", 56)), TL.get("size", 56), FONT)

        # ---------- Figuras del siguiente sorteo ----------
        fig_lay = layout.get("figs", {})
        for f in figs_manana:
            name = f["nombre"]
            val = f.get("valor") or 0.0
            pos = fig_lay.get(name) or {}
            bx = float(pos.get("x", 50))
            by = float(pos.get("y", header_h + 28))
            bw = float(pos.get("size", 96))

            _chip(c, bx, H - by, bw, T(_money(val)), FONT, "#1F58FF", 10)
            grid_top = H - by - 22
            mask = shapes.get(name.strip().lower(), [False] * 25)
            _grid5(c, bx, grid_top, bw, mask)
            _bar(c, bx, grid_top - (bw + 8), bw, T(name.upper()), FONT, "#0E2E8E", 10)

        # ---------- Resultados estructurados ----------
        block_h_extra = 22 + 8 + 18
        max_depth = header_h
        for f in figs_manana:
            pos = fig_lay.get(f["nombre"]) or {}
            by = float(pos.get("y", header_h + 28))
            bw = float(pos.get("size", 96))
            depth = by + (bw + block_h_extra)
            if depth > max_depth:
                max_depth = depth

        depth = max_depth + 24
        y = H - depth
        MIN_Y_FIRST_PAGE = 126
        if y < MIN_Y_FIRST_PAGE:
            y = MIN_Y_FIRST_PAGE


        items_resultado = list(resultados.get("items") or [])
        items_con_ganador = [it for it in items_resultado if (it.get("ganadores") or [])]
        items_a_mostrar = items_con_ganador or items_resultado
        total_ganadores = sum(len(it.get("ganadores") or []) for it in items_resultado)

        c.setFillColor(colors.HexColor("#2B2370"))
        c.rect(0, y, W, 18, 0, 1)
        c.setFillColor(colors.white)
        c.setFont(FONT, 10)
        c.drawCentredString(W/2, y + 5, T(f"RESULTADOS DEL SORTEO · { _es_largo(fecha).upper() }"))
        y -= 8

        chip_y = y
        _chip(c, 16, chip_y, 132, T(f"FIGURAS DEL DIA: {len(items_resultado)}"), FONT, "#1E40AF", 9)
        _chip(c, 154, chip_y, 136, T(f"FIGURAS PREMIADAS: {len(items_con_ganador)}"), FONT, "#1D4ED8", 9)
        _chip(c, 296, chip_y, 118, T(f"GANADORES: {total_ganadores}"), FONT, "#0F766E", 9)
        y -= 28

        agenda = _figuras_de_fecha(fecha)
        premio_map = {a["nombre"].strip().lower(): (a.get("valor") or 0.0) for a in agenda}

        # ---------- Auto-ajuste del PDF: intenta 1 hoja y usa máximo 2 ----------
        MAX_PAGES_PDF = 2

        STYLE_NORMAL = {
            "row_h": 16.0,
            "box_top": 42.0,
            "box_bottom": 14.0,
            "gap_after": 10.0,
            "title_font": 10.0,
            "head_font": 8.0,
            "body_font": 8.7,
            "body_font_2": 8.5,
            "name_max": 230.0,
            "vend_max": 180.0,
            "extras_h": 160.0,
        }
        STYLE_COMPACT = {
            "row_h": 14.0,
            "box_top": 38.0,
            "box_bottom": 12.0,
            "gap_after": 8.0,
            "title_font": 9.2,
            "head_font": 7.6,
            "body_font": 8.0,
            "body_font_2": 7.8,
            "name_max": 245.0,
            "vend_max": 195.0,
            "extras_h": 145.0,
        }
        STYLE_MINI = {
            "row_h": 12.4,
            "box_top": 34.0,
            "box_bottom": 10.0,
            "gap_after": 6.0,
            "title_font": 8.5,
            "head_font": 7.0,
            "body_font": 7.3,
            "body_font_2": 7.1,
            "name_max": 260.0,
            "vend_max": 210.0,
            "extras_h": 128.0,
        }
        STYLE_MICRO = {
            "row_h": 11.2,
            "box_top": 31.0,
            "box_bottom": 9.0,
            "gap_after": 5.0,
            "title_font": 7.9,
            "head_font": 6.6,
            "body_font": 6.9,
            "body_font_2": 6.7,
            "name_max": 270.0,
            "vend_max": 220.0,
            "extras_h": 116.0,
        }
        STYLE_NANO = {
            "row_h": 10.2,
            "box_top": 28.0,
            "box_bottom": 8.0,
            "gap_after": 4.0,
            "title_font": 7.3,
            "head_font": 6.2,
            "body_font": 6.4,
            "body_font_2": 6.2,
            "name_max": 280.0,
            "vend_max": 230.0,
            "extras_h": 102.0,
        }

        def _rows_of_item(it):
            return max(1, len(it.get("ganadores") or []))

        extras_cards = []
        if bonus_data.get("nums") or bonus_data.get("texto"):
            extras_cards.append("bonus")
        if sp_data.get("nums") or (sp_data.get("valor") is not None):
            extras_cards.append("spinners")
        if rein_log.get("imagen") or rein_log.get("archivo"):
            extras_cards.append("reintegro")

        first_page_available = max(130.0, y - 22.0)
        second_page_available = H - 40.0

        def _fits(style):
            items_h = 0.0
            for it in items_a_mostrar:
                rows = _rows_of_item(it)
                box_h = style["box_top"] + (rows * style["row_h"]) + style["box_bottom"]
                items_h += box_h + style["gap_after"]

            extras_h = (style["extras_h"] + 26.0) if extras_cards else 0.0
            total_h = items_h + extras_h

            if total_h <= first_page_available:
                return True

            capacity_total = first_page_available + ((MAX_PAGES_PDF - 1) * second_page_available)
            return total_h <= capacity_total

        PDF_STYLE = STYLE_NANO
        for candidate in (STYLE_NORMAL, STYLE_COMPACT, STYLE_MINI, STYLE_MICRO, STYLE_NANO):
            if _fits(candidate):
                PDF_STYLE = candidate
                break

        section_h = PDF_STYLE["extras_h"]
        page_count = 1

        def _draw_continue_header():
            nonlocal y
            c.setFillColor(colors.HexColor("#2B2370"))
            c.rect(0, H - 18, W, 18, 0, 1)
            c.setFillColor(colors.white)
            c.setFont(FONT, 10)
            c.drawCentredString(W/2, H - 13, T(f"RESULTADOS DEL SORTEO · CONTINUA"))
            y = H - 28

        def ensure_space(hmin=70, top_margin=16):
            nonlocal y, page_count
            if y - hmin < top_margin:
                if page_count >= MAX_PAGES_PDF:
                    return False
                c.showPage()
                page_count += 1
                _draw_continue_header()
            return True

        def bloque(fig, ganadores, premio_total):
            nonlocal y
            rows = list(ganadores or [])
            if not rows:
                rows = [{
                    "boleto": "—",
                    "nombre": "SIN GANADOR REGISTRADO",
                    "vendedor": "—",
                    "sector": "",
                    "premio": 0.0,
                    "_placeholder": True
                }]

            row_h = PDF_STYLE["row_h"]
            box_h = PDF_STYLE["box_top"] + (len(rows) * row_h) + PDF_STYLE["box_bottom"]

            if not ensure_space(box_h + 12, top_margin=26):
                return False

            y -= box_h

            bx = 14
            bw = W - 28
            by = y

            c.setFillColor(colors.HexColor("#F8FAFF"))
            c.setStrokeColor(colors.HexColor("#CBD5F1"))
            c.roundRect(bx, by, bw, box_h, 10, stroke=1, fill=1)

            c.setFillColor(colors.HexColor("#203880"))
            c.roundRect(bx, by + box_h - 22, bw, 22, 10, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.setFont(FONT, PDF_STYLE["title_font"])
            c.drawString(bx + 10, by + box_h - 15, T(fig.upper()))
            c.drawRightString(bx + bw - 10, by + box_h - 15, T(f"PREMIO TOTAL { _money(premio_total) }"))

            c.setFillColor(colors.HexColor("#64748B"))
            c.setFont(FONT, PDF_STYLE["head_font"])
            c.drawString(bx + 8, by + box_h - 34, T("Boleto"))
            c.drawString(bx + 74, by + box_h - 34, T("Nombre / Observacion"))
            c.drawString(bx + 322, by + box_h - 34, T("Vendedor / Sector"))
            c.drawRightString(bx + bw - 10, by + box_h - 34, T("Premio"))
            c.setStrokeColor(colors.HexColor("#E2E8F0"))
            c.line(bx + 8, by + box_h - 38, bx + bw - 8, by + box_h - 38)

            row_y = by + box_h - 52
            for i, g in enumerate(rows):
                if i % 2 == 0:
                    c.setFillColor(colors.HexColor("#F1F5FF"))
                    c.roundRect(
                        bx + 6,
                        row_y - 9,
                        bw - 12,
                        max(10, row_h - 2),
                        4,
                        stroke=0,
                        fill=1
                    )

                boleto = str(g.get("boleto") or "—")
                nombre = str(g.get("nombre") or "—")
                vendedor = str(g.get("vendedor") or "").strip()
                sector = str(g.get("sector") or "").strip()

                if not vendedor:
                    vendedor = (layout.get("sorteo") or layout.get("nombre_sorteo") or "GOLPE DE SUERTE")

                vend_show = vendedor if not sector else f"{vendedor} · {sector}"
                nombre = _fit_text_one_line(c, nombre, FONT, PDF_STYLE["body_font"], PDF_STYLE["name_max"])
                vend_show = _fit_text_one_line(c, vend_show, FONT, PDF_STYLE["body_font_2"], PDF_STYLE["vend_max"])

                try:
                    prem = float(g.get("premio") or 0.0)
                except Exception:
                    prem = 0.0

                if g.get("_placeholder") and premio_total:
                    prem = float(premio_total or 0.0)

                c.setFillColor(colors.HexColor("#111827"))
                c.setFont(FONT, PDF_STYLE["body_font"])
                c.drawString(bx + 8, row_y - 5, T(boleto))
                c.drawString(bx + 74, row_y - 5, T(nombre))
                c.drawString(bx + 322, row_y - 5, T(vend_show))
                c.drawRightString(bx + bw - 10, row_y - 5, T(_money(prem)))
                row_y -= row_h

            y -= PDF_STYLE["gap_after"]
            return True

        for item in items_a_mostrar:
            nom = item.get("figura", "")
            gan = item.get("ganadores") or []
            premio = premio_map.get(nom.strip().lower(), 0.0)
            if premio == 0.0:
                premio = sum((g.get("premio") or 0.0) for g in gan)

            ok = bloque(nom, gan, premio)
            if not ok:
                break

        # ---------- Extras inferiores: BONUS, SPINNERS, REINTEGRO ----------
        if extras_cards and ensure_space(section_h + 24, top_margin=24):
            c.setFillColor(colors.HexColor("#2B2370"))
            c.rect(0, y, W, 16, 0, 1)
            c.setFillColor(colors.white)
            c.setFont(FONT, 10)
            c.drawCentredString(W/2, y + 4, T("EXTRAS DEL SORTEO"))
            y -= (section_h + 10)

            margin = 12
            gap = 10
            count = len(extras_cards)
            slot_w = (W - (2 * margin) - ((count - 1) * gap)) / max(1, count)
            card_y = y
            cur_x = margin

            for kind in extras_cards:
                if kind == "bonus":
                    _draw_bonus_card(c, cur_x, card_y, slot_w, section_h, bonus_data.get("nums") or [], bonus_data.get("texto") or "", FONT)
                elif kind == "spinners":
                    _draw_spinners_card(c, cur_x, card_y, slot_w, section_h, sp_data.get("nums") or [], sp_data.get("valor"), FONT)
                elif kind == "reintegro":
                    c.setFillColor(colors.HexColor("#FFFFFF"))
                    c.setStrokeColor(colors.HexColor("#CBD5F1"))
                    c.roundRect(cur_x, card_y, slot_w, section_h, 10, stroke=1, fill=1)

                    c.setFillColor(colors.HexColor("#2B2370"))
                    c.roundRect(cur_x, card_y + section_h - 20, slot_w, 20, 10, stroke=0, fill=1)
                    c.setFillColor(colors.white)
                    c.setFont(FONT, 10)
                    c.drawCentredString(cur_x + slot_w/2, card_y + section_h - 14, "REINTEGRO")

                    label = str((rein_log.get("archivo") or "")).rsplit('.', 1)[0].strip() or "SIN REINTEGRO"
                    c.setFillColor(colors.HexColor("#1F2937"))
                    c.setFont(FONT, 8.5)
                    txt = _fit_text_one_line(c, label, FONT, 8.5, slot_w - 20)
                    c.drawCentredString(cur_x + slot_w/2, card_y + 18, T(txt))

                    if rein_log.get("imagen") and os.path.exists(str(rein_log.get("imagen"))):
                        try:
                            img = ImageReader(str(rein_log.get("imagen")))
                            iw, ih = img.getSize()
                            max_w = min(slot_w * 0.72, slot_w - 34)
                            max_h = min(section_h * 0.52, section_h - 78)
                            s = min(max_w / float(iw), max_h / float(ih), 1.0)
                            draw_w = iw * s
                            draw_h = ih * s
                            ix = cur_x + (slot_w - draw_w) / 2.0
                            iy = card_y + 34 + max(0, (max_h - draw_h) / 2.0)
                            c.drawImage(img, ix, iy, width=draw_w, height=draw_h, preserveAspectRatio=True, mask='auto')
                        except Exception:
                            c.setFillColor(colors.HexColor("#9CA3AF"))
                            c.setFont(FONT, 10)
                            c.drawCentredString(cur_x + slot_w/2, card_y + section_h/2, "SIN IMAGEN")
                    else:
                        c.setFillColor(colors.HexColor("#9CA3AF"))
                        c.setFont(FONT, 10)
                        c.drawCentredString(cur_x + slot_w/2, card_y + section_h/2, "SIN IMAGEN")

                cur_x += slot_w + gap

        c.save()
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"boletin_{fecha}.pdf", mimetype="application/pdf")

    except Exception:
        import traceback
        print("[/boletin/pdf ERROR]\n", traceback.format_exc())
        return "Error generando PDF", 500


# (opcional) arrancar si se ejecuta directo






# ------------------------------------------------------------------------------
# Run
# FIN BOLETIN CERRADO ------------------------------------------------------------------------------










#PAGO DE PREMIOS

# =========================
#  PAGO DE PREMIOS (MÓDULO)
# =========================
# No toca boletín ni "figuras de mañana"

import os, re, json, xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import request, jsonify, send_file, render_template, session
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth

# ---- Rutas base / compatibilidad con tu app principal ----
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR   = globals().get("DATA_DIR") or os.path.join(BASE_DIR, "DATA")
DB_DIR     = globals().get("DB_DIR_PERSIST") or os.path.join(DATA_DIR, "static", "db")
IMG_DIR    = os.path.join(STATIC_DIR, "img")

os.makedirs(DB_DIR, exist_ok=True)

RESULTADOS_XML = globals().get("RESULTADOS_SORTEO_XML", os.path.join(DB_DIR, "resultados_sorteo.xml"))

def _pp_is_fecha_iso(s):
    try:
        datetime.fromisoformat((s or "").strip()); return True
    except Exception:
        return False

def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def _ensure_xml(path, root_name):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        ET.ElementTree(ET.Element(root_name)).write(path, encoding="utf-8", xml_declaration=True)
        return
    try:
        ET.parse(path)
    except ET.ParseError:
        ET.ElementTree(ET.Element(root_name)).write(path, encoding="utf-8", xml_declaration=True)

# Intenta usar una TTF del sistema; si no, Helvetica
def _pp_register_font():
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for p in [
            os.path.join(STATIC_DIR, "fonts", "DejaVuSans.ttf"),
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]:
            if os.path.exists(p):
                pdfmetrics.registerFont(TTFont("GLTTF", p))
                return "GLTTF"
    except Exception:
        pass
    return "Helvetica"

_PPFONT     = _pp_register_font()
_PPBOLDFONT = "Helvetica-Bold"
_ppT        = lambda s: "" if s is None else str(s)

# ---- Archivos del módulo ----
PAGOS_XML = globals().get(
    "PAGOS_PREMIOS_XML",
    os.path.join(DB_DIR, "pagos_premios.xml")
)
RECIBOS_DIR = os.path.join(
    globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")),
    "static",
    "tmp",
    "recibos"
)
CFG_JSON = globals().get("PAGOS_CONFIG_JSON", _persist("static", "db", "pagos_config.json"))

os.makedirs(RECIBOS_DIR, exist_ok=True)
_ensure_xml(PAGOS_XML, "pagos")

CFG_DEFAULT = {
    "company_name": "Gran Sorteo Ventanas",
    "city_default": "Vinces",
    "letterhead": "HOJA-MEMBRETADA.png"  # en static/img/
}

def _cfg_read():
    if not os.path.exists(CFG_JSON):
        with open(CFG_JSON, "w", encoding="utf-8") as f:
            json.dump(CFG_DEFAULT, f, ensure_ascii=False, indent=2)
        return CFG_DEFAULT.copy()
    try:
        with open(CFG_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in CFG_DEFAULT.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return CFG_DEFAULT.copy()

def _cfg_write(obj):
    with open(CFG_JSON, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ---- Utilidades de pagos ----
def _pp_premio_key(fecha_iso, figura_nombre, boleto):
    return f"{(fecha_iso or '').strip()}||{(figura_nombre or '').strip().lower()}||{(boleto or '').strip()}"

def _pp_leer_pagos_map():
    _ensure_xml(PAGOS_XML, "pagos")
    try:
        root = ET.parse(PAGOS_XML).getroot()
    except ET.ParseError:
        root = ET.Element("pagos")
    out = {}
    for p in root.findall("pago"):
        k = p.attrib.get("key") or _pp_premio_key(
            p.attrib.get("fecha_sorteo", ""),
            p.attrib.get("figura", ""),
            p.attrib.get("boleto", "")
        )
        out[k] = p.attrib
    return out

def _pp_guardar_pago_registro(pago_dict):
    _ensure_xml(PAGOS_XML, "pagos")
    tree = ET.parse(PAGOS_XML); root = tree.getroot()
    ET.SubElement(root, "pago", pago_dict)
    tree.write(PAGOS_XML, encoding="utf-8", xml_declaration=True)

def _pp_iter_ganadores_de_fecha(fecha_iso):
    if not _pp_is_fecha_iso(fecha_iso): return
    _ensure_xml(RESULTADOS_XML, "resultados")
    try:
        root = ET.parse(RESULTADOS_XML).getroot()
    except ET.ParseError:
        return
    dia = None
    for d in root.findall("dia"):
        if d.attrib.get("fecha") == fecha_iso:
            dia = d; break
    if dia is None: return
    for fig in dia.findall("fig"):
        figura = fig.attrib.get("nombre", "")
        for g in fig.findall("ganador"):
            yield {
                "fecha": fecha_iso,
                "figura": figura,
                "boleto": g.attrib.get("boleto",""),
                "nombre": g.attrib.get("nombre",""),
                "vendedor": g.attrib.get("vendedor",""),
                "sector": g.attrib.get("sector",""),
                "premio": _safe_float(g.attrib.get("premio"))
            }

def _pp_ultima_fecha_con_resultados():
    _ensure_xml(RESULTADOS_XML, "resultados")
    try:
        root = ET.parse(RESULTADOS_XML).getroot()
    except ET.ParseError:
        return date.today().isoformat()
    fechas = []
    for d in root.findall("dia"):
        f = (d.attrib.get("fecha") or "").strip()
        if _pp_is_fecha_iso(f): fechas.append(f)
    return (sorted(fechas)[-1] if fechas else date.today().isoformat())

# -------------------- Helpers de dibujo (justificado) --------------------
def _wrap_words(text, font, size, max_width):
    words = (text or "").split()
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if stringWidth(trial, font, size) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(cur); cur = [w]
    if cur: lines.append(cur)
    return lines

def _draw_justified_paragraph(c, text, x, y, width, font, size, leading, min_justify_ratio=0.65):
    """
    Dibuja párrafo JUSTIFICADO entre [x, x+width]. Devuelve el nuevo y.
    Las líneas demasiado cortas se dibujan alineadas a la izquierda.
    """
    lines_words = _wrap_words(text, font, size, width)
    for idx, words in enumerate(lines_words):
        line = " ".join(words)
        n_spaces = max(len(words) - 1, 0)
        line_w = stringWidth(line, font, size)

        to = c.beginText()
        to.setTextOrigin(x, y)
        to.setFont(font, size)

        # Última línea o línea corta -> izquierda normal
        if idx == len(lines_words) - 1 or n_spaces == 0 or (line_w / float(width)) < min_justify_ratio:
            to.textLine(line)
        else:
            extra = (width - line_w)
            to.setWordSpace(extra / n_spaces)
            to.textLine(line)
        c.drawText(to)
        y -= leading
    return y

# ---- Generador de ACTA PDF (título centrado, texto justificado) ----
def _pp_generate_recibo_pdf(recibo_id, payload):
    cfg = _cfg_read()
    out = os.path.join(RECIBOS_DIR, f"{recibo_id}.pdf")

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Fondo membrete "cover"
    letter = (payload.get("letterhead") or cfg.get("letterhead") or "").strip()
    letter_path = os.path.join(IMG_DIR, letter)
    if os.path.exists(letter_path):
        img = ImageReader(letter_path)
        iw, ih = img.getSize()
        s = max(W/float(iw), H/float(ih))
        tw, th = iw*s, ih*s
        c.drawImage(img, (W-tw)/2.0, (H-th)/2.0, width=tw, height=th, mask="auto")

    # Márgenes
    LM, RM = 64, 64
    TOP    = 240     # bajamos todo más
    WIDTH  = W - LM - RM
    LEAD   = 16
    y = H - TOP
    T = _ppT

    # ---- TÍTULO CENTRADO ----
    c.setFont(_PPBOLDFONT, 13)
    c.drawCentredString(W/2, y, T(f"Acta {recibo_id.upper()}"))
    y -= 28

    # Ciudad y Fecha (centradas)
    c.setFont(_PPFONT, 11)
    c.drawCentredString(W/2, y, T(f"Ciudad: {payload.get('ciudad', cfg.get('city_default',''))}")); y -= 16
    c.drawCentredString(W/2, y, T(f"Fecha: {payload.get('fecha_pago','')}")); y -= 26

    # ---- PÁRRAFOS JUSTIFICADOS ----
    empresa  = payload.get("empresa") or cfg.get("company_name","")
    monto    = _safe_float(payload.get("premio"))
    cobr     = T(payload.get("cobrador_nombre",""))
    planilla = T(payload.get("ganador_nombre",""))
    figura   = T(payload.get("figura",""))
    boleto   = T(payload.get("boleto",""))
    fsort    = T(payload.get("fecha_sorteo",""))

    # Párrafo 1 (con el texto de planilla entre paréntesis)
    p1 = (f"La empresa {empresa} hace la entrega formal de un premio valorado en "
          f"$ {monto:.2f} al señor(a) {cobr} "
          + (f"({planilla}) " if planilla else "")
          + "en calidad de ganador(a).")
    c.setFont(_PPFONT, 11)
    y = _draw_justified_paragraph(c, p1, LM, y, WIDTH, _PPFONT, 11, LEAD)

    # Párrafo 2
    p2 = (f"Ganador(a) de la figura {figura} con el boleto No. {boleto} "
          f"del sorteo realizado el día {fsort}.")
    y = _draw_justified_paragraph(c, p2, LM, y, WIDTH, _PPFONT, 11, LEAD)

    # Caducidad
    try:
        f_sorteo = datetime.fromisoformat(fsort).date()
        f_caduca = f_sorteo + timedelta(days=30)
        hoy_pago = datetime.fromisoformat(T(payload.get("fecha_pago",""))).date()
        dias = (f_caduca - hoy_pago).days
        p3 = f"Caducidad del premio: {f_caduca.isoformat()} (quedaban {dias} días)."
        y = _draw_justified_paragraph(c, p3, LM, y, WIDTH, _PPFONT, 10, 14)
    except Exception:
        pass

    y -= 10
    p4 = "El ganador firma como constancia de haber recibido el premio ganado a conformidad."
    y = _draw_justified_paragraph(c, p4, LM, y, WIDTH, _PPFONT, 11, LEAD)

    # ---- FIRMA (más abajo) ----
    y = max(y - 48, 260)  # garantiza que quede bien abajo
    x1, x2 = LM + 140, W - RM - 140
    c.setLineWidth(1)
    c.line(x1, y, x2, y)
    y -= 18
    c.setFont(_PPFONT, 12)
    c.drawCentredString(W/2, y, cobr.upper()); y -= 14
    c.setFont(_PPFONT, 10)
    c.drawCentredString(W/2, y, f"C.I.: {T(payload.get('cobrador_ci',''))}    Telf: {T(payload.get('cobrador_tel','-'))}")
    y -= 18
    c.setFont(_PPFONT, 9)
    c.drawCentredString(W/2, y, "Firma de quien cobra")

    c.save()
    with open(out, "wb") as f:
        f.write(buf.getvalue())
    return out

# ------------------ Rutas del módulo ------------------

@app.get("/pago-premios")
def pagos_premios_view():
    try:
        return render_template("pago_premios.html", fecha_inicial=_pp_ultima_fecha_con_resultados())
    except Exception:
        f = _pp_ultima_fecha_con_resultados()
        return f"""
        <html><body style="font-family:Arial;background:#0b1324;color:#e5e7eb">
            <div style="max-width:920px;margin:40px auto;padding:16px;background:#111827;border-radius:12px;">
                <h2>Pago de premios</h2>
                <p>Instala <code>templates/pago_premios.html</code>. Por ahora, usa las APIs:</p>
                <ul>
                    <li><code>/api/premios/ultima-fecha</code></li>
                    <li><code>/api/premios-pendientes?fecha={f}</code></li>
                </ul>
            </div>
        </body></html>
        """

@app.get("/api/pagos/config")
def api_pagos_config_get():
    return jsonify({"ok": True, "config": _cfg_read()})

@app.post("/api/pagos/config")
def api_pagos_config_set():
    data = request.get_json(silent=True) or {}
    cfg = _cfg_read()
    for k in ("company_name","city_default","letterhead"):
        if k in data and isinstance(data[k], str):
            cfg[k] = data[k].strip()
    _cfg_write(cfg)
    return jsonify({"ok": True, "config": cfg})

@app.get("/api/premios/ultima-fecha")
def api_premios_ultima_fecha():
    return jsonify({"ok": True, "fecha": _pp_ultima_fecha_con_resultados()})

@app.get("/api/premios-pendientes")
def api_premios_pendientes():
    fecha = (request.args.get("fecha") or _pp_ultima_fecha_con_resultados()).strip()
    if not _pp_is_fecha_iso(fecha):
        fecha = _pp_ultima_fecha_con_resultados()

    pagos = _pp_leer_pagos_map()
    hoy = datetime.now().date()
    f_sorteo = datetime.fromisoformat(fecha).date()
    caduca = f_sorteo + timedelta(days=30)

    out = []
    for g in _pp_iter_ganadores_de_fecha(fecha) or []:
        k = _pp_premio_key(fecha, g["figura"], g["boleto"])
        pp = pagos.get(k)
        out.append({
            **g,
            "key": k,
            "pagado": bool(pp),
            "expirado": (hoy > caduca),
            "fecha_caduca": caduca.isoformat(),
            "recibo_id": (pp or {}).get("recibo_id"),
            "pagado_por": (pp or {}).get("pagado_por"),
            "fecha_pago": (pp or {}).get("fecha_pago")
        })
    return jsonify({"ok": True, "items": out})

@app.post("/api/premios/pagar")
def api_premio_pagar():
    fecha = (request.form.get("fecha") or "").strip()
    figura = (request.form.get("figura") or "").strip()
    boleto = (request.form.get("boleto") or "").strip()
    ganador_nombre = (request.form.get("ganador_nombre") or "").strip()
    premio = _safe_float(request.form.get("premio"))
    cobr_ci  = (request.form.get("cobrador_ci") or "").strip()
    cobr_nom = (request.form.get("cobrador_nombre") or "").strip()
    ciudad   = (request.form.get("ciudad") or "").strip() or _cfg_read().get("city_default","")
    empresa  = (request.form.get("empresa") or "").strip() or _cfg_read().get("company_name","")
    tel      = (request.form.get("telefono") or "").strip()

    if not (_pp_is_fecha_iso(fecha) and figura and boleto and cobr_ci and cobr_nom):
        return jsonify({"ok": False, "msg": "Datos incompletos."}), 400

    f_sorteo = datetime.fromisoformat(fecha).date()
    if datetime.now().date() > f_sorteo + timedelta(days=30):
        return jsonify({"ok": False, "msg": "Premio caducado (más de 30 días)."}), 400

    key = _pp_premio_key(fecha, figura, boleto)
    pagos = _pp_leer_pagos_map()
    if key in pagos:
        return jsonify({"ok": False, "msg": "Este premio ya fue pagado."}), 400

    pagado_por = session.get("usuario", "GLSTUDIOS")
    fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    recibo_id  = re.sub(r'[^A-Za-z0-9]', '', f"{fecha}-{figura}-{boleto}-{int(datetime.now().timestamp())}")

    payload = {
        "fecha_sorteo": fecha, "ciudad": ciudad, "empresa": empresa,
        "cobrador_ci": cobr_ci, "cobrador_nombre": cobr_nom, "cobrador_tel": tel,
        "ganador_nombre": ganador_nombre, "figura": figura, "boleto": boleto,
        "premio": premio, "fecha_pago": fecha_pago
    }
    try:
        _pp_generate_recibo_pdf(recibo_id, payload)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error generando acta: {e}"}), 500

    _pp_guardar_pago_registro({
        "key": key,
        "fecha_sorteo": fecha,
        "figura": figura,
        "boleto": boleto,
        "ganador_nombre": ganador_nombre,
        "premio": f"{premio:.2f}",
        "cobrador_ci": cobr_ci,
        "cobrador_nombre": cobr_nom,
        "pagado_por": pagado_por,
        "fecha_pago": fecha_pago,
        "recibo_id": recibo_id
    })
    return jsonify({"ok": True, "recibo": f"/recibos/{recibo_id}.pdf", "recibo_id": recibo_id})

@app.get("/recibos/<rid>.pdf")
def pagos_descargar_recibo(rid):
    p = os.path.join(RECIBOS_DIR, f"{rid}.pdf")
    if not os.path.exists(p):
        return "No encontrado", 404
    return send_file(p, as_attachment=False, download_name=f"{rid}.pdf", mimetype="application/pdf")



#FIN PAGO DE PREOS





#SORTEOS CODIGOS GENERALES #

# -*- coding: utf-8 -*-
# GL Bingo — Sorteo + XMLs vMix (ventas, figuras, spinners, reintegro)
# Versión unificada: guarda XMLs en DATA/static/db y espejo en static/db

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
import os, re
from datetime import date, datetime
import xml.etree.ElementTree as ET


app.secret_key = "glbingo"

# -------------------- Paths base --------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR  = os.path.join(BASE_DIR, "static")
DATA_DIR    = globals().get("DATA_DIR") or os.path.join(BASE_DIR, "DATA")                 # carpeta de datos viva
DB_STATIC   = os.path.join(STATIC_DIR, "db")                 # espejo servible por /static/db/...
DB_DATA     = os.path.join(DATA_DIR, "static", "db")         # **principal** para Juego

LOGS_DATA = os.path.join(DATA_DIR, "static", "LOGS")

# asegurar directorios
for d in (
    STATIC_DIR,
    DB_STATIC,
    DATA_DIR,
    DB_DATA,
    os.path.join(DB_DATA, "spinners"),
    LOGS_DATA,
    os.path.join(STATIC_DIR, "LOGS"),
):
    os.makedirs(d, exist_ok=True)

LOGS_DIR = LOGS_DATA

# --------------- Helpers de escritura ---------------
def _write_xml_both(tree: ET.ElementTree, relpath: str):
    """Escribe el XML tanto en DATA/static/db/<relpath> como en static/db/<relpath>."""
    # destino en DATA
    dst_data   = os.path.join(DB_DATA, relpath)
    os.makedirs(os.path.dirname(dst_data), exist_ok=True)
    tree.write(dst_data, encoding="utf-8", xml_declaration=True)
    # espejo en STATIC
    dst_static = os.path.join(DB_STATIC, relpath)
    os.makedirs(os.path.dirname(dst_static), exist_ok=True)
    tree.write(dst_static, encoding="utf-8", xml_declaration=True)
    return {"data": dst_data, "static": dst_static}

def _write_text_both(text: str, relpath: str):
    dst_data   = os.path.join(DB_DATA, relpath)
    dst_static = os.path.join(DB_STATIC, relpath)
    os.makedirs(os.path.dirname(dst_data), exist_ok=True)
    os.makedirs(os.path.dirname(dst_static), exist_ok=True)
    with open(dst_data, "w", encoding="utf-8") as f:   f.write(text)
    with open(dst_static, "w", encoding="utf-8") as f: f.write(text)
    return {"data": dst_data, "static": dst_static}

# --------------- Rutas de archivos (relativas) ---------------
# Entradas
FIGS_XML_REL        = "figuras_por_fecha.xml"
ASIG_XML_REL        = "asignaciones.xml"
IMP_XML_PATH = (
    globals().get("IMPRESIONES_XML")
    or globals().get("LOGS_IMPRESIONES_XML")
    or os.path.join(LOGS_DIR, "impresiones.xml")
)
CATALOGO_FIGXML_REL = "datos_figuras.xml"                        # opcional

# Salidas vMix (todas en /db)
VMIX_VENTAS_REL       = "vmix_ventas.xml"
VMIX_FIG_NOMB_REL     = "vmix_figuras_nombres.xml"
VMIX_FIG_COLORES_REL  = "vmix_figuras_colores.xml"
VMIX_FIG_GRID_REL     = "vmix_figuras.xml"            # 25 celdas
VMIX_SPINNERS_REL     = "vmix_spinners.xml"           # PRIORIDAD para Juego
STD_SPINNERS_REL      = "spinners.xml"                # Fallback para Juego
VMIX_REINTEGRO_REL    = "vmix_reintegro.xml"
VMIX_REINTEGROS_REL   = "vmix_reintegros.xml"

# Ruta base de medios local (ajustable por variable de entorno)
VMIX_MEDIA_ROOT = (os.getenv("VMIX_MEDIA_ROOT") or r"D:\PRODUCCIONES\VENTANAS\MEDIA").strip().rstrip("\\/")

# Rutas reales de medios para reintegros (heredan de VMIX_MEDIA_ROOT si no defines variables individuales)
REINTEGRO_MEDIA_DIR  = (os.getenv("REINTEGRO_MEDIA_DIR")  or os.path.join(VMIX_MEDIA_ROOT, "REINTEGRO")).strip()
REINTEGROS_MEDIA_DIR = (os.getenv("REINTEGROS_MEDIA_DIR") or os.path.join(VMIX_MEDIA_ROOT, "REINTEGROS")).strip()

def _reintegro_stem(name: str) -> str:
    base = os.path.basename(str(name or "").strip())
    stem, _ext = os.path.splitext(base)
    return (stem or base).strip()

def _pick_file_case_insensitive(folder: str, preferred_names=None, prefix: str = ""):
    try:
        names = sorted(os.listdir(folder))
    except Exception:
        return ""

    preferred_names = [str(x or "").strip() for x in (preferred_names or []) if str(x or "").strip()]
    lower_map = {nm.lower(): nm for nm in names}

    for want in preferred_names:
        hit = lower_map.get(want.lower())
        if hit:
            return hit

    if prefix:
        pref = str(prefix).strip().lower()
        for nm in names:
            low = nm.lower()
            if low.startswith(pref) and low.endswith('.png'):
                return nm

    for nm in names:
        if nm.lower().endswith('.png'):
            return nm
    return ""

def _find_subdir_case_insensitive(folder: str, wanted: str) -> str:
    wanted = str(wanted or "").strip()
    if not wanted or not os.path.isdir(folder):
        return wanted
    try:
        for nm in os.listdir(folder):
            if nm.lower() == wanted.lower() and os.path.isdir(os.path.join(folder, nm)):
                return nm
    except Exception:
        pass
    return wanted

def _resolve_reintegro_media(reinteg_name: str):
    nombre = str(reinteg_name or "").strip()
    stem = _reintegro_stem(nombre)

    flat_carpeta = os.path.normpath(REINTEGRO_MEDIA_DIR) if str(REINTEGRO_MEDIA_DIR or "").strip() else ""
    flat_archivo = f"{stem}.png" if stem else ""
    flat_ruta = os.path.normpath(os.path.join(flat_carpeta, flat_archivo)) if flat_carpeta and flat_archivo else ""
    flat_encontrado = False

    if stem and flat_carpeta and os.path.isdir(flat_carpeta):
        hit = _pick_file_case_insensitive(flat_carpeta, [f"{stem}.png"], prefix=stem)
        if hit:
            flat_archivo = hit
            flat_ruta = os.path.normpath(os.path.join(flat_carpeta, hit))
            flat_encontrado = True

    seq_base = os.path.normpath(REINTEGROS_MEDIA_DIR) if str(REINTEGROS_MEDIA_DIR or "").strip() else ""
    seq_dir_name = _find_subdir_case_insensitive(seq_base, stem) if stem else ""
    seq_carpeta = os.path.normpath(os.path.join(seq_base, seq_dir_name)) if seq_base and seq_dir_name else (seq_base or "")
    seq_archivo = f"{stem}00000.png" if stem else ""
    seq_ruta = os.path.normpath(os.path.join(seq_carpeta, seq_archivo)) if seq_carpeta and seq_archivo else ""
    seq_encontrado = False

    if stem and seq_carpeta and os.path.isdir(seq_carpeta):
        hit = _pick_file_case_insensitive(seq_carpeta, [f"{stem}00000.png", f"{stem}0000.png", f"{stem}.png"], prefix=stem)
        if hit:
            seq_archivo = hit
            seq_ruta = os.path.normpath(os.path.join(seq_carpeta, hit))
            seq_encontrado = True

    return {
        "nombre": nombre,
        "flat_archivo": flat_archivo,
        "flat_ruta": flat_ruta,
        "flat_carpeta": flat_carpeta,
        "flat_encontrado": flat_encontrado,
        "seq_archivo": seq_archivo,
        "seq_ruta": seq_ruta,
        "seq_carpeta": seq_carpeta,
        "seq_encontrado": seq_encontrado,
    }

def _build_reintegro_root(fecha: str, nombre: str, archivo: str, ruta: str, carpeta: str, encontrado=False, click_count=0, click_token=""):
    root = ET.Element("reintegro", {"fecha": str(fecha or "")})
    nombre_limpio = _reintegro_stem(nombre)
    ET.SubElement(root, "nombre").text = str(nombre_limpio or "")
    ET.SubElement(root, "valor").text = str(nombre_limpio or "")
    ET.SubElement(root, "activo").text = "1" if str(nombre or "").strip() else "0"
    ET.SubElement(root, "click_count").text = str(int(click_count or 0))
    ET.SubElement(root, "click_token").text = str(click_token or "")
    ET.SubElement(root, "updated_at").text = datetime.now().isoformat(timespec="seconds")
    ET.SubElement(root, "archivo").text = str(archivo or "")
    ET.SubElement(root, "ruta").text = str(ruta or "")
    ET.SubElement(root, "carpeta").text = str(carpeta or "")
    ET.SubElement(root, "display").text = str(ruta or archivo or nombre or "")
    ET.SubElement(root, "encontrado").text = "1" if bool(encontrado) else "0"
    return root


# Nuevos pedidos
XML_FIGURAS_LISTA_REL = "xml_figuras_lista.xml"       # presentación (25 columnas)
XML_FIGURAS_2COL_REL  = "xml_figuras.xml"             # tablero (2 columnas)
SPINNERS_HIST_DIR_REL = "spinners"                    # carpeta para YYYY-MM-DD.xml

# Para leer entradas, preferimos DATA si existe; fallback a STATIC
def _in_db_existing(relname: str) -> str:
    p_data   = os.path.join(DB_DATA, relname)
    p_static = os.path.join(DB_STATIC, relname)
    if os.path.exists(p_data):   return p_data
    if os.path.exists(p_static): return p_static
    return p_data  # por defecto apuntamos a DATA

# --------------- Constantes de tablero ---------------
COLOR_ON  = "#ff0037"
COLOR_OFF = "#E8E8E8"

POS_25_ROW = [
    "B1","I1","N1","G1","O1",
    "B2","I2","N2","G2","O2",
    "B3","I3","N3","G3","O3",
    "B4","I4","N4","G4","O4",
    "B5","I5","N5","G5","O5",
]
POS_25_COL = [
    "B1","B2","B3","B4","B5",
    "I1","I2","I3","I4","I5",
    "N1","N2","N3","N4","N5",
    "G1","G2","G3","G4","G5",
    "O1","O2","O3","O4","O5",
]

# ---------------- Utils ----------------
def _parse_float(x):
    try:
        return float(str(x).replace(",", "."))
    except:
        return 0.0

def _fmt_int(x):
    try:
        n = int(round(float(x)))
        return str(n)
    except:
        return "0"

def code_for(name: str) -> str:
    """
    Genera un código ESTABLE y sin colisiones para las figuras.

    Importante:
    - Conserva TL1..TL4 para la lógica histórica.
    - Conserva códigos semánticos legacy para LLENA / RELLENA / COMPLETA.
    - Normaliza variantes del usuario como "LLENA 1" / "LLENA 2"
      a sus semánticas reales: LLENA / RELLENA.
    - Evita choques reales como:
        MINI K  -> MINIK
        MINI Y  -> MINIY
        NUMERO 4 -> NUM04
        NUMERO 12 -> NUM12
      que antes colisionaban por usar solo los primeros 4 caracteres.
    """
    raw = "" if name is None else str(name)
    n = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"\s+", " ", n).strip().upper()

    # Prioridad: tablas llenas numeradas / programadas
    if n.startswith("TABLA LLENA 1"): return "TL1"
    if n.startswith("TABLA LLENA 2"): return "TL2"
    if n.startswith("TABLA LLENA 3"): return "TL3"
    if n.startswith("TABLA LLENA 4"): return "TL4"

    # Variantes semánticas usadas por el usuario en figuras del día.
    # Ojo: esto NO significa "tabla programada"; solo normaliza el nombre.
    if re.fullmatch(r"LLENA\s*1", n): return "LLEN"
    if re.fullmatch(r"LLENA\s*2", n): return "RELL"
    if re.fullmatch(r"LLENA\s*3", n): return "YAPA"
    if re.fullmatch(r"LLENA\s*4", n): return "COMP"

    # Compatibilidad semántica legacy
    if "RELLENA" in n:
        return "RELL"
    if ("TABLA LLENA" in n) or (n == "LLENA") or n.endswith(" LLENA"):
        return "LLEN"
    if "COMPLETA" in n or "COMPLETO" in n:
        return "COMP"
    if n == "YAPA":
        return "YAPA"

    # Casos comunes con número explícito
    m_num = re.match(r"^(?:NUMERO|N)\s*(\d{1,2})$", n)
    if m_num:
        try:
            return f"NUM{int(m_num.group(1)):02d}"
        except Exception:
            pass

    # Código legible y suficientemente largo para no chocar entre figuras parecidas
    base = re.sub(r"[^A-Z0-9]", "", n)
    if not base:
        return "FIG"

    # Nombres cortos quedan casi idénticos al nombre real
    if len(base) <= 8:
        return base

    # Nombres largos: prefijo + hash corto estable
    import zlib
    crc = zlib.crc32(base.encode("utf-8")) % 10000
    return f"{base[:8]}{crc:04d}"

def _tl_semantic_name(nombre: str, code: str = "") -> str:
    """Convierte códigos/nombres internos a nombres semánticos visibles."""
    raw = str(nombre or "").strip()
    c = str(code or code_for(raw)).strip().upper()
    return {
        "TL1": "LLENA",
        "TL2": "RELLENA",
        "TL3": "YAPA",
        "TL4": "SUPER YAPA",
        "LLEN": "LLENA",
        "RELL": "RELLENA",
        "YAPA": "YAPA",
        "COMP": "COMPLETA",
    }.get(c, raw)

def _san4(v: str) -> str:
    """Normaliza string a 4 dígitos (0-9). Vacío => ''."""
    if v is None: return ""
    v = re.sub(r"\D", "", str(v))[:4]
    return v.zfill(4) if v else ""

# ---------------- Lecturas ----------------
def get_figuras_del_dia(fecha):
    """TL1..TL4 + resto (nombre/valor) desde figuras_por_fecha.xml."""
    tl = [0.0, 0.0, 0.0, 0.0]
    resto = []
    FIGS_XML = _in_db_existing(FIGS_XML_REL)
    if not os.path.exists(FIGS_XML):
        return tl, resto
    root = ET.parse(FIGS_XML).getroot()
    dia = root.find(f".//dia[@fecha='{fecha}']")
    if dia is None:
        return tl, resto
    for fig in dia.findall("fig"):
        nombre = (fig.attrib.get("nombre","") or "").strip()
        val    = _parse_float(fig.attrib.get("valor","0"))
        low    = nombre.lower()
        if "llena" in low and "1" in low:   tl[0] = val
        elif "llena" in low and "2" in low: tl[1] = val
        elif "llena" in low and "3" in low: tl[2] = val
        elif "llena" in low and "4" in low: tl[3] = val
        else:
            resto.append({"nombre": nombre, "valor": _fmt_int(val)})
    return tl, resto

def get_asignaciones_del_dia(fecha):
    """
    Lee asignaciones.xml para una fecha y devuelve rangos asignados.
    Devuelve lista de dicts con:
      - desde, hasta
      - vendedor (seudónimo o nombre)
      - planilla (número/id si existe)
      - rango (texto 'a-b')
      - serie_archivo (si la planilla lo trae)
    """
    filas = []
    ASIG_XML = _in_db_existing(ASIG_XML_REL)
    if not os.path.exists(ASIG_XML):
        return filas
    root = ET.parse(ASIG_XML).getroot()
    dia = root.find(f".//dia[@fecha='{fecha}']")
    if dia is None:
        return filas

    for vend in dia.findall("vendedor"):
        nom = vend.attrib.get("seudonimo") or (
            " ".join([vend.attrib.get("nombre", ""), vend.attrib.get("apellido", "")]).strip() or "—"
        )

        for p in vend.findall("planilla"):
            r = (p.attrib.get("rango", "") or "").strip()
            if r and "-" in r:
                a, b = r.split("-", 1)
                desde, hasta = a.strip(), b.strip()
            else:
                desde = p.attrib.get("desde", "") or p.attrib.get("inicio", "") or "0"
                hasta = p.attrib.get("hasta", "") or p.attrib.get("fin", "") or "0"

            plan_num = (p.attrib.get("numero") or p.attrib.get("planilla") or p.attrib.get("id") or "").strip()
            serie_archivo = (p.attrib.get("serie_archivo") or p.attrib.get("serie") or "").strip()

            # normaliza rango para mostrar en UI/PDF
            rango_txt = r.strip() if r else (f"{desde}-{hasta}" if str(desde).strip() and str(hasta).strip() else "")

            filas.append({
                "desde": desde,
                "hasta": hasta,
                "vendedor": nom,
                "planilla": plan_num,
                "rango": rango_txt,
                "serie_archivo": serie_archivo,
            })

    return filas


def _serie_equal(a: str, b: str) -> bool:
    """Compara series ignorando carpetas (Srs_ib1.csv vs data/Srs_ib1.csv)."""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return True
    try:
        return os.path.basename(a) == os.path.basename(b)
    except Exception:
        return a == b


def buscar_info_por_boleto(fecha, boleto, serie_archivo: str = ""):
    """
    Devuelve dict con vendedor/planilla/rango para un boleto (tabla) dentro del rango asignado.
    Si serie_archivo se proporciona y en asignaciones viene 'serie_archivo', se filtra por serie.
    """
    try:
        num = int(str(boleto).strip())
    except Exception:
        return {}

    serie_archivo = (serie_archivo or "").strip()
    for f in get_asignaciones_del_dia(fecha):
        try:
            a = int(re.sub(r"\D", "", str(f.get("desde", ""))) or 0)
            b = int(re.sub(r"\D", "", str(f.get("hasta", ""))) or 0)
        except Exception:
            continue

        if not (a <= num <= b):
            continue

        # si tenemos serie, intentamos hacer match con la serie guardada en la planilla
        s2 = (f.get("serie_archivo") or "").strip()
        if serie_archivo and s2 and not _serie_equal(serie_archivo, s2):
            continue

        return f

    return {}


def buscar_vendedor_por_boleto(fecha, boleto):
    info = buscar_info_por_boleto(fecha, boleto)
    return (info.get("vendedor") or "").strip()


def get_impresiones_info(fecha):
    serie = "—"; primer = 0; ultimo = 0; total_b = 0; valor_b = 0; rein = "—"
    if not os.path.exists(IMP_XML_PATH):
        return dict(
            serie_detectada=serie, primer_boleto=str(primer), ultimo_boleto=str(ultimo),
            boletos_impresos=_fmt_int(total_b), valor_boleto=_fmt_int(valor_b), reintegro_dia=rein
        )
    root = ET.parse(IMP_XML_PATH).getroot()
    primera = None; ultima  = None
    for n in root.findall("impresion"):
        if n.attrib.get("tipo") != "boletos": continue
        if (n.findtext("fecha_sorteo") or "").strip() != fecha: continue
        try: total_b += int(n.findtext("total_boletos") or "0")
        except: pass
        valor_b = _parse_float(n.findtext("valor") or "0")
        if (n.findtext("reintegro_especial") or "").strip():
            rein = n.findtext("reintegro_especial").strip()
        try:
            d = int(n.attrib.get("desde","0") or 0)
            h = int(n.attrib.get("hasta","0") or 0)
            if primera is None or d < primera: primera = d
            if ultima  is None or h > ultima:  ultima  = h
        except: pass
        if n.attrib.get("serie_archivo"): serie = n.attrib.get("serie_archivo")
    primer = primera or 0
    ultimo = ultima or 0
    return dict(
        serie_detectada=serie, primer_boleto=str(primer), ultimo_boleto=str(ultimo),
        boletos_impresos=_fmt_int(total_b), valor_boleto=_fmt_int(valor_b), reintegro_dia=rein
    )

# --------- Catálogo de figuras dibujadas (opcional) ----------
def load_catalogo_figuras():
    """Índice por código con sus celdas."""
    catalogo = {}
    CATALOGO_FIGXML = _in_db_existing(CATALOGO_FIGXML_REL)
    if not os.path.exists(CATALOGO_FIGXML):
        return catalogo
    root = ET.parse(CATALOGO_FIGXML).getroot()
    for f in root.findall(".//figura"):
        nombre = (f.attrib.get("nombre","") or "").strip()
        codigo = code_for(nombre)
        cbloq  = f.attrib.get("centro_bloqueado","0")
        celdas = []
        for c in f.findall("celda"):
            idx   = int(c.attrib.get("idx","0") or 0)
            color = (c.attrib.get("color","#FFFFFF") or "#FFFFFF").upper()
            pos   = c.attrib.get("pos") or (POS_25_ROW[idx-1] if 1 <= idx <= 25 else "B1")
            celdas.append({"idx": idx, "color": color, "pos": pos})
        if len(celdas) < 25:
            ya = {x["idx"] for x in celdas}
            for i in range(1,26):
                if i not in ya:
                    celdas.append({"idx": i, "color": "#FFFFFF", "pos": POS_25_ROW[i-1]})
            celdas.sort(key=lambda x:x["idx"])
        catalogo[codigo] = {"nombre": nombre, "centro_bloqueado": cbloq, "celdas": celdas}
    return catalogo

# ======================== Escritura de XMLs ========================
def grid_colors_for(codigo, catalogo):
    """25 colores ON/OFF para una figura."""
    if codigo in ("TL1","TL2") and codigo not in catalogo:
        return [COLOR_ON] * 25
    if codigo not in catalogo:
        return [COLOR_OFF] * 25
    cols = []
    for cel in sorted(catalogo[codigo]["celdas"], key=lambda x:x["idx"]):
        raw = (cel["color"] or "#FFFFFF").upper()
        on = raw not in ("#FFFFFF", "#FFF", "#FFFFFF00", "TRANSPARENT")
        cols.append(COLOR_ON if on else COLOR_OFF)
    if len(cols) < 25:
        cols += [COLOR_OFF] * (25 - len(cols))
    return cols[:25]

def write_vmix_ventas(fecha, imp):
    root = ET.Element("ventas", {"fecha": fecha})
    ET.SubElement(root, "serie").text            = imp["serie_detectada"]
    ET.SubElement(root, "primer_boleto").text    = imp["primer_boleto"]
    ET.SubElement(root, "ultimo_boleto").text    = imp["ultimo_boleto"]
    ET.SubElement(root, "valor_boleto").text     = _fmt_int(imp["valor_boleto"])
    ET.SubElement(root, "boletos_impresos").text = _fmt_int(imp["boletos_impresos"])
    _write_xml_both(ET.ElementTree(root), VMIX_VENTAS_REL)

def write_vmix_figuras_listas(fecha, tl, resto):
    """vmix_figuras_nombres.xml y vmix_figuras_colores.xml. Retorna lista ordenada del día."""
    fig_elegidas = []
    if tl[0] > 0: fig_elegidas.append({"nombre":"Tabla Llena 1","valor":_fmt_int(tl[0])})
    if tl[1] > 0: fig_elegidas.append({"nombre":"Tabla Llena 2","valor":_fmt_int(tl[1])})
    if tl[2] > 0: fig_elegidas.append({"nombre":"Tabla Llena 3","valor":_fmt_int(tl[2])})
    if tl[3] > 0: fig_elegidas.append({"nombre":"Tabla Llena 4","valor":_fmt_int(tl[3])})
    fig_elegidas += resto

    root = ET.Element("figuras_nombres", {"fecha": fecha})
    for f in fig_elegidas:
        ET.SubElement(root, "fig", {"nombre": f["nombre"], "valor": f["valor"]})
    _write_xml_both(ET.ElementTree(root), VMIX_FIG_NOMB_REL)

    root2 = ET.Element("figuras_colores", {"fecha": fecha})
    for f in fig_elegidas:
        ET.SubElement(root2, "fig", {"nombre": f["nombre"], "valor": f["valor"], "codigo": code_for(f["nombre"]), "color": ""})
    _write_xml_both(ET.ElementTree(root2), VMIX_FIG_COLORES_REL)

    return fig_elegidas

def write_vmix_figuras_grid(fecha, figuras_dia, catalogo):
    """vmix_figuras.xml (cada figura con 25 celdas idx/pos/color)."""
    root = ET.Element("figuras")
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for f in figuras_dia:
        nombre = f["nombre"]; codigo = code_for(nombre)
        nodo_f = ET.SubElement(root, "figura", {
            "nombre": nombre, "fecha": ahora,
            "centro_bloqueado": "1" if (codigo in catalogo and catalogo[codigo].get("centro_bloqueado","0") == "1") else "0"
        })
        cols = grid_colors_for(codigo, catalogo)
        for i, col in enumerate(cols, start=1):
            ET.SubElement(nodo_f, "celda", {"idx": str(i), "color": col, "pos": POS_25_ROW[i-1]})
    _write_xml_both(ET.ElementTree(root), VMIX_FIG_GRID_REL)

def write_xml_figuras_lista_presentacion(fecha, figuras_dia, catalogo):
    """
    XML de presentación para vMix.
    Mantiene el formato legado (<figuraB1>..</figuraB1>) y agrega
    una sección explícita <cuadros><cuadro codigo=... color=.../></cuadros>.
    """
    root = ET.Element("juego", {"fecha": str(fecha)})
    ident = 1
    for f in figuras_dia:
        nombre = f["nombre"]; valor = f["valor"]; codigo = code_for(nombre)
        fila = ET.SubElement(root, "filaFiguras")
        ET.SubElement(fila, "figuraIDENTIFICADOR").text = str(ident)
        ET.SubElement(fila, "figuraCODIGO").text        = str(codigo)
        ET.SubElement(fila, "figuraNOMBRE").text        = nombre
        ET.SubElement(fila, "figuraVALOR").text         = str(valor)
        ET.SubElement(fila, "figuraESTADO").text        = "inactivo"

        cols = grid_colors_for(codigo, catalogo)
        pos_to_col = {POS_25_ROW[i]: cols[i] for i in range(25)}

        # Formato legado (figuraB1..figuraO5)
        for lab in POS_25_COL:  # orden columna-primero
            ET.SubElement(fila, f"figura{lab}").text = pos_to_col[lab]

        # Formato explícito (cuadros con código/color)
        cuadros = ET.SubElement(fila, "cuadros")
        for i, lab in enumerate(POS_25_COL, start=1):
            ET.SubElement(cuadros, "cuadro", {
                "idx": str(i),
                "codigo": lab,
                "pos": lab,
                "color": pos_to_col[lab],
            })

        ident += 1

    _write_xml_both(ET.ElementTree(root), XML_FIGURAS_LISTA_REL)
    # Alias de presentación para vMix (opcional, sin romper lo anterior)
    try:
        _write_xml_both(ET.ElementTree(root), "vmix_figuras_presentacion.xml")
    except Exception:
        pass

def write_xml_figuras_tablero_2columnas(fecha, figuras_dia):
    """
    <juego fecha="..."><filaTablero><colA>Nombre|Valor|Estado</colA><colB>...</colB></filaTablero></juego>
    """
    root = ET.Element("juego", {"fecha": fecha})
    fila = ET.SubElement(root, "filaTablero")
    a = figuras_dia[0] if len(figuras_dia) >= 1 else None
    b = figuras_dia[1] if len(figuras_dia) >= 2 else None
    def pack(fig): return f"{fig['nombre']}|{fig['valor']}|inactivo" if fig else ""
    ET.SubElement(fila, "colA").text = pack(a)
    ET.SubElement(fila, "colB").text = pack(b)
    _write_xml_both(ET.ElementTree(root), XML_FIGURAS_2COL_REL)


def write_vmix_figuras_dia_resumen(fecha, figuras_dia, catalogo):
    """
    Resumen completo del día para vMix/DS:
    - nombre, valor, código, estado
    - los 25 cuadros con código/idx/color
    """
    root = ET.Element("figuras_dia", {"fecha": str(fecha)})
    for pos, f in enumerate(figuras_dia, start=1):
        nombre = str(f.get("nombre") or "")
        valor  = str(f.get("valor") or "0")
        codigo = code_for(nombre)
        nodo = ET.SubElement(root, "figura", {
            "orden": str(pos),
            "codigo": str(codigo),
            "nombre": nombre,
            "valor": valor,
            "estado": "inactivo",
        })
        cols = grid_colors_for(codigo, catalogo)
        # IMPORTANTE: grid_colors_for() devuelve colores en orden POR FILAS (B1,I1,N1,G1,O1,...)
        # Para evitar cruces (ej. 4TA LINEA mal pintada), publicamos los cuadros en ese mismo orden.
        for i in range(25):
            lab = POS_25_ROW[i]
            ET.SubElement(nodo, "cuadro", {
                "idx": str(i+1),
                "codigo": lab,
                "pos": lab,
                "color": cols[i],
            })

    _write_xml_both(ET.ElementTree(root), "vmix_figuras_dia.xml")
    return True

# ======================== Panel 5xN para vMix (figura base + overlay de estado) ========================
VMIX_FIG_PANEL_REL = "vmix_figuras_panel.xml"
XML_FIG_PANEL_REL  = "xml_figuras_panel.xml"
VMIX_ESTADOS_BASE  = (os.getenv("VMIX_ESTADOS_BASE") or os.path.join(VMIX_MEDIA_ROOT, "ESTADOS")).strip() or os.path.join(VMIX_MEDIA_ROOT, "ESTADOS")

def _panel_name_display(nombre: str) -> str:
    return _tl_semantic_name(str(nombre or ""), code_for(str(nombre or "")))

def _panel_state_norm(estado: str) -> str:
    s = re.sub(r"\s+", " ", str(estado or "INACTIVO").strip().upper())
    if s == "ACTIVO":
        s = "INACTIVO"
    if s not in ("INACTIVO", "SE FUE", "SE QUEDO"):
        s = "INACTIVO"
    return s

def _panel_overlay_file(estado: str) -> str:
    e = _panel_state_norm(estado)
    if e == "SE FUE":
        return "SE FUE_00000.PNG"
    if e == "SE QUEDO":
        return "SE QUEDO_00000.PNG"
    return "INACTIVO.PNG"

def _panel_overlay_dir(estado: str) -> str:
    e = _panel_state_norm(estado)
    if e == "SE QUEDO":
        return os.path.join(VMIX_ESTADOS_BASE, "SE QUEDO")
    # INACTIVO usa la misma carpeta base que SE FUE, con PNG transparente/vacío
    return os.path.join(VMIX_ESTADOS_BASE, "SE FUE")

def _panel_overlay_path(estado: str) -> str:
    return os.path.join(_panel_overlay_dir(estado), _panel_overlay_file(estado))

def _panel_apply_visual_states(fecha: str, figuras_dia: list):
    try:
        cache = (_safe_json_read(FIG_ESTADOS_JSON) or {}).get(str(fecha), {}) or {}
    except Exception:
        cache = {}
    if not cache:
        return list(figuras_dia or [])

    out = []
    for f in (figuras_dia or []):
        if not isinstance(f, dict):
            continue
        nombre = str(f.get("nombre") or "").strip()
        valor = f.get("valor", 0)
        key_disp = _panel_name_display(nombre)
        estado = cache.get(nombre) or cache.get(key_disp) or f.get("estado") or "INACTIVO"
        out.append({
            "nombre": nombre,
            "valor": valor,
            "estado": _panel_state_norm(estado),
        })
    return out

def write_vmix_figuras_panel(fecha, figuras_dia, catalogo):
    """
    XML para vMix Data Source:
    - 5 figuras por fila
    - mínimo 2 filas (10 slots)
    - la figura base NO cambia; el estado sale en campos overlay aparte
    - overlay pensado para capas ESTADO1, ESTADO2, ... en vMix
    """
    figuras = _panel_apply_visual_states(str(fecha or ""), list(figuras_dia or []))

    rows = max(2, (len(figuras) + 4) // 5)
    total_slots = rows * 5

    while len(figuras) < total_slots:
        figuras.append({"nombre": "-", "valor": "-", "estado": "INACTIVO"})

    root = ET.Element("figuras_panel", {
        "fecha": str(fecha or ""),
        "filas": str(rows),
        "por_fila": "5",
        "total_slots": str(total_slots),
    })

    for fila_idx in range(rows):
        fila_node = ET.SubElement(root, "fila")
        ET.SubElement(fila_node, "numero_fila").text = str(fila_idx + 1)

        for col_idx in range(5):
            slot_global = fila_idx * 5 + col_idx
            item = figuras[slot_global] if slot_global < len(figuras) else {"nombre": "-", "valor": "-", "estado": "INACTIVO"}

            nombre_raw = str(item.get("nombre") or "-").strip() or "-"
            nombre_disp = _panel_name_display(nombre_raw) if nombre_raw != "-" else "-"
            valor_raw = item.get("valor", "-")
            valor_txt = "-" if nombre_raw == "-" else _fmt_int(valor_raw)
            estado = _panel_state_norm(item.get("estado") or "INACTIVO")
            codigo = "-" if nombre_raw == "-" else code_for(nombre_raw)
            colors = ["#FFFFFF"] * 25 if nombre_raw == "-" else grid_colors_for(codigo, catalogo or {})
            colors = [str(c or "#FFFFFF").upper() for c in (colors[:25] + ["#FFFFFF"] * 25)[:25]]

            pref = f"fig{col_idx + 1}_"
            overlay_png = _panel_overlay_file(estado)
            overlay_dir = _panel_overlay_dir(estado)
            overlay_src = _panel_overlay_path(estado)

            ET.SubElement(fila_node, f"{pref}slot").text = str(slot_global + 1)
            ET.SubElement(fila_node, f"{pref}fila").text = str(fila_idx + 1)
            ET.SubElement(fila_node, f"{pref}columna").text = str(col_idx + 1)
            ET.SubElement(fila_node, f"{pref}nombre").text = nombre_disp
            ET.SubElement(fila_node, f"{pref}valor").text = valor_txt
            ET.SubElement(fila_node, f"{pref}codigo").text = codigo
            ET.SubElement(fila_node, f"{pref}estado").text = estado

            # Compatibilidad con lo que ya estás usando
            ET.SubElement(fila_node, f"{pref}estado_png").text = overlay_png
            ET.SubElement(fila_node, f"{pref}estado_carpeta").text = overlay_dir
            ET.SubElement(fila_node, f"{pref}estado_ruta").text = overlay_src
            ET.SubElement(fila_node, f"{pref}estado_source").text = overlay_src

            # Campos claros para superposición de imagen (ESTADO1, ESTADO2, ...)
            ET.SubElement(fila_node, f"{pref}overlay_png").text = overlay_png
            ET.SubElement(fila_node, f"{pref}overlay_carpeta").text = overlay_dir
            ET.SubElement(fila_node, f"{pref}overlay_source").text = overlay_src
            ET.SubElement(fila_node, f"{pref}overlay_visible").text = "1"

            ET.SubElement(fila_node, f"{pref}flag_inactivo").text = "1" if estado == "INACTIVO" else "0"
            ET.SubElement(fila_node, f"{pref}flag_se_fue").text = "1" if estado == "SE FUE" else "0"
            ET.SubElement(fila_node, f"{pref}flag_se_quedo").text = "1" if estado == "SE QUEDO" else "0"

            for lab, color in zip(POS_25_ROW, colors):
                ET.SubElement(fila_node, f"{pref}codigo_{lab}").text = lab
                ET.SubElement(fila_node, f"{pref}figura{lab}").text = color

    tree = ET.ElementTree(root)
    _write_xml_both(tree, VMIX_FIG_PANEL_REL)
    _write_xml_both(tree, XML_FIG_PANEL_REL)
    return True

def _next_sorteo_identificador_auto():
    """
    Genera H1, H2, H3... leyendo sorteos.xml finalizados o existentes.
    """
    try:
        tree = _sorteos_load_tree()
        root = tree.getroot()
        maxn = 0
        for d in root.findall("dia"):
            ident = (d.attrib.get("identificador") or "").strip().upper()
            m = re.match(r"^H\s*(\d+)$", ident)
            if m:
                maxn = max(maxn, int(m.group(1)))
        return f"H{maxn+1}"
    except Exception:
        return "H1"

def _sorteo_generar_xmls(fecha, spins=None, cfg_in=None):
    """
    Genera TODOS los XMLs del sorteo sin cambiar estado.
    Se usa en Guardar, Activar y Finalizar para que todo quede sincronizado.
    """
    cfg_in = cfg_in or {}
    spins = spins if isinstance(spins, list) else (cfg_in.get("spinners") if isinstance(cfg_in.get("spinners"), list) else [])

    imp = get_impresiones_info(fecha)
    tl, resto = get_figuras_del_dia(fecha)

    # Permitir edición visual de TL desde sorteo sin tocar figuras_por_fecha.xml
    for idx_tl, key in enumerate(("tl1", "tl2", "tl3", "tl4")):
        if cfg_in.get(key) not in (None, ""):
            tl[idx_tl] = _parse_float(cfg_in.get(key))

    # 1) ventas (boletos/serie/valor)
    write_vmix_ventas(fecha, imp)

    # 2) listas de figuras (nombre/valor/código)
    figuras_dia = write_vmix_figuras_listas(fecha, tl, resto)

    # 3) grid de figuras (25 celdas idx/pos/color)
    catalogo = load_catalogo_figuras()
    write_vmix_figuras_grid(fecha, figuras_dia, catalogo)

    # 4) XML presentación (legado + cuadros explícitos)
    write_xml_figuras_lista_presentacion(fecha, figuras_dia, catalogo)

    # 5) XML tablero 2 columnas (overlay rápido)
    write_xml_figuras_tablero_2columnas(fecha, figuras_dia)

    # 6) XML resumen figuras del día (nuevo, claro para vMix Data Source)
    write_vmix_figuras_dia_resumen(fecha, figuras_dia, catalogo)
    try:
        write_vmix_figuras_panel(fecha, figuras_dia, catalogo)
    except Exception:
        pass

    # 7) Spinners del día (manuales del usuario)
    save_spinners(spins or [], fecha)

    # 8) Reintegro/comodín
    write_vmix_reintegro(fecha, imp.get("reintegro_dia", ""))

    total_prem = int(round(sum(tl) + sum(_parse_float(f.get("valor")) for f in resto)))

    return {
        "impresion": imp,
        "tl": tl,
        "resto": resto,
        "figuras_dia": figuras_dia,
        "total_premios": total_prem,
    }

# ================== Spinners (estándar) ==================
def make_spinners_tree(vals, fecha_iso: str):
    root = ET.Element("spinners", {"fecha": fecha_iso})
    for i in range(20):
        v = _san4(vals[i] if i < len(vals) else "")
        n = ET.SubElement(root, "n", {"i": str(i+1)})
        if v:
            n.set("v", v)
    return ET.ElementTree(root)

def save_spinners(vals, fecha_iso: str | None = None):
    """
    Guarda spinners en:
      - vmix_spinners.xml (prioridad para Juego)
      - spinners.xml      (fallback)
      - spinners/YYYY-MM-DD.xml (histórico)
    Y en **ambas ubicaciones**: DATA/static/db y static/db.
    """
    if not fecha_iso:
        fecha_iso = date.today().isoformat()
    tree = make_spinners_tree(vals, fecha_iso)

    _write_xml_both(tree, VMIX_SPINNERS_REL)
    _write_xml_both(tree, STD_SPINNERS_REL)
    # Alias explícito para sorteo/presentación (sin romper nombres anteriores)
    try:
        _write_xml_both(tree, "vmix_spinners_dia.xml")
    except Exception:
        pass
    # histórico por fecha
    hist_rel = os.path.join(SPINNERS_HIST_DIR_REL, f"{fecha_iso}.xml")
    _write_xml_both(tree, hist_rel)

    return {
        "vmix": os.path.join(DB_DATA, VMIX_SPINNERS_REL),
        "std":  os.path.join(DB_DATA, STD_SPINNERS_REL),
        "hist": os.path.join(DB_DATA, hist_rel),
    }

def read_spinners_current():
    """Devuelve lista de 20 (4 dígitos) desde vmix_spinners.xml o spinners.xml."""
    for rel in (VMIX_SPINNERS_REL, STD_SPINNERS_REL):
        p = _in_db_existing(rel)
        if os.path.exists(p):
            try:
                root = ET.parse(p).getroot()
                out=[]
                for n in root.findall(".//n"):
                    v = n.attrib.get("v") or (n.text or "")
                    v = _san4(v)
                    out.append(v if v else "")
                return (out + [""]*20)[:20]
            except:
                pass
    return [""]*20

def write_vmix_reintegro(fecha, reinteg_name):
    meta = _resolve_reintegro_media(reinteg_name)

    root_flat = _build_reintegro_root(
        fecha, meta.get("nombre"), meta.get("flat_archivo"), meta.get("flat_ruta"),
        meta.get("flat_carpeta"), meta.get("flat_encontrado"), 0, ""
    )
    root_seq = _build_reintegro_root(
        fecha, meta.get("nombre"), meta.get("seq_archivo"), meta.get("seq_ruta"),
        meta.get("seq_carpeta"), meta.get("seq_encontrado"), 0, ""
    )

    _write_xml_both(ET.ElementTree(root_flat), VMIX_REINTEGRO_REL)
    _write_xml_both(ET.ElementTree(root_seq), VMIX_REINTEGROS_REL)
    return meta

# ---------------- Sorteos (estado/config por fecha) ----------------
def _sorteos_load_tree():
    p = _in_db_existing("sorteos.xml")
    if os.path.exists(p):
        try:
            return ET.parse(p)
        except Exception:
            pass
    return ET.ElementTree(ET.Element("sorteos"))

def _sorteos_write_tree(tree):
    return _write_xml_both(tree, "sorteos.xml")


def _sorteo_activo_snapshot_paths():
    """Rutas candidatas para snapshot del sorteo activo (JSON) en DATA y espejo static."""
    paths = []
    try:
        if "DB_DATA" in globals() and globals().get("DB_DATA"):
            paths.append(os.path.join(globals().get("DB_DATA"), "sorteo_activo.json"))
    except Exception:
        pass
    try:
        if "DB_STATIC" in globals() and globals().get("DB_STATIC"):
            paths.append(os.path.join(globals().get("DB_STATIC"), "sorteo_activo.json"))
    except Exception:
        pass
    try:
        ddir = globals().get("DATA_DIR")
        if ddir:
            paths.append(os.path.join(ddir, "static", "db", "sorteo_activo.json"))
    except Exception:
        pass
    try:
        base_dir = globals().get("BASE_DIR") or os.path.dirname(os.path.abspath(__file__))
        paths.append(os.path.join(base_dir, "static", "db", "sorteo_activo.json"))
    except Exception:
        pass
    # únicos
    out = []
    seen = set()
    for p in paths:
        if not p:
            continue
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        out.append(ap)
    return out

def _write_sorteo_activo_snapshot(info: dict | None):
    """Guarda un snapshot simple del sorteo activo/finalizado para que /juego lo lea sin ambigüedad."""
    info = info or {}
    payload = {
        "fecha": str(info.get("fecha") or "").strip(),
        "nombre_sorteo": str(info.get("nombre_sorteo") or info.get("sorteo") or "").strip(),
        "identificador": str(info.get("identificador") or info.get("id") or "").strip(),
        "estado": str(info.get("estado") or "").strip(),
        "activo": str(info.get("activo") or "0").strip(),
        "finalizado": str(info.get("finalizado") or "0").strip(),
        "origen_finalizado": str(info.get("origen_finalizado") or info.get("historico") or "0").strip(),
        "actualizado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # compatibilidad: si viene activo=1 pero estado vacío, marcar activo
    if payload["activo"] in ("1", "true", "True", "si", "sí", "activo") and not payload["estado"]:
        payload["estado"] = "activo"
    for p in _sorteo_activo_snapshot_paths():
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return payload

def _sorteos_find_dia(root, fecha):
    for d in root.findall("dia"):
        if (d.attrib.get("fecha") or "").strip() == str(fecha):
            return d
    return None

def _sorteos_get_or_create_dia(root, fecha):
    d = _sorteos_find_dia(root, fecha)
    if d is not None:
        return d
    d = ET.SubElement(root, "dia", {
        "fecha": str(fecha),
        "activo": "0",
        "finalizado": "0",
        "estado": "borrador",
        "creado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    ET.SubElement(d, "basicos")
    ET.SubElement(d, "programacion")
    ET.SubElement(d, "tablas_llenas")
    ET.SubElement(d, "figuras")
    ET.SubElement(d, "spinners")
    ET.SubElement(d, "cierre")
    ET.SubElement(d, "boletos_no_vendidos_qr")
    return d

def _node(dia, tag):
    n = dia.find(tag)
    return n if n is not None else ET.SubElement(dia, tag)

def _sorteo_upsert_boletos_no_vendidos_qr(fecha: str, seudonimo: str, items: list):
    tree = _sorteos_load_tree()
    root = tree.getroot()
    dia = _sorteos_get_or_create_dia(root, fecha)
    cont = _node(dia, "boletos_no_vendidos_qr")
    cont.attrib["actualizado_en"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    seud = str(seudonimo or "").strip()
    vnode = None
    for v in cont.findall("vendedor"):
        if (v.attrib.get("seudonimo") or "").strip() == seud:
            vnode = v
            break
    if vnode is None:
        vnode = ET.SubElement(cont, "vendedor", {"seudonimo": seud})

    for oldb in list(vnode):
        vnode.remove(oldb)

    clean = []
    seen = set()
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        serie = str(it.get("serie") or "").strip()
        num = str(it.get("boleto") or "").strip()
        if not serie or not num:
            continue
        key = (serie.upper(), num)
        if key in seen:
            continue
        seen.add(key)
        clean.append({
            "serie": serie,
            "boleto": num,
            "idx": str(it.get("idx") or ""),
            "planilla": str(it.get("planilla") or ""),
            "ts": str(it.get("ts") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        })

    clean.sort(key=lambda x: _safe_int_local(x.get("idx", 0), 0))
    vnode.attrib["total"] = str(len(clean))
    vnode.attrib["actualizado_en"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for it in clean:
        ET.SubElement(vnode, "boleto", {
            "serie": it["serie"],
            "numero": it["boleto"],
            "idx": it["idx"],
            "planilla": it["planilla"],
            "ts": it["ts"],
        })

    total = 0
    for v in cont.findall("vendedor"):
        total += _safe_int_local(v.attrib.get("total", 0), 0)
    cont.attrib["total"] = str(total)

    _sorteos_write_tree(tree)
    return True

def _fmt_money2(x):
    try:
        return f"{float(str(x).replace(',', '.')):.2f}"
    except Exception:
        return "0.00"

def _load_spinners_for_fecha(fecha_iso: str):
    rel_hist = os.path.join(SPINNERS_HIST_DIR_REL, f"{fecha_iso}.xml")
    for rel in (rel_hist, VMIX_SPINNERS_REL, STD_SPINNERS_REL):
        p = _in_db_existing(rel)
        if not os.path.exists(p):
            continue
        try:
            root = ET.parse(p).getroot()
            out = []
            for n in root.findall('.//n'):
                v = _san4(n.attrib.get('v') or (n.text or ''))
                out.append(v if v else '')
            return (out + ['']*20)[:20]
        except Exception:
            pass
    return ['']*20

def _sorteo_build_defaults(fecha):
    imp = get_impresiones_info(fecha)
    tl, resto = get_figuras_del_dia(fecha)
    total_boletos_x_valor = int(_fmt_int(imp["boletos_impresos"])) * int(_fmt_int(imp["valor_boleto"]))
    total_premios = int(round(sum(tl) + sum(_parse_float(f["valor"]) for f in resto)))
    return {
        "fecha": fecha,
        "nombre_sorteo": f"Sorteo {fecha}",
        "identificador": "",
        "serie_detectada": imp["serie_detectada"],
        "primer_boleto": _fmt_int(imp["primer_boleto"]),
        "ultimo_boleto": _fmt_int(imp["ultimo_boleto"]),
        "reintegro_dia": imp["reintegro_dia"],
        "valor_boleto": _fmt_int(imp["valor_boleto"]),
        "boletos_impresos": _fmt_int(imp["boletos_impresos"]),
        "total_a_jugar": _fmt_int(total_boletos_x_valor),
        "total_premios": _fmt_int(total_premios),
        "tl1": _fmt_int(tl[0]), "tl2": _fmt_int(tl[1]), "tl3": _fmt_int(tl[2]), "tl4": _fmt_int(tl[3]),
        "figs_resto": resto,
        "spinners": _load_spinners_for_fecha(fecha),
        "estado": "borrador",
        "activo": "0",
        "finalizado": "0",
        "creado_en": "",
        "activado_en": "",
        "finalizado_en": "",
        "premios_a_pagar_cantidad": "0",
        "premios_a_pagar_monto": "0.00",
        "premios_no_salieron_cantidad": "0",
        "premios_no_salieron_monto": "0.00",
        "observacion_cierre": "",
        "boletos_no_vendidos_qr": [],
        "boletos_no_vendidos_qr_total": "0",
        "boletos_no_vendidos_qr_actualizado": "",
        "tl_programadas_activas": "0",
        "tl_programadas_cartones": "",
        "tl_programada_llena": "",
        "tl_programada_rellena": "",
        "tl_programada_yapa": "",
        "tl_objetivo_llena": "",
        "tl_objetivo_rellena": "",
        "tl_objetivo_yapa": "",
        "tl_serie_llena": "",
        "tl_serie_rellena": "",
        "tl_serie_yapa": "",
        "tl_serie_super_yapa": "",
    }

def _sorteo_read_config(fecha):
    cfg = _sorteo_build_defaults(fecha)
    try:
        tree = _sorteos_load_tree()
        root = tree.getroot()
        d = _sorteos_find_dia(root, fecha)
        if d is None:
            return cfg

        cfg.update({
            "estado": (d.attrib.get("estado") or cfg["estado"]),
            "activo": (d.attrib.get("activo") or cfg["activo"]),
            "finalizado": (d.attrib.get("finalizado") or cfg["finalizado"]),
            "creado_en": (d.attrib.get("creado_en") or ""),
            "activado_en": (d.attrib.get("activado_en") or ""),
            "finalizado_en": (d.attrib.get("finalizado_en") or ""),
        })

        b = d.find("basicos")
        if b is not None:
            cfg["nombre_sorteo"] = (b.attrib.get("nombre_sorteo") or cfg["nombre_sorteo"])
            cfg["identificador"] = (b.attrib.get("identificador") or cfg["identificador"])

        pr = d.find("programacion")
        if pr is not None:
            for k in ("serie_detectada","primer_boleto","ultimo_boleto","reintegro_dia","valor_boleto","boletos_impresos","total_a_jugar","total_premios"):
                if pr.attrib.get(k) not in (None, ""):
                    cfg[k] = pr.attrib.get(k)

        tl = d.find("tablas_llenas")
        if tl is not None:
            for k in ("tl1","tl2","tl3","tl4"):
                if tl.attrib.get(k) not in (None, ""):
                    cfg[k] = tl.attrib.get(k)
            if tl.attrib.get("tl_programadas_activas") not in (None, ""):
                cfg["tl_programadas_activas"] = tl.attrib.get("tl_programadas_activas")
            if tl.attrib.get("tl_programadas_cartones") not in (None, ""):
                cfg["tl_programadas_cartones"] = tl.attrib.get("tl_programadas_cartones")
            for k in (
                "tl_programada_llena", "tl_programada_rellena", "tl_programada_yapa",
                "tl_objetivo_llena", "tl_objetivo_rellena", "tl_objetivo_yapa",
                "tl_serie_llena", "tl_serie_rellena", "tl_serie_yapa", "tl_serie_super_yapa",
            ):
                if tl.attrib.get(k) not in (None, ""):
                    cfg[k] = tl.attrib.get(k)

        sp = d.find("spinners")
        if sp is not None:
            vals = []
            for n in sp.findall("n"):
                vals.append(_san4(n.attrib.get("v") or (n.text or "")) or "")
            if vals:
                cfg["spinners"] = (vals + [""]*20)[:20]

        c = d.find("cierre")
        if c is not None:
            cfg["premios_a_pagar_cantidad"] = c.attrib.get("premios_a_pagar_cantidad", cfg["premios_a_pagar_cantidad"])
            cfg["premios_a_pagar_monto"] = c.attrib.get("premios_a_pagar_monto", cfg["premios_a_pagar_monto"])
            cfg["premios_no_salieron_cantidad"] = c.attrib.get("premios_no_salieron_cantidad", cfg["premios_no_salieron_cantidad"])
            cfg["premios_no_salieron_monto"] = c.attrib.get("premios_no_salieron_monto", cfg["premios_no_salieron_monto"])
            cfg["observacion_cierre"] = c.attrib.get("observacion", cfg["observacion_cierre"])

        qn = d.find("boletos_no_vendidos_qr")
        if qn is not None:
            cfg["boletos_no_vendidos_qr_total"] = qn.attrib.get("total", cfg.get("boletos_no_vendidos_qr_total", "0"))
            cfg["boletos_no_vendidos_qr_actualizado"] = qn.attrib.get("actualizado_en", "")
            grupos = []
            for v in qn.findall("vendedor"):
                lst = []
                for b in v.findall("boleto"):
                    lst.append({
                        "serie": b.attrib.get("serie", ""),
                        "boleto": b.attrib.get("numero", ""),
                        "idx": b.attrib.get("idx", ""),
                        "planilla": b.attrib.get("planilla", ""),
                        "ts": b.attrib.get("ts", ""),
                    })
                lst.sort(key=lambda x: _safe_int_local(x.get("idx", 0), 0))
                grupos.append({
                    "seudonimo": v.attrib.get("seudonimo", ""),
                    "total": str(v.attrib.get("total", len(lst))),
                    "actualizado_en": v.attrib.get("actualizado_en", ""),
                    "boletos": lst,
                })
            grupos.sort(key=lambda x: (x.get("seudonimo") or "").lower())
            cfg["boletos_no_vendidos_qr"] = grupos
    except Exception:
        pass
    return cfg

def _sorteo_save_config(fecha, payload, *, activar=False, finalizar=False):
    payload = payload or {}
    defaults = _sorteo_build_defaults(fecha)
    tree = _sorteos_load_tree()
    root = tree.getroot()
    dia = _sorteos_get_or_create_dia(root, fecha)

    # básicos
    b = _node(dia, "basicos")
    b.attrib.update({
        "nombre_sorteo": (str(payload.get("nombre_sorteo") or defaults["nombre_sorteo"]).strip()),
        "identificador": (str(payload.get("identificador") or "").strip()),
    })

    # programacion (snapshot del día)
    pr = _node(dia, "programacion")
    pr.attrib.update({
        "serie_detectada": str(payload.get("serie_detectada") or defaults["serie_detectada"]),
        "primer_boleto": _fmt_int(payload.get("primer_boleto") or defaults["primer_boleto"]),
        "ultimo_boleto": _fmt_int(payload.get("ultimo_boleto") or defaults["ultimo_boleto"]),
        "reintegro_dia": str(payload.get("reintegro_dia") or defaults["reintegro_dia"]),
        "valor_boleto": _fmt_int(payload.get("valor_boleto") or defaults["valor_boleto"]),
        "boletos_impresos": _fmt_int(payload.get("boletos_impresos") or defaults["boletos_impresos"]),
        "total_a_jugar": _fmt_int(payload.get("total_a_jugar") or defaults["total_a_jugar"]),
        "total_premios": _fmt_int(payload.get("total_premios") or defaults["total_premios"]),
    })

    # TLs (editables desde UI)
    tln = _node(dia, "tablas_llenas")
    for k in ("tl1","tl2","tl3","tl4"):
        tln.attrib[k] = _fmt_int(payload.get(k) if payload.get(k) not in (None,"") else defaults[k])
    tln.attrib["tl_programadas_activas"] = str(
        payload.get("tl_programadas_activas")
        if payload.get("tl_programadas_activas") not in (None, "")
        else tln.attrib.get("tl_programadas_activas", defaults.get("tl_programadas_activas", "0"))
    ).strip() or "0"
    tln.attrib["tl_programadas_cartones"] = str(
        payload.get("tl_programadas_cartones")
        if payload.get("tl_programadas_cartones") not in (None, "")
        else tln.attrib.get("tl_programadas_cartones", defaults.get("tl_programadas_cartones", ""))
    ).strip()
    for _k in (
        "tl_programada_llena", "tl_programada_rellena", "tl_programada_yapa",
        "tl_objetivo_llena", "tl_objetivo_rellena", "tl_objetivo_yapa",
        "tl_serie_llena", "tl_serie_rellena", "tl_serie_yapa", "tl_serie_super_yapa",
    ):
        tln.attrib[_k] = str(
            payload.get(_k)
            if payload.get(_k) not in (None, "")
            else tln.attrib.get(_k, defaults.get(_k, ""))
        ).strip()

    # figuras snapshot (resto)
    figs = _node(dia, "figuras")
    for old in list(figs):
        figs.remove(old)
    for f in (defaults.get("figs_resto") or []):
        ET.SubElement(figs, "fig", {
            "nombre": str(f.get("nombre") or ""),
            "valor": _fmt_int(f.get("valor") or 0)
        })

    # spinners snapshot
    spins = payload.get("spinners")
    if not isinstance(spins, list):
        spins = defaults.get("spinners") or []
    spn = _node(dia, "spinners")
    for old in list(spn):
        spn.remove(old)
    for i in range(20):
        v = _san4(spins[i] if i < len(spins) else "")
        n = ET.SubElement(spn, "n", {"i": str(i+1)})
        if v:
            n.attrib["v"] = v

    # cierre
    c = _node(dia, "cierre")
    c.attrib.update({
        "premios_a_pagar_cantidad": _fmt_int(payload.get("premios_a_pagar_cantidad") or c.attrib.get("premios_a_pagar_cantidad") or 0),
        "premios_a_pagar_monto": _fmt_money2(payload.get("premios_a_pagar_monto") if payload.get("premios_a_pagar_monto") not in (None,"") else c.attrib.get("premios_a_pagar_monto", "0")),
        "premios_no_salieron_cantidad": _fmt_int(payload.get("premios_no_salieron_cantidad") or c.attrib.get("premios_no_salieron_cantidad") or 0),
        "premios_no_salieron_monto": _fmt_money2(payload.get("premios_no_salieron_monto") if payload.get("premios_no_salieron_monto") not in (None,"") else c.attrib.get("premios_no_salieron_monto", "0")),
        "observacion": str(payload.get("observacion_cierre") or c.attrib.get("observacion") or "").strip(),
    })

    # estado
    nowtxt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if activar:
        for x in root.findall("dia"):
            x.attrib["activo"] = "0"
            if (x.attrib.get("estado") or "") == "activo":
                x.attrib["estado"] = "borrador"
        dia.attrib["activo"] = "1"
        dia.attrib["finalizado"] = "0"
        dia.attrib["estado"] = "activo"
        dia.attrib["activado_en"] = nowtxt
    elif finalizar:
        dia.attrib["activo"] = "0"
        dia.attrib["finalizado"] = "1"
        dia.attrib["estado"] = "finalizado"
        dia.attrib["finalizado_en"] = nowtxt
    else:
        # solo guardar configuración
        if (dia.attrib.get("estado") or "") not in ("activo","finalizado"):
            dia.attrib["estado"] = "borrador"

    _sorteos_write_tree(tree)
    return _sorteo_read_config(fecha)

# ---------------- Rutas ----------------

from flask import render_template, request

@app.route("/juego/spinner_overlay")
def spinner_overlay():
    return render_template("spinner_overlay.html")




@app.route("/inicio-sorteo")
def root():
    return redirect(url_for("sorteo", fecha=date.today().isoformat()))

@app.route("/sorteos")
def sorteos():
    return redirect(url_for("sorteo", fecha=request.args.get("fecha") or date.today().isoformat()))

@app.route("/sorteo")
def sorteo():
    fecha = request.args.get("fecha") or date.today().isoformat()
    cfg = _sorteo_read_config(fecha)
    asignaciones = get_asignaciones_del_dia(fecha)
    return render_template(
        "sorteo.html",
        fecha=fecha,
        serie_detectada=cfg["serie_detectada"],
        primer_boleto=cfg["primer_boleto"],
        ultimo_boleto=cfg["ultimo_boleto"],
        reintegro_dia=cfg["reintegro_dia"],
        valor_boleto=cfg["valor_boleto"],
        boletos_impresos=cfg["boletos_impresos"],
        total_a_jugar=cfg["total_a_jugar"],
        total_premios=cfg["total_premios"],
        tl1=cfg["tl1"], tl2=cfg["tl2"], tl3=cfg["tl3"], tl4=cfg["tl4"],
        figs_resto=cfg.get("figs_resto") or [],
        asignaciones=asignaciones,
        spinners=cfg.get("spinners") or ["" for _ in range(20)],
        sorteo_nombre=cfg.get("nombre_sorteo") or f"Sorteo {fecha}",
        sorteo_identificador=cfg.get("identificador") or "",
        sorteo_estado=cfg.get("estado") or "borrador",
        sorteo_activo=cfg.get("activo") or "0",
        sorteo_finalizado=cfg.get("finalizado") or "0",
        creado_en=cfg.get("creado_en") or "",
        activado_en=cfg.get("activado_en") or "",
        finalizado_en=cfg.get("finalizado_en") or "",
        premios_a_pagar_cantidad=cfg.get("premios_a_pagar_cantidad") or "0",
        premios_a_pagar_monto=cfg.get("premios_a_pagar_monto") or "0.00",
        premios_no_salieron_cantidad=cfg.get("premios_no_salieron_cantidad") or "0",
        premios_no_salieron_monto=cfg.get("premios_no_salieron_monto") or "0.00",
        observacion_cierre=cfg.get("observacion_cierre") or "",
        boletos_no_vendidos_qr=cfg.get("boletos_no_vendidos_qr") or [],
        boletos_no_vendidos_qr_total=cfg.get("boletos_no_vendidos_qr_total") or "0",
        boletos_no_vendidos_qr_actualizado=cfg.get("boletos_no_vendidos_qr_actualizado") or "",
        tl_programadas_activas=cfg.get("tl_programadas_activas") or "0",
        tl_programadas_cartones=cfg.get("tl_programadas_cartones") or "",
        tl_programada_llena=cfg.get("tl_programada_llena") or "",
        tl_programada_rellena=cfg.get("tl_programada_rellena") or "",
        tl_programada_yapa=cfg.get("tl_programada_yapa") or "",
        tl_objetivo_llena=cfg.get("tl_objetivo_llena") or "",
        tl_objetivo_rellena=cfg.get("tl_objetivo_rellena") or "",
        tl_objetivo_yapa=cfg.get("tl_objetivo_yapa") or "",
        tl_serie_llena=cfg.get("tl_serie_llena") or "",
        tl_serie_rellena=cfg.get("tl_serie_rellena") or "",
        tl_serie_yapa=cfg.get("tl_serie_yapa") or "",
    )

@app.route("/api/vendedor-por-boleto", methods=["GET","POST"])
def api_vend_boleto():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        fecha  = data.get("fecha",""); boleto = data.get("boleto","")
    else:
        fecha  = request.args.get("fecha",""); boleto = request.args.get("boleto","")
    vendedor = buscar_vendedor_por_boleto(fecha, boleto)
    return jsonify(ok=True, vendedor=vendedor)

@app.post("/api/sorteo/secure-access")
def api_sorteo_secure_access():
    data = request.get_json(silent=True) or {}
    scope = (data.get('scope') or '').strip()
    password = data.get('password') or ''
    ok, msg = _verify_scope_password(scope, password)
    if not ok:
        return jsonify(ok=False, mensaje=msg), 403
    return jsonify(ok=True, mensaje='Acceso concedido')


def _bonus_history_items_for_date(fecha_iso: str):
    items = []
    try:
        if not os.path.isdir(LOGS_DIR):
            return items
        for name in sorted(os.listdir(LOGS_DIR), reverse=True):
            if not (name.startswith('bonus_') and name.endswith('.json')):
                continue
            path = os.path.join(LOGS_DIR, name)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue
            fecha_item = str(data.get('fecha_sorteo') or data.get('fecha') or '').strip()
            if fecha_item != str(fecha_iso or '').strip():
                continue
            req = data.get('requested') or {}
            win = data.get('winners') or {}
            items.append({
                'log_id': data.get('log_id') or (name.replace('bonus_', '').replace('.json', '')),
                'serie_archivo': data.get('serie_archivo') or '',
                'desde': data.get('desde') or '',
                'hasta': data.get('hasta') or '',
                'numbers': data.get('numbers') or data.get('bonus_numbers') or [],
                'requested': {str(k): int(req.get(str(k), 0) or 0) for k in [5,4,3,2,1]},
                'winners': {str(k): len(win.get(str(k), []) or []) if isinstance(win.get(str(k), []), list) else int(win.get(str(k), 0) or 0) for k in [5,4,3,2,1]},
                'url_html': url_for('bonus_informe_html', log_id=int(data.get('log_id') or 0)) if str(data.get('log_id') or '').isdigit() else '#',
            })
    except Exception:
        return items
    return items


@app.get("/api/sorteo/bonus-historial")
def api_sorteo_bonus_historial():
    fecha = (request.args.get('fecha') or date.today().isoformat()).strip()
    if not _sorteo_scope_allowed('bonus_history'):
        return jsonify(ok=False, mensaje='No tienes permiso para esta sección.'), 403
    return jsonify(ok=True, items=_bonus_history_items_for_date(fecha))

@app.post("/api/sorteo/guardar")
def api_sorteo_guardar():
    data = request.get_json(silent=True) or {}
    fecha = (data.get("fecha") or date.today().isoformat()).strip()
    cfg = data.get("config") or {}
    spins = data.get("spinners")
    if isinstance(spins, list):
        cfg["spinners"] = spins

    # IMPORTANTE: Guardar también genera/sincroniza XMLs (figuras/spinners/presentación)
    xml_info = _sorteo_generar_xmls(fecha, spins=spins if isinstance(spins, list) else None, cfg_in=cfg)

    # Guarda configuración del sorteo (estado borrador/activo según corresponda)
    cfg.setdefault("total_premios", _fmt_int(xml_info.get("total_premios", 0)))
    saved = _sorteo_save_config(fecha, cfg, activar=False, finalizar=False)

    return jsonify(
        ok=True,
        mensaje="Configuración guardada y XMLs sincronizados correctamente.",
        sorteo=saved
    )

# --------- NUEVOS endpoints de spinners ---------
@app.get("/api/spinners")
def api_spinners_get():
    return jsonify(ok=True, spinners=read_spinners_current())

@app.post("/api/spinners/guardar")
def api_spinners_guardar():
    data  = request.get_json(silent=True) or {}
    fecha = data.get("fecha") or date.today().isoformat()
    vals  = data.get("spinners", [])
    files = save_spinners(vals, fecha)
    return jsonify(ok=True, files=files, fecha=fecha)

# --------- Activar sorteo (escribe TODO) ---------
@app.post("/api/activar-sorteo")
def sorteo_activar():
    data  = request.get_json(silent=True) or {}
    fecha = (data.get("fecha") or "").strip()
    spins = data.get("spinners", [])
    cfg_in = data.get("config") or {}
    if not fecha:
        return jsonify(ok=False, mensaje="Falta la fecha")

    # Lee lo ya guardado para no perder campos cuando el frontend activa sin pasar toda la configuración.
    try:
        prev = _sorteo_read_config(fecha)
    except Exception:
        prev = {}

    # Si el frontend no envía spinners al activar, NO los borres:
    # carga los spinners guardados para esa fecha desde sorteos.xml.
    try:
        if (not isinstance(spins, list)) or (isinstance(spins, list) and not any(str(x).strip() for x in spins)):
            spins = prev.get("spinners", []) if isinstance(prev, dict) else spins
    except Exception:
        pass

    # Genera/sincroniza XMLs usando lo que el usuario cargó manualmente (spinners, TL editadas, etc.)
    xml_info = _sorteo_generar_xmls(fecha, spins=spins if isinstance(spins, list) else None, cfg_in=cfg_in)

    imp = xml_info.get("impresion", {}) or {}
    tl = xml_info.get("tl", [0, 0, 0, 0])
    total_prem = int(xml_info.get("total_premios", 0))

    # Guardar configuración/estado del sorteo en sorteos.xml
    # Mezclamos: valores ya guardados -> valores nuevos del frontend -> datos calculados del día.
    defaults = _sorteo_build_defaults(fecha)
    base_cfg = dict(prev) if isinstance(prev, dict) else {}
    if isinstance(cfg_in, dict):
        for _k, _v in cfg_in.items():
            base_cfg[_k] = _v

    cfg_payload = {
        "nombre_sorteo": (base_cfg.get("nombre_sorteo") or f"Sorteo {fecha}"),
        "identificador": (base_cfg.get("identificador") or ""),
        "serie_detectada": (base_cfg.get("serie_detectada") or defaults.get("serie_detectada") or imp.get("serie_detectada", "")),
        "primer_boleto": (base_cfg.get("primer_boleto") or defaults.get("primer_boleto") or imp.get("primer_boleto", 0)),
        "ultimo_boleto": (base_cfg.get("ultimo_boleto") or defaults.get("ultimo_boleto") or imp.get("ultimo_boleto", 0)),
        "reintegro_dia": (base_cfg.get("reintegro_dia") or defaults.get("reintegro_dia") or imp.get("reintegro_dia", "")),
        "valor_boleto": (base_cfg.get("valor_boleto") or defaults.get("valor_boleto") or imp.get("valor_boleto", 0)),
        "boletos_impresos": (base_cfg.get("boletos_impresos") or defaults.get("boletos_impresos") or imp.get("boletos_impresos", 0)),
        "total_a_jugar": (base_cfg.get("total_a_jugar") or defaults.get("total_a_jugar") or 0),
        "total_premios": _fmt_int(total_prem),
        "tl1": _fmt_int(tl[0]), "tl2": _fmt_int(tl[1]), "tl3": _fmt_int(tl[2]), "tl4": _fmt_int(tl[3]),
        "tl_programadas_activas": base_cfg.get("tl_programadas_activas", prev.get("tl_programadas_activas", "0") if isinstance(prev, dict) else "0"),
        "tl_programadas_cartones": base_cfg.get("tl_programadas_cartones", prev.get("tl_programadas_cartones", "") if isinstance(prev, dict) else ""),
        "tl_programada_llena": base_cfg.get("tl_programada_llena", prev.get("tl_programada_llena", "") if isinstance(prev, dict) else ""),
        "tl_programada_rellena": base_cfg.get("tl_programada_rellena", prev.get("tl_programada_rellena", "") if isinstance(prev, dict) else ""),
        "tl_programada_yapa": base_cfg.get("tl_programada_yapa", prev.get("tl_programada_yapa", "") if isinstance(prev, dict) else ""),
        "tl_objetivo_llena": base_cfg.get("tl_objetivo_llena", prev.get("tl_objetivo_llena", "") if isinstance(prev, dict) else ""),
        "tl_objetivo_rellena": base_cfg.get("tl_objetivo_rellena", prev.get("tl_objetivo_rellena", "") if isinstance(prev, dict) else ""),
        "tl_objetivo_yapa": base_cfg.get("tl_objetivo_yapa", prev.get("tl_objetivo_yapa", "") if isinstance(prev, dict) else ""),
        "tl_serie_llena": base_cfg.get("tl_serie_llena", prev.get("tl_serie_llena", "") if isinstance(prev, dict) else ""),
        "tl_serie_rellena": base_cfg.get("tl_serie_rellena", prev.get("tl_serie_rellena", "") if isinstance(prev, dict) else ""),
        "tl_serie_yapa": base_cfg.get("tl_serie_yapa", prev.get("tl_serie_yapa", "") if isinstance(prev, dict) else ""),
        "spinners": spins if isinstance(spins, list) else [],
        "premios_a_pagar_cantidad": base_cfg.get("premios_a_pagar_cantidad", 0),
        "premios_a_pagar_monto": base_cfg.get("premios_a_pagar_monto", 0),
        "premios_no_salieron_cantidad": base_cfg.get("premios_no_salieron_cantidad", 0),
        "premios_no_salieron_monto": base_cfg.get("premios_no_salieron_monto", 0),
        "observacion_cierre": base_cfg.get("observacion_cierre") or "",
    }
    saved = _sorteo_save_config(fecha, cfg_payload, activar=True, finalizar=False)
    try:
        _write_sorteo_activo_snapshot({
            "fecha": fecha,
            "nombre_sorteo": saved.get("nombre_sorteo") if isinstance(saved, dict) else (cfg_payload.get("nombre_sorteo") or f"Sorteo {fecha}"),
            "identificador": (saved.get("identificador") if isinstance(saved, dict) else cfg_payload.get("identificador")) or "",
            "estado": "activo",
            "activo": "1",
            "finalizado": "0",
            "origen_finalizado": str((prev or {}).get("finalizado") or "0"),
        })
    except Exception:
        pass

    try:
        _restore_game_state_for_fecha(str(fecha), save_if_missing=True)
    except Exception:
        pass

    return jsonify(ok=True, mensaje="Sorteo activado y XMLs sincronizados correctamente.", sorteo=saved)

@app.post("/api/finalizar-sorteo")
def api_finalizar_sorteo():
    data = request.get_json(silent=True) or {}
    fecha = (data.get("fecha") or "").strip()
    if not fecha:
        return jsonify(ok=False, mensaje="Falta la fecha del sorteo")

    prev = _sorteo_read_config(fecha) if fecha else {}
    cfg = dict(prev) if isinstance(prev, dict) else {}
    cfg_in = data.get("config") or {}
    if isinstance(cfg_in, dict):
        for _k, _v in cfg_in.items():
            cfg[_k] = _v
    spins = data.get("spinners") if isinstance(data.get("spinners"), list) else None
    if spins is not None:
        cfg["spinners"] = spins

    # Re-sincroniza XMLs al cerrar/procesar el día (último snapshot del sorteo)
    xml_info = _sorteo_generar_xmls(fecha, spins=spins, cfg_in=cfg)
    cfg.setdefault("total_premios", _fmt_int(xml_info.get("total_premios", 0)))

    # Identificador automático H1, H2... al procesar/cerrar (si el usuario no lo puso)
    ident_actual = str(cfg.get("identificador") or "").strip()
    if not ident_actual:
        try:
            actual_cfg = _sorteo_read_config(fecha)
            ident_actual = str((actual_cfg or {}).get("identificador") or "").strip()
        except Exception:
            ident_actual = ""
    if not ident_actual:
        cfg["identificador"] = _next_sorteo_identificador_auto()

    saved = _sorteo_save_config(fecha, cfg, activar=False, finalizar=True)
    try:
        _write_sorteo_activo_snapshot({
            "fecha": fecha,
            "nombre_sorteo": (saved.get("nombre_sorteo") if isinstance(saved, dict) else cfg.get("nombre_sorteo")) or f"Sorteo {fecha}",
            "identificador": (saved.get("identificador") if isinstance(saved, dict) else cfg.get("identificador")) or "",
            "estado": "finalizado",
            "activo": "0",
            "finalizado": "1",
            "origen_finalizado": "1",
        })
    except Exception:
        pass
    try:
        _save_game_state_snapshot(str(fecha))
    except Exception:
        pass
    return jsonify(ok=True, mensaje="Sorteo finalizado, procesado y XMLs sincronizados.", sorteo=saved)

# --------- (Opcional) servir DATA por URL para depurar ---------
@app.route("/data-db/<path:rel>")
def serve_data_db(rel):
    """Útil para ver que realmente se escribió en DATA/static/db/."""
    return send_from_directory(DB_DATA, rel, as_attachment=False)

# ----------------- MAIN -----------------
if False and __name__ == "__main__":  # DESHABILITADO (evita arrancar antes de cargar rutas)
    app.run(debug=True)




#FIN SORTEO #





# ================= CONTABILIDAD: helpers y rutas =================
# Seguridad por rol, gastos, banco, resumen, y endpoints de curvas por vendedor

import os
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from flask import jsonify, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from io import BytesIO
try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None

# === Comprobantes (subidas) ===
ALLOWED_EXTS = {"pdf", "png", "jpg", "jpeg", "webp"}

# Guardado PERSISTENTE: todo va a DATA_DIR/static/CONTABILIDAD/...
# y se "espeja" a /static/CONTABILIDAD/... para que el navegador pueda abrirlo.
import shutil

PUBLIC_STATIC_DIR   = os.path.join(BASE_DIR, "static")
PERSIST_STATIC_DIR  = os.path.join(DATA_DIR, "static")
PERSIST_CONTAB_DIR  = os.path.join(PERSIST_STATIC_DIR, "CONTABILIDAD")

COMPROB_DIR         = os.path.join(PERSIST_CONTAB_DIR, "comprobantes")
BANK_FILES          = os.path.join(COMPROB_DIR, "banco")
GASTO_FILES         = os.path.join(COMPROB_DIR, "gastos")

PUBLIC_COMPROB_DIR  = os.path.join(PUBLIC_STATIC_DIR, "CONTABILIDAD", "comprobantes")
PUBLIC_BANK_FILES   = os.path.join(PUBLIC_COMPROB_DIR, "banco")
PUBLIC_GASTO_FILES  = os.path.join(PUBLIC_COMPROB_DIR, "gastos")

os.makedirs(BANK_FILES, exist_ok=True)
os.makedirs(GASTO_FILES, exist_ok=True)
os.makedirs(PUBLIC_BANK_FILES, exist_ok=True)
os.makedirs(PUBLIC_GASTO_FILES, exist_ok=True)

def _mirror_persist_static_to_public(persist_abs: str) -> str | None:
    """Copia un archivo dentro de DATA_DIR/static/... hacia BASE_DIR/static/... y devuelve la ruta pública."""
    try:
        if not persist_abs or not os.path.exists(persist_abs):
            return None
        persist_abs_norm = os.path.abspath(persist_abs)
        persist_root = os.path.abspath(PERSIST_STATIC_DIR)
        if os.path.commonpath([persist_abs_norm, persist_root]) != persist_root:
            return None
        # persist_abs debería estar dentro de DATA_DIR/static
        rel = os.path.relpath(persist_abs, PERSIST_STATIC_DIR).replace("\\", "/")
        public_abs = os.path.join(PUBLIC_STATIC_DIR, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(public_abs), exist_ok=True)
        shutil.copy2(persist_abs, public_abs)
        return public_abs
    except Exception as e:
        print(f"[WARN] mirror static falló: {e}")
        return None

def _ext_ok(filename: str) -> bool:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return ext in ALLOWED_EXTS

def _save_upload(fs, folder: str, base: str) -> str:
    """Guarda comprobante en persistente y retorna ruta relativa desde /static.

    - Si es imagen (png/jpg/jpeg/webp): la comprime y la guarda como .jpg (ligera).
    - Si es PDF: la guarda tal cual.
    """
    fname = secure_filename(fs.filename or "")
    ext0 = os.path.splitext(fname)[1].lower().lstrip(".")
    if not ext0 or ext0 not in ALLOWED_EXTS:
        raise ValueError("extensión no permitida")

    # Límite duro de subida (evita reventar el servidor con fotos gigantes)
    try:
        if request.content_length and request.content_length > 25 * 1024 * 1024:  # 25MB
            raise ValueError("archivo-demasiado-grande")
    except Exception:
        pass

    is_img = ext0 in {"png", "jpg", "jpeg", "webp"}
    if is_img and Image is not None:
        # Siempre guardamos imágenes como JPG comprimido
        ext = ".jpg"
        persist_path = os.path.join(folder, f"{base}{ext}")
        os.makedirs(os.path.dirname(persist_path), exist_ok=True)

        try:
            raw = fs.read()
            fs.stream.seek(0)
            img = Image.open(BytesIO(raw))
            if ImageOps is not None:
                img = ImageOps.exif_transpose(img)

            if img.mode != "RGB":
                img = img.convert("RGB")

            # Redimensionar (recibos/fotos de celular suelen venir enormes)
            max_dim = 1600
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim))

            # Guardado con compresión adaptativa (objetivo <= ~650KB)
            target = 650 * 1024
            for q in (80, 74, 68, 62, 56):
                tmp = BytesIO()
                img.save(tmp, format="JPEG", quality=q, optimize=True, progressive=True)
                if tmp.tell() <= target or q == 56:
                    with open(persist_path, "wb") as f:
                        f.write(tmp.getvalue())
                    break
        except Exception:
            # Fallback: si por alguna razón falla Pillow, guardamos el original sin romper el flujo
            persist_path = os.path.join(folder, f"{base}.{ext0}")
            os.makedirs(os.path.dirname(persist_path), exist_ok=True)
            fs.save(persist_path)
    else:
        # PDF (o sin Pillow): guardar tal cual
        ext = "." + ext0
        persist_path = os.path.join(folder, f"{base}{ext}")
        os.makedirs(os.path.dirname(persist_path), exist_ok=True)
        fs.save(persist_path)

    # espejo -> carpeta pública /static
    public_abs = _mirror_persist_static_to_public(persist_path)
    if public_abs and os.path.exists(public_abs):
        rel = os.path.relpath(public_abs, PUBLIC_STATIC_DIR).replace("\\", "/")
        return rel

    # fallback: si no se pudo espejar, devolvemos una ruta "segura" sin .. (solo nombre)
    return f"CONTABILIDAD/comprobantes/{os.path.basename(folder)}/{os.path.basename(persist_path)}".replace("\\", "/")

# ---- Archivo de gastos ----

GASTOS_XML = globals().get("CONTAB_GASTOS_XML", _persist('static', 'CONTABILIDAD', 'gastos.xml'))
os.makedirs(os.path.dirname(GASTOS_XML), exist_ok=True)
if not os.path.exists(GASTOS_XML):
    ET.ElementTree(ET.Element('gastos')).write(GASTOS_XML, encoding='utf-8', xml_declaration=True)
_mirror_persist_static_to_public(GASTOS_XML)

# ---- Auditoría (registro de acciones contables) ----
AUDIT_XML = _persist('static', 'CONTABILIDAD', 'auditoria.xml')
os.makedirs(os.path.dirname(AUDIT_XML), exist_ok=True)
if not os.path.exists(AUDIT_XML):
    ET.ElementTree(ET.Element('auditoria')).write(AUDIT_XML, encoding='utf-8', xml_declaration=True)
_mirror_persist_static_to_public(AUDIT_XML)

def _audit_event(modulo: str, accion: str, ref: str = "", extra: dict | None = None):
    """Guarda un evento de auditoría (quién, cuándo, IP y detalle)."""
    extra = extra or {}
    try:
        tree, root = _xml_read(AUDIT_XML)
    except Exception:
        # si por alguna razón falla la lectura, recreamos
        root = ET.Element('auditoria')
        tree = ET.ElementTree(root)

    now = datetime.now()
    eid = str(int(now.timestamp()*1000))
    e = ET.SubElement(root, "evento", {"id": eid})
    ET.SubElement(e, "fecha").text = now.date().isoformat()
    ET.SubElement(e, "hora").text = now.strftime("%H:%M:%S")
    ET.SubElement(e, "timestamp").text = now.isoformat(timespec="seconds")
    ET.SubElement(e, "usuario").text = (session.get("usuario") if session else "") or ""
    ET.SubElement(e, "rol").text = (session.get("rol") if session else "") or ""
    ET.SubElement(e, "ip").text = (request.remote_addr if request else "") or ""
    ET.SubElement(e, "modulo").text = modulo or ""
    ET.SubElement(e, "accion").text = accion or ""
    ET.SubElement(e, "ref").text = ref or ""

    det = ET.SubElement(e, "detalle")
    for k, v in (extra or {}).items():
        it = ET.SubElement(det, "d", {"k": str(k)})
        it.text = str(v)

    _xml_write(tree, AUDIT_XML)
    return eid

def _is_admin() -> bool:
    rol_n = _normalize(session.get('rol', '') or '')
    return rol_n in {'administrador', 'admin', 'super administrador', 'superadministrador', 'superadmin'}

def _require_super() -> bool:
    return _is_superadmin()

def _client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr) if request else ""

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _now_hora() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _safe_backup_copy(src: str, dst_dir: str):
    try:
        if src and os.path.exists(src):
            os.makedirs(dst_dir, exist_ok=True)
            base = os.path.basename(src)
            shutil.copy2(src, os.path.join(dst_dir, base))
    except Exception as e:
        print("[WARN] backup copy failed:", e)

def _reset_xml(path: str, root_tag: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ET.ElementTree(ET.Element(root_tag)).write(path, encoding='utf-8', xml_declaration=True)
    _mirror_persist_static_to_public(path)



def _xml_read(path):
    tree = ET.parse(path)
    return tree, tree.getroot()

def _xml_write(tree, path):
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(path, encoding='utf-8', xml_declaration=True)
    _mirror_persist_static_to_public(path)

# ---- Gastos CRUD ----
def _gasto_row(elem):
    return {
        "id": elem.get("id"),
        "fecha": elem.findtext("fecha", ""),
        "hora": elem.findtext("hora", ""),
        "categoria": elem.findtext("categoria", ""),
        "medio": elem.findtext("medio", ""),     # caja | banco
        "banco": elem.findtext("banco", ""),
        "monto": float(elem.findtext("monto", "0") or 0),
        "descripcion": elem.findtext("descripcion", ""),
        "creado_por": elem.findtext("creado_por", ""),
        "creado_rol": elem.findtext("creado_rol", ""),
        "creado_ip": elem.findtext("creado_ip", ""),
        "creado_en": elem.findtext("creado_en", ""),
        "comprobante": elem.findtext("comprobante", ""),
    }

def _gastos_list(desde_iso, hasta_iso):
    _, root = _xml_read(GASTOS_XML)
    out = []
    for g in root.findall("gasto"):
        f = g.findtext("fecha", "")
        if not f:
            continue
        if f >= desde_iso and f <= hasta_iso:
            out.append(_gasto_row(g))
    out.sort(key=lambda x: (x["fecha"], x["id"]))
    return out

def _gasto_add(data, usuario, comp_path=None, gid_forced=None, monto_comprobante=None,
              ip=None, rol=None, creado_en=None):
    tree, root = _xml_read(GASTOS_XML)
    now = datetime.now()
    gid = gid_forced or str(int(now.timestamp()*1000))
    g = ET.SubElement(root, "gasto", {"id": gid})

    fecha = (data.get("fecha") or date.today().isoformat())
    hora  = (data.get("hora")  or now.strftime("%H:%M:%S"))
    ET.SubElement(g, "fecha").text = fecha
    ET.SubElement(g, "hora").text  = hora
    ET.SubElement(g, "categoria").text = (data.get("categoria") or "Gasto")
    ET.SubElement(g, "medio").text = (data.get("medio") or "caja")
    ET.SubElement(g, "banco").text = (data.get("banco") or data.get("cuenta") or "")
    ET.SubElement(g, "monto").text = str(float(data.get("monto") or 0))
    ET.SubElement(g, "descripcion").text = (data.get("descripcion") or "")

    ET.SubElement(g, "creado_por").text = (usuario or "sistema")
    ET.SubElement(g, "creado_rol").text = (rol or session.get("rol", "") or "")
    ET.SubElement(g, "creado_ip").text  = (ip or (request.remote_addr if request else "") or "")
    ET.SubElement(g, "creado_en").text  = (creado_en or now.isoformat(timespec="seconds"))

    if comp_path:
        ET.SubElement(g, "comprobante").text = comp_path
    if monto_comprobante is not None:
        ET.SubElement(g, "monto_comprobante").text = str(float(monto_comprobante))

    _xml_write(tree, GASTOS_XML)
    return gid

def _gasto_delete(gid):
    tree, root = _xml_read(GASTOS_XML)
    for g in root.findall("gasto"):
        if g.get("id") == gid:
            root.remove(g); _xml_write(tree, GASTOS_XML); return True
    return False

# ---- Auxiliares generales ----
def _daterange(d1_iso, d2_iso):
    d1 = datetime.fromisoformat(d1_iso).date()
    d2 = datetime.fromisoformat(d2_iso).date()
    curr = d1
    while curr <= d2:
        yield curr.isoformat()
        curr += timedelta(days=1)

def _safe_int(x, d=0):
    try: return int(str(x).strip() or d)
    except Exception: return d

def _safe_float(x, d=0.0):
    try: return float(str(x).strip() or d)
    except Exception: return d

def _to_bool(x):
    s = str(x or '').strip().lower()
    return s in ('1', 'true', 't', 'yes', 'si', 'sí')

# ---- Impresos (desde LOG de impresión) ----
def _sum_impresos(desde_iso, hasta_iso):
    total = 0
    for n in _iter_impresiones():  # definido en tu app (impresión de boletos)
        if (n.get('tipo') or '').lower() != 'boletos':
            continue
        f = (n.findtext('fecha_sorteo') or '').strip()
        if f and (desde_iso <= f <= hasta_iso):
            try:
                total += int(n.findtext('total_boletos') or '0')
            except Exception:
                pass
    return total

# ---- Lectura flexible de CAJA (cobros) ----
def _caja_iter_cobros_dia(root_dia: ET.Element):
    """
    Itera cobros pagados del nodo <dia>.
    Soporta:
      A) <cobros><cobro .../></cobros> (nuevo)
      B) <vendedor>...</vendedor> (antiguo)
    """
    cobros = root_dia.find('cobros')
    if cobros is not None:
        for c in cobros.findall('cobro'):
            yield {
                "seudonimo": c.attrib.get('seudonimo', ''),
                "vendidos": _safe_int(c.attrib.get('vendidos', 0)),
                "devueltos": _safe_int(c.attrib.get('devueltos', 0)),
                "efectivo": _safe_float(c.attrib.get('efectivo', 0)),
                "transferencia": _safe_float(c.attrib.get('transferencia', 0)),
                "pagado": _to_bool(c.attrib.get('pagado', '0')),
                # snapshot/montos guardados si existen (para consistencia histórica)
                "valor_boleto": _safe_float(c.attrib.get('valor_boleto', 0)),
                "comision_vendedor": _safe_float(c.attrib.get('comision_vendedor', 0)),
                "comision_extra_meta": _safe_float(c.attrib.get('comision_extra_meta', 0)),
                "meta_boletos": _safe_int(c.attrib.get('meta_boletos', 0)),
                "modo_comision": (c.attrib.get('modo_comision', 'normal') or 'normal'),
                "comision_manual": _safe_float(c.attrib.get('comision_manual', 0)),
                "pct_aplicado": _safe_float(c.attrib.get('pct_aplicado', 0)),
                "valor_total_venta": _safe_float(c.attrib.get('valor_total_venta', 0)),
                "gan_vendedor": _safe_float(c.attrib.get('gan_vendedor', 0)),
                "a_pagar_caja": _safe_float(c.attrib.get('a_pagar_caja', 0)),
                "total_pagar": _safe_float(c.attrib.get('total_pagar', 0)),
            }
        return

    # B) Antiguo (sin snapshot)
    for v in root_dia.findall('vendedor'):
        yield {
            "seudonimo": v.attrib.get('seudonimo', ''),
            "vendidos": _safe_int(v.findtext('vendidos', 0)),
            "devueltos": _safe_int(v.findtext('devueltos', 0)),
            "efectivo": _safe_float(v.findtext('efectivo', 0)),
            "transferencia": _safe_float(v.findtext('transferencia', 0)),
            "pagado": _to_bool(v.findtext('pagado', 'false') or v.attrib.get('pagado')),
            "valor_boleto": 0.0,
            "comision_vendedor": 0.0,
            "comision_extra_meta": 0.0,
            "meta_boletos": 0,
            "modo_comision": "normal",
            "comision_manual": 0.0,
            "pct_aplicado": 0.0,
            "valor_total_venta": 0.0,
            "gan_vendedor": 0.0,
            "a_pagar_caja": 0.0,
            "total_pagar": 0.0,
        }

# ---- Caja (vendidos/devueltos/recaudo/comisiones, efectivo/transferencia) ----
def _sum_caja(desde_iso, hasta_iso):
    vendidos = devueltos = 0
    total_recaudado = gan_vendedores = a_caja = 0.0
    tot_efectivo = tot_transfer = 0.0

    _, root = _leer_xml(CAJA_XML)

    for f in _daterange(desde_iso, hasta_iso):
        dia = root.find(f"./dia[@fecha='{f}']")
        if dia is None:
            continue

        cfg_dia = get_configuracion_dia(f)

        for r in _caja_iter_cobros_dia(dia):
            if not r.get('pagado'):
                continue

            vend = _safe_int(r.get('vendidos', 0))
            dev  = _safe_int(r.get('devueltos', 0))
            vendidos  += vend
            devueltos += dev

            # Si el cobro tiene montos guardados, usar esos (exactitud histórica).
            total_venta = _safe_float(r.get('valor_total_venta', 0))
            gan_v = _safe_float(r.get('gan_vendedor', 0))
            caja = _safe_float(r.get('a_pagar_caja', 0))

            if total_venta <= 0 and vend > 0:
                cfg_calc = {
                    "valor_boleto": _safe_float(r.get("valor_boleto", 0)) or _safe_float(cfg_dia.get("valor_boleto"), 0.0),
                    "comision_vendedor": _safe_float(r.get("comision_vendedor", 0)) or _safe_float(cfg_dia.get("comision_vendedor"), 0.0),
                    "comision_extra_meta": _safe_float(r.get("comision_extra_meta", 0)) or _safe_float(cfg_dia.get("comision_extra_meta"), 0.0),
                    "meta_boletos": _safe_int(r.get("meta_boletos", 0)) or _safe_int(cfg_dia.get("meta_boletos"), 0),
                    "modo_comision": r.get("modo_comision", "normal"),
                    "comision_manual": _safe_float(r.get("comision_manual", 0), 0.0),
                }
                det = _calc_cobro_detalle(vend, cfg_calc)
                total_venta = det["valor_total_venta"]
                gan_v = det["gan_vendedor"]
                caja = det["a_pagar_caja"]

            total_recaudado += total_venta
            gan_vendedores  += gan_v
            a_caja          += caja

            tot_transfer += _safe_float(r.get('transferencia', 0))
            tot_efectivo += _safe_float(r.get('efectivo', 0))

    return {
        "vendidos": vendidos,
        "devueltos": devueltos,
        "total_recaudado": round(total_recaudado, 2),
        "gan_vendedores": round(gan_vendedores, 2),
        "a_pagar_caja": round(a_caja, 2),
        "efectivo": round(tot_efectivo, 2),
        "transferencia": round(tot_transfer, 2)
    }

# ---- Asignaciones: planillas / entregados ----
def _sum_asignaciones(desde_iso, hasta_iso):
    path_asig = globals().get("ASIGNACIONES_XML", _persist("static", "db", "asignaciones.xml"))
    boletos_por_planilla = int(globals().get("BOLETOS_POR_PLANILLA", 20))
    if not os.path.exists(path_asig):
        return 0, 0
    try:
        root = ET.parse(path_asig).getroot()
    except ET.ParseError:
        return 0, 0

    planillas = 0
    for d in root.findall("dia"):
        f = (d.attrib.get("fecha") or "").strip()
        if not f or f < desde_iso or f > hasta_iso:
            continue
        for _ in d.findall("vendedor"):
            planillas += len(_.findall("planilla"))
    entregados = planillas * boletos_por_planilla
    return planillas, entregados

# ---- Premios (pagados / por caducar / caducados) ----


def _sum_premios(desde_iso, hasta_iso):
    pagos_map = _pp_leer_pagos_map()  # ya definido en tu módulo de premios
    hoy = date.today()

    total_pagado = 0.0
    pagados_count = 0
    por_caducar = 0
    caducados   = 0

    for f in _daterange(desde_iso, hasta_iso):
        f_sorteo = datetime.fromisoformat(f).date()
        caduca = f_sorteo + timedelta(days=30)
        for g in (_pp_iter_ganadores_de_fecha(f) or []):
            k = _pp_premio_key(f, g["figura"], g["boleto"])
            pp = pagos_map.get(k)
            premio_val = _safe_float(g.get("premio", 0), 0)
            if pp:
                pagados_count += 1
                total_pagado += _safe_float(pp.get("premio", premio_val), premio_val)
            else:
                if hoy > caduca:
                    caducados += 1
                elif 0 <= (caduca - hoy).days <= 5:
                    por_caducar += 1

    return {
        "premios_pagados_total": round(total_pagado, 2),
        "premios_pagados_cantidad": int(pagados_count),
        "premios_por_caducar": por_caducar,
        "premios_caducados": caducados
    }


def _premios_pagados_detalle(desde_iso, hasta_iso):
    pagos = _pp_leer_pagos_map()
    items = []
    for p in pagos.values():
        f = (p.get("fecha_sorteo") or "").strip()
        if not f or f < desde_iso or f > hasta_iso:
            continue
        try:
            items.append({
                "fecha_sorteo": f,
                "figura": p.get("figura", ""),
                "boleto": p.get("boleto", ""),
                "ganador": p.get("ganador_nombre", ""),
                "premio": _safe_float(p.get("premio", 0), 0),
                "fecha_pago": p.get("fecha_pago", ""),
                "recibo_id": p.get("recibo_id", ""),
                "pagado_por": p.get("pagado_por", "")
            })
        except Exception:
            pass
    items.sort(key=lambda x: (x["fecha_sorteo"], x["figura"], x["boleto"]))
    return items

# ---- Ruta HTML protegida ----
@app.route("/contabilidad")
def contabilidad():
    if 'usuario' not in session:
        return redirect(_login_url())
    rol = session.get('rol', '')
    if rol not in ('Super Administrador', 'Administrador'):
        flash('Acceso restringido a Contabilidad', 'error')
        return redirect(url_for('dashboard'))
    return render_template(
        "contabilidad.html",
        usuario=session.get('usuario', ''),
        rol=rol,
        avatar=session.get('avatar', 'avatar-male.png')
    )

# ---- Gastos con foto (pantalla simple, sin depender del template contabilidad.html) ----
@app.get("/contabilidad/gastos-fotos")
def contabilidad_gastos_fotos():
    if 'usuario' not in session:
        return redirect(_login_url())
    rol = session.get('rol', '')
    if rol not in ('Super Administrador', 'Administrador'):
        flash('Acceso restringido a Contabilidad', 'error')
        return redirect(url_for('dashboard'))

    # Página mínima para registrar gastos con foto/PDF (el backend comprime imágenes automáticamente).
    return """<!doctype html>
<html lang='es'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>Gastos con Foto</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,'Helvetica Neue',Arial; background:#0b1220; color:#e6e8ef; margin:0;}
    .wrap{max-width:980px;margin:24px auto;padding:0 16px;}
    .card{background:#111a2e;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:16px;box-shadow:0 12px 30px rgba(0,0,0,.35);}
    h1{font-size:20px;margin:0 0 12px;}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
    label{font-size:12px;opacity:.9;display:block;margin:0 0 6px;}
    input,select,textarea{width:100%;padding:10px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:#0b1220;color:#e6e8ef;outline:none;}
    textarea{min-height:80px;resize:vertical;}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
    .btn{background:#2b6cff;color:white;border:0;border-radius:12px;padding:10px 14px;font-weight:700;cursor:pointer}
    .btn:disabled{opacity:.6;cursor:not-allowed}
    .note{font-size:12px;opacity:.8;margin-top:8px;line-height:1.35}
    table{width:100%;border-collapse:collapse;margin-top:14px;}
    th,td{text-align:left;padding:10px 8px;border-bottom:1px solid rgba(255,255,255,.08);font-size:13px;vertical-align:top;}
    th{opacity:.85}
    a{color:#9bd0ff}
    .pill{display:inline-block;padding:4px 10px;border-radius:999px;background:rgba(43,108,255,.18);border:1px solid rgba(43,108,255,.35);font-size:12px}
    @media (max-width:760px){.grid{grid-template-columns:1fr;}}
  </style>
</head>
<body>
  <div class='wrap'>
    <div class='card'>
      <div class='row' style='justify-content:space-between'>
        <h1>Registrar gasto con foto (comprimida)</h1>
        <a href='/contabilidad' class='pill'>Volver a Contabilidad</a>
      </div>

      <form id='f' class='grid' enctype='multipart/form-data'>
        <div>
          <label>Categoria</label>
          <select name='categoria' required>
            <option value='Pago de Personal'>Pago de Personal</option>
            <option value='Arriendo'>Arriendo</option>
            <option value='Internet'>Internet</option>
            <option value='Café'>Café</option>
            <option value='Servicios Básicos'>Servicios Básicos</option>
            <option value='Otros'>Otros</option>
          </select>
        </div>

        <div>
          <label>Medio</label>
          <select name='medio' required>
            <option value='caja'>Caja (Efectivo)</option>
            <option value='banco'>Banco (Transferencia)</option>
          </select>
        </div>

        <div>
          <label>Monto ($)</label>
          <input name='monto' type='number' step='0.01' min='0' required placeholder='0.00'/>
        </div>

        <div>
          <label>Fecha</label>
          <input name='fecha' id='fecha' type='date' required/>
        </div>

        <div style='grid-column:1/-1'>
          <label>Descripción</label>
          <textarea name='descripcion' placeholder='Ej: Pago internet febrero, arriendo local, etc.'></textarea>
        </div>

        <div style='grid-column:1/-1'>
          <label>Foto/PDF del comprobante (se comprimirá automáticamente si es imagen)</label>
          <input name='comprobante' type='file' accept='image/*,application/pdf' required/>
          <div class='note'>Tip: puedes subir una foto tomada con el celular. El sistema la reduce (máx. 1600px) y la guarda ligera (~650KB aprox.).</div>
        </div>

        <div class='row' style='grid-column:1/-1;justify-content:flex-end'>
          <button class='btn' id='btn'>Guardar gasto</button>
        </div>
      </form>

      <div id='msg' class='note'></div>

      <h1 style='margin-top:18px'>Últimos gastos (30 días)</h1>
      <div style='overflow:auto'>
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Categoría</th>
              <th>Medio</th>
              <th>Monto</th>
              <th>Descripción</th>
              <th>Comprobante</th>
            </tr>
          </thead>
          <tbody id='tb'></tbody>
        </table>
      </div>
    </div>
  </div>

<script>
  const $ = (s) => document.querySelector(s);
  const tb = $('#tb');
  const msg = $('#msg');
  const btn = $('#btn');

  // Fecha por defecto: hoy (la API permite solo hoy)
  const today = new Date();
  const iso = today.toISOString().slice(0,10);
  $('#fecha').value = iso;

  function money(n){ try{return Number(n).toFixed(2);}catch(e){return n;} }

  async function cargar(){
    const desde = new Date(Date.now() - 30*24*3600*1000).toISOString().slice(0,10);
    const hasta = iso;
    const r = await fetch(`/api/gastos?desde=${desde}&hasta=${hasta}`, {credentials:'same-origin'});
    const j = await r.json();
    tb.innerHTML = '';
    if(!j.ok){ tb.innerHTML = `<tr><td colspan='6'>No se pudo cargar: ${j.error||r.status}</td></tr>`; return; }
    const items = j.items || [];
    if(items.length===0){ tb.innerHTML = `<tr><td colspan='6'>Sin gastos en este rango</td></tr>`; return; }
    for(const g of items){
      const link = g.comprobante ? `<a target='_blank' href='/static/${g.comprobante}'>Ver</a>` : '';
      tb.innerHTML += `<tr>
        <td>${g.fecha||''}</td>
        <td>${g.categoria||''}</td>
        <td>${g.medio||''}</td>
        <td>$${money(g.monto||0)}</td>
        <td>${(g.descripcion||'').replace(/</g,'&lt;')}</td>
        <td>${link}</td>
      </tr>`;
    }
  }

  $('#f').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    msg.textContent = '';
    btn.disabled = true;
    try{
      const fd = new FormData(ev.target);
      // Para pasar la validación del backend
      const monto = fd.get('monto') || '0';
      fd.set('monto_confirm', monto);

      const r = await fetch('/api/gastos', {method:'POST', body: fd, credentials:'same-origin'});
      const j = await r.json().catch(()=>({}));
      if(!r.ok || !j.ok){
        msg.textContent = 'No se pudo guardar: ' + (j.error || r.status);
      }else{
        msg.textContent = '✅ Gasto guardado correctamente.';
        ev.target.reset();
        $('#fecha').value = iso;
        await cargar();
      }
    }catch(e){
      msg.textContent = 'Error: ' + e;
    }finally{
      btn.disabled = false;
    }
  });

  cargar();
</script>
</body>
</html>"""



# ========================= BANCO (Empresa) =========================
BANCOS_XML = globals().get("CONTAB_BANCOS_XML", _persist('static', 'CONTABILIDAD', 'bancos.xml'))
os.makedirs(os.path.dirname(BANCOS_XML), exist_ok=True)
if not os.path.exists(BANCOS_XML):
    ET.ElementTree(ET.Element('bancos')).write(BANCOS_XML, encoding='utf-8', xml_declaration=True)
_mirror_persist_static_to_public(BANCOS_XML)

def _bank_xml():
    tree = ET.parse(BANCOS_XML)
    return tree, tree.getroot()

def _bank_write(tree):
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(BANCOS_XML, encoding='utf-8', xml_declaration=True)
    _mirror_persist_static_to_public(BANCOS_XML)

def _bank_row(e: ET.Element):
    return {
        "id": e.get("id"),
        "fecha": e.findtext("fecha", ""),
        "hora": e.findtext("hora", ""),
        "cuenta": e.findtext("cuenta", "Empresa"),
        "tipo": (e.findtext("tipo", "ingreso") or "").lower(),  # ingreso|egreso|transferencia
        "monto": float(e.findtext("monto", "0") or 0),
        "referencia": e.findtext("referencia", ""),
        "creado_por": e.findtext("creado_por", ""),
        "creado_rol": e.findtext("creado_rol", ""),
        "creado_ip": e.findtext("creado_ip", ""),
        "creado_en": e.findtext("creado_en", ""),
        "comprobante": e.findtext("comprobante", ""),
        "monto_comprobante": float(e.findtext("monto_comprobante", "0") or 0) if e.find("monto_comprobante") is not None else None,
        "locked": (e.findtext("locked", "false") == "true"),
    }

def _bank_get(mid: str):
    tree, root = _bank_xml()
    for e in root.findall("mov"):
        if e.get("id") == mid:
            return tree, root, e
    return tree, root, None

def _bank_add(fecha:str, cuenta:str, tipo:str, monto:float, referencia:str, creado_por:str,
              comprobante:str=None, locked:bool=False, forced_id:str=None, monto_comprobante:float=None,
              ip:str=None, rol:str=None, creado_en:str=None, hora:str=None):
    tree, root = _bank_xml()
    now = datetime.now()
    mid = forced_id or str(int(now.timestamp()*1000))
    m = ET.SubElement(root, "mov", {"id": mid})

    ET.SubElement(m, "fecha").text = (fecha or date.today().isoformat())
    ET.SubElement(m, "hora").text  = (hora or now.strftime("%H:%M:%S"))
    ET.SubElement(m, "cuenta").text = (cuenta or "Empresa")
    ET.SubElement(m, "tipo").text = (tipo or "ingreso")  # ingreso | egreso | transferencia
    ET.SubElement(m, "monto").text = str(float(monto or 0))
    ET.SubElement(m, "referencia").text = (referencia or "")
    ET.SubElement(m, "creado_por").text = (creado_por or "sistema")
    ET.SubElement(m, "creado_rol").text = (rol or session.get("rol", "") or "")
    ET.SubElement(m, "creado_ip").text  = (ip or (request.remote_addr if request else "") or "")
    ET.SubElement(m, "creado_en").text  = (creado_en or now.isoformat(timespec="seconds"))

    if comprobante:
        ET.SubElement(m, "comprobante").text = comprobante
    ET.SubElement(m, "locked").text = "true" if locked else "false"
    if monto_comprobante is not None:
        ET.SubElement(m, "monto_comprobante").text = str(float(monto_comprobante))

    _bank_write(tree)
    return mid

def _bank_list(desde:str, hasta:str, cuenta:str=None):
    _, root = _bank_xml()
    items = []
    for e in root.findall('mov'):
        f = e.findtext('fecha') or ''
        if not f:
            continue
        if desde and f < desde:  # fuera de rango inferior
            continue
        if hasta and f > hasta:  # fuera de rango superior
            continue
        if cuenta and (e.findtext('cuenta') or 'Empresa') != cuenta:
            continue
        items.append(_bank_row(e))
    items.sort(key=lambda x: (x["fecha"], x["id"]))
    return items

def _bank_delete(mid:str):
    tree, root, e = _bank_get(mid)
    if e is None:
        return False
    if (e.findtext("locked", "false") == "true"):
        return False
    root.remove(e); _bank_write(tree); return True

def _bank_delete_force(mid:str):
    """Borra un movimiento aun si está locked. SOLO usar para Super Admin."""
    tree, root, e = _bank_get(mid)
    if e is None:
        return False
    root.remove(e)
    _bank_write(tree)
    return True

def _bank_saldo(cuenta:str="Empresa", hasta:str=None):
    _, root = _bank_xml()
    total = 0.0
    for e in root.findall('mov'):
        if (e.findtext('cuenta') or 'Empresa') != cuenta:
            continue
        f = e.findtext('fecha') or ''
        if hasta and f > hasta:
            continue
        tipo = (e.findtext('tipo') or 'ingreso').lower()
        monto = float(e.findtext('monto') or 0)
        if tipo == 'ingreso':
            total += monto
        else:
            total -= monto
    return round(total, 2)

def _require_admin():
    return session.get('rol', '') in ('Super Administrador', 'Administrador')

# -------------------- Rutas Banco (REST) --------------------
@app.get("/api/banco/saldo")
def api_banco_saldo():
    cuenta = request.args.get("cuenta") or "Empresa"
    hasta = request.args.get("hasta") or date.today().isoformat()
    return jsonify({"ok": True, "cuenta": cuenta, "hasta": hasta, "saldo": _bank_saldo(cuenta, hasta)})

@app.get("/api/banco/movimientos")
def api_banco_movimientos():
    cuenta = request.args.get("cuenta") or "Empresa"
    desde = request.args.get("desde") or (date.today() - timedelta(days=30)).isoformat()
    hasta = request.args.get("hasta") or date.today().isoformat()
    return jsonify({"ok": True, "items": _bank_list(desde, hasta, cuenta)})

@app.post("/api/banco/deposito")
def api_banco_deposito():
    if not _require_admin():
        return jsonify({"ok": False, "error": "no-autorizado"}), 403

    if request.content_type and "multipart/form-data" in request.content_type:
        form = request.form
        file = request.files.get("comprobante") or request.files.get("foto")
        if not file or not file.filename:
            return jsonify({"ok": False, "error": "comprobante-requerido"}), 400
        if not _ext_ok(file.filename):
            return jsonify({"ok": False, "error": "ext-archivo-no-valida"}), 400

        monto = float(form.get("monto") or 0)
        monto_comp = float(form.get("monto_confirm") or form.get("monto_comprobante") or 0)
        if round(monto, 2) != round(monto_comp, 2):
            return jsonify({"ok": False, "error": "monto-comprobante-difiere"}), 400

        mid = str(int(datetime.now().timestamp()*1000))
        comp_rel = _save_upload(file, BANK_FILES, f"dep_{mid}")
        _bank_add(
            fecha = form.get("fecha") or date.today().isoformat(),
            cuenta = form.get("cuenta") or "Empresa",
            tipo = "ingreso",
            monto = monto,
            referencia = form.get("referencia") or "Depósito",
            creado_por = session.get('usuario', 'sistema'),
            comprobante = comp_rel,
            locked = True,
            forced_id = mid,
            monto_comprobante = monto_comp,
            ip = request.remote_addr,
            rol = session.get('rol',''),
            creado_en = datetime.now().isoformat(timespec='seconds'),
            hora = datetime.now().strftime('%H:%M:%S')
        )
        return jsonify({"ok": True, "id": mid, "saldo": _bank_saldo(form.get('cuenta') or "Empresa")})
    else:
        return jsonify({"ok": False, "error": "usar-multipart-con-comprobante"}), 400

@app.post("/api/banco/retiro")
def api_banco_retiro():
    if not _require_admin():
        return jsonify({"ok": False, "error": "no-autorizado"}), 403
    data = request.get_json(force=True) or {}
    mid = _bank_add(
        fecha = data.get("fecha") or date.today().isoformat(),
        cuenta = data.get("cuenta") or "Empresa",
        tipo = "egreso",
        monto = float(data.get("monto") or 0),
        referencia = data.get("referencia") or "Retiro",
        creado_por = session.get('usuario', 'sistema'),
        locked = False,
        ip = request.remote_addr,
        rol = session.get('rol',''),
        creado_en = datetime.now().isoformat(timespec='seconds'),
        hora = datetime.now().strftime('%H:%M:%S')
    )
    return jsonify({"ok": True, "id": mid, "saldo": _bank_saldo(data.get("cuenta") or "Empresa")})

@app.delete("/api/banco/movimientos/<mid>")
def api_banco_borrar(mid):
    if not _require_admin() and not _is_superadmin():
        return jsonify({"ok": False, "error": "no-autorizado"}), 403

    force = (request.args.get("force") == "1")
    if force:
        # Solo SUPER ADMIN puede forzar borrado (incluye locked)
        if not _is_superadmin():
            return jsonify({"ok": False, "error": "solo-superadmin"}), 403
        ok = _bank_delete_force(mid)
    else:
        ok = _bank_delete(mid)

    if not ok:
        return jsonify({"ok": False, "error": "mov-bloqueado-o-inexistente"}), 400

    try:
        _audit_event("banco", "delete", mid, {"force": force})
    except Exception:
        pass
    return jsonify({"ok": True})

# -------------------- API: GASTOS --------------------
@app.get("/api/gastos")
def api_gastos_list():
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    desde = (request.args.get("desde") or (date.today() - timedelta(days=30)).isoformat()).strip()
    hasta = (request.args.get("hasta") or date.today().isoformat()).strip()
    return jsonify({"ok": True, "items": _gastos_list(desde, hasta)})

@app.post("/api/gastos")
def api_gastos_add():
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401

    if request.content_type and "multipart/form-data" in request.content_type:
        form = request.form
        # Regla: solo se pueden ingresar gastos del día actual
        hoy = date.today().isoformat()
        fecha_form = (form.get("fecha") or hoy).strip()
        if fecha_form != hoy:
            return jsonify({"ok": False, "error": "solo-hoy"}), 400

        file = request.files.get("comprobante") or request.files.get("foto")
        if not file or not file.filename:
            return jsonify({"ok": False, "error": "comprobante-requerido"}), 400
        if not _ext_ok(file.filename):
            return jsonify({"ok": False, "error": "ext-archivo-no-valida"}), 400

        monto = float(form.get("monto") or 0)
        monto_comp = float(form.get("monto_confirm") or form.get("monto_comprobante") or 0)
        if round(monto, 2) != round(monto_comp, 2):
            return jsonify({"ok": False, "error": "monto-comprobante-difiere"}), 400

        gid = str(int(datetime.now().timestamp()*1000))
        comp_rel = _save_upload(file, GASTO_FILES, f"gasto_{gid}")
        data = dict(form)
        data["fecha"] = fecha_form
        _gasto_add(data, session.get('usuario'), comp_rel, gid_forced=gid, monto_comprobante=monto_comp, ip=request.remote_addr, rol=session.get('rol',''), creado_en=datetime.now().isoformat(timespec='seconds'))
        return jsonify({"ok": True, "id": gid})
    else:
        return jsonify({"ok": False, "error": "usar-multipart-con-comprobante"}), 400

@app.delete("/api/gastos/<gid>")
def api_gastos_delete(gid):
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    # Solo SUPER ADMIN puede borrar gastos (control estricto)
    if not _is_superadmin():
        return jsonify({"ok": False, "error": "solo-superadmin"}), 403

    ok = _gasto_delete(gid)
    try:
        _audit_event("gastos", "delete", gid, {"ok": ok})
    except Exception:
        pass
    return jsonify({"ok": ok})

# -------------------- API: RESUMEN CONTABLE --------------------

@app.get("/api/contabilidad/resumen")
def api_contabilidad_resumen():
    desde = (request.args.get("desde") or (date.today() - timedelta(days=30)).isoformat()).strip()
    hasta = (request.args.get("hasta") or date.today().isoformat()).strip()
    try:
        if datetime.fromisoformat(desde) > datetime.fromisoformat(hasta):
            desde, hasta = hasta, desde
    except Exception:
        pass

    impresos = _sum_impresos(desde, hasta)
    caja     = _sum_caja(desde, hasta)
    premios  = _sum_premios(desde, hasta)

    gastos_items = _gastos_list(desde, hasta)
    gastos_total  = round(sum(g["monto"] for g in gastos_items if (g["categoria"] or "").lower() != "sueldo"), 2)
    sueldos_total = round(sum(g["monto"] for g in gastos_items if (g["categoria"] or "").lower() == "sueldo"), 2)
    gastos_caja   = round(sum(g["monto"] for g in gastos_items if g["medio"] == "caja"), 2)
    gastos_banco  = round(sum(g["monto"] for g in gastos_items if g["medio"] == "banco"), 2)

    banco_items = _bank_list(desde, hasta, "Empresa")
    planillas_asignadas, boletos_entregados = _sum_asignaciones(desde, hasta)

    boletos_por_planilla = max(1, int(globals().get("BOLETOS_POR_PLANILLA", 20) or 20))
    planillas_impresas = int((int(impresos or 0) + boletos_por_planilla - 1) // boletos_por_planilla) if int(impresos or 0) > 0 else 0
    planillas_no_asignadas = max(planillas_impresas - int(planillas_asignadas or 0), 0)
    boletos_no_asignados = max(int(impresos or 0) - int(boletos_entregados or 0), 0)

    gan_empresa   = round(caja["total_recaudado"] - caja["gan_vendedores"], 2)
    utilidad_neta = round(gan_empresa - premios["premios_pagados_total"] - gastos_total - sueldos_total, 2)

    saldo_caja  = round(caja["efectivo"]      - gastos_caja, 2)
    saldo_banco = round(caja["transferencia"] - gastos_banco, 2)

    premios_detalle = _premios_pagados_detalle(desde, hasta)

    return jsonify({
        "ok": True,
        "rango": {"desde": desde, "hasta": hasta},
        "planillas_impresas": planillas_impresas,
        "planillas_asignadas": planillas_asignadas,
        "planillas_no_asignadas": planillas_no_asignadas,
        "boletos_entregados": boletos_entregados,
        "boletos_no_asignados": boletos_no_asignados,
        "boletos_impresos": impresos,
        "boletos_vendidos": caja["vendidos"],
        "boletos_devueltos": caja["devueltos"],
        "ingresos_brutos": caja["total_recaudado"],
        "ganancia_vendedores": caja["gan_vendedores"],
        "ganancia_empresa": gan_empresa,
        "premios_pagados_total": premios["premios_pagados_total"],
        "premios_pagados_cantidad": premios["premios_pagados_cantidad"],
        "premios_por_caducar": premios["premios_por_caducar"],
        "premios_caducados": premios["premios_caducados"],
        "gastos_total": gastos_total,
        "sueldos_total": sueldos_total,
        "utilidad_neta": utilidad_neta,
        "efectivo_cobrado": caja["efectivo"],
        "transferencias_cobradas": caja["transferencia"],
        "saldo_caja": saldo_caja,
        "saldo_banco": saldo_banco,
        "gastos": gastos_items,
        "banco": banco_items,
        "premios_detalle": premios_detalle
    })


# -------------------- API: MOVIMIENTOS UNIFICADOS + SUPER ADMIN --------------------

def _caja_list_cobros_rango(desde_iso: str, hasta_iso: str):
    _, root = _leer_xml(CAJA_XML)
    items = []
    for dia in root.findall("dia"):
        fecha = (dia.get("fecha") or "").strip()
        if not fecha:
            continue
        if desde_iso and fecha < desde_iso:
            continue
        if hasta_iso and fecha > hasta_iso:
            continue
        cobros = dia.find("cobros")
        if cobros is None:
            continue
        for c in cobros.findall("cobro"):
            seud = (c.get("seudonimo") or "").strip()
            if not seud:
                continue
            transferencia = float(c.get("transferencia", "0") or 0)
            efectivo = float(c.get("efectivo", "0") or 0)
            total_pagar = float(c.get("total_pagar", "0") or 0)
            pagado = (c.get("pagado", "0") == "1")
            fh = c.get("fecha_hora", "") or ""
            hora = fh.split(" ")[1] if (" " in fh) else (fh.split("T")[1] if "T" in fh else "")
            medio = "mixto" if (transferencia > 0 and efectivo > 0) else ("transferencia" if transferencia > 0 else "efectivo")
            cid = c.get("id") or f"{fecha}__{seud}"
            items.append({
                "id": cid,
                "fecha": fecha,
                "hora": hora,
                "tipo": "cobro",
                "naturaleza": "ingreso",
                "monto": round(total_pagar, 2),
                "medio": medio,
                "banco": "",  # si quieres, aquí puedes guardar banco de transferencia en el futuro
                "referencia": f"Cobro vendedor {seud}",
                "seudonimo": seud,
                "pagado": pagado,
                "detalle": {
                    "vendidos": int(c.get("vendidos", "0") or 0),
                    "devueltos": int(c.get("devueltos", "0") or 0),
                    "transferencia": round(transferencia, 2),
                    "efectivo": round(efectivo, 2),
                },
                "creado_por": c.get("creado_por", "") or "",
                "creado_rol": c.get("creado_rol", "") or "",
                "creado_ip": c.get("creado_ip", "") or "",
                "creado_en": c.get("creado_en", "") or "",
                "actualizado_por": c.get("actualizado_por", "") or "",
                "actualizado_ip": c.get("actualizado_ip", "") or "",
                "actualizado_en": c.get("actualizado_en", "") or "",
                "comprobante": "",  # si deseas adjuntar comprobante al cobro, lo agregamos luego
            })
    items.sort(key=lambda x: (x["fecha"], x.get("hora",""), x["id"]))
    return items

@app.get("/api/session")
def api_session_info():
    return jsonify({
        "ok": True,
        "usuario": session.get("usuario", ""),
        "rol": session.get("rol", ""),
        "is_superadmin": _is_superadmin()
    })

@app.get("/api/contabilidad/movimientos")
def api_contabilidad_movimientos():
    desde = request.args.get("desde") or (date.today() - timedelta(days=30)).isoformat()
    hasta = request.args.get("hasta") or date.today().isoformat()
    # Cobros (caja)
    cobros = _caja_list_cobros_rango(desde, hasta)
    # Gastos
    gastos = _gastos_list(desde, hasta)
    mov_gastos = []
    for g in gastos:
        mov_gastos.append({
            "id": g["id"],
            "fecha": g["fecha"],
            "hora": g.get("hora",""),
            "tipo": "gasto",
            "naturaleza": "egreso",
            "monto": round(float(g.get("monto") or 0), 2),
            "medio": g.get("medio",""),
            "banco": g.get("banco",""),
            "referencia": g.get("categoria","Gasto"),
            "detalle": {"descripcion": g.get("descripcion","")},
            "creado_por": g.get("creado_por",""),
            "creado_rol": g.get("creado_rol",""),
            "creado_ip": g.get("creado_ip",""),
            "creado_en": g.get("creado_en",""),
            "comprobante": g.get("comprobante",""),
        })
    # Banco (movimientos)
    banco = _bank_list(desde, hasta, None)
    mov_banco = []
    for b in banco:
        mov_banco.append({
            "id": b["id"],
            "fecha": b["fecha"],
            "hora": b.get("hora",""),
            "tipo": "banco",
            "naturaleza": "ingreso" if b.get("tipo") == "ingreso" else "egreso",
            "monto": round(float(b.get("monto") or 0), 2),
            "medio": "banco",
            "banco": b.get("cuenta","Empresa"),
            "referencia": b.get("referencia",""),
            "detalle": {"tipo_banco": b.get("tipo","")},
            "creado_por": b.get("creado_por",""),
            "creado_rol": b.get("creado_rol",""),
            "creado_ip": b.get("creado_ip",""),
            "creado_en": b.get("creado_en",""),
            "comprobante": b.get("comprobante",""),
            "locked": bool(b.get("locked")),
        })

    # Unificado
    items = cobros + mov_gastos + mov_banco
    items.sort(key=lambda x: (x["fecha"], x.get("hora",""), x["tipo"], x["id"]))
    return jsonify({"ok": True, "desde": desde, "hasta": hasta, "items": items})

@app.get("/api/contabilidad/export.csv")
def api_contabilidad_export_csv():
    desde = request.args.get("desde") or (date.today() - timedelta(days=30)).isoformat()
    hasta = request.args.get("hasta") or date.today().isoformat()
    data = api_contabilidad_movimientos().get_json()
    items = data.get("items", []) if isinstance(data, dict) else []
    import csv
    from io import StringIO
    buff = StringIO()
    w = csv.writer(buff)
    w.writerow(["fecha","hora","tipo","naturaleza","monto","medio","banco","referencia","usuario","rol","ip","timestamp","comprobante","id"])
    for it in items:
        w.writerow([
            it.get("fecha",""),
            it.get("hora",""),
            it.get("tipo",""),
            it.get("naturaleza",""),
            it.get("monto",""),
            it.get("medio",""),
            it.get("banco",""),
            it.get("referencia",""),
            it.get("creado_por",""),
            it.get("creado_rol",""),
            it.get("creado_ip",""),
            it.get("creado_en",""),
            it.get("comprobante",""),
            it.get("id",""),
        ])
    out = buff.getvalue()
    return Response(out, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=contabilidad_{desde}_a_{hasta}.csv"})


@app.get('/api/contabilidad/reporte.pdf')
def api_contabilidad_reporte_pdf():
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401

    desde = (request.args.get('desde') or (date.today() - timedelta(days=30)).isoformat()).strip()
    hasta = (request.args.get('hasta') or date.today().isoformat()).strip()
    try:
        if datetime.fromisoformat(desde) > datetime.fromisoformat(hasta):
            desde, hasta = hasta, desde
    except Exception:
        pass

    resumen_resp = api_contabilidad_resumen().get_json()
    ranking_resp = api_vendedores_ranking().get_json() if 'api_vendedores_ranking' in globals() else {'items': []}
    j = resumen_resp if isinstance(resumen_resp, dict) else {}
    ranking = (ranking_resp or {}).get('items', [])[:12]

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 34

    pdf.setTitle(f"contabilidad_{desde}_a_{hasta}")
    pdf.setFont('Helvetica-Bold', 18)
    pdf.drawString(34, y, 'Reporte de Contabilidad')
    y -= 16
    pdf.setFont('Helvetica', 10)
    pdf.drawString(34, y, f'Rango: {desde} a {hasta}')
    pdf.drawRightString(w-34, y, f'Usuario: {session.get("usuario","") or "Sistema"}')
    y -= 24

    resumen_rows = [
        ('Boletos impresos', j.get('boletos_impresos', 0)),
        ('Boletos vendidos', j.get('boletos_vendidos', 0)),
        ('Boletos devueltos', j.get('boletos_devueltos', 0)),
        ('Boletos no asignados', j.get('boletos_no_asignados', 0)),
        ('Planillas impresas', j.get('planillas_impresas', 0)),
        ('Planillas asignadas', j.get('planillas_asignadas', 0)),
        ('Planillas no asignadas', j.get('planillas_no_asignadas', 0)),
        ('Ingresos brutos', f"${float(j.get('ingresos_brutos', 0) or 0):.2f}"),
        ('Ganancia vendedores', f"${float(j.get('ganancia_vendedores', 0) or 0):.2f}"),
        ('Ganancia empresa', f"${float(j.get('ganancia_empresa', 0) or 0):.2f}"),
        ('Premios pagados (cantidad)', j.get('premios_pagados_cantidad', 0)),
        ('Premios pagados (valor)', f"${float(j.get('premios_pagados_total', 0) or 0):.2f}"),
        ('Premios por caducar', j.get('premios_por_caducar', 0)),
        ('Premios caducados', j.get('premios_caducados', 0)),
        ('Gastos', f"${float(j.get('gastos_total', 0) or 0):.2f}"),
        ('Sueldos', f"${float(j.get('sueldos_total', 0) or 0):.2f}"),
        ('Utilidad neta', f"${float(j.get('utilidad_neta', 0) or 0):.2f}"),
    ]
    tbl = Table(resumen_rows, colWidths=[210, 120])
    tbl.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), .5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    tw, th = tbl.wrapOn(pdf, w-68, h)
    tbl.drawOn(pdf, 34, y-th)
    y = y - th - 18

    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(34, y, 'Ranking de vendedores (vendidos / devueltos)')
    y -= 14
    ranking_rows = [['Vendedor', 'Vendidos', 'Devueltos']]
    for it in ranking:
        ranking_rows.append([str(it.get('vendedor') or '—'), str(it.get('vendidos') or 0), str(it.get('devueltos') or 0)])
    if len(ranking_rows) == 1:
        ranking_rows.append(['—', '0', '0'])
    tbl2 = Table(ranking_rows, colWidths=[220, 80, 80])
    tbl2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E2E8F0')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), .5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    tw2, th2 = tbl2.wrapOn(pdf, w-68, h)
    if y - th2 < 40:
        pdf.showPage(); y = h - 40
    tbl2.drawOn(pdf, 34, y-th2)

    pdf.showPage()
    pdf.save()
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'contabilidad_{desde}_a_{hasta}.pdf')

# ---- SUPER ADMIN: borrar/anular cobros y reset total ----

def _caja_delete_cobro(fecha_str: str, seudonimo: str):
    t, r = _leer_xml(CAJA_XML)
    dia = _get_dia(r, fecha_str)
    cobros = dia.find("cobros")
    if cobros is None:
        return False
    node = cobros.find(f"./cobro[@seudonimo='{seudonimo}']")
    if node is None:
        return False
    cobros.remove(node)
    _guardar_xml(t, CAJA_XML)
    return True

@app.delete("/api/superadmin/cobro")
def api_superadmin_delete_cobro():
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    if not _require_super():
        return jsonify({"ok": False, "error": "solo-superadmin"}), 403
    fecha = (request.args.get("fecha") or "").strip()
    seud = (request.args.get("seudonimo") or "").strip()
    if not fecha or not seud:
        return jsonify({"ok": False, "error": "faltan-parametros"}), 400
    ok = _caja_delete_cobro(fecha, seud)
    _audit_event("caja", "delete_cobro", f"{fecha}__{seud}", {"ok": ok})
    return jsonify({"ok": ok})

@app.post("/api/superadmin/cobro/anular")
def api_superadmin_anular_cobro():
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    if not _require_super():
        return jsonify({"ok": False, "error": "solo-superadmin"}), 403
    data = request.get_json(silent=True) or {}
    fecha = (data.get("fecha") or "").strip()
    seud = (data.get("seudonimo") or "").strip()
    motivo = (data.get("motivo") or "").strip()
    if not fecha or not seud:
        return jsonify({"ok": False, "error": "faltan-parametros"}), 400
    # Anular: deja registro pero lo marca NO pagado y en cero
    _upsert_cobro(fecha, seud, {
        "devueltos": 0,
        "vendidos": 0,
        "total_pagar": 0,
        "transferencia": 0,
        "efectivo": 0,
        "pagado": False,
        "creado_por": session.get("usuario",""),
        "creado_rol": session.get("rol",""),
        "creado_ip": request.remote_addr or "",
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    _audit_event("caja", "anular_cobro", f"{fecha}__{seud}", {"motivo": motivo})
    return jsonify({"ok": True})

@app.post("/api/superadmin/reset-contabilidad")
def api_superadmin_reset_contabilidad():
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    if not _require_super():
        return jsonify({"ok": False, "error": "solo-superadmin"}), 403

    data = request.get_json(silent=True) or {}
    confirm = (data.get("confirm") or "").strip().upper()
    if confirm != "BORRAR TODO":
        return jsonify({"ok": False, "error": "confirmacion-invalida", "hint": "Envíe confirm='BORRAR TODO'"}), 400

    scopes = data.get("scopes") or ["caja", "gastos", "banco", "asignaciones"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(PERSIST_CONTAB_DIR, "backups", f"reset_{ts}")
    os.makedirs(backup_dir, exist_ok=True)

    # Backup antes de borrar
    for p in [CAJA_XML, GASTOS_XML, BANCOS_XML, ASIGNACIONES_XML, AUDIT_XML]:
        _safe_backup_copy(p, backup_dir)

    # Reset según scopes
    if "caja" in scopes:
        _reset_xml(CAJA_XML, "caja")
    if "gastos" in scopes:
        _reset_xml(GASTOS_XML, "gastos")
    if "banco" in scopes:
        _reset_xml(BANCOS_XML, "banco")
    if "asignaciones" in scopes:
        _reset_xml(ASIGNACIONES_XML, "asignaciones")

    _audit_event("sistema", "reset_contabilidad", "", {"scopes": ",".join(scopes), "backup_dir": backup_dir})

    return jsonify({"ok": True, "backup_dir": backup_dir, "scopes": scopes})

@app.get("/api/superadmin/auditoria")
def api_superadmin_auditoria():
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    if not _require_super():
        return jsonify({"ok": False, "error": "solo-superadmin"}), 403
    desde = request.args.get("desde") or (date.today() - timedelta(days=30)).isoformat()
    hasta = request.args.get("hasta") or date.today().isoformat()
    tree, root = _xml_read(AUDIT_XML)
    out = []
    for ev in root.findall("evento"):
        f = ev.findtext("fecha","")
        if f and f < desde: 
            continue
        if f and f > hasta:
            continue
        det = {}
        dnode = ev.find("detalle")
        if dnode is not None:
            for d in dnode.findall("d"):
                det[d.get("k","")] = d.text or ""
        out.append({
            "id": ev.get("id",""),
            "fecha": f,
            "hora": ev.findtext("hora",""),
            "timestamp": ev.findtext("timestamp",""),
            "usuario": ev.findtext("usuario",""),
            "rol": ev.findtext("rol",""),
            "ip": ev.findtext("ip",""),
            "modulo": ev.findtext("modulo",""),
            "accion": ev.findtext("accion",""),
            "ref": ev.findtext("ref",""),
            "detalle": det,
        })
    out.sort(key=lambda x: (x["fecha"], x["hora"], x["id"]))
    return jsonify({"ok": True, "items": out})

@app.route("/contabilidad/balance")
def contabilidad_balance():
    if 'usuario' not in session:
        return redirect(_login_url())
    # HTML + JS (sin f-strings para evitar errores)
    return Response("""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Balance Contable - GL</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body{font-family:system-ui,Segoe UI,Roboto,Arial; background:#0b1220; color:#e8eefc; margin:0}
    header{padding:16px 20px; background:linear-gradient(90deg,#0d1b3d,#0b1220); border-bottom:1px solid rgba(255,255,255,.08)}
    h1{margin:0; font-size:18px; letter-spacing:.3px}
    .wrap{padding:18px; display:grid; gap:14px}
    .row{display:grid; grid-template-columns: 1fr; gap:14px}
    @media(min-width:1100px){ .row{grid-template-columns: 360px 1fr} }
    .card{background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.10); border-radius:14px; padding:14px}
    .grid4{display:grid; grid-template-columns:repeat(2,1fr); gap:10px}
    @media(min-width:900px){ .grid4{grid-template-columns:repeat(4,1fr)} }
    .k{font-size:12px; opacity:.85}
    .v{font-size:20px; font-weight:800; margin-top:6px}
    input,button,select{background:#0f1a33; color:#e8eefc; border:1px solid rgba(255,255,255,.12); border-radius:10px; padding:10px 12px}
    button{cursor:pointer}
    button.danger{background:#3a0c12; border-color:#7c1b2a}
    table{width:100%; border-collapse:collapse; font-size:13px}
    th,td{padding:10px 8px; border-bottom:1px solid rgba(255,255,255,.08); text-align:left; vertical-align:top}
    th{font-size:12px; opacity:.9}
    a{color:#9ad1ff; text-decoration:none}
    .pill{display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; border:1px solid rgba(255,255,255,.16); background:rgba(255,255,255,.06)}
    .muted{opacity:.75}
    .right{display:flex; gap:10px; flex-wrap:wrap; align-items:center}
  </style>
</head>
<body>
<header>
  <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap">
    <h1>Balance contable (Caja + Banco + Gastos)</h1>
    <div class="right">
      <label class="muted">Desde</label><input id="desde" type="date">
      <label class="muted">Hasta</label><input id="hasta" type="date">
      <button id="btnCargar">Cargar</button>
      <a id="btnExport" class="pill" href="#" target="_blank">Exportar CSV</a>
      <a class="pill" href="/contabilidad" target="_blank">Resumen</a>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="grid4">
    <div class="card"><div class="k">Ingresos (Cobros)</div><div class="v" id="kIngresos">$0.00</div></div>
    <div class="card"><div class="k">Gastos</div><div class="v" id="kGastos">$0.00</div></div>
    <div class="card"><div class="k">Banco (Saldo neto rango)</div><div class="v" id="kBanco">$0.00</div></div>
    <div class="card"><div class="k">Balance (Ingresos - Gastos)</div><div class="v" id="kBalance">$0.00</div></div>
  </div>

  <div class="row">
    <div class="card">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap">
        <div>
          <div class="k">Acciones</div>
          <div class="muted" id="who"></div>
        </div>
        <div class="right" id="superBox" style="display:none">
          <button class="danger" id="btnReset">Reset contabilidad</button>
        </div>
      </div>
      <hr style="border:0;border-top:1px solid rgba(255,255,255,.10);margin:12px 0">
      <div class="k">Auditoría (últimos 30 días)</div>
      <div style="max-height:260px; overflow:auto; margin-top:10px">
        <table id="tblAudit">
          <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Ref</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="k" style="margin-bottom:8px">Curva (Ingresos vs Gastos)</div>
      <canvas id="ch1" height="120"></canvas>
      <div class="k" style="margin-top:14px;margin-bottom:8px">Detalle de movimientos</div>
      <div style="max-height:420px; overflow:auto">
        <table id="tblMov">
          <thead>
            <tr>
              <th>Fecha</th><th>Tipo</th><th>Monto</th><th>Medio/Banco</th><th>Referencia</th><th>Usuario</th><th>Comprobante</th><th id="thAcc" style="display:none">Acción</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<script>
const money = n => {
  const x = Number(n||0);
  return x.toLocaleString('es-EC',{style:'currency',currency:'USD'});
};

let chart1 = null;
let isSuper = false;

async function sessionInfo(){
  const r = await fetch('/api/session'); const j = await r.json();
  isSuper = !!j.is_superadmin;
  document.getElementById('who').textContent = `${j.usuario || ''} • ${j.rol || ''}`;
  document.getElementById('superBox').style.display = isSuper ? '' : 'none';
  document.getElementById('thAcc').style.display = isSuper ? '' : 'none';
}

function todayISO(){
  const d = new Date();
  return d.toISOString().slice(0,10);
}
function daysAgoISO(n){
  const d = new Date(); d.setDate(d.getDate()-n);
  return d.toISOString().slice(0,10);
}

async function cargar(){
  const desde = document.getElementById('desde').value;
  const hasta = document.getElementById('hasta').value;

  document.getElementById('btnExport').href = `/api/contabilidad/export.csv?desde=${desde}&hasta=${hasta}`;

  // resumen básico
  const r1 = await fetch(`/api/contabilidad/resumen?desde=${desde}&hasta=${hasta}`);
  const j1 = await r1.json();

  const ingresos = (j1.caja && j1.caja.total_pagado) ? Number(j1.caja.total_pagado) : 0;
  const gastos   = (j1.gastos && j1.gastos.total) ? Number(j1.gastos.total) : 0;
  const bancoN   = (j1.banco && j1.banco.saldo) ? Number(j1.banco.saldo) : 0;

  document.getElementById('kIngresos').textContent = money(ingresos);
  document.getElementById('kGastos').textContent   = money(gastos);
  document.getElementById('kBanco').textContent    = money(bancoN);
  document.getElementById('kBalance').textContent  = money(ingresos - gastos);

  // movimientos
  const r2 = await fetch(`/api/contabilidad/movimientos?desde=${desde}&hasta=${hasta}`);
  const j2 = await r2.json();
  renderMov(j2.items || []);

  // curva simple por día desde resumen (si existe)
  const labels = (j1.curva && j1.curva.labels) ? j1.curva.labels : [];
  const dataIngresos = (j1.curva && j1.curva.ingresos) ? j1.curva.ingresos : [];
  const dataGastos   = (j1.curva && j1.curva.gastos) ? j1.curva.gastos : [];

  if(chart1) chart1.destroy();
  const ctx = document.getElementById('ch1').getContext('2d');
  chart1 = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Ingresos', data: dataIngresos },
      { label: 'Gastos', data: dataGastos },
    ]},
    options: { responsive:true, plugins:{legend:{labels:{color:'#e8eefc'}}}, scales:{x:{ticks:{color:'#e8eefc'}},y:{ticks:{color:'#e8eefc'}}}}
  });
}

function renderMov(items){
  const tbody = document.querySelector('#tblMov tbody');
  tbody.innerHTML = '';
  for(const it of items){
    const tr = document.createElement('tr');
    const comp = it.comprobante ? `<a href="/static/${it.comprobante}" target="_blank">Ver</a>` : '';
    const monto = (it.naturaleza === 'egreso') ? -Number(it.monto||0) : Number(it.monto||0);
    const tipo = it.tipo === 'banco' ? `Banco (${it.detalle && it.detalle.tipo_banco ? it.detalle.tipo_banco : ''})` : it.tipo;
    const medio = it.tipo === 'banco' ? (it.banco || '') : (it.medio || '');
    const usuario = it.creado_por || '';

    let btn = '';
    if(isSuper){
      if(it.tipo === 'gasto'){
        btn = `<button class="danger" data-t="gasto" data-id="${it.id}">Eliminar</button>`;
      } else if(it.tipo === 'banco'){
        btn = `<button class="danger" data-t="banco" data-id="${it.id}">Eliminar</button>`;
      } else if(it.tipo === 'cobro'){
        btn = `<button class="danger" data-t="cobro" data-id="${it.id}" data-f="${it.fecha}" data-s="${it.seudonimo}">Eliminar</button>`;
      }
    }

    tr.innerHTML = `
      <td>${it.fecha || ''} <span class="muted">${it.hora || ''}</span></td>
      <td><span class="pill">${tipo}</span></td>
      <td>${money(monto)}</td>
      <td>${medio}</td>
      <td>${it.referencia || ''}</td>
      <td>${usuario}</td>
      <td>${comp}</td>
      <td class="acc" style="display:${isSuper?'table-cell':'none'}">${btn}</td>
    `;
    tbody.appendChild(tr);
  }

  // acciones borrar
  if(isSuper){
    tbody.querySelectorAll('button.danger').forEach(b=>{
      b.addEventListener('click', async ()=>{
        const t = b.dataset.t;
        if(!confirm('¿Seguro? Esto quedará registrado en auditoría.')) return;
        if(t === 'gasto'){
          const r = await fetch(`/api/gastos/${b.dataset.id}`, {method:'DELETE'});
          await r.json(); await cargar(); await cargarAuditoria();
        }
        if(t === 'banco'){
          const r = await fetch(`/api/banco/movimientos/${b.dataset.id}?force=1`, {method:'DELETE'});
          await r.json(); await cargar(); await cargarAuditoria();
        }
        if(t === 'cobro'){
          const f = b.dataset.f; const s = b.dataset.s;
          const r = await fetch(`/api/superadmin/cobro?fecha=${f}&seudonimo=${encodeURIComponent(s)}`, {method:'DELETE'});
          await r.json(); await cargar(); await cargarAuditoria();
        }
      })
    })
  }
}

async function cargarAuditoria(){
  if(!isSuper){
    document.querySelector('#tblAudit tbody').innerHTML = '<tr><td colspan="4" class="muted">Solo visible para Super Admin</td></tr>';
    return;
  }
  const desde = daysAgoISO(30);
  const hasta = todayISO();
  const r = await fetch(`/api/superadmin/auditoria?desde=${desde}&hasta=${hasta}`);
  const j = await r.json();
  const tbody = document.querySelector('#tblAudit tbody');
  tbody.innerHTML = '';
  (j.items || []).slice(-200).reverse().forEach(ev=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${ev.fecha} <span class="muted">${ev.hora||''}</span></td><td>${ev.usuario||''}</td><td>${ev.modulo||''}:${ev.accion||''}</td><td class="muted">${ev.ref||''}</td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById('btnCargar').addEventListener('click', async ()=>{ await cargar(); await cargarAuditoria(); });

document.getElementById('btnReset').addEventListener('click', async ()=>{
  if(!isSuper) return;
  const txt = prompt('Escribe BORRAR TODO para dejar contabilidad en blanco (se hace backup automático).');
  if(!txt) return;
  const r = await fetch('/api/superadmin/reset-contabilidad', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({confirm: txt, scopes:['caja','gastos','banco','asignaciones']})
  });
  const j = await r.json();
  if(!j.ok){ alert('No se pudo: ' + (j.error||'')); return; }
  alert('Listo. Backup: ' + j.backup_dir);
  await cargar(); await cargarAuditoria();
});

// init
(async ()=>{
  document.getElementById('desde').value = daysAgoISO(30);
  document.getElementById('hasta').value = todayISO();
  await sessionInfo();
  await cargar();
  await cargarAuditoria();
})();
</script>
</body>
</html>""", mimetype="text/html")


# ---- ENDPOINTS para curvas por vendedor (ventas / devueltos / combinado) ----
def _caja_iter_cobros_rango(desde_iso, hasta_iso):
    _, root = _leer_xml(CAJA_XML)
    for f in _daterange(desde_iso, hasta_iso):
        dia = root.find(f"./dia[@fecha='{f}']")
        if dia is None:
            continue
        for r in _caja_iter_cobros_dia(dia):
            if r.get('pagado'):
                yield (f, r.get('seudonimo') or '', _safe_int(r.get('vendidos', 0)), _safe_int(r.get('devueltos', 0)))

@app.get("/api/contabilidad/ventas-vendedores")
def api_ventas_vendedores():
    desde = (request.args.get("desde") or date.today().isoformat()).strip()
    hasta = (request.args.get("hasta") or date.today().isoformat()).strip()
    agg = {}
    for _, seud, vend, _ in _caja_iter_cobros_rango(desde, hasta):
        agg[seud] = agg.get(seud, 0) + vend
    items = [{"vendedor": k or "(sin seudónimo)", "vendidos": v} for k, v in agg.items()]
    return jsonify(ok=True, items=sorted(items, key=lambda x: -x["vendidos"]))

@app.get("/api/contabilidad/devueltos-vendedores")
def api_devueltos_vendedores():
    desde = (request.args.get("desde") or date.today().isoformat()).strip()
    hasta = (request.args.get("hasta") or date.today().isoformat()).strip()
    agg = {}
    for _, seud, _, dev in _caja_iter_cobros_rango(desde, hasta):
        agg[seud] = agg.get(seud, 0) + dev
    items = [{"vendedor": k or "(sin seudónimo)", "devueltos": v} for k, v in agg.items()]
    return jsonify(ok=True, items=sorted(items, key=lambda x: -x["devueltos"]))

@app.get("/api/contabilidad/vendedores_ranking")
def api_vendedores_ranking():
    desde = (request.args.get("desde") or date.today().isoformat()).strip()
    hasta = (request.args.get("hasta") or date.today().isoformat()).strip()
    agg = {}
    for _, seud, vend, dev in _caja_iter_cobros_rango(desde, hasta):
        ref = agg.setdefault(seud or "(sin seudónimo)", {"vendedor": seud or "(sin seudónimo)", "vendidos": 0, "devueltos": 0})
        ref["vendidos"]  += vend
        ref["devueltos"] += dev
    return jsonify(ok=True, items=sorted(agg.values(), key=lambda x: (-x["vendidos"], x["devueltos"])))





#JUEGO #

# ===========================
#  JUEGO + SPINNERS + FIGURAS
#  (Blueprint: /juego/*)
# ===========================
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
import os, json, re, xml.etree.ElementTree as ET
from datetime import datetime, date
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, session, send_file, make_response

# ============================================================
#  CONFIG & RUTAS (respeta tu DATA_DIR si ya existe)
# ============================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = globals().get("DATA_DIR") or os.getenv("DATA_DIR") or _BASE_DIR
# DB pública (para el navegador /static/*) y DB persistente (Render: DATA_DIR/static/db)
DB_DIR_PUBLIC = os.path.join(_BASE_DIR, "static", "db")
DB_DIR_PERSIST = os.path.join(DATA_DIR, "static", "db")
os.makedirs(DB_DIR_PUBLIC, exist_ok=True)
os.makedirs(DB_DIR_PERSIST, exist_ok=True)

# Sembrar archivos del repo hacia el disco persistente si aún no existen
for _rel in (
    "datos_bingo.xml",
    "historial.json",
    "vmix_spinners.xml",
    "spinners.xml",
    "vmix_bonus.xml",
    "vmix_reintegro.xml",
    "vmix_reintegros.xml",
    "sorteos.xml",
    "figuras_del_dia.xml",
    "datos_figuras.xml",
    "figuras_estado.json",
    "ganadores.xml",
    "ganadores.json",
    "ganadores_state.json",
    "spinners_state.json",
    "config_sorteo.json",
    "sorteo.json",
):
    try:
        _seed(os.path.join("static", "db", _rel), os.path.join(DB_DIR_PERSIST, _rel))
    except Exception:
        pass

# La base viva siempre se trabaja desde el disco persistente
DB_DIR = DB_DIR_PERSIST
# Archivos core
BINGO_XML     = os.path.join(DB_DIR, "datos_bingo.xml")
HIST_JSON     = os.path.join(DB_DIR, "historial.json")
VMIX_NUMEROS_XML = os.path.join(DB_DIR, "vmix_numeros.xml")
VMIX_NUMEROS_MEDIA_DIR = (os.getenv("VMIX_NUMEROS_MEDIA_DIR") or os.path.join(VMIX_MEDIA_ROOT, "NUMEROS")).strip()
VMIX_NUMEROS_INACTIVA_FILE = os.getenv("VMIX_NUMEROS_INACTIVA_FILE", "INACTIVA")

# Spinners (VMIX overlay + fallback XML)
VMIX_SPINNERS_XML = globals().get("VMIX_SPINNERS_XML", os.path.join(DB_DIR, "vmix_spinners.xml"))
SPINNERS_XML      = globals().get("SPINNERS_XML",      os.path.join(DB_DIR, "spinners.xml"))
SPINNERS_STATE_JSON = os.path.join(DB_DIR, "spinners_state.json")

# Bonus / Reintegro para panel de juego (XML para vMix Data Source)
VMIX_BONUS_XML = os.path.join(DB_DIR, "vmix_bonus.xml")
VMIX_REINTEGRO_XML_GAME = os.path.join(DB_DIR, "vmix_reintegro.xml")
VMIX_REINTEGROS_XML_GAME = os.path.join(DB_DIR, "vmix_reintegros.xml")

# Sorteos / Figuras
SORTEOS_XML = globals().get("SORTEOS_XML", os.path.join(DB_DIR, "sorteos.xml"))
SORTEO_JSON_CANDIDATES = [
    os.path.join(DB_DIR, "sorteo.json"),
    os.path.join(DB_DIR, "config_sorteo.json"),
]
FIGURAS_DIR         = os.path.join(DB_DIR, "figuras")
FIGURAS_DEL_DIA_XML = os.path.join(DB_DIR, "figuras_del_dia.xml")
DATOS_FIGURAS_XML   = os.path.join(DB_DIR, "datos_figuras.xml")
os.makedirs(FIGURAS_DIR, exist_ok=True)
FIG_ESTADOS_JSON = os.path.join(DB_DIR, "figuras_estado.json")
GAME_STATES_DIR = os.path.join(DB_DIR, "juegos_estado")
os.makedirs(GAME_STATES_DIR, exist_ok=True)

# vMix API (HTTP) — opcional
VMIX_HOST = os.getenv("VMIX_HOST", "127.0.0.1")
VMIX_PORT = os.getenv("VMIX_PORT", "8088")
VMIX_OVERLAY_INDEX = int(os.getenv("VMIX_OVERLAY_INDEX", "3"))
VMIX_SPINNER_INPUT = os.getenv("VMIX_SPINNER_INPUT", "SpinnerOverlay")

require_session = globals().get("require_session", None)

# ============================================================
#  BLUEPRINT
# ============================================================
juego_bp = Blueprint("juego", __name__, url_prefix="/juego")


# ============================
#  GANADORES (detección real)
#  - Detecta tablas ganadoras SOLO dentro de los rangos impresos (boletos) del día
#  - Cruza FIGURAS DEL DÍA (figuras_por_fecha.xml) + patrones (datos_figuras.xml)
#  - Escribe ganadores.xml (con colores + números) para usarlo en vMix / overlays
# ============================
from collections import defaultdict

GANADORES_XML         = os.path.join(DB_DIR, "ganadores.xml")
GANADORES_JSON        = os.path.join(DB_DIR, "ganadores.json")
GANADORES_STATE_JSON  = os.path.join(DB_DIR, "ganadores_state.json")
GANADORES_XML_PUBLIC  = os.path.join(BASE_DIR, "static", "db", "ganadores.xml")  # compat (por si alguien lee static/db)

def _safe_json_read(path):
    fn = globals().get("_json_read")
    if callable(fn):
        return fn(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _safe_json_write(path, data):
    fn = globals().get("_json_write")
    if callable(fn):
        return fn(path, data)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _game_state_path(fecha_iso: str) -> str:
    fecha = _norm_fecha_key(fecha_iso) or date.today().isoformat()
    fecha = re.sub(r"[^0-9\-]", "_", str(fecha))[:32] or date.today().isoformat()
    return os.path.join(GAME_STATES_DIR, f"{fecha}.json")


def _sanitize_stack_values(values):
    out = []
    seen = set()
    for x in (values or []):
        try:
            n = int(str(x).strip())
        except Exception:
            continue
        if not (1 <= n <= 75):
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _read_game_state_snapshot(fecha_iso: str):
    try:
        data = _safe_json_read(_game_state_path(fecha_iso)) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_game_state_snapshot(fecha_iso: str | None = None, *, stinger=None):
    try:
        fecha = _norm_fecha_key(fecha_iso or (_get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else date.today().isoformat())) or date.today().isoformat()
    except Exception:
        fecha = date.today().isoformat()

    stack = _sanitize_stack_values(_read_stack() if callable(globals().get("_read_stack")) else [])
    last = stack[-1] if stack else 0
    stinger_txt = str(stinger).strip() if stinger not in (None, "") else (str(last) if last else "")

    cfg = {}
    try:
        if callable(globals().get("_sorteo_read_config")):
            cfg = _sorteo_read_config(fecha) or {}
    except Exception:
        cfg = {}

    payload = {
        "fecha": fecha,
        "stack": stack,
        "last": last,
        "ultimos5": list(reversed(stack[-5:])),
        "total": len(stack),
        "stinger": stinger_txt,
        "activo": str((cfg or {}).get("activo") or ""),
        "finalizado": str((cfg or {}).get("finalizado") or ""),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _safe_json_write(_game_state_path(fecha), payload)
    return payload


def _restore_game_state_for_fecha(fecha_iso: str, *, save_if_missing: bool = False):
    fecha = _norm_fecha_key(fecha_iso) or date.today().isoformat()
    snap = _read_game_state_snapshot(fecha)
    stack = _sanitize_stack_values(snap.get("stack") or [])
    last = stack[-1] if stack else 0
    stinger_txt = str(snap.get("stinger") or (str(last) if last else "")).strip()

    _write_stack(stack)
    _sync_bingo_xml_from_stack(stack)

    try:
        tree = ET.parse(BINGO_XML)
        root = tree.getroot()
        st = root.find("stinger") or ET.SubElement(root, "stinger")
        st.text = stinger_txt
        tree.write(BINGO_XML, encoding="utf-8", xml_declaration=True)
    except Exception:
        pass

    ganadores_fecha = []
    try:
        data_g = _safe_json_read(GANADORES_JSON) or {}
        raw_g = data_g.get(str(fecha), [])
        if isinstance(raw_g, list):
            ganadores_fecha = raw_g
    except Exception:
        ganadores_fecha = []

    try:
        if ganadores_fecha:
            keys = []
            for g in ganadores_fecha:
                try:
                    keys.append(_ganador_key(str(fecha), g))
                except Exception:
                    continue
            keys = sorted(list(dict.fromkeys(keys)))
            _safe_json_write(GANADORES_STATE_JSON, {"keys": keys})
            _write_ganadores_xml(str(fecha), int(last or 0), ganadores_fecha)
        elif stack:
            ganadores_total, _ = _recalcular_ganadores(str(fecha), stack, int(last or 0))
            ganadores_fecha = ganadores_total or []
            if ganadores_fecha:
                _sync_resultados_from_juego(str(fecha), ganadores_fecha)
            else:
                _safe_json_write(GANADORES_STATE_JSON, {"keys": []})
                _write_ganadores_xml(str(fecha), int(last or 0), [])
        else:
            _safe_json_write(GANADORES_STATE_JSON, {"keys": []})
            _write_ganadores_xml(str(fecha), int(last or 0), [])
    except Exception:
        try:
            _safe_json_write(GANADORES_STATE_JSON, {"keys": []})
            _write_ganadores_xml(str(fecha), int(last or 0), [])
        except Exception:
            pass

    try:
        _refresh_vmix_figuras_panel_for_fecha(str(fecha))
    except Exception:
        pass

    if save_if_missing and not snap:
        try:
            _save_game_state_snapshot(str(fecha), stinger=stinger_txt)
        except Exception:
            pass

    return {
        "fecha": fecha,
        "stack": stack,
        "last": last,
        "restored": bool(snap),
        "snapshot_path": _game_state_path(fecha),
    }


def _write_game_xml_dual(tree: ET.ElementTree, filename: str):
    """Espeja XML en static/db y DATA/static/db para que vMix y Render lo lean igual."""
    destinos = []
    for base in (DB_DIR_PUBLIC, DB_DIR_PERSIST, DB_DIR):
        try:
            p = os.path.join(base, filename)
            if p not in destinos:
                destinos.append(p)
        except Exception:
            pass
    for p in destinos:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tree.write(p, encoding="utf-8", xml_declaration=True)
    return destinos

def _parse_bonus_numbers_any(raw):
    if raw is None:
        return []
    vals = []
    for tok in re.findall(r"\d+", str(raw)):
        try:
            n = int(tok)
        except Exception:
            continue
        if 1 <= n <= 75:
            vals.append(n)
    # quitar duplicados conservando orden y limitar a 5
    out, seen = [], set()
    for n in vals:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        if len(out) >= 5:
            break
    return out

def _norm_fecha_key(v):
    s = str(v or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", s)
    if m:
        d, mo, y = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    if len(s) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return s

def _get_extras_impresion_dia(fecha_iso: str):
    """Lee BONUS (5 números) y REINTEGRO desde impresiones.xml del día del sorteo."""
    fecha_key = _norm_fecha_key(fecha_iso)
    info = {"fecha": fecha_key, "bonus_numbers": [], "bonus_code": "", "bonus_feasible": None, "reintegro": ""}

    try:
        gi = globals().get("get_impresiones_info")
        if callable(gi):
            imp = gi(fecha_key) or {}
            info["reintegro"] = str(imp.get("reintegro_dia") or imp.get("reintegro") or "").strip()
    except Exception:
        pass

    imp_xml = globals().get("IMP_XML_PATH")
    if not imp_xml or (not os.path.exists(imp_xml)):
        return info
    try:
        root = ET.parse(imp_xml).getroot()
    except Exception:
        return info

    candidatos = []
    for it in root.findall(".//impresion"):
        fx = (
            (it.findtext("fecha_sorteo") or "").strip()
            or (it.attrib.get("fecha_sorteo") or "").strip()
            or (it.attrib.get("fecha") or "").strip()
            or (it.findtext("fecha") or "").strip()
        )
        if not fx:
            fh = (it.attrib.get("fecha_hora") or "").strip() or (it.findtext("fecha_hora") or "").strip()
            fx = _norm_fecha_key((fh[:10] if len(fh) >= 10 else fh))
        else:
            fx = _norm_fecha_key(fx)

        if fx != fecha_key:
            continue

        tipo = ((it.attrib.get("tipo") or "").strip().lower() or (it.findtext("tipo") or "").strip().lower())
        if tipo and tipo not in ("boletos", "b", "ticket", "tickets"):
            continue
        candidatos.append(it)

    if not candidatos:
        return info

    def _k(node):
        try:
            return int((node.attrib.get("id") or node.findtext("id") or "0").strip() or 0)
        except Exception:
            return 0
    candidatos.sort(key=_k)

    for it in reversed(candidatos):
        bx = it.find("bonus")
        bonus_raw = ((it.attrib.get("bonus_numbers") or "").strip() or (it.findtext("bonus_numbers") or "").strip())
        if not bonus_raw and bx is not None:
            bonus_raw = ((bx.attrib.get("numbers") or "").strip() or (bx.findtext("numbers") or "").strip())

        if not info.get("bonus_code"):
            info["bonus_code"] = (
                (it.attrib.get("bonus_code") or "").strip()
                or (it.findtext("bonus_code") or "").strip()
                or ((bx.attrib.get("code") if bx is not None else "") or "").strip()
                or ((bx.findtext("code") if bx is not None else "") or "").strip()
            )

        if info.get("bonus_feasible") is None and bx is not None:
            feas = ((bx.attrib.get("feasible") or "").strip() or (bx.findtext("feasible") or "").strip()).lower()
            if feas in ("1", "true", "si", "sí", "yes"):
                info["bonus_feasible"] = True
            elif feas in ("0", "false", "no"):
                info["bonus_feasible"] = False

        nums = _parse_bonus_numbers_any(bonus_raw)
        if nums and not info.get("bonus_numbers"):
            info["bonus_numbers"] = nums

        if not info.get("reintegro"):
            rein = ((it.attrib.get("reintegro_especial") or "").strip() or (it.findtext("reintegro_especial") or "").strip())
            if not rein:
                rn = it.find("reintegro")
                if rn is not None:
                    rein = ((rn.attrib.get("nombre") or rn.attrib.get("value") or "").strip() or (rn.text or "").strip())
            if rein:
                info["reintegro"] = rein

        if info.get("bonus_numbers") and info.get("reintegro"):
            break

    return info

def _read_bonus_click_state():
    out = {"selected_index": 0, "selected_number": 0, "click_count": 0, "click_token": ""}
    try:
        if not os.path.exists(VMIX_BONUS_XML):
            return out
        root = ET.parse(VMIX_BONUS_XML).getroot()
        out["selected_index"] = int((root.findtext("selected_index") or "0").strip() or 0)
        out["selected_number"] = int((root.findtext("selected_number") or "0").strip() or 0)
        out["click_count"] = int((root.findtext("click_count") or "0").strip() or 0)
        out["click_token"] = (root.findtext("click_token") or "").strip()
    except Exception:
        pass
    return out

def _read_reintegro_click_state():
    out = {"click_count": 0, "click_token": ""}
    try:
        if not os.path.exists(VMIX_REINTEGRO_XML_GAME):
            return out
        root = ET.parse(VMIX_REINTEGRO_XML_GAME).getroot()
        out["click_count"] = int((root.findtext("click_count") or "0").strip() or 0)
        out["click_token"] = (root.findtext("click_token") or "").strip()
    except Exception:
        pass
    return out

def _write_vmix_bonus_click(fecha_iso: str, bonus_numbers, selected_index: int):
    nums = []
    for x in (bonus_numbers or []):
        try:
            n = int(str(x).strip())
        except Exception:
            continue
        if 1 <= n <= 75:
            nums.append(n)
    nums = nums[:5]
    if not nums:
        raise ValueError("No hay bonus del día")

    try:
        idx = int(selected_index)
    except Exception:
        idx = 0
    if idx < 1 or idx > len(nums):
        raise ValueError("Índice de bonus inválido")

    sel = nums[idx - 1]
    prev = _read_bonus_click_state()
    click_count = int(prev.get("click_count") or 0) + 1
    token = datetime.now().strftime("%Y%m%d%H%M%S%f")

    root = ET.Element("bonus", fecha=str(fecha_iso or ""))
    ET.SubElement(root, "count").text = str(len(nums))
    lista = ET.SubElement(root, "numbers")
    for i in range(5):
        v = str(nums[i]) if i < len(nums) else ""
        ET.SubElement(lista, f"n{i+1}").text = v
    ET.SubElement(root, "selected_index").text = str(idx)
    ET.SubElement(root, "selected_number").text = str(sel)
    ET.SubElement(root, "click_count").text = str(click_count)
    ET.SubElement(root, "click_token").text = token
    ET.SubElement(root, "updated_at").text = datetime.now().isoformat(timespec="seconds")

    _write_game_xml_dual(ET.ElementTree(root), "vmix_bonus.xml")
    return {"selected_index": idx, "selected_number": sel, "click_count": click_count, "click_token": token}

def _write_vmix_reintegro_click(fecha_iso: str, reintegro_nombre: str):
    rein = str(reintegro_nombre or "").strip()
    if not rein:
        raise ValueError("No hay reintegro del día")

    prev_clicks = 0
    try:
        if os.path.exists(VMIX_REINTEGRO_XML_GAME):
            r0 = ET.parse(VMIX_REINTEGRO_XML_GAME).getroot()
            prev_clicks = int((r0.findtext("click_count") or "0").strip() or 0)
    except Exception:
        pass

    click_count = prev_clicks + 1
    token = datetime.now().strftime("%Y%m%d%H%M%S%f")
    meta = _resolve_reintegro_media(rein)

    root_flat = _build_reintegro_root(
        fecha_iso, rein, meta.get("flat_archivo"), meta.get("flat_ruta"),
        meta.get("flat_carpeta"), meta.get("flat_encontrado"), click_count, token
    )
    root_seq = _build_reintegro_root(
        fecha_iso, rein, meta.get("seq_archivo"), meta.get("seq_ruta"),
        meta.get("seq_carpeta"), meta.get("seq_encontrado"), click_count, token
    )

    _write_game_xml_dual(ET.ElementTree(root_flat), "vmix_reintegro.xml")
    _write_game_xml_dual(ET.ElementTree(root_seq), "vmix_reintegros.xml")
    return {
        "nombre": rein,
        "click_count": click_count,
        "click_token": token,
        "ruta": meta.get("flat_ruta") or "",
        "ruta_secundaria": meta.get("seq_ruta") or "",
    }

def _sync_vmix_bonus_snapshot(fecha_iso: str, bonus_numbers, bonus_code: str = "", bonus_feasible=None):
    """Escribe vmix_bonus.xml con los 5 números del día (sin disparar click)."""
    nums = []
    for x in (bonus_numbers or []):
        try:
            n = int(str(x).strip())
        except Exception:
            continue
        if 1 <= n <= 75 and n not in nums:
            nums.append(n)
    nums = nums[:5]

    prev = _read_bonus_click_state()
    root = ET.Element("bonus", fecha=str(fecha_iso or ""))
    ET.SubElement(root, "count").text = str(len(nums))
    ET.SubElement(root, "code").text = str(bonus_code or "")
    ET.SubElement(root, "feasible").text = ("" if bonus_feasible is None else ("1" if bool(bonus_feasible) else "0"))
    lista = ET.SubElement(root, "numbers")
    for i in range(5):
        ET.SubElement(lista, f"n{i+1}").text = str(nums[i]) if i < len(nums) else ""

    prev_sel_idx = int(prev.get("selected_index") or 0)
    prev_sel_num = int(prev.get("selected_number") or 0)
    if prev_sel_num and prev_sel_num in nums:
        sel_idx = nums.index(prev_sel_num) + 1
        sel_num = prev_sel_num
    elif 1 <= prev_sel_idx <= len(nums):
        sel_idx = prev_sel_idx
        sel_num = nums[sel_idx - 1]
    else:
        sel_idx = 0
        sel_num = 0

    ET.SubElement(root, "selected_index").text = str(sel_idx)
    ET.SubElement(root, "selected_number").text = str(sel_num)
    ET.SubElement(root, "click_count").text = str(int(prev.get("click_count") or 0))
    ET.SubElement(root, "click_token").text = str(prev.get("click_token") or "")
    ET.SubElement(root, "updated_at").text = datetime.now().isoformat(timespec="seconds")
    _write_game_xml_dual(ET.ElementTree(root), "vmix_bonus.xml")


def _sync_vmix_reintegro_snapshot(fecha_iso: str, reintegro_nombre: str):
    rein = str(reintegro_nombre or "").strip()
    prev_clicks = 0
    prev_token = ""
    try:
        if os.path.exists(VMIX_REINTEGRO_XML_GAME):
            r0 = ET.parse(VMIX_REINTEGRO_XML_GAME).getroot()
            prev_clicks = int((r0.findtext("click_count") or "0").strip() or 0)
            prev_token = (r0.findtext("click_token") or "").strip()
    except Exception:
        pass

    meta = _resolve_reintegro_media(rein)
    root_flat = _build_reintegro_root(
        fecha_iso, rein, meta.get("flat_archivo"), meta.get("flat_ruta"),
        meta.get("flat_carpeta"), meta.get("flat_encontrado"), prev_clicks, prev_token
    )
    root_seq = _build_reintegro_root(
        fecha_iso, rein, meta.get("seq_archivo"), meta.get("seq_ruta"),
        meta.get("seq_carpeta"), meta.get("seq_encontrado"), prev_clicks, prev_token
    )

    _write_game_xml_dual(ET.ElementTree(root_flat), "vmix_reintegro.xml")
    _write_game_xml_dual(ET.ElementTree(root_seq), "vmix_reintegros.xml")


def _ensure_extras_vmix_xmls():
    if not os.path.exists(VMIX_BONUS_XML):
        r = ET.Element("bonus")
        for t in ("count","selected_index","selected_number","click_count","click_token","updated_at"):
            ET.SubElement(r, t).text = "0" if t in ("count","selected_index","selected_number","click_count") else ""
        nums = ET.SubElement(r, "numbers")
        for i in range(5):
            ET.SubElement(nums, f"n{i+1}").text = ""
        _write_game_xml_dual(ET.ElementTree(r), "vmix_bonus.xml")
    if not os.path.exists(VMIX_REINTEGRO_XML_GAME):
        r = _build_reintegro_root("", "", "", "", os.path.normpath(REINTEGRO_MEDIA_DIR) if str(REINTEGRO_MEDIA_DIR or "").strip() else "", False, 0, "")
        _write_game_xml_dual(ET.ElementTree(r), "vmix_reintegro.xml")
    if not os.path.exists(VMIX_REINTEGROS_XML_GAME):
        r = _build_reintegro_root("", "", "", "", os.path.normpath(REINTEGROS_MEDIA_DIR) if str(REINTEGROS_MEDIA_DIR or "").strip() else "", False, 0, "")
        _write_game_xml_dual(ET.ElementTree(r), "vmix_reintegros.xml")

def _agenda_paths():
    """figuras_por_fecha.xml (donde guardas las FIGURAS DEL DÍA con VALOR)."""
    paths = []
    # módulo /escoger-figuras guarda aquí:
    paths.append(os.path.join(BASE_DIR, "static", "db", "figuras_por_fecha.xml"))
    # por si existiera en DATA/static/db
    paths.append(os.path.join(DB_DIR, "figuras_por_fecha.xml"))
    # si alguien lo dejó en raíz
    paths.append(os.path.join(BASE_DIR, "figuras_por_fecha.xml"))
    return [p for p in paths if p]

def _load_figuras_por_fecha(fecha_iso: str):
    """Devuelve lista: [{"nombre":..., "valor":float}, ...]"""
    for path in _agenda_paths():
        if not os.path.exists(path):
            continue
        try:
            root = ET.parse(path).getroot()
        except Exception:
            continue
        dia = None
        for d in root.findall("dia"):
            if (d.attrib.get("fecha") or "").strip() == fecha_iso:
                dia = d
                break
        if dia is None:
            continue
        out = []
        for f in dia.findall("fig"):
            nombre = (f.attrib.get("nombre") or "").strip()
            if not nombre:
                continue
            try:
                valor = float((f.attrib.get("valor") or "0").replace(",", "."))
            except Exception:
                valor = 0.0
            out.append({"nombre": nombre, "valor": round(max(valor, 0.0), 2)})
        return out
    return []

def _catalogo_paths():
    """Posibles ubicaciones de datos_figuras.xml (patrones 5x5)."""
    paths = []
    # variable global (módulo principal)
    gx = globals().get("FIGURAS_XML")
    if gx: paths.append(gx)
    # ubicaciones comunes
    paths.append(os.path.join(BASE_DIR, "static", "db", "datos_figuras.xml"))
    paths.append(os.path.join(DB_DIR, "datos_figuras.xml"))
    # fallback: por si quedó con otro nombre
    paths.append(os.path.join(BASE_DIR, "static", "db", "datos_figuras.XML"))
    return [p for p in paths if p]

def _load_catalogo_figuras_any():
    """Intenta usar load_catalogo_figuras() si existe; si no, carga datos_figuras.xml directamente."""
    fn = globals().get("load_catalogo_figuras")
    if callable(fn):
        try:
            cat = fn()
            if isinstance(cat, dict) and cat:
                return cat
        except Exception:
            pass

    for path in _catalogo_paths():
        if not os.path.exists(path):
            continue
        try:
            root = ET.parse(path).getroot()
        except Exception:
            continue

        catalogo = {}
        # soporta <figuras><figura ...> o cualquier raíz con .//figura
        for f in root.findall(".//figura"):
            nombre = (f.attrib.get("nombre","") or "").strip()
            if not nombre:
                continue
            code = globals().get("code_for")(nombre) if callable(globals().get("code_for")) else re.sub(r"[^A-Z0-9]", "", nombre.upper())[:4] or "FIG"
            cbloq  = f.attrib.get("centro_bloqueado","0")
            celdas = []
            for c in f.findall("celda"):
                try:
                    idx = int(c.attrib.get("idx","0") or 0)
                except Exception:
                    idx = 0
                color = (c.attrib.get("color","#FFFFFF") or "#FFFFFF").upper()
                pos   = (c.attrib.get("pos") or "").upper()
                celdas.append({"idx": idx, "color": color, "pos": pos})
            # completa 25 si falta
            if len(celdas) < 25:
                pos_order = globals().get("POS_25_ROW") or []
                ya = {x.get("idx") for x in celdas}
                for i in range(1,26):
                    if i in ya:
                        continue
                    pos = pos_order[i-1] if i-1 < len(pos_order) else ""
                    celdas.append({"idx": i, "color": "#FFFFFF", "pos": pos})
            celdas.sort(key=lambda x: (x.get("idx") or 0))
            catalogo[code] = {"nombre": nombre, "centro_bloqueado": cbloq, "celdas": celdas}
        if catalogo:
            return catalogo

    return {}

def _get_rangos_en_juego(fecha_iso: str):
    """Rangos impresos (boletos) para la fecha (solo tablas EN JUEGO)."""
    paths = []
    # constantes existentes (según tu app)
    if "IMPRESIONES_XML" in globals(): paths.append(globals().get("IMPRESIONES_XML"))
    if "IMP_XML_PATH" in globals(): paths.append(globals().get("IMP_XML_PATH"))
    if "LOGS_IMPRESIONES_XML" in globals(): paths.append(globals().get("LOGS_IMPRESIONES_XML"))
    # fallback
    paths.append(os.path.join(BASE_DIR, "static", "LOGS", "impresiones.xml"))
    paths.append(os.path.join(DB_DIR, "impresiones.xml"))

    imp_path = next((p for p in paths if p and os.path.exists(p)), None)
    if not imp_path:
        return []

    try:
        root = ET.parse(imp_path).getroot()
    except Exception:
        return []

    rangos = []
    for imp in root.findall(".//impresion"):
        tipo = (imp.get("tipo") or "").strip().lower()
        if tipo != "boletos":
            continue
        f = (imp.findtext("fecha_sorteo") or imp.get("fecha_sorteo") or imp.findtext("fecha") or "").strip()
        # normaliza a ISO si viene como dd/mm/yyyy
        if f and callable(globals().get("_to_iso_date")):
            try:
                f = globals().get("_to_iso_date")(f)
            except Exception:
                pass
        if f != fecha_iso:
            continue

        serie_archivo = (imp.get("serie_archivo") or imp.findtext("serie_archivo") or "").strip()
        desde = (imp.get("desde") or imp.findtext("desde") or "").strip()
        hasta = (imp.get("hasta") or imp.findtext("hasta") or "").strip()
        if not serie_archivo or not desde or not hasta:
            continue
        rangos.append({"serie_archivo": serie_archivo, "desde": desde, "hasta": hasta})

    return rangos

def _pos_to_key(pos: str) -> str:
    """B1 -> b1 (como vienen las columnas en el CSV/XLSX)."""
    pos = (pos or "").strip().upper()
    if not pos:
        return ""
    return pos[0].lower() + pos[1:]  # B10 -> b10

def _is_free_cell(v: str) -> bool:
    vv = (str(v) if v is not None else "").strip().upper()
    return (vv == "" or vv == "0" or vv == "00" or vv == "FREE" or vv == "LIBRE")

def _build_grid_from_row(row_lower: dict):
    """Devuelve grid 5x5 y pos->valor usando b1..o5."""
    def g(col, n):
        return str(row_lower.get(f"{col}{n}", "")).strip()
    grid = [
        [g('b',1), g('i',1), g('n',1), g('g',1), g('o',1)],
        [g('b',2), g('i',2), g('n',2), g('g',2), g('o',2)],
        [g('b',3), g('i',3), g('n',3), g('g',3), g('o',3)],
        [g('b',4), g('i',4), g('n',4), g('g',4), g('o',4)],
        [g('b',5), g('i',5), g('n',5), g('g',5), g('o',5)],
    ]
    pos_map = {}
    pos_order = globals().get("POS_25_ROW") or []
    # rellena pos_map usando pos_order
    flat = []
    for r in range(5):
        for c in range(5):
            flat.append(grid[r][c])
    for i, pos in enumerate(pos_order):
        if i < len(flat):
            pos_map[pos] = flat[i]
    return grid, pos_map

def _required_positions_for_fig(code: str, catalogo: dict):
    """Devuelve (required_pos_list, color_map_pos)."""
    pos_order = globals().get("POS_25_ROW") or []
    color_off = (globals().get("COLOR_OFF") or "#E8E8E8").upper()

    # IMPORTANTE:
    # Las TL programadas (TL1..TL4) y sus equivalentes semánticos
    # LLEN / RELL / YAPA / COMP SIEMPRE se tratan como tabla completa.
    # No debemos depender del catálogo porque, si allí existe una figura
    # parcial con el mismo código/nombre, la programación terminaba usando
    # solo algunas casillas y el boleto se veía "tal cual venía".
    #
    # Con esto, cuando una LLENA / RELLENA / YAPA programada dispare,
    # la forzada reemplazará TODO lo que aún no haya salido usando solo
    # números ya marcados y respetando B/I/N/G/O.
    if code in ("TL1", "TL2", "TL3", "TL4", "RELL", "LLEN", "YAPA", "COMP"):
        color_on = (globals().get("COLOR_ON") or "#FF0000").upper()
        return list(pos_order), {p: (color_on if p else "#FFFFFF") for p in pos_order}

    f = catalogo.get(code)
    if not f:
        return [], {}

    required = []
    cmap = {}
    for cel in (f.get("celdas") or []):
        pos = (cel.get("pos") or "").upper()
        col = (cel.get("color") or "#FFFFFF").upper()
        if not pos:
            continue
        cmap[pos] = col
        if col not in ("#FFFFFF", color_off, "#E8E8E8"):
            required.append(pos)

    # completa cmap con blancos para posiciones faltantes
    for p in pos_order:
        if p and p not in cmap:
            cmap[p] = "#FFFFFF"

    return required, cmap

def _tl_prog_on(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "si", "sí", "activo", "on")

def _tl_prog_norm_carton(v) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    try:
        return str(int(float(s)))
    except Exception:
        m = re.search(r"\d+", s)
        if m:
            try:
                return str(int(m.group(0)))
            except Exception:
                return m.group(0)
    return s

def _tl_prog_parse_cartones(raw) -> list:
    out = []
    seen = set()
    for part in re.split(r"[;,]+", str(raw or "")):
        part = (part or "").strip()
        if not part:
            continue
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", part)
        if m:
            a = int(m.group(1)); b = int(m.group(2))
            step = 1 if b >= a else -1
            for n in range(a, b + step, step):
                s = str(n)
                if s not in seen:
                    seen.add(s)
                    out.append(s)
            continue
        norm = _tl_prog_norm_carton(part)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _tl_prog_parse_int(v, default=0) -> int:
    try:
        s = str(v or "").strip()
    except Exception:
        s = ""
    if not s:
        return int(default)
    m = re.search(r"\d+", s)
    if not m:
        return int(default)
    try:
        return int(m.group(0))
    except Exception:
        return int(default)


def _tl_prog_semantic_code(code: str) -> str:
    raw = str(code or "").strip().upper()
    return {"TL1": "LLEN", "TL2": "RELL", "TL3": "YAPA", "TL4": "COMP"}.get(raw, raw)


def _tl_prog_build_slots(cfg: dict) -> dict:
    cfg = cfg or {}
    slots = {
        "TL1": {
            "carton": _tl_prog_norm_carton(cfg.get("tl_programada_llena")),
            "objetivo": _tl_prog_parse_int(cfg.get("tl_objetivo_llena"), 0),
            "serie": str(cfg.get("tl_serie_llena") or "").strip(),
        },
        "TL2": {
            "carton": _tl_prog_norm_carton(cfg.get("tl_programada_rellena")),
            "objetivo": _tl_prog_parse_int(cfg.get("tl_objetivo_rellena"), 0),
            "serie": str(cfg.get("tl_serie_rellena") or "").strip(),
        },
        "TL3": {
            "carton": _tl_prog_norm_carton(cfg.get("tl_programada_yapa")),
            "objetivo": _tl_prog_parse_int(cfg.get("tl_objetivo_yapa"), 0),
            "serie": str(cfg.get("tl_serie_yapa") or "").strip(),
        },
        "TL4": {
            "carton": _tl_prog_norm_carton(cfg.get("tl_programadas_super_yapa")),
            "objetivo": _tl_prog_parse_int(cfg.get("tl_objetivo_super_yapa"), 0),
            "serie": str(cfg.get("tl_serie_super_yapa") or "").strip(),
        },
    }
    legacy = _tl_prog_parse_cartones(cfg.get("tl_programadas_cartones"))
    for i, carton in enumerate(legacy[:4], start=1):
        slot = f"TL{i}"
        if not slots[slot]["carton"]:
            slots[slot]["carton"] = _tl_prog_norm_carton(carton)
    return {k: v for k, v in slots.items() if v.get("carton")}

def _tl_prog_band_bounds(col_idx: int):
    bands = [(1,15), (16,30), (31,45), (46,60), (61,75)]
    try:
        return bands[int(col_idx)]
    except Exception:
        return (1, 75)


def _tl_prog_col_for_num(n: int) -> int:
    try:
        n = int(n)
    except Exception:
        return -1
    if 1 <= n <= 15:
        return 0
    if 16 <= n <= 30:
        return 1
    if 31 <= n <= 45:
        return 2
    if 46 <= n <= 60:
        return 3
    if 61 <= n <= 75:
        return 4
    return -1


def _tl_prog_force_grid_with_marked(original_grid, marked_stack, ultimo=0, required_pos=None, force_ultimo=False):
    """
    Ajusta el cartón programado usando ÚNICAMENTE números YA marcados.

    Reglas:
    - Conserva todo número original del cartón que ya salió.
    - Reemplaza solo las casillas objetivo que aún no han salido.
    - Nunca mezcla bandas B/I/N/G/O.
    - Para una tabla completa, la composición final debe quedar 5-5-4-5-5.
    - No altera el historial real de balotas.

    Devuelve:
      (grid_forzada, numeros_figura, marcados_nums_en_grid, completa)
    """
    grid = []
    for row in (original_grid or []):
        try:
            grid.append([str(x).strip() for x in list(row)])
        except Exception:
            grid.append(["", "", "", "", ""])
    while len(grid) < 5:
        grid.append(["", "", "", "", ""])
    for r in range(5):
        while len(grid[r]) < 5:
            grid[r].append("")

    marked_seq = []
    seen_seq = set()
    for x in (marked_stack or []):
        try:
            xi = int(str(x).strip())
        except Exception:
            continue
        if 1 <= xi <= 75 and xi not in seen_seq:
            seen_seq.add(xi)
            marked_seq.append(xi)
    marked_set = set(marked_seq)

    try:
        ultimo = int(str(ultimo).strip()) if ultimo not in (None, "") else 0
    except Exception:
        ultimo = 0
    ultimo_col = _tl_prog_col_for_num(ultimo) if ultimo else -1

    pos_order = globals().get("POS_25_ROW") or []

    def _req_pos_to_rc(pos):
        raw = str(pos or "").strip().upper()
        if not raw:
            return None
        if len(raw) == 2 and raw.isdigit():
            rr = int(raw[0]); cc = int(raw[1])
            if 0 <= rr < 5 and 0 <= cc < 5:
                return (rr, cc)
            return None
        if raw in pos_order:
            idx = pos_order.index(raw)
            return (idx // 5, idx % 5)
        if len(raw) >= 2 and raw[0] in "BINGO" and raw[1:].isdigit():
            c_map = {"B": 0, "I": 1, "N": 2, "G": 3, "O": 4}
            rr = int(raw[1:]) - 1
            cc = c_map.get(raw[0], -1)
            if 0 <= rr < 5 and 0 <= cc < 5:
                return (rr, cc)
        return None

    target_positions = []
    if required_pos:
        for pos in (required_pos or []):
            rc = _req_pos_to_rc(pos)
            if not rc:
                continue
            rr, cc = rc
            if not _is_free_cell(grid[rr][cc]):
                target_positions.append((rr, cc))
    else:
        for rr in range(5):
            for cc in range(5):
                if not _is_free_cell(grid[rr][cc]):
                    target_positions.append((rr, cc))

    if required_pos and not target_positions:
        marcados_en_grid = []
        seen_grid = set()
        for rr in range(5):
            for cc in range(5):
                v = str(grid[rr][cc]).strip()
                if v.isdigit():
                    n = int(v)
                    if n in marked_set and n not in seen_grid:
                        seen_grid.add(n)
                        marcados_en_grid.append(n)
        return grid, [], sorted(marcados_en_grid), False

    target_set = set(target_positions)
    target_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for _rr, _cc in target_positions:
        target_counts[_cc] = target_counts.get(_cc, 0) + 1

    used = set()
    replace_cells = {0: [], 1: [], 2: [], 3: [], 4: []}

    for r in range(5):
        for c in range(5):
            v = str(grid[r][c]).strip()
            if _is_free_cell(v):
                continue
            if v.isdigit() and int(v) in marked_set:
                used.add(int(v))
            if (r, c) not in target_set:
                continue
            if v.isdigit() and int(v) in marked_set:
                continue
            replace_cells[c].append((r, c))

    if force_ultimo and ultimo and ultimo_col >= 0:
        ultimo_present = False
        for rr, cc in target_positions:
            v = str(grid[rr][cc]).strip()
            if v.isdigit() and int(v) == ultimo:
                ultimo_present = True
                break
        if not ultimo_present:
            target_cell = None
            if replace_cells.get(ultimo_col):
                target_cell = replace_cells[ultimo_col].pop(0)
            else:
                for rr, cc in reversed(target_positions):
                    if cc == ultimo_col:
                        target_cell = (rr, cc)
                        break
            if target_cell is not None:
                rr, cc = target_cell
                old_v = str(grid[rr][cc]).strip()
                if old_v.isdigit() and int(old_v) in used:
                    used.discard(int(old_v))
                grid[rr][cc] = str(ultimo)
                used.add(ultimo)

    pendientes = []
    for c in range(5):
        lo, hi = _tl_prog_band_bounds(c)
        pool = [n for n in marked_seq if lo <= n <= hi and n not in used]
        for rr, cc in list(replace_cells.get(c) or []):
            if not pool:
                pendientes.append((rr, cc))
                continue
            n = pool.pop(0)
            grid[rr][cc] = str(n)
            used.add(n)

    numeros_figura = []
    completa = True
    col_counts_ok = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for rr, cc in target_positions:
        v = str(grid[rr][cc]).strip()
        if _is_free_cell(v):
            continue
        if not (v.isdigit() and int(v) in marked_set):
            completa = False
            continue
        col_counts_ok[cc] = col_counts_ok.get(cc, 0) + 1
        numeros_figura.append(int(v))

    marcados_en_grid = []
    seen_grid = set()
    for rr in range(5):
        for cc in range(5):
            v = str(grid[rr][cc]).strip()
            if v.isdigit():
                n = int(v)
                if n in marked_set and n not in seen_grid:
                    seen_grid.add(n)
                    marcados_en_grid.append(n)

    if pendientes:
        completa = False

    for c in range(5):
        if int(col_counts_ok.get(c, 0)) != int(target_counts.get(c, 0)):
            completa = False
            break

    return grid, numeros_figura, sorted(marcados_en_grid), completa

def _resolve_tl_programadas_for_day(fecha_iso: str, by_series: dict) -> dict:
    """
    Resuelve TL1..TL4 programadas a un cartón real del día.
    Usa primero los campos explícitos por etapa y mantiene compatibilidad con
    tl_programadas_cartones legado.
    Devuelve: {"TL1": {"serie": ..., "carton_id": ..., "objetivo": ...}, ...}
    """
    try:
        cfg = _sorteo_read_config(str(fecha_iso))
    except Exception:
        cfg = {}

    if not _tl_prog_on((cfg or {}).get("tl_programadas_activas")):
        return {}

    solicitados = _tl_prog_build_slots(cfg)
    if not solicitados:
        return {}

    series_info = []
    for serie_archivo, spans in (by_series or {}).items():
        try:
            df, id_col, ids, id_to_idx, _mtime = _get_series_meta_cached(serie_archivo)
        except Exception:
            continue
        if df is None or getattr(df, 'empty', True):
            continue

        intervals = []
        for desde, hasta in (spans or []):
            if desde not in id_to_idx or hasta not in id_to_idx:
                continue
            s = id_to_idx[desde]
            e = id_to_idx[hasta] + 1
            if e <= s:
                e = s + 1
            intervals.append((s, e))
        if not intervals:
            continue

        intervals.sort()
        merged = []
        for s, e in intervals:
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            else:
                merged[-1][1] = max(merged[-1][1], e)

        valid_ids = []
        seen_ids = set()
        for s, e in merged:
            for raw_id in ids[s:e]:
                real = str(raw_id).strip()
                if not real or real in seen_ids:
                    continue
                seen_ids.add(real)
                valid_ids.append(real)
        if not valid_ids:
            continue

        norm_to_real = {}
        numeric_pairs = []
        for real in valid_ids:
            norm = _tl_prog_norm_carton(real)
            if norm and norm not in norm_to_real:
                norm_to_real[norm] = real
            if norm and norm.isdigit():
                numeric_pairs.append((int(norm), real))

        series_info.append({
            "serie": serie_archivo,
            "valid_ids": valid_ids,
            "norm_to_real": norm_to_real,
            "numeric_pairs": numeric_pairs,
        })

    if not series_info:
        return {}

    resolved = {}
    for slot, req in solicitados.items():
        req_norm = _tl_prog_norm_carton(req.get("carton"))
        if not req_norm:
            continue

        chosen = None
        wanted_serie = str(req.get("serie") or "").strip()
        if wanted_serie:
            for info in series_info:
                try:
                    same = _serie_equal(info["serie"], wanted_serie)
                except Exception:
                    same = (str(info["serie"]).strip() == wanted_serie)
                if not same:
                    continue
                real = info["norm_to_real"].get(req_norm)
                if real:
                    chosen = {"serie": info["serie"], "carton_id": real}
                    break

        if chosen is None:
            for info in series_info:
                real = info["norm_to_real"].get(req_norm)
                if real:
                    chosen = {"serie": info["serie"], "carton_id": real}
                    break

        if chosen is None:
            req_num = int(req_norm) if req_norm.isdigit() else None
            best = None
            if req_num is not None:
                for info in series_info:
                    for cand_num, cand_real in info["numeric_pairs"]:
                        dist = abs(cand_num - req_num)
                        if (best is None) or (dist < best[0]):
                            best = (dist, info["serie"], cand_real)
            if best is not None:
                chosen = {"serie": best[1], "carton_id": best[2]}
            else:
                info = series_info[0]
                chosen = {"serie": info["serie"], "carton_id": info["valid_ids"][0]}

        if chosen:
            chosen["objetivo"] = max(0, _tl_prog_parse_int(req.get("objetivo"), 0))
            chosen["carton_solicitado"] = req_norm
            resolved[slot] = chosen

    return resolved

# ============================
#  Ganadores: dedupe & normalización
# ============================
def _norm_tabla_id(v) -> str:
    """Normaliza el id de tabla/boleta para evitar duplicados tipo 580 vs 580.0."""
    try:
        s = str(v or "").strip()
    except Exception:
        s = ""
    if not s:
        return ""
    # Si viene como float-string "580.0", lo llevamos a "580"
    if re.fullmatch(r"\d+(?:\.0+)?", s):
        try:
            return str(int(float(s)))
        except Exception:
            return s
    return s

def _ganador_key(fecha_iso: str, g: dict) -> str:
    fig_code = str((g or {}).get("fig_code") or code_for((g or {}).get("figura",""))).strip()
    serie    = str((g or {}).get("serie","") or "").strip()
    tabla    = _norm_tabla_id((g or {}).get("tabla",""))
    return f"{str(fecha_iso)}|{fig_code}|{serie}|{tabla}"

def _dedupe_ganadores(fecha_iso: str, ganadores: list) -> list:
    """Elimina duplicados por (fecha, fig_code, serie, tabla) conservando el orden."""
    seen = set()
    out = []
    for g in (ganadores or []):
        if not isinstance(g, dict):
            continue
        gg = dict(g)
        gg["fig_code"] = str(gg.get("fig_code") or code_for(gg.get("figura",""))).strip()
        gg["serie"]    = str(gg.get("serie","") or "").strip()
        gg["tabla"]    = _norm_tabla_id(gg.get("tabla",""))
        k = _ganador_key(fecha_iso, gg)
        if k in seen:
            continue
        seen.add(k)
        out.append(gg)
    return out

def _write_ganadores_xml(fecha_iso: str, ultimo_marcado: int, ganadores: list):
    """Escribe ganadores.xml con estructura + colores + números."""
    root = ET.Element("ganadores", {
        "fecha": str(fecha_iso),
        "ultimo_marcado": (str(ultimo_marcado) if ultimo_marcado else "")
    })
    ganadores = _dedupe_ganadores(str(fecha_iso), ganadores)


    for g in ganadores:
        figura_sem = str(g.get("figura", ""))
        boleto_sem = _norm_tabla_id(g.get("boleto") or g.get("tabla") or "")
        meta = _resultado_meta_para_ganador(fecha_iso, figura_sem, boleto_sem)
        premio_xml = _safe_float(meta.get("premio"), None)
        if premio_xml is None:
            premio_xml = _safe_float(g.get("premio"), None)
        if premio_xml is None:
            premio_xml = _safe_float(g.get("valor"), 0.0)
        vendedor_xml = str(meta.get("vendedor") or g.get("vendedor") or "").strip()
        sector_xml = str(meta.get("sector") or g.get("sector") or g.get("planilla") or g.get("rango") or "").strip()
        nombre_xml = str(meta.get("nombre") or g.get("nombre") or g.get("nota") or "").strip()

        ga = ET.SubElement(root, "ganador", {
            "figura": figura_sem,
            "fig_code": str(g.get("fig_code","")),
            "valor": f'{float(premio_xml or 0):.2f}',
            "serie": str(g.get("serie","")),
            "tabla": boleto_sem,
            "ultima_bola": str(g.get("ultima_bola","")),
            "vendedor": vendedor_xml,
            "sector": sector_xml,
            "planilla": sector_xml,
            "nombre": nombre_xml
        })

        # resumen
        ET.SubElement(ga, "numeros_figura").text = ",".join(str(x) for x in (g.get("numeros_figura") or []))
        ET.SubElement(ga, "numero_ganador").text = str(g.get("numero_ganador","") or "")
        ET.SubElement(ga, "nombre").text = nombre_xml
        ET.SubElement(ga, "vendedor").text = vendedor_xml
        ET.SubElement(ga, "sector").text = sector_xml
        ET.SubElement(ga, "planilla").text = sector_xml
        ET.SubElement(ga, "premio").text = f'{float(premio_xml or 0):.2f}'

        # grilla
        carton = ET.SubElement(ga, "carton", {"id": str(g.get("tabla",""))})
        pos_order = globals().get("POS_25_ROW") or []
        grid = g.get("grid") or [[""]*5 for _ in range(5)]
        cmap = g.get("color_map_pos") or {}
        req  = set(g.get("required_pos") or [])
        marked = set(str(x) for x in (g.get("marcados_nums") or []))

        # exporta 25 celdas, en orden B1..O5
        # además exporta el número del cartón y si está marcado y si es requerido por la figura
        for i, pos in enumerate(pos_order):
            r = i // 5
            c = i % 5
            num = ""
            try:
                num = str(grid[r][c]).strip()
            except Exception:
                num = ""
            cel = ET.SubElement(carton, "celda", {
                "pos": pos,
                "numero": num,
                "figura_color": (cmap.get(pos,"#FFFFFF") or "#FFFFFF"),
                "requerido": ("1" if pos in req else "0"),
                "marcado": ("1" if (num in marked or (num and num.isdigit() and str(int(num)) in marked) or _is_free_cell(num)) else "0")
            })

    xml_bytes = ET.tostring(root, encoding="utf-8")
    # pretty simple: deja tal cual (vMix no exige "pretty")
    for path in [GANADORES_XML, GANADORES_XML_PUBLIC]:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
                f.write(xml_bytes)
        except Exception:
            pass

def _write_ganadores_json(fecha_iso: str, ganadores: list, keys: list):
    ganadores = _dedupe_ganadores(str(fecha_iso), ganadores)
    # Recalcula claves desde ganadores dedupe para mantener consistencia
    keys = [_ganador_key(str(fecha_iso), g) for g in (ganadores or [])]
    keys = sorted(list(dict.fromkeys(keys)))
    data = _safe_json_read(GANADORES_JSON) or {}
    data[str(fecha_iso)] = ganadores
    _safe_json_write(GANADORES_JSON, data)
    _safe_json_write(GANADORES_STATE_JSON, {"keys": keys})

def _recalcular_ganadores(fecha_iso: str, stack: list, ultimo_marcado: int = 0):
    """
    Recalcula TODO (para reversa/reset) respetando la regla de juego:
    cuando una figura ya tuvo ganador(es), esa figura deja de participar.

    Importante: se rehace el historial REPROCESANDO la pila en orden (bola por bola),
    para conservar correctamente las figuras que "se fueron" en el momento exacto.
    """
    fecha_iso = str(fecha_iso)

    # Normaliza stack (mantiene orden)
    stack_norm = []
    for x in (stack or []):
        try:
            xi = int(str(x).strip())
            if 1 <= xi <= 75:
                stack_norm.append(xi)
        except Exception:
            pass

    # Limpia SOLO el día actual y el estado de claves, sin tocar otros días
    data_all = _safe_json_read(GANADORES_JSON) or {}
    data_all[fecha_iso] = []
    _safe_json_write(GANADORES_JSON, data_all)
    _safe_json_write(GANADORES_STATE_JSON, {"keys": []})

    ganadores_total = []
    nuevos_total = []
    keys = []
    pref = []

    # Replay bola por bola para respetar el cierre de cada figura al primer acierto
    for n in stack_norm:
        pref.append(n)
        ganadores_total, nuevos, keys = _detectar_ganadores(fecha_iso, pref, n, recalc=False)
        if nuevos:
            nuevos_total.extend(nuevos)
            _write_ganadores_json(fecha_iso, ganadores_total, keys)

    # Persistencia final (aunque no haya ganadores)
    _write_ganadores_json(fecha_iso, ganadores_total, keys)
    _write_ganadores_xml(fecha_iso, int(ultimo_marcado or 0), ganadores_total)
    return ganadores_total, nuevos_total

# ============================================================
#  PERFORMANCE: caches para acelerar lectura/detección de tablas
# ============================================================
try:
    _SERIES_META_CACHE  # noqa
except NameError:
    _SERIES_META_CACHE = {}
    _SERIES_META_LOCK = RLock()
    _CARTONES_INDEX_CACHE = {}
    _CARTONES_INDEX_LOCK = RLock()

def _get_series_meta_cached(archivo: str):
    """Devuelve (df, id_col, ids, id_to_idx, mtime) con caché por mtime del archivo."""
    path = _resolve_series_path(archivo)
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        mtime = 0.0

    with _SERIES_META_LOCK:
        c = _SERIES_META_CACHE.get(path)
        if c and c.get("mtime") == mtime:
            return c["df"], c["id_col"], c["ids"], c["id_to_idx"], mtime

    # Lee del disco (lento) solo si cambió
    df = _read_df_for_series(archivo)
    if df is None or df.empty:
        raise ValueError(f"Serie vacía: {archivo}")

    id_col = df.columns[0]
    ids = df[id_col].astype(str).tolist()
    id_to_idx = {v: i for i, v in enumerate(ids)}

    with _SERIES_META_LOCK:
        _SERIES_META_CACHE[path] = {
            "mtime": mtime,
            "df": df,
            "id_col": id_col,
            "ids": ids,
            "id_to_idx": id_to_idx
        }
        # límite simple para evitar crecimiento infinito
        if len(_SERIES_META_CACHE) > 8:
            # borra uno cualquiera (suficiente)
            _SERIES_META_CACHE.pop(next(iter(_SERIES_META_CACHE.keys())), None)

    return df, id_col, ids, id_to_idx, mtime

def _get_cartones_index_cached(fecha_iso: str, serie_archivo: str, merged, df, id_col: str, mtime: float):
    """Construye (1 sola vez) el índice por número para las tablas en juego del día."""
    merged_sig = tuple((int(s), int(e)) for s, e in merged)
    key = (str(fecha_iso), str(serie_archivo), merged_sig, float(mtime))

    with _CARTONES_INDEX_LOCK:
        c = _CARTONES_INDEX_CACHE.get(key)
        if c:
            return c["tickets"], c["by_num"]

    tickets = []
    by_num = defaultdict(list)
    by_id_exact = {}
    by_id_num = {}

    for s, e in merged_sig:
        if s < 0: s = 0
        if e > len(df): e = len(df)
        if e <= s:
            continue
        sub = df.iloc[s:e]

        # Nota: esto corre SOLO cuando cambia el rango / serie (no en cada click)
        for _, row in sub.iterrows():
            rowd = row.to_dict()
            row_lower = {str(k).lower(): str(v).strip() for k, v in rowd.items()}
            carton_id = str(rowd.get(id_col, row_lower.get(str(id_col).lower(), ""))).strip()
            if not carton_id:
                carton_id = str(row_lower.get(str(id_col).lower(), "")).strip()

            grid, pos_map = _build_grid_from_row(row_lower)

            nums_in_carton = set()
            for v in pos_map.values():
                if _is_free_cell(v):
                    continue
                sv = str(v).strip()
                if sv.isdigit():
                    nums_in_carton.add(int(sv))

            tidx = len(tickets)
            tickets.append({
                "carton_id": carton_id,
                "grid": grid,
                "pos_map": pos_map,
                "nums": nums_in_carton
            })
            if carton_id:
                by_id_exact[str(carton_id).strip()] = tidx
                try:
                    by_id_num[int(re.sub(r"\D", "", str(carton_id)) or 0)] = tidx
                except Exception:
                    pass
            for n in nums_in_carton:
                by_num[n].append(tidx)

    payload = {
        "tickets": tickets,
        "by_num": dict(by_num),
        "by_id_exact": by_id_exact,
        "by_id_num": by_id_num,
    }

    with _CARTONES_INDEX_LOCK:
        _CARTONES_INDEX_CACHE[key] = payload
        # límite simple para evitar crecimiento infinito
        if len(_CARTONES_INDEX_CACHE) > 20:
            _CARTONES_INDEX_CACHE.clear()

    return payload["tickets"], payload["by_num"]

def _clear_juego_caches():
    """Útil si quieres limpiar manualmente la caché (por ejemplo al resetear)."""
    try:
        with _SERIES_META_LOCK:
            _SERIES_META_CACHE.clear()
    except Exception:
        pass
    try:
        with _CARTONES_INDEX_LOCK:
            _CARTONES_INDEX_CACHE.clear()
    except Exception:
        pass


def _detectar_ganadores(fecha_iso: str, stack: list, ultimo_marcado: int, recalc: bool = False):
    """
    Detecta ganadores reales respetando la estructura actual de lectura y, además,
    permite LLENA/RELLENA/YAPA programadas sin alterar el historial de balotas.
    """
    marked_nums = set()
    for x in (stack or []):
        try:
            xi = int(str(x).strip())
            if 1 <= xi <= 75:
                marked_nums.add(xi)
        except Exception:
            pass
    marked_count = len(marked_nums)

    state = _safe_json_read(GANADORES_STATE_JSON) or {}
    known = set(state.get("keys") or [])
    if recalc:
        known = set()

    allj = _safe_json_read(GANADORES_JSON) or {}
    ganadores = allj.get(str(fecha_iso), []) if not recalc else []
    ganadores = _dedupe_ganadores(str(fecha_iso), ganadores)
    for _g in (ganadores or []):
        try:
            known.add(_ganador_key(str(fecha_iso), _g))
        except Exception:
            pass
    nuevos = []

    def _norm_fig_name(v):
        try:
            t = str(v or "").strip().lower()
        except Exception:
            t = ""
        return re.sub(r"\s+", " ", t)

    def _semantic_stage(code: str) -> str:
        raw = str(code or "").strip().upper()
        return {"TL1": "LLEN", "TL2": "RELL", "TL3": "YAPA", "TL4": "COMP"}.get(raw, raw)

    def _stage_order(code: str) -> int:
        return {"LLEN": 1, "TL1": 1, "RELL": 2, "TL2": 2, "YAPA": 3, "TL3": 3, "COMP": 4, "TL4": 4}.get(str(code or "").strip().upper(), 0)

    figuras_cerradas_prev = set()
    tl_codes_closed_prev = set()
    semantic_closed_prev = set()
    if not recalc:
        for g in (ganadores or []):
            fk = _norm_fig_name((g or {}).get("figura") or (g or {}).get("nombre_figura") or "")
            if fk:
                figuras_cerradas_prev.add(fk)
            gc = str((g or {}).get("fig_code") or "").strip().upper()
            if gc in ("TL1", "TL2", "TL3", "TL4"):
                tl_codes_closed_prev.add(gc)
            sc = _semantic_stage(gc or code_for((g or {}).get("figura", "")))
            if sc in ("LLEN", "RELL", "YAPA", "COMP"):
                semantic_closed_prev.add(sc)

    figuras = _load_figuras_por_fecha(fecha_iso)
    if not figuras:
        return ganadores, nuevos, sorted(known)

    try:
        sorteo_cfg = _sorteo_read_config(str(fecha_iso)) or {}
    except Exception:
        sorteo_cfg = {}
    tl_slots_cfg = _tl_prog_build_slots(sorteo_cfg) if _tl_prog_on((sorteo_cfg or {}).get("tl_programadas_activas")) else {}

    fig_states = {}
    if "FIG_ESTADOS_JSON" in globals():
        try:
            fig_states = (_safe_json_read(globals().get("FIG_ESTADOS_JSON")) or {}).get(str(fecha_iso), {}) or {}
        except Exception:
            fig_states = {}

    catalogo = _load_catalogo_figuras_any()
    patrones = []
    _TL_DISPLAY_NAME = {"TL1": "LLENA", "TL2": "RELLENA", "TL3": "YAPA", "TL4": "SUPER YAPA"}
    for it in figuras:
        nombre_src = it.get("nombre", "")
        if not nombre_src:
            continue
        estado = str(fig_states.get(nombre_src, "") or "").strip().upper()
        estado = re.sub(r"\s+", " ", estado)
        if estado and estado not in ("ACTIVO", "INACTIVO", "SE FUE", "SE QUEDO"):
            continue
        code = globals().get("code_for")(nombre_src) if callable(globals().get("code_for")) else re.sub(r"[^A-Z0-9]", "", nombre_src.upper())[:4] or "FIG"
        nombre = _tl_semantic_name(nombre_src, code)
        required_pos, cmap = _required_positions_for_fig(code, catalogo)
        if not required_pos and not (code in ("TL1", "TL2", "TL3", "TL4")):
            any_on = any(v not in ("#FFFFFF", (globals().get("COLOR_OFF") or "#E8E8E8").upper(), "#E8E8E8") for v in (cmap.values() or []))
            if not any_on:
                continue
        patrones.append({
            "nombre": nombre,
            "fig_key": _norm_fig_name(nombre),
            "code": code,
            "valor": float(it.get("valor", 0) or 0),
            "required_pos": required_pos,
            "color_map_pos": cmap
        })

    codes_present = {str(p.get("code") or "").strip().upper() for p in (patrones or [])}
    for _slot, _slot_cfg in (tl_slots_cfg or {}).items():
        if _slot in codes_present:
            continue
        slot_num = int(_slot[-1]) if _slot[-1:].isdigit() else 0
        try:
            _valor_tl = float(str((sorteo_cfg or {}).get(f"tl{slot_num}") or "0").replace(",", "."))
        except Exception:
            _valor_tl = 0.0
        _req_tl, _cmap_tl = _required_positions_for_fig(_slot, catalogo)
        patrones.append({
            "nombre": _TL_DISPLAY_NAME.get(_slot, _slot),
            "fig_key": _norm_fig_name(_TL_DISPLAY_NAME.get(_slot, _slot)),
            "code": _slot,
            "valor": round(max(_valor_tl, 0.0), 2),
            "required_pos": _req_tl,
            "color_map_pos": _cmap_tl,
        })

    if not patrones:
        return ganadores, nuevos, sorted(known)

    full_stage_codes = {"LLEN", "RELL", "YAPA", "COMP"}
    tl_stage_codes = {"TL1", "TL2", "TL3", "TL4"}
    figuras_base_keys = {
        p.get("fig_key") for p in (patrones or [])
        if p.get("fig_key") and p.get("code") not in tl_stage_codes and p.get("code") not in full_stage_codes
    }

    full_table_claimed_prev = set()
    if not recalc:
        for _g in (ganadores or []):
            try:
                _gc = str((_g or {}).get("fig_code") or code_for((_g or {}).get("figura", ""))).strip().upper()
            except Exception:
                _gc = ""
            if _semantic_stage(_gc) in {"LLEN", "RELL", "YAPA", "COMP"}:
                _tb = _norm_tabla_id((_g or {}).get("tabla", ""))
                if _tb:
                    full_table_claimed_prev.add(_tb)

    rangos = _get_rangos_en_juego(fecha_iso)
    if not rangos:
        return ganadores, nuevos, sorted(known)

    by_series = defaultdict(list)
    for r in rangos:
        by_series[r["serie_archivo"]].append((r["desde"], r["hasta"]))

    tl_programadas_map = _resolve_tl_programadas_for_day(str(fecha_iso), by_series)

    try:
        ultimo = int(ultimo_marcado) if ultimo_marcado else 0
    except Exception:
        ultimo = 0

    non_tl_patterns = [p for p in patrones if p.get("code") not in tl_stage_codes]
    tl_patterns = [p for p in patrones if p.get("code") in tl_stage_codes]

    natural_stage_hits_now = set()

    def _make_win(pat, serie_archivo, carton_id_raw, carton_id_norm, grid_out, marked_out, nums_fig_out):
        numero_ganador = ultimo if ultimo else (nums_fig_out[-1] if nums_fig_out else "")
        info_b = buscar_info_por_boleto(str(fecha_iso), carton_id_raw, serie_archivo)
        vendedor_b = (info_b.get("vendedor") or "").strip()
        planilla_b = (info_b.get("planilla") or "").strip()
        rango_b = (info_b.get("rango") or "").strip()
        return {
            "fecha": str(fecha_iso),
            "figura": pat["nombre"],
            "fig_code": pat["code"],
            "valor": round(float(pat["valor"]), 2),
            "serie": serie_archivo,
            "vendedor": vendedor_b,
            "planilla": planilla_b,
            "rango": rango_b,
            "sector": (planilla_b or rango_b),
            "tabla": carton_id_norm,
            "ultima_bola": int(ultimo) if ultimo else "",
            "numero_ganador": int(numero_ganador) if str(numero_ganador).isdigit() else str(numero_ganador),
            "numeros_figura": nums_fig_out,
            "grid": grid_out,
            "required_pos": pat["required_pos"],
            "color_map_pos": pat["color_map_pos"],
            "marcados_nums": marked_out,
        }

    for serie_archivo, spans in by_series.items():
        try:
            df, id_col, ids, id_to_idx, mtime = _get_series_meta_cached(serie_archivo)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        intervals = []
        for desde, hasta in spans:
            if desde not in id_to_idx or hasta not in id_to_idx:
                continue
            s = id_to_idx[desde]
            e = id_to_idx[hasta] + 1
            if e <= s:
                e = s + 1
            intervals.append((s, e))
        if not intervals:
            continue

        intervals.sort()
        merged = []
        for s, e in intervals:
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            else:
                merged[-1][1] = max(merged[-1][1], e)

        tickets, by_num = _get_cartones_index_cached(str(fecha_iso), str(serie_archivo), merged, df, id_col, mtime)
        if (not recalc) and (1 <= ultimo <= 75):
            cand_idxs = list(by_num.get(ultimo, []))
        else:
            cand_idxs = list(range(len(tickets)))

        idx_by_carton = {}
        for _i, _t in enumerate(tickets):
            idx_by_carton[_tl_prog_norm_carton(_t.get("carton_id", ""))] = _i
        if (not recalc) and tl_programadas_map:
            for slot, target in (tl_programadas_map or {}).items():
                if str(target.get("serie") or "") != str(serie_archivo):
                    continue
                _ix = idx_by_carton.get(_tl_prog_norm_carton(target.get("carton_id", "")))
                if _ix is not None and _ix not in cand_idxs:
                    cand_idxs.append(_ix)
        if not cand_idxs:
            continue

        full_table_claimed_series = set(full_table_claimed_prev)

        for tidx in cand_idxs:
            t = tickets[tidx]
            carton_id = t.get("carton_id", "")
            grid = t.get("grid")
            pos_map = t.get("pos_map") or {}
            carton_id_norm = _norm_tabla_id(carton_id)
            for pat in non_tl_patterns:
                if (not recalc) and pat.get("fig_key") and pat.get("fig_key") in figuras_cerradas_prev:
                    continue
                fig_code = pat["code"]
                key = f"{fecha_iso}|{fig_code}|{serie_archivo}|{carton_id_norm}"
                if key in known:
                    continue

                stage_code = _semantic_stage(fig_code)
                stage_idx = _stage_order(fig_code)
                if stage_code in full_stage_codes:
                    closed_fig_keys_now = set(figuras_cerradas_prev)
                    if not recalc:
                        for _g_now in (ganadores or []):
                            _fk_now = _norm_fig_name((_g_now or {}).get("figura") or (_g_now or {}).get("nombre_figura") or "")
                            if _fk_now:
                                closed_fig_keys_now.add(_fk_now)
                    if not figuras_base_keys.issubset(closed_fig_keys_now):
                        continue
                    prev_stage_ok = True
                    if stage_idx >= 2 and "LLEN" not in semantic_closed_prev:
                        prev_stage_ok = False
                    if stage_idx >= 3 and "RELL" not in semantic_closed_prev:
                        prev_stage_ok = False
                    if stage_idx >= 4 and "YAPA" not in semantic_closed_prev:
                        prev_stage_ok = False
                    if not prev_stage_ok:
                        continue
                    if stage_code in {"LLEN", "RELL", "COMP"} and carton_id_norm in full_table_claimed_series:
                        continue

                needed = []
                has_ultimo = False
                for pos in pat["required_pos"]:
                    v = pos_map.get(pos, "")
                    if _is_free_cell(v):
                        continue
                    sv = str(v).strip()
                    if sv.isdigit():
                        n = int(sv)
                        needed.append(n)
                        if (not recalc) and (n == ultimo):
                            has_ultimo = True
                if not needed:
                    continue
                if (not recalc) and (1 <= ultimo <= 75) and (not has_ultimo):
                    continue
                if any(n not in marked_nums for n in needed):
                    continue

                known.add(key)
                win = _make_win(pat, serie_archivo, carton_id, carton_id_norm, grid, sorted(list(marked_nums)), needed)
                ganadores.append(win)
                nuevos.append(win)
                if stage_code in full_stage_codes:
                    natural_stage_hits_now.add(stage_code)
                if stage_code in {"LLEN", "RELL", "COMP"} and carton_id_norm:
                    full_table_claimed_series.add(carton_id_norm)
                    full_table_claimed_prev.add(carton_id_norm)

        for pat in tl_patterns:
            fig_code = pat["code"]
            target_tl = tl_programadas_map.get(fig_code)
            if not target_tl:
                continue
            if str(target_tl.get("serie") or "") != str(serie_archivo):
                continue
            _ix = idx_by_carton.get(_tl_prog_norm_carton(target_tl.get("carton_id", "")))
            if _ix is None:
                continue
            t = tickets[_ix]
            carton_id = t.get("carton_id", "")
            grid = t.get("grid")
            carton_id_norm = _norm_tabla_id(carton_id)
            key = f"{fecha_iso}|{fig_code}|{serie_archivo}|{carton_id_norm}"
            if key in known:
                continue
            # NO bloquear la TL programada por coincidencia semántica de nombre ("LLENA", "RELLENA", etc.).
            # Solo se evita repetirla por key única y por estado real ya guardado en known / tl_codes_closed_prev.

            closed_fig_keys_now = set(figuras_cerradas_prev)
            if not recalc:
                for _g_now in (ganadores or []):
                    _fk_now = _norm_fig_name((_g_now or {}).get("figura") or (_g_now or {}).get("nombre_figura") or "")
                    if _fk_now:
                        closed_fig_keys_now.add(_fk_now)
            if not figuras_base_keys.issubset(closed_fig_keys_now):
                continue

            slot_num = int(fig_code[-1]) if fig_code[-1:].isdigit() else 1
            prev_tl_ok = True
            if slot_num >= 2 and "TL1" not in tl_codes_closed_prev:
                prev_tl_ok = False
            if slot_num >= 3 and "TL2" not in tl_codes_closed_prev:
                prev_tl_ok = False
            if slot_num >= 4 and "TL3" not in tl_codes_closed_prev:
                prev_tl_ok = False
            if not prev_tl_ok:
                continue

            semantic_code = _tl_prog_semantic_code(fig_code)
            natural_trigger = semantic_code in natural_stage_hits_now
            objetivo = max(0, _tl_prog_parse_int(target_tl.get("objetivo"), 0))
            count_trigger = (marked_count >= objetivo) if objetivo > 0 else True
            if not (natural_trigger or count_trigger):
                continue

            grid_forzada, needed_forzados, marked_forzados, tl_grid_completa = _tl_prog_force_grid_with_marked(
                grid, stack, ultimo, required_pos=pat["required_pos"], force_ultimo=True
            )
            if not tl_grid_completa:
                continue

            known.add(key)
            win = _make_win(pat, serie_archivo, carton_id, carton_id_norm, grid_forzada, marked_forzados, needed_forzados)
            ganadores.append(win)
            nuevos.append(win)
            if semantic_code in {"LLEN", "RELL", "COMP"} and carton_id_norm:
                full_table_claimed_series.add(carton_id_norm)
                full_table_claimed_prev.add(carton_id_norm)

    return ganadores, nuevos, sorted(known)

@juego_bp.get("/ganadores")
def juego_ganadores_list():
    """Lista ganadores detectados (JSON), normalizando TL programadas y enriqueciendo datos de planilla/resultados."""
    fecha = _get_sorteo_fecha()
    data = _safe_json_read(GANADORES_JSON) or {}
    raw = data.get(str(fecha), []) or []
    out = []
    for w in raw:
        if not isinstance(w, dict):
            continue
        item = dict(w)
        try:
            item["figura"] = _tl_semantic_name(
                str(item.get("figura") or item.get("nombre_figura") or ""),
                str(item.get("fig_code") or "")
            )
        except Exception:
            pass

        try:
            boleto = _norm_tabla_id(item.get("boleto") or item.get("tabla") or "")
            meta = _resultado_meta_para_ganador(fecha, item.get("figura") or "", boleto)
            item["boleto"] = boleto
            item["tabla"] = boleto
            item["nombre"] = str(meta.get("nombre") or item.get("nombre") or item.get("nota") or "").strip()
            item["vendedor"] = str(meta.get("vendedor") or item.get("vendedor") or "").strip()
            item["sector"] = str(meta.get("sector") or item.get("sector") or item.get("planilla") or item.get("rango") or "").strip()
            item["planilla"] = item["sector"]
            premio_res = _safe_float(meta.get("premio"), None)
            if premio_res is None:
                premio_res = _safe_float(item.get("premio"), None)
            if premio_res is None:
                premio_res = _safe_float(item.get("valor"), 0.0)
            item["premio"] = premio_res
            item["valor"] = premio_res
        except Exception:
            pass

        out.append(item)
    return jsonify(ok=True, fecha=fecha, ganadores=out)

@juego_bp.get("/ganadores.xml")
def juego_ganadores_xml():
    """XML para vMix: ganadores con colores + números."""
    path = GANADORES_XML if os.path.exists(GANADORES_XML) else GANADORES_XML_PUBLIC
    if not path or not os.path.exists(path):
        # crea vacío
        _write_ganadores_xml(_get_sorteo_fecha(), 0, [])
        path = GANADORES_XML if os.path.exists(GANADORES_XML) else GANADORES_XML_PUBLIC
    return send_file(path, mimetype="application/xml", as_attachment=False, download_name="ganadores.xml")

# ============================================================
#  HELPERS JSON/XML
# ============================================================
def _json_read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _json_write(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _ensure_hist():
    if not os.path.exists(HIST_JSON):
        _json_write(HIST_JSON, {"stack": [], "ts": datetime.utcnow().isoformat()})

def _read_stack():
    _ensure_hist()
    try:
        data = _json_read(HIST_JSON) or {}
        return [int(x) for x in data.get("stack", []) if 1 <= int(x) <= 75]
    except Exception:
        return []

def _write_stack(stack):
    _json_write(HIST_JSON, {"stack": [int(x) for x in stack], "ts": datetime.utcnow().isoformat()})

def _ensure_bingo_xml():
    if os.path.exists(BINGO_XML):
        return
    root = ET.Element("bingo")
    balotas = ET.SubElement(root, "balotas")
    for n in range(1, 76):
        # 'estado' y 'ultimo'
        ET.SubElement(balotas, "balota", numero=str(n), estado="", ultimo="")
    ET.SubElement(root, "ultimos5").text = ""
    ET.SubElement(root, "totalMarcadas").text = "0"
    ET.SubElement(root, "ultimoMarcado").text = ""
    ET.SubElement(root, "stinger").text = ""
    ET.ElementTree(root).write(BINGO_XML, encoding="utf-8", xml_declaration=True)

def _vmix_num_path(filename: str) -> str:
    base = str(VMIX_NUMEROS_MEDIA_DIR or "").strip().rstrip("\\/")
    if not base:
        return filename
    return os.path.join(base, filename)

def _ensure_vmix_numeros_xml():
    if os.path.exists(VMIX_NUMEROS_XML):
        return
    try:
        _sync_vmix_numeros_xml_from_stack(_read_stack())
    except Exception:
        pass

def _sync_vmix_numeros_xml_from_stack(stack):
    """
    XML paralelo para vMix con rutas directas a PNG:
      - si el número está marcado: ruta_actual = E:\\MEDIA\\NUMEROS\\N.png
      - si no está marcado:       ruta_actual = E:\\MEDIA\\NUMEROS\\INACTIVA.png
    No toca datos_bingo.xml; es un espejo exclusivo para overlays/imágenes.
    """
    marked = set(int(x) for x in (stack or []) if 1 <= int(x) <= 75)
    last = (stack or [])[-1] if stack else None
    ult5 = list(reversed((stack or [])[-5:])) if stack else []

    inactive_name = f"{VMIX_NUMEROS_INACTIVA_FILE}.png"
    inactive_path = _vmix_num_path(inactive_name)

    root = ET.Element("numeros")
    meta = ET.SubElement(root, "meta")
    ET.SubElement(meta, "directorio").text = str(VMIX_NUMEROS_MEDIA_DIR or "")
    ET.SubElement(meta, "inactiva").text = inactive_path
    ET.SubElement(meta, "ultimoMarcado").text = (str(last) if last is not None else "")
    ET.SubElement(meta, "ultimos5").text = ",".join(str(x) for x in ult5)
    ET.SubElement(meta, "totalMarcadas").text = str(len(marked))

    items = ET.SubElement(root, "items")
    for n in range(1, 76):
        active = n in marked
        active_path = _vmix_num_path(f"{n}.png")
        current_path = active_path if active else inactive_path
        ET.SubElement(
            items,
            "numero",
            id=str(n),
            valor=str(n),
            archivo=f"{n}.png",
            activo=("1" if active else "0"),
            estado=("ACTIVO" if active else "INACTIVO"),
            ultimo=("1" if last == n else "0"),
            ruta_activa=active_path,
            ruta_inactiva=inactive_path,
            ruta_actual=current_path,
        )

    _write_game_xml_dual(ET.ElementTree(root), "vmix_numeros.xml")

def _sync_bingo_xml_from_stack(stack):
    """
    Reglas pedidas (como tu captura):
      - estado="n" para marcadas, "" para no marcadas
      - ultimo="X" SOLO en <balota numero="1">, X = último marcado; todas las demás "", incluida la balota X
      - ultimos5: más reciente → más antiguo
      - ultimoMarcado: último marcado

    HOTFIX:
      - si datos_bingo.xml existe pero le faltan nodos, se recrean en caliente
      - así el reset no se cae por AttributeError sobre .text
    """
    _ensure_bingo_xml()
    tree = ET.parse(BINGO_XML)
    root = tree.getroot()

    balotas_el = root.find("balotas")
    if balotas_el is None:
        balotas_el = ET.SubElement(root, "balotas")

    existentes = {str(b.get("numero") or "").strip() for b in balotas_el.findall("balota")}
    for n in range(1, 76):
        if str(n) not in existentes:
            ET.SubElement(balotas_el, "balota", numero=str(n), estado="", ultimo="")

    ult5_el = root.find("ultimos5")
    if ult5_el is None:
        ult5_el = ET.SubElement(root, "ultimos5")

    total_el = root.find("totalMarcadas")
    if total_el is None:
        total_el = ET.SubElement(root, "totalMarcadas")

    ultimo_el = root.find("ultimoMarcado")
    if ultimo_el is None:
        ultimo_el = ET.SubElement(root, "ultimoMarcado")

    stinger_el = root.find("stinger")
    if stinger_el is None:
        stinger_el = ET.SubElement(root, "stinger")
    if stinger_el.text is None:
        stinger_el.text = ""

    stack = [int(x) for x in (stack or []) if 1 <= int(x) <= 75]
    marked = set(stack)
    last = stack[-1] if stack else None

    for b in balotas_el.findall("balota"):
        b.set("estado", "")
        b.set("ultimo", "")

    for b in balotas_el.findall("balota"):
        try:
            n = int(b.get("numero"))
        except Exception:
            continue
        if n in marked:
            b.set("estado", str(n))

    first = balotas_el.find(".//balota[@numero='1']")
    if first is None:
        first = ET.SubElement(balotas_el, "balota", numero="1", estado="", ultimo="")
    first.set("ultimo", str(last) if last is not None else "")

    ult5 = list(reversed(stack[-5:])) if stack else []
    ult5_el.text = ",".join(str(x) for x in ult5)
    total_el.text = str(len(marked))
    ultimo_el.text = (str(last) if last is not None else "")

    tree.write(BINGO_XML, encoding="utf-8", xml_declaration=True)
    try:
        _sync_vmix_numeros_xml_from_stack(stack)
    except Exception:
        pass

def _to_iso_date(s: str) -> str:
    s = (s or "").strip()
    if not s: return ""
    if "/" in s:
        try:
            d, m, y = s.split("/")
            return f"{y}-{int(m):02d}-{int(d):02d}"
        except Exception:
            pass
    try:
        return str(date.fromisoformat(s))
    except Exception:
        return ""

def _get_sorteo_activo_info() -> dict:
    """
    Lee el sorteo ACTIVO desde sorteos.xml de forma robusta:
    - soporta varias rutas (DATA/static/db, static/db, etc.)
    - soporta esquemas viejos y nuevos
    - evita el bug de ElementTree (usar `or` con nodos vacíos)
    """
    base = {
        "fecha": "",
        "nombre_sorteo": "",
        "identificador": "",
        "estado": "",
        "activo": "0",
        "finalizado": "0",
        "fuente": "",
    }

    def _is_on(v):
        s = str(v or "").strip().lower()
        return s in ("1", "true", "si", "sí", "yes", "activo")

    def _txt(node, tag, default=""):
        try:
            if node is None:
                return default
            val = node.findtext(tag)
            return (val or default).strip()
        except Exception:
            return default


    # 0) Snapshot rápido (sorteo_activo.json) para evitar ambigüedad de rutas
    try:
        for pjson in _sorteo_activo_snapshot_paths():
            if not pjson or not os.path.exists(pjson):
                continue
            with open(pjson, "r", encoding="utf-8") as f:
                snap = json.load(f) or {}
            s_estado = str(snap.get("estado") or "").strip().lower()
            s_activo = str(snap.get("activo") or "0").strip().lower()
            if s_activo in ("1", "true", "si", "sí", "activo") or s_estado == "activo":
                fecha_raw = (snap.get("fecha") or "").strip()
                fecha_out = _to_iso_date(fecha_raw) if fecha_raw else ""
                nombre_sorteo = (snap.get("nombre_sorteo") or "").strip()
                if not nombre_sorteo and fecha_out:
                    nombre_sorteo = f"Sorteo {fecha_out}"
                return {
                    "fecha": fecha_out or date.today().isoformat(),
                    "nombre_sorteo": nombre_sorteo or f"Sorteo {date.today().isoformat()}",
                    "identificador": (snap.get("identificador") or "").strip(),
                    "estado": "activo",
                    "activo": "1",
                    "finalizado": "0",
                    "origen_finalizado": str(snap.get("origen_finalizado") or "0").strip(),
                    "fuente": pjson,
                }
    except Exception:
        pass

    # 1) Candidatos de rutas para sorteos.xml (tu app tiene varias secciones que usan rutas distintas)
    candidatos = []

    # ruta global si existe
    try:
        p = globals().get("SORTEOS_XML")
        if p:
            candidatos.append(p)
    except Exception:
        pass

    # helper de tu módulo de sorteos (lee primero DATA y luego STATIC)
    try:
        if "_in_db_existing" in globals():
            p = _in_db_existing("sorteos.xml")
            if p:
                candidatos.append(p)
    except Exception:
        pass

    # rutas directas comunes
    try:
        base_dir = globals().get("BASE_DIR") or os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    posibles = [
        os.path.join(base_dir, "DATA", "static", "db", "sorteos.xml"),
        os.path.join(base_dir, "static", "db", "sorteos.xml"),
    ]

    for gname in ("DB_DATA", "DB_DIR", "DB_STATIC"):
        try:
            d = globals().get(gname)
            if d:
                posibles.append(os.path.join(d, "sorteos.xml"))
        except Exception:
            pass

    try:
        ddir = globals().get("DATA_DIR")
        if ddir:
            posibles.append(os.path.join(ddir, "static", "db", "sorteos.xml"))
    except Exception:
        pass

    # únicos y válidos
    seen = set()
    rutas = []
    for p in candidatos + posibles:
        if not p:
            continue
        p = os.path.abspath(p)
        if p in seen:
            continue
        seen.add(p)
        rutas.append(p)

    # 2) Buscar el sorteo activo en cualquiera de las rutas
    def _ruta_score(pp):
        try:
            ap = os.path.abspath(pp).replace("\\", "/").lower()
            pri = 0 if ("/data/static/db/" in ap or ap.endswith("/data/static/db/sorteos.xml")) else 1
            mtime = os.path.getmtime(pp) if os.path.exists(pp) else 0
            return (pri, -mtime)
        except Exception:
            return (9, 0)

    rutas = sorted(rutas, key=_ruta_score)

    for p in rutas:
        try:
            if not os.path.exists(p):
                continue

            tree = ET.parse(p)
            root = tree.getroot()

            # Recolectar nodos candidatos (esquema nuevo: <dia>, esquema viejo: <sorteo>)
            nodos = []
            if root.tag in ("dia", "sorteo"):
                nodos.append(root)

            nodos.extend(root.findall(".//dia"))
            nodos.extend(root.findall(".//sorteo"))

            # quitar duplicados por id de objeto
            tmp = []
            ids = set()
            for n in nodos:
                if id(n) not in ids:
                    ids.add(id(n))
                    tmp.append(n)
            nodos = tmp

            if not nodos:
                continue

            # Buscar activo primero
            dia = None
            for n in nodos:
                estado_attr = (n.attrib.get("estado") or "").strip().lower()
                estado_txt  = (_txt(n, "estado", "") or "").strip().lower()

                if (
                    _is_on(n.attrib.get("activo")) or
                    _is_on(n.attrib.get("active")) or
                    estado_attr == "activo" or
                    estado_txt == "activo"
                ):
                    dia = n
                    break

            # Si no encuentra activo, intentamos uno que tenga activado_en (por compatibilidad)
            if dia is None:
                for n in nodos:
                    if (n.attrib.get("activado_en") or "").strip():
                        dia = n
                        break

            if dia is None:
                continue

            # Nodos hijos (IMPORTANTE: sin usar `or` directo con ElementTree)
            b = dia.find("basicos")
            if b is None:
                b = dia.find("config")
            if b is None:
                b = dia

            pr = dia.find("programacion")
            if pr is None:
                pr = dia

            # Fecha (atributo o tag)
            fecha_raw = (
                (dia.attrib.get("fecha") or "").strip() or
                _txt(dia, "fecha", "") or
                _txt(pr, "fecha", "")
            )

            # Nombre / identificador
            nombre_sorteo = (
                (b.attrib.get("nombre_sorteo") or "").strip() or
                (b.attrib.get("nombre") or "").strip() or
                _txt(b, "nombre_sorteo", "") or
                _txt(b, "nombre", "") or
                _txt(dia, "nombre_sorteo", "") or
                _txt(dia, "nombre", "")
            )

            identificador = (
                (b.attrib.get("identificador") or "").strip() or
                (b.attrib.get("id") or "").strip() or
                _txt(b, "identificador", "") or
                _txt(b, "id", "") or
                _txt(dia, "identificador", "") or
                _txt(dia, "id", "")
            )

            estado = (
                (dia.attrib.get("estado") or "").strip() or
                _txt(dia, "estado", "") or
                ("activo" if _is_on(dia.attrib.get("activo")) else "")
            )

            activo = "1" if (
                _is_on(dia.attrib.get("activo")) or
                _is_on(dia.attrib.get("active")) or
                str(estado).strip().lower() == "activo"
            ) else "0"

            finalizado = (
                "1" if _is_on(dia.attrib.get("finalizado")) else
                ("1" if str(estado).strip().lower() == "finalizado" else "0")
            )

            # Normalizar fecha a YYYY-MM-DD si viene en dd/mm/yyyy
            try:
                fecha_out = _to_iso_date(fecha_raw) if fecha_raw else ""
            except Exception:
                fecha_out = str(fecha_raw or "").strip()

            # Compatibilidad con UI vieja: si no hay nombre, mostrar "Sorteo FECHA"
            if not nombre_sorteo and fecha_out:
                nombre_sorteo = f"Sorteo {fecha_out}"

            return {
                "fecha": fecha_out,
                "nombre_sorteo": nombre_sorteo,
                "identificador": identificador,
                "estado": estado,
                "activo": activo,
                "finalizado": finalizado,
                "fuente": p,
            }

        except Exception:
            continue

    # 3) Fallback opcional: JSON (si en algún momento lo usas)
    try:
        for pjson in (globals().get("SORTEO_JSON_CANDIDATES") or []):
            if not pjson or not os.path.exists(pjson):
                continue
            with open(pjson, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            fecha_raw = (data.get("fecha") or data.get("fecha_sorteo") or "").strip()
            fecha_out = _to_iso_date(fecha_raw) if fecha_raw else ""
            if fecha_out:
                return {
                    "fecha": fecha_out,
                    "nombre_sorteo": (data.get("nombre_sorteo") or data.get("sorteo") or f"Sorteo {fecha_out}").strip(),
                    "identificador": (data.get("identificador") or data.get("id") or "").strip(),
                    "estado": (data.get("estado") or "").strip(),
                    "activo": "1" if _is_on(data.get("activo")) else "0",
                    "finalizado": "1" if _is_on(data.get("finalizado")) else "0",
                    "fuente": pjson,
                }
    except Exception:
        pass

    # 4) Fallback final (mantiene compatibilidad con tu UI)
    hoy = date.today().isoformat()
    return {
        "fecha": hoy,
        "nombre_sorteo": f"Sorteo {hoy}",
        "identificador": "",
        "estado": "",
        "activo": "0",
        "finalizado": "0",
        "fuente": "fecha_hoy",
    }

def _get_sorteo_fecha() -> str:
    return (_get_sorteo_activo_info().get("fecha") or date.today().isoformat())

# ============================================================
#  SPINNERS: estado persistente + XML fallback + vMix API
# ============================================================
def _ensure_vmix_xml():
    if os.path.exists(VMIX_SPINNERS_XML):
        return
    root = ET.Element("vmix")
    ET.SubElement(root, "overlay", index=str(VMIX_OVERLAY_INDEX), state="off")
    ET.SubElement(root, "spinner", state="idle", locked="0")
    nums = ET.SubElement(root, "nums")
    for _ in range(20):
        ET.SubElement(nums, "n", v="")
    ET.ElementTree(root).write(VMIX_SPINNERS_XML, encoding="utf-8", xml_declaration=True)

def _read_spinners_list():
    for path in (VMIX_SPINNERS_XML, SPINNERS_XML):
        try:
            if not os.path.exists(path): continue
            root = ET.parse(path).getroot()
            out = []
            for n in root.findall(".//n"):
                val = (n.attrib.get("v") if hasattr(n, "attrib") else None) or (n.text or "")
                val = re.sub(r"\D", "", val)[:4]
                out.append(val.zfill(4) if val else "")
            out = (out + [""] * 20)[:20]
            return out
        except Exception:
            pass
    return [""] * 20

def _write_spinners_list(values):
    _ensure_vmix_xml()
    tree = ET.parse(VMIX_SPINNERS_XML); root = tree.getroot()
    nums = root.find("nums")
    if nums is None:
        nums = ET.SubElement(root, "nums")
    for el in list(nums):
        nums.remove(el)
    for i in range(20):
        v = ""
        if i < len(values):
            raw = str(values[i]).strip()
            v = re.sub(r"\D", "", raw)[:4]
            if v: v = v.zfill(4)
        ET.SubElement(nums, "n", v=v)
    tree.write(VMIX_SPINNERS_XML, encoding="utf-8", xml_declaration=True)

def _read_spinner_state():
    st = _json_read(SPINNERS_STATE_JSON) or {}
    return {
        "running": bool(st.get("running", False)),
        "locked":  bool(st.get("locked", False)),
        "overlay_on": bool(st.get("overlay_on", False)),
        "ts": st.get("ts") or datetime.utcnow().isoformat(),
    }

def _write_spinner_state(running=None, locked=None, overlay_on=None):
    cur = _read_spinner_state()
    if running is not None:   cur["running"] = bool(running)
    if locked is not None:    cur["locked"] = bool(locked)
    if overlay_on is not None:cur["overlay_on"] = bool(overlay_on)
    cur["ts"] = datetime.utcnow().isoformat()
    _json_write(SPINNERS_STATE_JSON, cur)

    # Espejo en XML
    _ensure_vmix_xml()
    tree = ET.parse(VMIX_SPINNERS_XML); root = tree.getroot()
    spn = root.find("spinner") or ET.SubElement(root, "spinner")
    spn.set("state", "running" if cur["running"] else "idle")
    spn.set("locked", "1" if cur["locked"] else "0")
    ov = root.find("overlay") or ET.SubElement(root, "overlay", index=str(VMIX_OVERLAY_INDEX))
    ov.set("index", str(VMIX_OVERLAY_INDEX))
    ov.set("state", "on" if cur["overlay_on"] else "off")
    tree.write(VMIX_SPINNERS_XML, encoding="utf-8", xml_declaration=True)
    return cur

def _vmix_call(function, **params):
    import socket
    try:
        import requests
    except Exception:
        return False, "requests-not-available"
    base = f"http://{VMIX_HOST}:{VMIX_PORT}/api/"
    q = {"Function": function}
    q.update({k: str(v) for k, v in params.items() if v is not None})
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect((VMIX_HOST, int(VMIX_PORT)))
        sock.close()
    except Exception:
        return False, "vmix-offline"
    try:
        r = requests.get(base, params=q, timeout=1.5)
        if r.status_code == 200:
            return True, "ok"
        return False, f"http-{r.status_code}"
    except Exception as e:
        return False, f"err:{e}"

def _overlay_on():
    ok, msg = _vmix_call(f"OverlayInput{VMIX_OVERLAY_INDEX}On", Input=VMIX_SPINNER_INPUT)
    st = _write_spinner_state(overlay_on=True)
    return ok, msg, st

def _overlay_off():
    ok, msg = _vmix_call(f"OverlayInput{VMIX_OVERLAY_INDEX}Off", Input=VMIX_SPINNER_INPUT)
    st = _write_spinner_state(overlay_on=False)
    return ok, msg, st

# ============================================================
#  FIGURAS HELPERS
# ============================================================
def _pick_figuras_xml_for_fecha(fecha: str) -> str:
    candidates = [
        os.path.join(FIGURAS_DIR, f"{fecha}.xml"),
        FIGURAS_DEL_DIA_XML,
        DATOS_FIGURAS_XML,
    ]
    for c in candidates:
        if os.path.exists(c): return c
    root = ET.Element("figuras")
    ET.ElementTree(root).write(FIGURAS_DEL_DIA_XML, encoding="utf-8", xml_declaration=True)
    return FIGURAS_DEL_DIA_XML

def _parse_valor_int(v):
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except Exception:
        return 0

def _parse_fig_item_from_text(txt: str):
    s = (txt or "").strip()
    if not s: return None
    s = s.replace("—", "-").replace("–", "-")
    m = re.match(r"^(.*?)[\s:\-]+(\d+(\.\d+)?)\s*$", s)
    if m:
        nombre = m.group(1).strip()
        valor  = _parse_valor_int(m.group(2))
        if nombre:
            return {"nombre": nombre, "valor": valor}
    return {"nombre": s, "valor": 0}

def _read_figuras_from_xml(path_xml: str):
    out = []
    try:
        root = ET.parse(path_xml).getroot()
        for f in root.findall(".//figura"):
            nombre = (f.get("nombre") or f.findtext("figuraNOMBRE") or "").strip()
            valor  = _parse_valor_int(f.get("valor") or f.findtext("figuraVALOR") or 0)
            estado = (f.get("estado") or "").strip().upper() or "INACTIVO"
            if nombre:
                out.append({"nombre": nombre, "valor": valor, "estado": estado})
    except Exception:
        pass
    return out

def _merge_estado_desde_xml(path_xml: str, base_list: list):
    try:
        current = _read_figuras_from_xml(path_xml)
        m = {c["nombre"].strip().lower(): c for c in current}
        out = []
        for f in base_list:
            key = f["nombre"].strip().lower()
            estado = (m.get(key, {}).get("estado") or f.get("estado") or "INACTIVO").upper()
            out.append({"nombre": f["nombre"], "valor": _parse_valor_int(f["valor"]), "estado": estado})
        return out
    except Exception:
        return base_list

def _load_figuras_desde_json_o_xml(fecha: str):
    for path in SORTEO_JSON_CANDIDATES:
        js = _json_read(path)
        if isinstance(js, dict):
            for k in ("figuras_del_dia", "figs_del_dia", "figuras"):
                raw = js.get(k)
                if isinstance(raw, list) and raw:
                    out = []
                    for item in raw:
                        if isinstance(item, dict):
                            nombre = (item.get("nombre") or item.get("name") or "").strip()
                            valor  = _parse_valor_int(item.get("valor") or item.get("value") or 0)
                            if nombre:
                                out.append({"nombre": nombre, "valor": valor, "estado": "INACTIVO"})
                        else:
                            p = _parse_fig_item_from_text(str(item))
                            if p:
                                out.append({"nombre": p["nombre"], "valor": p["valor"], "estado": "INACTIVO"})
                    path_xml = _pick_figuras_xml_for_fecha(fecha)
                    out = _merge_estado_desde_xml(path_xml, out)
                    return (out, path_xml)
    path_xml = _pick_figuras_xml_for_fecha(fecha)
    figs = _read_figuras_from_xml(path_xml)
    return (figs, path_xml)

def _write_figure_state_to_xml(path_xml: str, nombre: str, estado: str, valor: int | None = None):
    estado = _panel_state_norm(estado)
    if not os.path.exists(path_xml):
        root = ET.Element("figuras")
        ET.ElementTree(root).write(path_xml, encoding="utf-8", xml_declaration=True)

    tree = ET.parse(path_xml); root = tree.getroot()

    target = None
    wanted = str(nombre or "").strip()
    wanted_code = code_for(wanted) if wanted else ""

    for f in root.findall(".//figura"):
        n = (f.get("nombre") or f.findtext("figuraNOMBRE") or "").strip()
        if not n:
            continue
        if n.lower() == wanted.lower():
            target = f
            break
        try:
            # Soporta clic sobre nombres semánticos: LLENA / RELLENA / YAPA / SUPER YAPA
            if wanted_code and wanted_code in ("TL1", "TL2", "TL3", "TL4") and code_for(n) == wanted_code:
                target = f
                break
        except Exception:
            pass

    if target is None:
        target = ET.SubElement(root, "figura", nombre=wanted)
        stored_name = wanted
    else:
        stored_name = (target.get("nombre") or target.findtext("figuraNOMBRE") or wanted).strip() or wanted

    target.set("nombre", stored_name)
    target.set("estado", estado)
    if valor is not None:
        target.set("valor", str(_parse_valor_int(valor)))
    else:
        if target.get("valor") is None:
            target.set("valor", "0")

    tree.write(path_xml, encoding="utf-8", xml_declaration=True)
    return True

def _refresh_vmix_figuras_panel_for_fecha(fecha: str | None = None):
    try:
        fecha = str(fecha or _get_sorteo_fecha() or "").strip()
        figuras = []
        try:
            figuras = _load_figuras_por_fecha(fecha) or []
        except Exception:
            figuras = []
        if not figuras:
            try:
                path_xml = _pick_figuras_xml_for_fecha(fecha)
                figuras = _read_figuras_from_xml(path_xml) or []
            except Exception:
                figuras = []
        return write_vmix_figuras_panel(fecha, figuras or [], load_catalogo_figuras())
    except Exception:
        return False


# ============================================================
#  RUTAS UI
# ============================================================
@juego_bp.route("/")
def juego_ui():
    try:
        if require_session and not session.get("usuario"):
            return redirect(url_for("login"))
    except Exception:
        pass
    return render_template("juego.html")

@juego_bp.get("/spinner_overlay")
def spinner_overlay_ui():
    return render_template("spinner_overlay.html")

# ============================================================
#  RUTAS: XML públicos (no cache)
# ============================================================
def _no_cache_file(path, mime="application/xml"):
    resp = make_response(send_file(path, mimetype=mime))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@juego_bp.get("/xml/bingo")
def juego_xml_bingo():
    _ensure_bingo_xml()
    return _no_cache_file(BINGO_XML)

@juego_bp.get("/xml/numeros")
def juego_xml_numeros():
    _ensure_vmix_numeros_xml()
    return _no_cache_file(VMIX_NUMEROS_XML)

@juego_bp.get("/xml/spinners")
def juego_xml_spinners():
    _ensure_vmix_xml()
    return _no_cache_file(VMIX_SPINNERS_XML)

# ============================================================
#  RUTAS vMix: enlaces y XMLs tabulares (Data Source)
# ============================================================
def _vmix_xml_response(root_elem: ET.Element):
    xml_bytes = ET.tostring(root_elem, encoding="utf-8")
    resp = make_response(b'<?xml version="1.0" encoding="utf-8"?>\n' + xml_bytes)
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def _vmix_base_url():
    # Respeta host/puerto actual (localhost o IP LAN)
    try:
        return (request.host_url or "").rstrip("/")
    except Exception:
        return ""


def _vmix_block_color():
    # Casilla central bloqueada para overlays (puedes cambiar el tono si quieres)
    return "#BFC7D5"

def _vmix_text_color_for_fill(fill_hex):
    c = str(fill_hex or "#FFFFFF").strip().upper()
    if c in ("#FF4040", "#2D7FF9"):
        return "#FFFFFF"  # rojo / azul => texto blanco
    if c in (_vmix_block_color().upper(), "#BFC7D5", "#D9E0EA", "#E5E7EB", "#E6E9EF"):
        return "#9CA3AF"  # bloqueado / free
    return "#000000"      # fondo blanco => texto negro


def _vmix_split_num_layers(num_text, fill_hex):
    """Devuelve (nb, nw, tcolor) para overlays con doble capa de texto en vMix.

    - nb: texto para capa negra (cuando el cuadro es blanco)
    - nw: texto para capa blanca (cuando el cuadro es rojo/azul)
    - tcolor: color de texto dinámico (compatibilidad con títulos viejos)
    """
    txt = str(num_text or "").strip()
    c = str(fill_hex or "#FFFFFF").strip().upper()
    if not c:
        c = "#FFFFFF"
    if not c.startswith("#"):
        c = "#" + c

    # Casilla bloqueada / centro
    if c in (_vmix_block_color().upper(), "#BFC7D5", "#D9E0EA", "#E5E7EB", "#E6E9EF", "#000000"):
        return "", "", "#9CA3AF"

    # Figuras (rojo) y última bola (azul) -> número blanco
    if c in ("#FF4040", "#2D7FF9", "#007BFF", "#1E90FF", "#3B82F6"):
        return "", txt, "#FFFFFF"

    # Fondo normal -> número negro
    return txt, "", "#000000"

VMIX_CARTON_GANADOR_STATE_JSON = os.path.join(DB_DIR, "vmix_carton_ganador_state.json")

def _vmix_carton_state_read():
    data = _safe_json_read(VMIX_CARTON_GANADOR_STATE_JSON) or {}
    if not isinstance(data, dict):
        data = {}
    return data

def _vmix_carton_state_write(data):
    try:
        _safe_json_write(VMIX_CARTON_GANADOR_STATE_JSON, data or {})
    except Exception:
        pass

def _vmix_carton_pick_index(total, fecha_iso, action=None, index_override=None):
    """Retorna índice 0-based persistido para el XML de cartón ganador (una sola fila)."""
    try:
        total = int(total or 0)
    except Exception:
        total = 0
    if total <= 0:
        return 0, 0

    state = _vmix_carton_state_read()
    by_fecha = state.get("por_fecha") if isinstance(state.get("por_fecha"), dict) else {}
    raw = by_fecha.get(str(fecha_iso), 1)
    try:
        current_1 = int(raw)
    except Exception:
        current_1 = 1
    if current_1 < 1:
        current_1 = 1
    if current_1 > total:
        current_1 = total

    if index_override is not None:
        try:
            idx1 = int(index_override)
        except Exception:
            idx1 = current_1
        if idx1 < 1:
            idx1 = 1
        if idx1 > total:
            idx1 = total
        current_1 = idx1
    else:
        a = str(action or "").strip().lower()
        if a in ("next", "siguiente", "sig"):
            current_1 = (current_1 % total) + 1
        elif a in ("prev", "anterior", "back"):
            current_1 = total if current_1 <= 1 else (current_1 - 1)
        elif a in ("first", "primero"):
            current_1 = 1
        elif a in ("last", "ultimo", "último"):
            current_1 = total

    by_fecha[str(fecha_iso)] = current_1
    state["por_fecha"] = by_fecha
    state["fecha"] = str(fecha_iso)
    state["actual"] = current_1
    state["total"] = total
    _vmix_carton_state_write(state)

    return current_1 - 1, current_1

def _vmix_money_fmt(v):
    try:
        n = float(v or 0)
    except Exception:
        n = 0.0
    # Formato estilo local para overlay: 5000 -> 5.000
    txt = f"{n:,.2f}"
    txt = txt.replace(",", "X").replace(".", ",").replace("X", ".")
    # si termina en ,00 lo quitamos
    if txt.endswith(",00"):
        txt = txt[:-3]
    return txt


def _vmix_load_figuras_dia_xml():
    # Prioriza el XML resumen generado por sorteo
    candidatos = []
    for base in (globals().get("DB_DATA"), globals().get("DB_STATIC"), globals().get("DB_DIR")):
        if base:
            candidatos.append(os.path.join(base, "vmix_figuras_dia.xml"))
    for path in candidatos:
        try:
            if path and os.path.exists(path):
                return ET.parse(path).getroot(), path
        except Exception:
            continue
    return None, None


def _vmix_load_ganadores_xml():
    for path in (globals().get("GANADORES_XML"), globals().get("GANADORES_XML_PUBLIC")):
        try:
            if path and os.path.exists(path):
                return ET.parse(path).getroot(), path
        except Exception:
            continue
    # crea uno vacío si no existe
    try:
        _write_ganadores_xml(_get_sorteo_fecha(), 0, [])
        for path in (globals().get("GANADORES_XML"), globals().get("GANADORES_XML_PUBLIC")):
            if path and os.path.exists(path):
                return ET.parse(path).getroot(), path
    except Exception:
        pass
    return None, None


def _vmix_figure_row_payload(fig_node):
    pos_order = globals().get("POS_25_ROW") or [
        "B1","I1","N1","G1","O1","B2","I2","N2","G2","O2",
        "B3","I3","N3","G3","O3","B4","I4","N4","G4","O4",
        "B5","I5","N5","G5","O5"
    ]
    color_by_pos = {}
    for c in fig_node.findall("./cuadro"):
        pos = (c.attrib.get("pos") or c.attrib.get("codigo") or "").strip().upper()
        if not pos:
            continue
        color_by_pos[pos] = (c.attrib.get("color") or "#FFFFFF").strip().upper()

    row = {
        "ORDEN": str(fig_node.attrib.get("orden") or ""),
        "CODIGO": str(fig_node.attrib.get("codigo") or ""),
        "FIGURA": str(fig_node.attrib.get("nombre") or ""),
        "VALOR": str(fig_node.attrib.get("valor") or "0"),
        "ESTADO": str(fig_node.attrib.get("estado") or "inactivo"),
    }
    for i, pos in enumerate(pos_order, start=1):
        color = color_by_pos.get(pos, "#FFFFFF")
        # Casilla 13 (N3) siempre bloqueada visualmente para presentación de figuras
        if pos == "N3":
            color = _vmix_block_color()
        n_text = pos
        nb, nw, tcolor = _vmix_split_num_layers(n_text, color)
        row[f"N{i}"] = n_text
        row[f"C{i}"] = color
        row[f"T{i}"] = tcolor
        row[f"NB{i}"] = nb
        row[f"NW{i}"] = nw
        row[f"P{i}"] = pos
    return row


def _vmix_build_figuras_presentacion_table_xml():
    root_src, _ = _vmix_load_figuras_dia_xml()
    out = ET.Element("presentacion", {"tipo": "figuras", "orden": "filas"})
    if root_src is None:
        return out

    # Soporta <figuras_dia><figura ...>...</figura></figuras_dia>
    for fig in root_src.findall("./figura"):
        payload = _vmix_figure_row_payload(fig)
        fila = ET.SubElement(out, "fila")
        # metadatos primero
        for k in ("ORDEN", "CODIGO", "FIGURA", "VALOR", "ESTADO"):
            ET.SubElement(fila, k).text = payload.get(k, "")
        # luego 25 celdas en orden POR FILAS (1..25)
        for i in range(1, 26):
            ET.SubElement(fila, f"N{i}").text = payload.get(f"N{i}", "")
            ET.SubElement(fila, f"C{i}").text = payload.get(f"C{i}", "#FFFFFF")
            ET.SubElement(fila, f"T{i}").text = payload.get(f"T{i}", _vmix_text_color_for_fill(payload.get(f"C{i}", "#FFFFFF")))
            ET.SubElement(fila, f"NB{i}").text = payload.get(f"NB{i}", "")
            ET.SubElement(fila, f"NW{i}").text = payload.get(f"NW{i}", "")
            ET.SubElement(fila, f"P{i}").text = payload.get(f"P{i}", "")
    return out


def _vmix_build_carton_ganador_table_xml(action=None, index_override=None):
    pos_order = globals().get("POS_25_ROW") or [
        "B1","I1","N1","G1","O1","B2","I2","N2","G2","O2",
        "B3","I3","N3","G3","O3","B4","I4","N4","G4","O4",
        "B5","I5","N5","G5","O5"
    ]
    root_g, _ = _vmix_load_ganadores_xml()
    fecha_attr = (root_g.attrib.get("fecha", "") if root_g is not None else "")
    out = ET.Element("carton_ganador", {"orden": "filas", "fecha": str(fecha_attr or _get_sorteo_fecha())})
    if root_g is None:
        return out

    ganadores = root_g.findall("./ganador")
    total = len(ganadores)
    idx0, idx1 = _vmix_carton_pick_index(total, (fecha_attr or _get_sorteo_fecha()), action=action, index_override=index_override)
    if ganadores:
        idx0 = max(0, min(idx0, len(ganadores)-1))
        sel_g = ganadores[idx0]
        carton = sel_g.find("./carton")
    else:
        sel_g = None
        carton = None

    fila = ET.SubElement(out, "fila")
    fig_name = (sel_g.attrib.get("figura", "") if sel_g is not None else "")
    val_raw = (sel_g.attrib.get("valor", "0") if sel_g is not None else "0")
    ET.SubElement(fila, "INDICE_ACTUAL").text = str(idx1 if total else 0)
    ET.SubElement(fila, "TOTAL_GANADORES").text = str(total)
    ET.SubElement(fila, "FIGURA").text = fig_name
    ET.SubElement(fila, "VALOR").text = val_raw
    ET.SubElement(fila, "VALOR_FMT").text = _vmix_money_fmt(val_raw)
    boleto_sel = (sel_g.attrib.get("tabla", "") if sel_g is not None else "")
    vendedor_sel = (sel_g.attrib.get("vendedor", "") if sel_g is not None else "")
    sector_sel = (sel_g.attrib.get("sector", "") if sel_g is not None else "")
    nombre_sel = (sel_g.attrib.get("nombre", "") if sel_g is not None else "")
    ET.SubElement(fila, "BOLETO").text = boleto_sel
    ET.SubElement(fila, "TABLA").text = boleto_sel
    ET.SubElement(fila, "NUMERO_CARTON_GANADOR").text = boleto_sel
    ET.SubElement(fila, "SERIE").text = (sel_g.attrib.get("serie", "") if sel_g is not None else "")
    ET.SubElement(fila, "ULTIMA_BOLA").text = (sel_g.attrib.get("ultima_bola", "") if sel_g is not None else "")
    ET.SubElement(fila, "VENDEDOR").text = vendedor_sel
    ET.SubElement(fila, "NOMBRE_VENDEDOR").text = vendedor_sel
    ET.SubElement(fila, "SECTOR").text = sector_sel
    ET.SubElement(fila, "PLANILLA").text = sector_sel
    ET.SubElement(fila, "PLANILLA_ASIGNADA").text = sector_sel
    ET.SubElement(fila, "NOMBRE_BOLETIN").text = nombre_sel
    ET.SubElement(fila, "OBSERVACION").text = nombre_sel
    ET.SubElement(fila, "GANADORES_FIGURA").text = str(sum(1 for g in ganadores if (g.attrib.get("figura","") == fig_name)))
    ET.SubElement(fila, "GANADORES_TOTAL").text = str(total)

    numero_ganador = ""
    try:
        if sel_g is not None:
            ng = sel_g.findtext("./numero_ganador") or sel_g.attrib.get("ultima_bola") or ""
            numero_ganador = str(ng).strip()
    except Exception:
        numero_ganador = ""

    num_by_pos, color_by_pos, text_by_pos = {}, {}, {}
    if carton is not None:
        for cel in carton.findall("./celda"):
            pos = (cel.attrib.get("pos") or "").strip().upper()
            if not pos:
                continue
            num = (cel.attrib.get("numero") or "").strip()
            fig_col = (cel.attrib.get("figura_color") or "#FFFFFF").strip().upper()
            requerido = (cel.attrib.get("requerido") or "0").strip() == "1"

            final_col = "#FFFFFF"
            if requerido or (fig_col not in ("#FFFFFF", "#E8E8E8", _vmix_block_color().upper())):
                final_col = "#FF4040"
            # Resalta la bola que completó el premio (si viene número)
            if numero_ganador and num and str(num).strip() == str(numero_ganador):
                final_col = "#2D7FF9"

            if pos == "N3":
                num = ""
                final_col = _vmix_block_color()

            num_by_pos[pos] = num
            color_by_pos[pos] = final_col
            text_by_pos[pos] = _vmix_text_color_for_fill(final_col)

    # Completa 25 posiciones SIEMPRE en orden por filas (B1,I1,N1,G1,O1 ... B5,I5,N5,G5,O5)
    for i, pos in enumerate(pos_order, start=1):
        default_num = "" if pos == "N3" else ""
        fill_color = color_by_pos.get(pos, _vmix_block_color() if pos == "N3" else "#FFFFFF")
        n_val = num_by_pos.get(pos, default_num)
        nb, nw, tcolor = _vmix_split_num_layers(n_val, fill_color)
        ET.SubElement(fila, f"N{i}").text = n_val
        ET.SubElement(fila, f"C{i}").text = fill_color
        ET.SubElement(fila, f"T{i}").text = text_by_pos.get(pos, tcolor)
        ET.SubElement(fila, f"NB{i}").text = nb
        ET.SubElement(fila, f"NW{i}").text = nw
        ET.SubElement(fila, f"P{i}").text = pos
    return out


@juego_bp.get("/vmix")
def juego_vmix_panel():
    base = _vmix_base_url()
    fecha_actual = ""
    try:
        fecha_actual = _get_sorteo_fecha()
    except Exception:
        fecha_actual = ""

    groups = [
        {
            "titulo": "Juego",
            "items": [
                {"nombre": "Bingo XML", "tipo": "xml", "url": f"{base}/juego/xml/bingo", "ruta": "/juego/xml/bingo", "nota": "Tablero de balotas para Data Source.", "disponible": True},
                {"nombre": "Números PNG XML", "tipo": "xml", "url": f"{base}/juego/xml/numeros", "ruta": "/juego/xml/numeros", "nota": "Rutas de imágenes PNG por número para vMix.", "disponible": True},
                {"nombre": "Spinners XML", "tipo": "xml", "url": f"{base}/juego/xml/spinners", "ruta": "/juego/xml/spinners", "nota": "Spinners activos para overlays.", "disponible": True},
                {"nombre": "Ganadores XML", "tipo": "xml", "url": f"{base}/juego/ganadores.xml", "ruta": "/juego/ganadores.xml", "nota": "Listado de premios ganadores.", "disponible": True},
                {"nombre": "Cartón ganador (tabla DS)", "tipo": "xml", "url": f"{base}/juego/xml/carton_ganador", "ruta": "/juego/xml/carton_ganador", "nota": "Tabla única para vMix Data Source.", "disponible": True},
                {"nombre": "Cartón ganador (siguiente)", "tipo": "xml", "url": f"{base}/juego/xml/carton_ganador/next", "ruta": "/juego/xml/carton_ganador/next", "nota": "Avanza al siguiente ganador.", "disponible": True},
                {"nombre": "Cartón ganador (anterior)", "tipo": "xml", "url": f"{base}/juego/xml/carton_ganador/prev", "ruta": "/juego/xml/carton_ganador/prev", "nota": "Regresa al ganador anterior.", "disponible": True},
            ],
        },
        {
            "titulo": "Figuras",
            "items": [
                {"nombre": "Figuras presentación (tabla DS)", "tipo": "xml", "url": f"{base}/juego/xml/figuras_presentacion", "ruta": "/juego/xml/figuras_presentacion", "nota": "Figuras del día en orden por filas.", "disponible": True},
                {"nombre": "Figura presentación RAW", "tipo": "xml", "url": f"{base}/juego/xml/figura_presentacion_raw", "ruta": "/juego/xml/figura_presentacion_raw", "nota": "Alias optimizado para Data Source.", "disponible": True},
            ],
        },
        {
            "titulo": "Extras",
            "items": [
                {"nombre": "Bonus XML", "tipo": "xml", "url": f"{base}/static/db/vmix_bonus.xml", "ruta": "/static/db/vmix_bonus.xml", "nota": "Bonus del día para overlays.", "disponible": True},
                {"nombre": "Reintegro XML", "tipo": "xml", "url": f"{base}/static/db/vmix_reintegro.xml", "ruta": "/static/db/vmix_reintegro.xml", "nota": "Reintegro activo del sorteo.", "disponible": True},
                {"nombre": "Figuras día XML (base)", "tipo": "xml", "url": f"{base}/static/db/vmix_figuras_dia.xml", "ruta": "/static/db/vmix_figuras_dia.xml", "nota": "Resumen base de figuras y valores.", "disponible": True},
            ],
        },
    ]
    vmix = {
        "host": request.host,
        "fecha": fecha_actual,
        "base_url": base,
        "groups": groups,
    }
    return render_template("juego_vmix.html", vmix=vmix)


@juego_bp.get("/vmix/links.json")
def juego_vmix_links_json():
    base = _vmix_base_url()
    fecha_actual = ""
    try:
        fecha_actual = _get_sorteo_fecha()
    except Exception:
        fecha_actual = ""
    payload = {
        "ok": True,
        "host": request.host,
        "fecha": fecha_actual,
        "base_url": base,
        "links": {
            "bingo": f"{base}/juego/xml/bingo",
            "numeros_png": f"{base}/juego/xml/numeros",
            "spinners": f"{base}/juego/xml/spinners",
            "ganadores": f"{base}/juego/ganadores.xml",
            "carton_ganador": f"{base}/juego/xml/carton_ganador",
            "carton_ganador_next": f"{base}/juego/xml/carton_ganador/next",
            "carton_ganador_prev": f"{base}/juego/xml/carton_ganador/prev",
            "figuras_presentacion": f"{base}/juego/xml/figuras_presentacion",
            "figura_presentacion_raw": f"{base}/juego/xml/figura_presentacion_raw",
            "bonus": f"{base}/static/db/vmix_bonus.xml",
            "reintegro": f"{base}/static/db/vmix_reintegro.xml",
            "figuras_dia": f"{base}/static/db/vmix_figuras_dia.xml",
        }
    }
    return jsonify(payload)


@juego_bp.get("/xml/figuras_presentacion")
def juego_xml_figuras_presentacion_table():
    return _vmix_xml_response(_vmix_build_figuras_presentacion_table_xml())


@juego_bp.get("/xml/figura_presentacion")
@juego_bp.get("/xml/figura_presentacion_raw")
def juego_xml_figura_presentacion_raw():
    # Alias raw: mismo formato tabular, optimizado para vMix Data Source (una fila por figura)
    return _vmix_xml_response(_vmix_build_figuras_presentacion_table_xml())


@juego_bp.get("/xml/carton_ganador")
def juego_xml_carton_ganador_table():
    accion = (request.args.get("accion") or request.args.get("a") or "").strip()
    idx = request.args.get("index") or request.args.get("idx")
    try:
        idx_val = int(idx) if idx not in (None, "") else None
    except Exception:
        idx_val = None
    return _vmix_xml_response(_vmix_build_carton_ganador_table_xml(action=accion, index_override=idx_val))


@juego_bp.get("/xml/carton_ganador/next")
def juego_xml_carton_ganador_table_next():
    return _vmix_xml_response(_vmix_build_carton_ganador_table_xml(action="next"))


@juego_bp.get("/xml/carton_ganador/prev")
def juego_xml_carton_ganador_table_prev():
    return _vmix_xml_response(_vmix_build_carton_ganador_table_xml(action="prev"))


@juego_bp.get("/xml/carton_ganador/first")
def juego_xml_carton_ganador_table_first():
    return _vmix_xml_response(_vmix_build_carton_ganador_table_xml(action="first"))


@juego_bp.get("/xml/carton_ganador/last")
def juego_xml_carton_ganador_table_last():
    return _vmix_xml_response(_vmix_build_carton_ganador_table_xml(action="last"))

# ============================================================
#  RUTAS ESTADO JUEGO / SPINNERS
# ============================================================
@juego_bp.get("/estado.json")
def juego_estado_json():
    stack = _read_stack()
    last = (stack[-1] if stack else None)
    spinners = _read_spinners_list()
    spn_state = _read_spinner_state()
    return jsonify(
        ok=True,
        stack=stack,
        last=last,
        total=len(stack),
        ultimos5=list(reversed(stack[-5:])),
        spinners=spinners,
        spinner_state=spn_state
    )

@juego_bp.get("/spinners")
def juego_spinners():
    return jsonify(ok=True, spinners=_read_spinners_list(), state=_read_spinner_state())

@juego_bp.post("/spinners/update_list")
def juego_spinners_update_list():
    data = request.get_json(silent=True) or {}
    values = data.get("values") or data.get("spinners") or []
    if not isinstance(values, list):
        return jsonify(ok=False, error="values debe ser lista"), 400
    _write_spinners_list(values)
    return jsonify(ok=True, spinners=_read_spinners_list())

@juego_bp.post("/spinners/launch")
def juego_spinners_launch():
    """
    Lanza un spinner (por HTTP) para que el overlay en vMix lo vea.
    Espera: {index:int (0-19 o 1-20), target:str (4 dígitos), overlay_on:bool}
    - Guarda un "evento" en static/db/spinners_event.json
    - (Opcional) enciende overlay via vMix API si está configurado
    """
    st = _read_spinner_state()
    if st["locked"]:
        return jsonify(ok=False, error="Spinners bloqueados. Desbloquea para lanzar."), 409

    data = request.get_json(silent=True) or {}
    idx = int(data.get("index", 0))
    # aceptar 1..20 o 0..19
    if 1 <= idx <= 20:
        idx0 = idx - 1
    else:
        idx0 = idx
    if idx0 < 0 or idx0 > 19:
        return jsonify(ok=False, error="index inválido (debe ser 0-19 o 1-20)"), 400

    raw_target = data.get("target") or data.get("value") or ""
    target = re.sub(r"\D", "", str(raw_target))[:4]
    if target:
        target = target.zfill(4)

    # si no viene target, usar el listado actual del día
    if not target:
        lst = _read_spinners_list()
        if idx0 < len(lst):
            target = re.sub(r"\D", "", str(lst[idx0] or ""))[:4]
            if target:
                target = target.zfill(4)

    if not target:
        return jsonify(ok=False, error="Este spinner no tiene valor asignado."), 400

    overlay_on = bool(data.get("overlay_on", True))

    # Registrar evento para que vMix lo lea (polling)
    ev_path = os.path.join(DB_DIR, "spinners_event.json")
    ev = {
        "t": int(datetime.utcnow().timestamp() * 1000),
        "op": "launch",
        "index": idx0,
        "target": target,
    }
    _json_write(ev_path, ev)

    # overlay ON (opcional): enciende overlay en vMix si VMIX_API_URL está configurado
    vmix_ok, vmix_msg = True, ""
    if overlay_on:
        ok, msg, _ = _overlay_on()
        vmix_ok, vmix_msg = ok, msg

    st = _write_spinner_state(running=True, locked=False, overlay_on=overlay_on)
    return jsonify(ok=True, target=target, event=ev, state=st, vmix_ok=vmix_ok, vmix_msg=vmix_msg)

@juego_bp.post("/spinners/generate")
def juego_spinners_generate():
    """
    Resetea el overlay a 0000 (por HTTP) para vMix.
    Espera: {index:int (opcional)}
    """
    st = _read_spinner_state()
    if st["locked"]:
        return jsonify(ok=False, error="Spinners bloqueados. Desbloquea para generar."), 409

    data = request.get_json(silent=True) or {}
    idx = int(data.get("index", 0))
    if 1 <= idx <= 20:
        idx0 = idx - 1
    else:
        idx0 = idx
    if idx0 < 0 or idx0 > 19:
        idx0 = 0

    ev_path = os.path.join(DB_DIR, "spinners_event.json")
    ev = {
        "t": int(datetime.utcnow().timestamp() * 1000),
        "op": "gen",
        "index": idx0,
        "target": "0000",
    }
    _json_write(ev_path, ev)

    overlay_on = True
    ok, msg, _ = _overlay_on()
    st = _write_spinner_state(running=True, locked=False, overlay_on=overlay_on)
    return jsonify(ok=True, event=ev, state=st, vmix_ok=ok, vmix_msg=msg)

@juego_bp.get("/spinners/event")
def juego_spinners_event():
    """
    Devuelve el último evento de spinners para que el overlay (vMix) lo consulte.
    """
    ev_path = os.path.join(DB_DIR, "spinners_event.json")
    ev = _json_read(ev_path) or {}
    resp = jsonify(ok=True, event=ev)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@juego_bp.post("/spinners/lock")
def juego_spinners_lock():
    ok, msg, _ = _overlay_off()
    st = _write_spinner_state(running=False, locked=True, overlay_on=False)
    return jsonify(ok=True, vmix_ok=ok, vmix_msg=msg, state=st)

@juego_bp.post("/spinners/unlock")
def juego_spinners_unlock():
    st = _write_spinner_state(locked=False)
    return jsonify(ok=True, state=st)

@juego_bp.post("/spinners/overlay")
def juego_spinners_overlay():
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    if action not in ("on", "off"):
        return jsonify(ok=False, error="action debe ser 'on' o 'off'"), 400
    if action == "on":
        ok, msg, st = _overlay_on()
    else:
        ok, msg, st = _overlay_off()
    return jsonify(ok=True, vmix_ok=ok, vmix_msg=msg, state=st)

# ============================================================
#  RUTAS JUEGO
# ============================================================
@juego_bp.post("/marcar")
def juego_marcar():
    data = request.get_json(silent=True) or {}
    numero = str(data.get("numero", "")).strip()
    if not numero.isdigit():
        return jsonify(success=False, error="Número inválido"), 400

    n = int(numero)
    if n < 1 or n > 75:
        return jsonify(success=False, error="Rango 1–75"), 400

    stack = _read_stack()
    if n not in stack:
        stack.append(n)
        _write_stack(stack)
        _sync_bingo_xml_from_stack(stack)

    # escribe stinger/última bola (si lo usas en vMix)
    try:
        tree = ET.parse(BINGO_XML); root = tree.getroot()
        st = root.find("stinger") or ET.SubElement(root, "stinger")
        st.text = str(n)
        tree.write(BINGO_XML, encoding="utf-8", xml_declaration=True)
    except Exception:
        pass

    # ===== Detectar GANADORES reales (figuras del día + rangos impresos) =====
    fecha = _get_sorteo_fecha()
    ganadores_nuevos = []
    ganadores_total = []
    try:
        # Si por alguna razón ganadores_state.json se perdió, aquí también limpiamos duplicados del día
        _prev = _safe_json_read(GANADORES_JSON) or {}
        _prev_list = _prev.get(str(fecha), [])
        _prev_len = len(_prev_list) if isinstance(_prev_list, list) else 0

        ganadores_total, ganadores_nuevos, keys = _detectar_ganadores(str(fecha), stack, n, recalc=False)

        # Escribe si hay nuevos ganadores o si se eliminaron duplicados (cambio de longitud)
        if ganadores_nuevos or (isinstance(ganadores_total, list) and len(ganadores_total) != _prev_len):
            _write_ganadores_json(str(fecha), ganadores_total, keys)
            _write_ganadores_xml(str(fecha), n, ganadores_total)

        if isinstance(ganadores_total, list):
            _sync_resultados_from_juego(str(fecha), ganadores_total)
    except Exception:
        pass

    try:
        _save_game_state_snapshot(str(fecha), stinger=n)
    except Exception:
        pass

    return jsonify(
        success=True,
        stack=stack,
        last=n,
        total=len(stack),
        ultimos5=list(reversed(stack[-5:])),
        ganadores_nuevos=ganadores_nuevos,
        ganadores_total=len(ganadores_total),
        fecha=str(fecha)
    )


@juego_bp.post("/reversa")
def juego_reversa():
    data = request.get_json(silent=True) or {}
    stack = _read_stack()
    if str(data.get("all", "")).lower() in ("1", "true", "si", "sí", "yes"):
        stack = []
    else:
        if stack:
            stack.pop()

    _write_stack(stack)
    _sync_bingo_xml_from_stack(stack)

    last = (stack[-1] if stack else 0)

    try:
        tree = ET.parse(BINGO_XML); root = tree.getroot()
        st = root.find("stinger") or ET.SubElement(root, "stinger")
        st.text = (str(last) if last else "")
        tree.write(BINGO_XML, encoding="utf-8", xml_declaration=True)
    except Exception:
        pass

    # Recalcula ganadores (por si desmarcaste un número)
    try:
        fecha = _get_sorteo_fecha()
        ganadores_total, _ = _recalcular_ganadores(str(fecha), stack, int(last) if last else 0)
        _sync_resultados_from_juego(str(fecha), ganadores_total)
        gcount = len(ganadores_total)
    except Exception:
        gcount = 0

    try:
        _save_game_state_snapshot(str(fecha), stinger=last)
    except Exception:
        pass

    return jsonify(
        success=True,
        stack=stack,
        last=(stack[-1] if stack else None),
        total=len(stack),
        ultimos5=list(reversed(stack[-5:])),
        ganadores_total=gcount
    )


@juego_bp.post("/reset")
def juego_reset():
    fecha = _get_sorteo_fecha()
    try:
        info_activa = _get_sorteo_activo_info() or {}
    except Exception:
        info_activa = {}
    try:
        cfg_fecha = _sorteo_read_config(str(fecha)) if callable(globals().get("_sorteo_read_config")) else {}
    except Exception:
        cfg_fecha = {}

    preserve_flags = [
        str((info_activa or {}).get("finalizado") or "").strip().lower(),
        str((info_activa or {}).get("origen_finalizado") or "").strip().lower(),
        str((cfg_fecha or {}).get("finalizado") or "").strip().lower(),
    ]
    preserve_history = any(v in ("1", "true", "si", "sí", "yes") for v in preserve_flags)

    # Si el día ya estaba finalizado, guarda snapshot ANTES de limpiar,
    # pero el reset operativo igual debe dejar el juego en cero.
    if preserve_history:
        try:
            _save_game_state_snapshot(str(fecha))
        except Exception:
            pass

    # 1) limpiar tablero / stack / stinger
    _write_stack([])
    try:
        _sync_bingo_xml_from_stack([])
    except Exception:
        try:
            _ensure_bingo_xml()
            tree = ET.parse(BINGO_XML)
            root = tree.getroot()

            balotas_el = root.find("balotas")
            if balotas_el is None:
                balotas_el = ET.SubElement(root, "balotas")
            existentes = {str(b.get("numero") or "").strip() for b in balotas_el.findall("balota")}
            for n in range(1, 76):
                if str(n) not in existentes:
                    ET.SubElement(balotas_el, "balota", numero=str(n), estado="", ultimo="")
            for b in balotas_el.findall("balota"):
                b.set("estado", "")
                b.set("ultimo", "")

            ult5_el = root.find("ultimos5") or ET.SubElement(root, "ultimos5")
            total_el = root.find("totalMarcadas") or ET.SubElement(root, "totalMarcadas")
            ultimo_el = root.find("ultimoMarcado") or ET.SubElement(root, "ultimoMarcado")
            st = root.find("stinger") or ET.SubElement(root, "stinger")

            ult5_el.text = ""
            total_el.text = "0"
            ultimo_el.text = ""
            st.text = ""

            tree.write(BINGO_XML, encoding="utf-8", xml_declaration=True)
        except Exception:
            pass
    try:
        tree = ET.parse(BINGO_XML)
        root = tree.getroot()
        st = root.find("stinger") or ET.SubElement(root, "stinger")
        st.text = ""
        tree.write(BINGO_XML, encoding="utf-8", xml_declaration=True)
    except Exception:
        pass

    # 2) apagar overlay/spinner
    try:
        _overlay_off()
    except Exception:
        pass
    try:
        _write_spinner_state(running=False, locked=False, overlay_on=False)
    except Exception:
        pass

    # 3) limpiar SIEMPRE estados visuales del juego actual
    try:
        cache = _json_read(FIG_ESTADOS_JSON) or {}
        cache[str(fecha)] = {}
        _json_write(FIG_ESTADOS_JSON, cache)
    except Exception:
        pass

    # 4) dejar en cero resultados/ganadores del día actual
    corrections_cleared = False
    vmix_carton_reset = False
    resultados_reset = False
    figuras_refresh_ok = False

    try:
        # ganadores.json + state + xml
        data = _safe_json_read(GANADORES_JSON) or {}
        data[str(fecha)] = []
        _safe_json_write(GANADORES_JSON, data)
        _safe_json_write(GANADORES_STATE_JSON, {"keys": []})
        _write_ganadores_xml(str(fecha), 0, [])

        # resultados_sorteo.xml: conservar filas base/extras, pero SIN ganadores
        try:
            actual = _cargar_resultados(str(fecha)) or {"items": [], "extras": {"comodin": {}, "gran_bonus": {}}}
            items_reset = []
            for item in list(actual.get("items") or []):
                figura = str(item.get("figura") or item.get("nombre") or "").strip()
                if not figura:
                    continue
                items_reset.append({"figura": figura, "ganadores": []})
            extras_reset = dict(actual.get("extras") or {})
            _guardar_resultados(str(fecha), items_reset, extras=extras_reset)
            resultados_reset = True
        except Exception:
            try:
                _sync_resultados_from_juego(str(fecha), [])
                resultados_reset = True
            except Exception:
                resultados_reset = False

        # correcciones + puntero de cartón ganador
        try:
            corrections_cleared = bool(_corr_clear_fecha(str(fecha))) if callable(globals().get('_corr_clear_fecha')) else False
        except Exception:
            corrections_cleared = False
        try:
            vmix_carton_reset = bool(_reset_vmix_carton_state_for_fecha(str(fecha))) if callable(globals().get('_reset_vmix_carton_state_for_fecha')) else False
        except Exception:
            vmix_carton_reset = False

        # refrescar panel/xml de figuras ya sin premios jugados
        try:
            _refresh_vmix_figuras_panel_for_fecha(str(fecha))
            figuras_refresh_ok = True
        except Exception:
            figuras_refresh_ok = False

        # snapshot final del estado limpio
        try:
            _save_game_state_snapshot(str(fecha), stinger="")
        except Exception:
            pass
    except Exception:
        pass

    return jsonify(
        success=True,
        preserve_history=preserve_history,
        fecha=str(fecha),
        corrections_cleared=corrections_cleared,
        vmix_carton_reset=vmix_carton_reset,
        resultados_reset=resultados_reset,
        figuras_refresh_ok=figuras_refresh_ok,
        ganadores_total=0,
        stack=[],
        ultimos5=[],
        last=None,
        force_reload=True,
    )


@juego_bp.post("/activar_stinger")
def juego_activar_stinger():
    data = request.get_json(silent=True) or {}
    numero = str(data.get("numero", "")).strip()
    if not numero:
        return jsonify(success=False, error="numero requerido"), 400
    _ensure_bingo_xml()
    tree = ET.parse(BINGO_XML); root = tree.getroot()
    st = root.find("stinger") or ET.SubElement(root, "stinger")
    st.text = numero
    tree.write(BINGO_XML, encoding="utf-8", xml_declaration=True)
    return jsonify(success=True)

# ============================================================
#  SORTEO / FIGURAS
# ============================================================
@juego_bp.get("/sorteo_fecha")
def juego_sorteo_fecha():
    info = _get_sorteo_activo_info()
    return jsonify(
        ok=True,
        fecha=info.get("fecha"),
        nombre_sorteo=info.get("nombre_sorteo"),
        identificador=info.get("identificador"),
        estado=info.get("estado"),
        activo=info.get("activo"),
        finalizado=info.get("finalizado"),
        fuente=info.get("fuente"),
    )


@juego_bp.get("/extras")
def juego_extras_dia():
    fecha = _get_sorteo_fecha()
    info = _get_extras_impresion_dia(fecha)

    try:
        _sync_vmix_bonus_snapshot(
            fecha,
            info.get("bonus_numbers") or [],
            info.get("bonus_code") or "",
            info.get("bonus_feasible"),
        )
        _sync_vmix_reintegro_snapshot(fecha, info.get("reintegro") or "")
    except Exception:
        _ensure_extras_vmix_xmls()

    bstate = _read_bonus_click_state()
    rstate = _read_reintegro_click_state()
    return jsonify({
        "ok": True,
        "fecha": fecha,
        "bonus_numbers": info.get("bonus_numbers") or [],
        "bonus_code": info.get("bonus_code") or "",
        "bonus_feasible": info.get("bonus_feasible"),
        "reintegro": info.get("reintegro") or "",
        "bonus_state": bstate,
        "reintegro_state": rstate,
        "bonus_xml": "/static/db/vmix_bonus.xml",
        "reintegro_xml": "/static/db/vmix_reintegro.xml",
        "reintegros_xml": "/static/db/vmix_reintegros.xml",
    })

@juego_bp.post("/bonus/click")
def juego_bonus_click():
    fecha = _get_sorteo_fecha()
    info = _get_extras_impresion_dia(fecha)
    nums = info.get("bonus_numbers") or []
    if not nums:
        return jsonify({"ok": False, "error": "No hay bonus configurado para este día"}), 400

    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    if idx in (None, ""):
        try:
            num_req = int(str(data.get("numero") or "").strip())
            idx = (nums.index(num_req) + 1) if num_req in nums else 0
        except Exception:
            idx = 0

    try:
        st = _write_vmix_bonus_click(fecha, nums, idx)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo escribir vmix_bonus.xml: {e}"}), 500

    return jsonify({
        "ok": True,
        "fecha": fecha,
        "bonus_numbers": nums,
        **st,
        "xml": "/static/db/vmix_bonus.xml",
    })

@juego_bp.post("/reintegro/click")
def juego_reintegro_click():
    fecha = _get_sorteo_fecha()
    info = _get_extras_impresion_dia(fecha)
    rein = str((request.get_json(silent=True) or {}).get("reintegro") or info.get("reintegro") or "").strip()
    if not rein:
        return jsonify({"ok": False, "error": "No hay reintegro configurado para este día"}), 400

    try:
        st = _write_vmix_reintegro_click(fecha, rein)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo escribir vmix_reintegro.xml: {e}"}), 500

    return jsonify({
        "ok": True,
        "fecha": fecha,
        **st,
        "xml": "/static/db/vmix_reintegro.xml",
        "xml_secundario": "/static/db/vmix_reintegros.xml",
    })

@juego_bp.get("/tabla_ganadora_random")
def juego_tabla_ganadora_random():
    """
    Si ya hay ganadores detectados, devuelve el ÚLTIMO ganador (real).
    Si aún no hay ganadores, devuelve una tabla aleatoria SOLO dentro de los rangos impresos del día.
    """
    fecha = _get_sorteo_fecha()

    # 1) Si existen ganadores reales, devuelve el último
    try:
        data = _safe_json_read(GANADORES_JSON) or {}
        wins = data.get(str(fecha), []) or []
        if wins:
            w = wins[-1]
            return jsonify(
                ok=True,
                tipo="ganadora",
                fecha=str(fecha),
                serie_archivo=w.get("serie", ""),
                tabla_num=w.get("tabla", ""),
                figura=w.get("figura", ""),
                valor=w.get("valor", 0),
                ultima_bola=w.get("ultima_bola", ""),
                numeros_figura=w.get("numeros_figura", []),
                grid=w.get("grid", [])
            )
    except Exception:
        pass

    # 2) Fallback: tabla aleatoria dentro de rangos impresos
    rangos = _get_rangos_en_juego(str(fecha))
    if not rangos:
        return jsonify(ok=False, error="No hay rangos impresos (boletos) para esta fecha"), 404

    # elige un rango aleatorio
    r = random.choice(rangos)
    serie_archivo = r["serie_archivo"]
    try:
        df = _read_df_for_series(serie_archivo)
    except Exception:
        return jsonify(ok=False, error=f"No se pudo leer la serie {serie_archivo}"), 500

    if df is None or df.empty:
        return jsonify(ok=False, error=f"Serie vacía: {serie_archivo}"), 500

    id_col = df.columns[0]
    ids = df[id_col].astype(str).tolist()
    id_to_idx = {v: i for i, v in enumerate(ids)}
    if r["desde"] not in id_to_idx or r["hasta"] not in id_to_idx:
        return jsonify(ok=False, error="Rango no encontrado en la serie"), 404

    s = id_to_idx[r["desde"]]
    e = id_to_idx[r["hasta"]] + 1
    if e <= s:
        e = s + 1
    pick_idx = random.randrange(s, min(e, len(df)))
    row = df.iloc[pick_idx].to_dict()
    row_lower = {str(k).lower(): str(v).strip() for k, v in row.items()}

    # construye grid (misma forma que la UI espera)
    grid, _ = _build_grid_from_row(row_lower)
    tabla_num = str(row.get(id_col, row_lower.get(str(id_col).lower(), ""))).strip()

    return jsonify(
        ok=True,
        tipo="aleatoria",
        fecha=str(fecha),
        serie_archivo=serie_archivo,
        tabla_num=tabla_num,
        grid=grid
    )


@juego_bp.get("/figuras")
def juego_figuras_list():
    # Lee FIGURAS DEL DÍA desde static/db/figuras_por_fecha.xml (mismo origen de /escoger-figuras)
    # y normaliza TL programadas para que hagan match con la UI de ganadores:
    #   TL1 -> LLENA, TL2 -> RELLENA, TL3 -> YAPA, TL4 -> SUPER YAPA
    fecha = _get_sorteo_fecha()
    figs = _load_figuras_por_fecha(str(fecha))
    estados = {}
    try:
        if "FIG_ESTADOS_JSON" in globals():
            estados = (_safe_json_read(FIG_ESTADOS_JSON) or {}).get(str(fecha), {}) or {}
    except Exception:
        estados = {}

    out = []
    seen = set()
    for f in figs:
        nombre_raw = str(f.get("nombre", "") or "").strip()
        if not nombre_raw:
            continue
        try:
            nombre = _tl_semantic_name(nombre_raw, "")
        except Exception:
            nombre = nombre_raw
        key = nombre.lower()
        if key in seen:
            continue
        seen.add(key)
        estado = (estados.get(nombre_raw) or estados.get(nombre) or "ACTIVO")
        out.append({
            "nombre": nombre,
            "valor": float(f.get("valor", 0) or 0),
            "estado": estado
        })

    origen = next((p for p in _agenda_paths() if os.path.exists(p)), "")
    return jsonify(ok=True, fecha=fecha, origen_xml=origen, figuras=out, figuras_del_dia=out, total=len(out))


@juego_bp.post("/figuras/estado")
def juego_figuras_estado():
    data = request.get_json(silent=True) or request.form.to_dict(flat=True) or {}
    if not isinstance(data, dict):
        data = {}

    nombre = (data.get("nombre") or data.get("figura") or "").strip()
    estado = (data.get("estado") or "").strip().upper()
    valor  = data.get("valor", None)
    fecha  = str(data.get("fecha") or _get_sorteo_fecha() or "").strip()

    if not nombre:
        return jsonify(ok=False, error="nombre requerido"), 400
    if estado not in ("INACTIVO", "SE FUE", "SE QUEDO"):
        return jsonify(ok=False, error="estado inválido"), 400

    path_xml = _pick_figuras_xml_for_fecha(fecha)
    ok = _write_figure_state_to_xml(path_xml, nombre, estado, valor)
    if not ok:
        return jsonify(ok=False, error="no se pudo escribir XML"), 500

    cache = _json_read(FIG_ESTADOS_JSON) or {}
    cache.setdefault(fecha, {})
    # Guarda alias útiles para UI y TL semánticas sin romper nombres originales
    cache[fecha][nombre] = estado
    try:
        cache[fecha][_panel_name_display(nombre)] = estado
    except Exception:
        pass
    try:
        wanted_code = code_for(nombre)
        for item in (_read_figuras_from_xml(path_xml) or []):
            nm = str((item or {}).get("nombre") or "").strip()
            if not nm:
                continue
            try:
                if wanted_code and code_for(nm) == wanted_code:
                    cache[fecha][nm] = estado
            except Exception:
                pass
    except Exception:
        pass
    _json_write(FIG_ESTADOS_JSON, cache)

    try:
        _refresh_vmix_figuras_panel_for_fecha(fecha)
    except Exception:
        pass

    figs = _read_figuras_from_xml(path_xml)
    return jsonify(ok=True, fecha=fecha, origen_xml=path_xml, figuras=figs)

@juego_bp.post("/figura_estado")
def juego_figura_estado_compat():
    return juego_figuras_estado()

@juego_bp.post("/figuras/sync-xml")
def juego_figuras_sync_xml():
    fecha = _get_sorteo_fecha()
    cache = _json_read(FIG_ESTADOS_JSON) or {}
    estados = cache.get(fecha, {})
    path_xml = _pick_figuras_xml_for_fecha(fecha)
    actual = {f["nombre"].strip().lower(): f for f in _read_figuras_from_xml(path_xml)}
    for nombre, estado in estados.items():
        low = nombre.strip().lower()
        valor = actual.get(low, {}).get("valor", 0)
        _write_figure_state_to_xml(path_xml, nombre, estado, valor)
    figs = _read_figuras_from_xml(path_xml)
    try:
        _refresh_vmix_figuras_panel_for_fecha(fecha)
    except Exception:
        pass
    return jsonify(ok=True, fecha=fecha, origen_xml=path_xml, figuras=figs)

# ============================================================
#  vMix XML extra: TOTAL A JUGAR + ESTADO DE FIGURAS
# ============================================================
VMIX_TOTAL_JUGAR_REL = "vmix_total_jugar.xml"
VMIX_FIGURAS_ESTADO_REL = "vmix_figuras_estado.xml"
VMIX_FIGURAS_ESTADO_2COL_REL = "vmix_figuras_estado_2col.xml"


def _vmix_money_fmt(v):
    try:
        return f"${_fmt_int(v)}"
    except Exception:
        try:
            return f"${int(float(str(v).replace(',', '.')))}"
        except Exception:
            return "$0"


def _vmix_total_jugar_root(fecha: str | None = None):
    fecha = str(fecha or _get_sorteo_fecha() or date.today().isoformat()).strip()
    cfg = _sorteo_read_config(fecha) or {}
    activo = _get_sorteo_activo_info() or {}

    valor = _fmt_int(cfg.get('total_a_jugar') or 0)
    premios = _fmt_int(cfg.get('total_premios') or 0)
    boletos = _fmt_int(cfg.get('boletos_impresos') or 0)
    valor_boleto = _fmt_int(cfg.get('valor_boleto') or 0)
    nombre_sorteo = (cfg.get('nombre_sorteo') or activo.get('nombre_sorteo') or f'Sorteo {fecha}').strip()
    identificador = (cfg.get('identificador') or activo.get('identificador') or '').strip()

    root = ET.Element('total_jugar', {
        'fecha': fecha,
        'sorteo': nombre_sorteo,
        'identificador': identificador,
        'orden': 'filas',
    })
    fila = ET.SubElement(root, 'fila')
    ET.SubElement(fila, 'fecha').text = fecha
    ET.SubElement(fila, 'sorteo').text = nombre_sorteo
    ET.SubElement(fila, 'identificador').text = identificador
    ET.SubElement(fila, 'concepto').text = 'TOTAL A JUGAR'
    ET.SubElement(fila, 'valor').text = valor
    ET.SubElement(fila, 'valor_fmt').text = _vmix_money_fmt(valor)
    ET.SubElement(fila, 'total_premios').text = premios
    ET.SubElement(fila, 'total_premios_fmt').text = _vmix_money_fmt(premios)
    ET.SubElement(fila, 'boletos_impresos').text = boletos
    ET.SubElement(fila, 'valor_boleto').text = valor_boleto
    ET.SubElement(fila, 'valor_boleto_fmt').text = _vmix_money_fmt(valor_boleto)
    return root


def _winner_name_for_vmix(g: dict) -> str:
    nombre = str((g or {}).get('nombre') or '').strip()
    if nombre:
        return nombre
    boleto = str((g or {}).get('boleto') or '').strip()
    if boleto:
        return f'BOLETO #{boleto}'
    vendedor = str((g or {}).get('vendedor') or '').strip()
    if vendedor:
        return vendedor
    sector = str((g or {}).get('sector') or '').strip()
    if sector:
        return sector
    return '-'


def _winner_ticket_text_for_vmix(g: dict) -> str:
    nombre = str((g or {}).get('nombre') or '').strip()
    boleto = str((g or {}).get('boleto') or '').strip()
    vendedor = str((g or {}).get('vendedor') or '').strip()
    sector = str((g or {}).get('sector') or '').strip()

    if boleto and nombre:
        return f'#{boleto} {nombre}'
    if boleto:
        return f'#{boleto}'
    if nombre:
        return nombre
    if vendedor:
        return vendedor
    if sector:
        return sector
    return '-'


def _vmix_figuras_estado_2col_root(fecha: str | None = None):
    fecha = str(fecha or _get_sorteo_fecha() or date.today().isoformat()).strip()
    resultados = _cargar_resultados(fecha) or {'items': []}
    items = list(resultados.get('items') or [])

    root = ET.Element('figuras_estado_2col', {
        'fecha': fecha,
        'total': str(len(items)),
        'orden': 'filas',
    })

    for idx, item in enumerate(items, start=1):
        nombre_raw = str(item.get('figura') or item.get('nombre') or '').strip()
        if not nombre_raw:
            continue

        figura = _panel_name_display(nombre_raw)
        ganadores = list(item.get('ganadores') or [])
        if ganadores:
            valores = []
            for g in ganadores:
                t = _winner_ticket_text_for_vmix(g)
                if t and t != '-':
                    valores.append(t)
            resultado = ' / '.join(valores) if valores else '-'
        else:
            resultado = '-'

        fila = ET.SubElement(root, 'fila')
        ET.SubElement(fila, 'figura').text = figura
        ET.SubElement(fila, 'resultado').text = resultado

    return root


def _vmix_figuras_estado_root(fecha: str | None = None):
    fecha = str(fecha or _get_sorteo_fecha() or date.today().isoformat()).strip()
    resultados = _cargar_resultados(fecha) or {'items': []}
    items = list(resultados.get('items') or [])

    root = ET.Element('figuras_estado', {
        'fecha': fecha,
        'total': str(len(items)),
        'orden': 'filas',
    })

    for idx, item in enumerate(items, start=1):
        nombre_raw = str(item.get('figura') or item.get('nombre') or '').strip()
        if not nombre_raw:
            continue
        figura = _panel_name_display(nombre_raw)
        ganadores = list(item.get('ganadores') or [])
        ganador_nombres = []
        for g in ganadores:
            nom = _winner_name_for_vmix(g)
            if nom != '-':
                ganador_nombres.append(nom)
        ganador_txt = ' / '.join(ganador_nombres) if ganador_nombres else '-'
        jugada = '1' if ganadores else '0'
        estado = 'JUGADA' if ganadores else 'PENDIENTE'
        texto = f'{figura} -' if not ganadores else f'{figura} {ganador_txt}'
        premio = '0'
        try:
            if ganadores:
                premio = _fmt_int(ganadores[0].get('premio') or 0)
        except Exception:
            premio = '0'

        fila = ET.SubElement(root, 'fila')
        ET.SubElement(fila, 'orden').text = str(idx)
        ET.SubElement(fila, 'figura').text = figura
        ET.SubElement(fila, 'figura_raw').text = nombre_raw
        ET.SubElement(fila, 'estado').text = estado
        ET.SubElement(fila, 'jugada').text = jugada
        ET.SubElement(fila, 'ganador').text = ganador_txt
        ET.SubElement(fila, 'texto').text = texto
        ET.SubElement(fila, 'cantidad_ganadores').text = str(len(ganadores))
        ET.SubElement(fila, 'premio').text = premio
        ET.SubElement(fila, 'premio_fmt').text = _vmix_money_fmt(premio)

    return root


@juego_bp.get('/xml/total_jugar')
def juego_xml_total_jugar():
    fecha = (request.args.get('fecha') or _get_sorteo_fecha()).strip()
    root = _vmix_total_jugar_root(fecha)
    try:
        _write_xml_both(ET.ElementTree(root), VMIX_TOTAL_JUGAR_REL)
    except Exception:
        pass
    return _vmix_xml_response(root)


@juego_bp.get('/xml/figuras_estado')
def juego_xml_figuras_estado():
    fecha = (request.args.get('fecha') or _get_sorteo_fecha()).strip()
    root = _vmix_figuras_estado_root(fecha)
    try:
        _write_xml_both(ET.ElementTree(root), VMIX_FIGURAS_ESTADO_REL)
    except Exception:
        pass
    return _vmix_xml_response(root)


@juego_bp.get('/xml/figuras_estado_2col')
def juego_xml_figuras_estado_2col():
    fecha = (request.args.get('fecha') or _get_sorteo_fecha()).strip()
    root = _vmix_figuras_estado_2col_root(fecha)
    try:
        _write_xml_both(ET.ElementTree(root), VMIX_FIGURAS_ESTADO_2COL_REL)
    except Exception:
        pass
    return _vmix_xml_response(root)


# ================== FIN JUEGO ==================

# inicio spinners #



# ===================== SPINNERS API + OVERLAY =====================

# ===========================
# ==== [ SPINNERS + VMIX OVERLAY ] ============================================
import os, xml.etree.ElementTree as ET
from datetime import datetime
from flask import request, jsonify, render_template

# ---------- Config ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA"))
DB_DIR = os.path.join(DATA_DIR, "static", "db")
os.makedirs(DB_DIR, exist_ok=True)

VMIX_SPINNERS_XML = os.path.join(DB_DIR, "vmix_spinners.xml")
SPINNERS_XML      = os.path.join(DB_DIR, "spinners.xml")

# Cambia esto si tu vMix API está en otra IP/puerto:
# Ej: "http://127.0.0.1:8088/api"
VMIX_API_URL = os.getenv("VMIX_API_URL", "").strip()  # vacío = desactivado
VMIX_OVERLAY_INDEX = int(os.getenv("VMIX_OVERLAY_INDEX", "1"))  # Overlay 1 por defecto

# ---------- Utilidades XML ----------
def _ensure_xml_files():
    """Crea plantillas XML si no existen."""
    if not os.path.exists(SPINNERS_XML):
        root = ET.Element("spinners")
        # 20 slots inicialmente vacíos (0000) y unlocked
        for i in range(1, 21):
            ET.SubElement(root, "spinner", index=str(i), value="0000", locked="0", used="0")
        ET.indent(root, space="  ")
        ET.ElementTree(root).write(SPINNERS_XML, encoding="utf-8", xml_declaration=True)

    if not os.path.exists(VMIX_SPINNERS_XML):
        root = ET.Element("vmix")
        overlay = ET.SubElement(root, "overlay", index=str(VMIX_OVERLAY_INDEX), state="off")
        # espejo de los 20
        group = ET.SubElement(root, "spinners")
        for i in range(1, 21):
            ET.SubElement(group, "spinner", index=str(i), value="0000", locked="0", used="0")
        ET.indent(root, space="  ")
        ET.ElementTree(root).write(VMIX_SPINNERS_XML, encoding="utf-8", xml_declaration=True)

def _read_spinners():
    _ensure_xml_files()
    tree = ET.parse(SPINNERS_XML); root = tree.getroot()
    data = []
    for node in root.findall("spinner"):
        data.append({
            "index": int(node.get("index", "0")),
            "value": node.get("value", "0000"),
            "locked": node.get("locked", "0") == "1",
            "used": node.get("used", "0") == "1",
        })
    return data

def _write_spinners(spinners):
    root = ET.Element("spinners")
    for s in spinners:
        ET.SubElement(root, "spinner",
                      index=str(s["index"]),
                      value=str(s["value"]).zfill(4)[:4],
                      locked="1" if s.get("locked") else "0",
                      used="1" if s.get("used") else "0")
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(SPINNERS_XML, encoding="utf-8", xml_declaration=True)

def _read_vmix():
    _ensure_xml_files()
    t = ET.parse(VMIX_SPINNERS_XML); r = t.getroot()
    return t, r

def _mirror_to_vmix(spinners, overlay_state=None):
    """Espeja lista de spinners a vmix_spinners.xml y opcionalmente cambia overlay on/off."""
    t, r = _read_vmix()
    # overlay
    overlay = r.find("overlay")
    if overlay is None:
        overlay = ET.SubElement(r, "overlay", index=str(VMIX_OVERLAY_INDEX), state="off")
    if overlay_state in ("on", "off"):
        overlay.set("state", overlay_state)

    # grupo
    group = r.find("spinners")
    if group is None:
        group = ET.SubElement(r, "spinners")
    # limpia
    for child in list(group):
        group.remove(child)
    # reescribe
    for s in spinners:
        ET.SubElement(group, "spinner",
                      index=str(s["index"]),
                      value=str(s["value"]).zfill(4)[:4],
                      locked="1" if s.get("locked") else "0",
                      used="1" if s.get("used") else "0")
    ET.indent(r, space="  ")
    t.write(VMIX_SPINNERS_XML, encoding="utf-8", xml_declaration=True)

# ---------- vMix API (opcional) ----------
def _vmix_call_api(function_name, **params):
    """
    Llama al API HTTP de vMix si VMIX_API_URL está definido.
    Ej: _vmix_call("OverlayInput1On")
    """
    if not VMIX_API_URL:
        return {"ok": False, "msg": "VMIX_API_URL no configurado"}
    try:
        import requests
        # Construye query tipo: ?Function=OverlayInput1On
        q = {"Function": function_name}
        # anexa params si aplica
        for k, v in params.items():
            q[k] = v
        resp = requests.get(VMIX_API_URL, params=q, timeout=3)
        return {"ok": resp.ok, "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

# ---------- Rutas JSON ----------
@app.get("/juego/spinners")
def get_spinners():
    """
    Devuelve los 20 spinners: index, value (0000-9999), locked, used
    """
    data = sorted(_read_spinners(), key=lambda x: x["index"])
    return jsonify(data)

@app.post("/juego/spinners/generar")
def post_spinner_generar():
    """
    Pone el visor del spinner (index) en 0000, no toca 'value' si ya existía
    pero deja 'used=0' y 'locked=0' si quieres relanzar.
    Body: {index:int}
    """
    payload = request.get_json(force=True, silent=True) or {}
    index = int(payload.get("index", 1))
    sp = _read_spinners()
    found = None
    for s in sp:
        if s["index"] == index:
            found = s; break
    if not found:
        return jsonify({"ok": False, "msg": "index inválido"}), 400

    # GENERAR → reset visual, desbloqueado y sin usado
    found["value"] = "0000"
    found["used"] = False
    found["locked"] = False
    _write_spinners(sp)
    _mirror_to_vmix(sp)   # espejo

    return jsonify({"ok": True, "index": index, "value": found["value"]})

@app.post("/juego/spinners/lanzar")
def post_spinner_lanzar():
    """
    Lanza el spinner al valor objetivo, marca used=1, locked=1 y enciende Overlay 1 (opcional).
    Body: {index:int, target:str|int, overlay_on:bool}
    """
    payload = request.get_json(force=True, silent=True) or {}
    index = int(payload.get("index", 1))
    raw_target = payload.get("target", "")
    target = _sp_hotfix_norm4(raw_target) if "_sp_hotfix_norm4" in globals() else str(raw_target).zfill(4)[:4]
    if not target or target == "0000":
        try:
            _rows = _sp_hotfix_read_rows() if "_sp_hotfix_read_rows" in globals() else []
            _found_cfg = next((r for r in _rows if int(r.get("index", 0)) == index), None)
            _cfg_target = str((_found_cfg or {}).get("value") or "")
            if _cfg_target and _cfg_target != "0000":
                target = _cfg_target
        except Exception:
            pass
    if not target:
        target = "0000"
    overlay_on = bool(payload.get("overlay_on", True))

    sp = _read_spinners()
    found = None
    for s in sp:
        if s["index"] == index:
            found = s; break
    if not found:
        return jsonify({"ok": False, "msg": "index inválido"}), 400
    if found.get("locked"):
        return jsonify({"ok": False, "msg": "Este spinner está bloqueado"}), 403

    # asigna valor, usa y bloquea
    found["value"] = target
    found["used"] = True
    found["locked"] = True
    _write_spinners(sp)

    # overlay ON (XML) y (opcional) API vMix
    _mirror_to_vmix(sp, overlay_state="on" if overlay_on else None)
    vmix_api = None
    if overlay_on:
        # Ej.: OverlayInput1On, OverlayInput1Off  (vMix es 1-indexed)
        vmix_api = _vmix_call_api(f"OverlayInput{VMIX_OVERLAY_INDEX}On")

    return jsonify({"ok": True, "index": index, "value": target, "vmix_api": vmix_api})

@app.post("/juego/spinners/unlock")
def post_spinner_unlock():
    """
    Desbloquea un spinner (o todos). Body: {index:int} o {all:true}
    """
    payload = request.get_json(force=True, silent=True) or {}
    all_flag = bool(payload.get("all"))
    sp = _read_spinners()

    if all_flag:
        for s in sp:
            s["locked"] = False
        _write_spinners(sp); _mirror_to_vmix(sp)
        return jsonify({"ok": True, "msg": "Todos desbloqueados"})

    index = int(payload.get("index", 1))
    for s in sp:
        if s["index"] == index:
            s["locked"] = False
            _write_spinners(sp); _mirror_to_vmix(sp)
            return jsonify({"ok": True, "index": index, "locked": False})
    return jsonify({"ok": False, "msg": "index inválido"}), 400

@app.post("/juego/spinners/lock")
def post_spinner_lock():
    """
    Bloquea un spinner (o todos). Body: {index:int} o {all:true}
    """
    payload = request.get_json(force=True, silent=True) or {}
    all_flag = bool(payload.get("all"))
    sp = _read_spinners()

    if all_flag:
        for s in sp:
            s["locked"] = True
        _write_spinners(sp); _mirror_to_vmix(sp)
        return jsonify({"ok": True, "msg": "Todos bloqueados"})

    index = int(payload.get("index", 1))
    for s in sp:
        if s["index"] == index:
            s["locked"] = True
            _write_spinners(sp); _mirror_to_vmix(sp)
            return jsonify({"ok": True, "index": index, "locked": True})
    return jsonify({"ok": False, "msg": "index inválido"}), 400

@app.post("/juego/spinners/reset_used")
def post_spinner_reset_used():
    """
    Resetea 'used' de todos a 0 (útil al preparar un nuevo sorteo).
    """
    sp = _read_spinners()
    for s in sp:
        s["used"] = False
        s["locked"] = False
        s["value"] = "0000"
    _write_spinners(sp)
    _mirror_to_vmix(sp, overlay_state="off")
    return jsonify({"ok": True})

# ---------- Rutas Overlay (HTML) ----------
@app.get("/juego/spinner_overlay")
def spinner_overlay_page():
    """
    Overlay transparente para vMix (usa tu spinner_overlay.html)
    """
    # Si usas render_template con archivo físico:
    return render_template("spinner_overlay.html")

# (Opcional) API rápida para apagar overlay vía backend + vMix API
@app.post("/vmix/overlay/off")
def vmix_overlay_off():
    sp = _read_spinners()
    _mirror_to_vmix(sp, overlay_state="off")
    vmix_api = _vmix_call_api(f"OverlayInput{VMIX_OVERLAY_INDEX}Off")
    return jsonify({"ok": True, "vmix_api": vmix_api})
# ==== [ FIN SPINNERS ] ========================================================






#--------FIN DE SPINNERS------------##





# ============================================================
# HOTFIX GLBINGO: resolver rutas de DB/LOGS + guardar figuras del día
# (Evita que "Figuras del día" salga vacío por estar leyendo/escribiendo
#  en carpetas distintas: static/db vs DATA/static/db, etc.)
# ============================================================
import os as _os
import json as _json
import datetime as _dt
import xml.etree.ElementTree as _ET

def _uniq(seq):
    seen=set()
    out=[]
    for x in seq:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def _candidate_db_dirs_hotfix():
    base = _os.path.dirname(_os.path.abspath(__file__))
    parent = _os.path.dirname(base)
    env_data = _os.environ.get("DATA_DIR", "").strip()

    candidates = []
    # 1) DATA_DIR (Render / disco persistente)
    if env_data:
        candidates += [
            _os.path.join(env_data, "static", "db"),
            _os.path.join(env_data, "db"),
        ]
    # 2) Carpeta DATA dentro del proyecto
    candidates += [
        _os.path.join(base, "DATA", "static", "db"),
        _os.path.join(base, "static", "db"),
        # por si estás ejecutando desde otra copia/carpeta
        _os.path.join(parent, "DATA", "static", "db"),
        _os.path.join(parent, "static", "db"),
    ]
    # 3) Algunos nombres comunes (si existen)
    for name in ["GOLPEDESUERTE.EC", "SISTEMA GOLPE", "SISTEMA_GOLPE"]:
        candidates += [
            _os.path.join(parent, name, "DATA", "static", "db"),
            _os.path.join(parent, name, "static", "db"),
        ]

    candidates = _uniq([c for c in candidates if _os.path.isdir(c)])

    # Escoge el "mejor" directorio por contenido real
    def score(d):
        s = 0.0
        def add_file(fname, weight, min_sz):
            p = _os.path.join(d, fname)
            if _os.path.exists(p):
                try:
                    sz = _os.path.getsize(p)
                except Exception:
                    sz = 0
                s_local = weight if sz >= min_sz else weight * 0.2
                return s_local
            return 0.0

        s += add_file("datos_figuras.xml", 6, 500)
        s += add_file("figuras_por_fecha.xml", 5, 80)
        s += add_file("datos_bingo.xml", 3, 80)
        s += add_file("historial.json", 2, 10)
        # bonus por cantidad de XML
        try:
            s += len([f for f in _os.listdir(d) if f.lower().endswith(".xml")]) * 0.01
        except Exception:
            pass
        return s

    if not candidates:
        # fallback
        return [ _os.path.join(base, "static", "db") ]
    best = max(candidates, key=score)
    # prioridad: best primero, luego el resto
    ordered = [best] + [c for c in candidates if c != best]
    return ordered

def _pick_best_db_dir_hotfix():
    return _candidate_db_dirs_hotfix()[0]

def _candidate_logs_dirs_hotfix():
    base = _os.path.dirname(_os.path.abspath(__file__))
    parent = _os.path.dirname(base)
    env_data = _os.environ.get("DATA_DIR", "").strip()

    candidates = []
    if env_data:
        candidates += [
            _os.path.join(env_data, "static", "LOGS"),
            _os.path.join(env_data, "LOGS"),
        ]
    candidates += [
        _os.path.join(base, "DATA", "static", "LOGS"),
        _os.path.join(base, "static", "LOGS"),
        _os.path.join(parent, "DATA", "static", "LOGS"),
        _os.path.join(parent, "static", "LOGS"),
    ]
    candidates = _uniq([c for c in candidates if _os.path.isdir(c)])
    if not candidates:
        # crea al menos la local
        local = _os.path.join(base, "static", "LOGS")
        _os.makedirs(local, exist_ok=True)
        candidates = [local]
    return candidates

def _agenda_paths_hotfix():
    # Devuelve TODAS las rutas posibles de figuras_por_fecha.xml (mejor primero)
    paths=[]
    for d in _candidate_db_dirs_hotfix():
        paths.append(_os.path.join(d, "figuras_por_fecha.xml"))
    return _uniq(paths)

def _datos_figuras_paths_hotfix():
    paths=[]
    for d in _candidate_db_dirs_hotfix():
        paths.append(_os.path.join(d, "datos_figuras.xml"))
    return _uniq(paths)

def _impresiones_paths_hotfix():
    # admite LOGS y también db (por si alguien lo guardó allí)
    paths=[]
    for d in _candidate_logs_dirs_hotfix():
        paths.append(_os.path.join(d, "impresiones.xml"))
    for d in _candidate_db_dirs_hotfix():
        paths.append(_os.path.join(d, "impresiones.xml"))
    return _uniq(paths)

def _parse_fecha_flexible(fecha_str):
    if not fecha_str:
        raise ValueError("fecha vacía")
    s = str(fecha_str).strip()
    # yyyy-mm-dd
    try:
        return _dt.datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        pass
    # dd/mm/yyyy
    try:
        return _dt.datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        pass
    # dd-mm-yyyy
    try:
        return _dt.datetime.strptime(s, "%d-%m-%Y").date()
    except Exception:
        pass
    raise ValueError(f"Formato de fecha no válido: {s}")

def _ensure_agenda_file(path):
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    if _os.path.exists(path):
        # si está corrupto, lo re-crea
        try:
            _ET.parse(path)
            return
        except Exception:
            pass
    root = _ET.Element("agenda")
    _ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

def _write_agenda_for_fecha(path, fecha_iso, figuras):
    """
    figuras: lista de dicts {nombre, valor, estado}
    """
    _ensure_agenda_file(path)
    tree = _ET.parse(path)
    root = tree.getroot()

    # Busca/crea nodo del día
    dia = None
    for d in root.findall("dia"):
        if (d.get("fecha") or "").strip() == fecha_iso:
            dia = d
            break
    if dia is None:
        dia = _ET.SubElement(root, "dia")
        dia.set("fecha", fecha_iso)

    # limpia y vuelve a escribir
    for child in list(dia):
        dia.remove(child)

    for it in figuras:
        nombre = str(it.get("nombre","")).strip()
        if not nombre:
            continue
        fig = _ET.SubElement(dia, "fig")
        fig.set("nombre", nombre)
        fig.set("valor", str(it.get("valor","")).strip())
        fig.set("estado", str(it.get("estado","en_juego")).strip() or "en_juego")

    tree.write(path, encoding="utf-8", xml_declaration=True)

def _debug_print_paths_hotfix():
    try:
        best_db = _pick_best_db_dir_hotfix()
        print("\n[GLBINGO HOTFIX] DB_DIR elegido:", best_db)
        print("[GLBINGO HOTFIX] Agenda candidates:")
        for p in _agenda_paths_hotfix():
            print(" -", p, "(existe)" if _os.path.exists(p) else "")
        print("[GLBINGO HOTFIX] Datos figuras candidates:")
        for p in _datos_figuras_paths_hotfix():
            print(" -", p, "(existe)" if _os.path.exists(p) else "")
        print("[GLBINGO HOTFIX] Impresiones candidates:")
        for p in _impresiones_paths_hotfix():
            print(" -", p, "(existe)" if _os.path.exists(p) else "")
        print("")
    except Exception as e:
        print("[GLBINGO HOTFIX] No se pudo imprimir rutas:", e)

# 1) Sobrescribimos helpers usados por el módulo de juego (si existen)
globals()["_agenda_paths"] = _agenda_paths_hotfix
globals()["_impresiones_paths"] = _impresiones_paths_hotfix

# 2) Forzamos variables globales típicas (si existen) a apuntar al mejor DB_DIR
try:
    _best_db = _pick_best_db_dir_hotfix()
    for _var, _fname in [
        ("DB_DIR", None),
        ("BINGO_XML", "datos_bingo.xml"),
        ("HIST_JSON", "historial.json"),
        ("GANADORES_XML", "ganadores_bingo.xml"),
        ("DATOS_FIGURAS_XML", "datos_figuras.xml"),
        ("FIGURAS_FECHA_XML", "figuras_por_fecha.xml"),
    ]:
        if _var in globals():
            globals()[_var] = _best_db if _fname is None else _os.path.join(_best_db, _fname)
except Exception:
    pass

# 3) PARCHAMOS la vista /escoger-figuras/guardar para guardar en TODAS las rutas candidatas
def _guardar_figuras_para_fecha_hotfix():
    from flask import request, redirect, url_for, flash
    # Acepta tanto form como JSON (por si mañana se cambia el front)
    fecha_raw = (request.form.get("fecha") or request.args.get("fecha") or
                 (request.json.get("fecha") if request.is_json else None))
    try:
        fecha = _parse_fecha_flexible(fecha_raw)
    except Exception as e:
        flash(f"Fecha inválida: {e}", "danger")
        return redirect(url_for("escoger_figuras"))

    seleccion_raw = (request.form.get("seleccion") or
                     (request.json.get("seleccion") if request.is_json else None))

    if not seleccion_raw:
        flash("No se recibió selección de figuras.", "danger")
        return redirect(url_for("escoger_figuras_view", fecha=fecha.isoformat()) if "escoger_figuras_view" in app.view_functions else url_for("escoger_figuras"))

    try:
        figuras = _json.loads(seleccion_raw)
        if not isinstance(figuras, list):
            raise ValueError("seleccion no es lista")
    except Exception as e:
        flash(f"Selección inválida: {e}", "danger")
        return redirect(url_for("escoger_figuras_view", fecha=fecha.isoformat()) if "escoger_figuras_view" in app.view_functions else url_for("escoger_figuras"))

    # Normaliza
    norm=[]
    for it in figuras:
        if not isinstance(it, dict):
            continue
        nombre = str(it.get("nombre","")).strip()
        if not nombre:
            continue
        norm.append({
            "nombre": nombre,
            "valor": str(it.get("valor","")).strip(),
            "estado": str(it.get("estado","en_juego")).strip() or "en_juego"
        })

    # Escribe en todas las rutas candidatas
    ok=0
    for path in _agenda_paths_hotfix():
        try:
            _write_agenda_for_fecha(path, fecha.isoformat(), norm)
            ok += 1
        except Exception as e:
            print("[GLBINGO HOTFIX] Error guardando agenda en", path, "->", e)

    if ok > 0:
        flash(f"Figuras del día guardadas en {ok} ruta(s).", "success")
    else:
        flash("No se pudo guardar la agenda de figuras (revisa permisos/carpetas).", "danger")

    # vuelve a la vista de escoger para esa fecha
    if "escoger_figuras_view" in app.view_functions:
        return redirect(url_for("escoger_figuras_view", fecha=fecha.isoformat()))
    return redirect(url_for("escoger_figuras"))

try:
    if "escoger_figuras_guardar" in app.view_functions:
        app.view_functions["escoger_figuras_guardar"] = _guardar_figuras_para_fecha_hotfix
    # Compatibilidad extra por si en otra versión el endpoint cambió de nombre
    if "guardar_figuras_para_fecha" in app.view_functions:
        app.view_functions["guardar_figuras_para_fecha"] = _guardar_figuras_para_fecha_hotfix
except Exception as e:
    print("[GLBINGO HOTFIX] No se pudo parchear escoger_figuras_guardar:", e)

# 4) imprime rutas en consola al iniciar
try:
    _debug_print_paths_hotfix()
except Exception:
    pass

# ============================================================
# FIN HOTFIX
# ============================================================



# ============================
# HOTFIX FINAL — Sincronización de rutas + APIs Juego (consulta/corrección)
# ============================
try:
    import copy as _copy_mod
except Exception:
    _copy_mod = None

# ---- Rutas canónicas/mirror para logs y db (evita desincronización static/ vs DATA/ vs instance/) ----
def _hf_abs(*parts):
    try:
        return os.path.abspath(os.path.join(*parts))
    except Exception:
        return os.path.join(*parts)

def _hf_all_logs_candidates():
    cands = []
    try:
        cands.append(_hf_abs(BASE_DIR, "instance", "gl_bingo", "logs", "impresiones.xml"))
    except Exception:
        pass
    try:
        cands.append(_hf_abs(BASE_DIR, "DATA", "static", "LOGS", "impresiones.xml"))
    except Exception:
        pass
    try:
        cands.append(_hf_abs(BASE_DIR, "static", "LOGS", "impresiones.xml"))
    except Exception:
        pass
    try:
        cands.append(_hf_abs(BASE_DIR, "static", "db", "impresiones.xml"))
    except Exception:
        pass
    out = []
    seen = set()
    for p in cands:
        if not p:
            continue
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        out.append(ap)
    return out

def _hf_pick_newest_file(paths):
    best = None
    best_m = -1.0
    for p in paths:
        try:
            if os.path.exists(p):
                m = os.path.getmtime(p)
                if m >= best_m:
                    best_m = m
                    best = p
        except Exception:
            pass
    return best

def _hf_copy_file(src_path, dst_path):
    try:
        if not src_path or not dst_path:
            return False
        if os.path.abspath(src_path) == os.path.abspath(dst_path):
            return True
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        import shutil as _sh
        _sh.copy2(src_path, dst_path)
        return True
    except Exception:
        return False

def _hf_sync_logs_startup():
    try:
        canon = _persist("static", "LOGS", "impresiones.xml")
        globals()["LOGS_IMPRESIONES_XML"] = canon
        globals()["IMPRESIONES_XML"] = canon
        globals()["IMP_XML_PATH"] = canon
        globals()["LOGS_DIR"] = os.path.dirname(canon)

        _ensure_logs_file()

        import shutil
        mirrors = [
            os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "logs", "impresiones.xml"),
            os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "static", "db", "impresiones.xml"),
            os.path.join(globals().get("DATA_DIR", os.path.join(BASE_DIR, "DATA")), "DB", "impresiones.xml"),
        ]

        for p in mirrors:
            try:
                if os.path.abspath(p) == os.path.abspath(canon):
                    continue
                os.makedirs(os.path.dirname(p), exist_ok=True)
                shutil.copy2(canon, p)
            except Exception:
                pass
    except Exception as _e:
        print("[HOTFIX LOGS] sync startup:", _e)

_hf_sync_logs_startup()


def _hf_db_file_candidates(path):
    try:
        bn = os.path.basename(path or "")
    except Exception:
        bn = ""
    if not bn:
        return []
    c = []
    try:
        c.append(_hf_abs(BASE_DIR, "DATA", "static", "db", bn))
    except Exception:
        pass
    try:
        c.append(_hf_abs(BASE_DIR, "static", "db", bn))
    except Exception:
        pass
    if bn == "impresiones.xml":
        c.extend(_hf_all_logs_candidates())
    out=[]; seen=set()
    for p in c:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap); out.append(ap)
    return out

try:
    _orig_json_write = _json_write
    def _json_write(path, obj):
        res = _orig_json_write(path, obj)
        try:
            cands = _hf_db_file_candidates(path)
            srcp = path if (path and os.path.exists(path)) else _hf_pick_newest_file(cands)
            if srcp:
                for p in cands:
                    _hf_copy_file(srcp, p)
        except Exception:
            pass
        return res
except Exception as _e:
    print("[HOTFIX DB] wrap _json_write:", _e)

CORRECCIONES_BOLETOS_JSON = _hf_abs(BASE_DIR, "DATA", "static", "db", "correcciones_boletos.json")

try:
    _CORR_JSON_CACHE  # noqa
except NameError:
    _CORR_JSON_CACHE = {"path": "", "mtime": None, "data": {}}
    _CORR_JSON_LOCK = RLock()
    _CORR_VERSION = 0
    _CARTONES_CORR_CACHE = {}
    _CARTONES_CORR_LOCK = RLock()

def _corr_paths():
    return _hf_db_file_candidates(CORRECCIONES_BOLETOS_JSON) or [CORRECCIONES_BOLETOS_JSON]

def _corr_cache_bump():
    global _CORR_VERSION
    try:
        with _CORR_JSON_LOCK:
            _CORR_VERSION += 1
            _CORR_JSON_CACHE["mtime"] = None
    except Exception:
        pass
    try:
        with _CARTONES_CORR_LOCK:
            _CARTONES_CORR_CACHE.clear()
    except Exception:
        pass

def _read_correcciones():
    srcp = _hf_pick_newest_file(_corr_paths())
    if not srcp:
        return {}
    try:
        mtime = os.path.getmtime(srcp)
    except Exception:
        mtime = None
    try:
        with _CORR_JSON_LOCK:
            if _CORR_JSON_CACHE.get("path") == srcp and _CORR_JSON_CACHE.get("mtime") == mtime:
                data = _CORR_JSON_CACHE.get("data") or {}
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    try:
        data = _safe_json_read(srcp) or {}
        data = data if isinstance(data, dict) else {}
        try:
            with _CORR_JSON_LOCK:
                _CORR_JSON_CACHE.update({"path": srcp, "mtime": mtime, "data": data})
        except Exception:
            pass
        return data
    except Exception:
        return {}

def _write_correcciones(data):
    try:
        cands = _corr_paths()
        can = cands[0]
        payload = data if isinstance(data, dict) else {}
        _safe_json_write(can, payload)
        srcp = _hf_pick_newest_file(cands) or can
        for p in cands:
            _hf_copy_file(srcp, p)
        try:
            with _CORR_JSON_LOCK:
                _CORR_JSON_CACHE.update({
                    "path": srcp,
                    "mtime": (os.path.getmtime(srcp) if os.path.exists(srcp) else None),
                    "data": payload,
                })
        except Exception:
            pass
        _corr_cache_bump()
    except Exception:
        pass

def _corr_get(fecha, serie_archivo, carton_id):
    data = _read_correcciones()
    return (((data.get(str(fecha), {}) or {}).get(str(serie_archivo), {}) or {}).get(str(carton_id), {}) or {})

def _corr_set(fecha, serie_archivo, carton_id, payload):
    data = _read_correcciones()
    fs = data.setdefault(str(fecha), {})
    ss = fs.setdefault(str(serie_archivo), {})
    ss[str(carton_id)] = payload
    _write_correcciones(data)


def _corr_clear_fecha(fecha):
    """Limpia todas las correcciones de boletos de una fecha completa."""
    try:
        key = str(fecha or "").strip()
        if not key:
            return False
        data = _read_correcciones()
        if not isinstance(data, dict):
            data = {}
        if key in data:
            data.pop(key, None)
            _write_correcciones(data)
        else:
            _corr_cache_bump()
        return True
    except Exception:
        return False


def _reset_vmix_carton_state_for_fecha(fecha_iso):
    """Reinicia el índice/puntero del XML de cartón ganador para una fecha."""
    try:
        state = _vmix_carton_state_read() or {}
        if not isinstance(state, dict):
            state = {}
        by_fecha = state.get("por_fecha") if isinstance(state.get("por_fecha"), dict) else {}
        by_fecha.pop(str(fecha_iso), None)
        state["por_fecha"] = by_fecha
        if str(state.get("fecha") or "") == str(fecha_iso):
            state["fecha"] = str(fecha_iso)
            state["actual"] = 0
            state["total"] = 0
        _vmix_carton_state_write(state)
        return True
    except Exception:
        return False

def _corr_norm_grid5(grid):
    if not isinstance(grid, list) or len(grid) != 5:
        raise ValueError("grid debe tener 5 filas")
    out = []
    for r in range(5):
        row = grid[r]
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError("grid debe ser 5x5")
        o = []
        for c in range(5):
            v = row[c]
            s = "" if v is None else str(v).strip()
            if r == 2 and c == 2:
                if not s or s.upper() in ("0","F","FREE","LIBRE","QR","X"):
                    s = "F"
            if s and (not s.isdigit()) and s.upper() != "F":
                raise ValueError("Solo números o F en la cuadrícula")
            o.append(s)
        out.append(o)
    return out

def _corr_apply_to_grid(grid2d, pos_map, corr_payload):
    if not corr_payload:
        return grid2d, pos_map
    g = corr_payload.get("grid")
    if not (isinstance(g, list) and len(g) == 5):
        return grid2d, pos_map
    try:
        g = _corr_norm_grid5(g)
    except Exception:
        return grid2d, pos_map
    cols = ["B","I","N","G","O"]
    pm = {}
    for r in range(5):
        for c in range(5):
            pm[f"{cols[c]}{r+1}"] = g[r][c]
    return g, pm

def _ticket_nums_from_grid(grid2d):
    nums = set()
    try:
        for row in (grid2d or []):
            for v in (row or []):
                s = "" if v is None else str(v).strip()
                if s.isdigit():
                    nums.add(int(s))
    except Exception:
        pass
    return nums

try:
    _orig_get_cartones_index_cached = _get_cartones_index_cached
    def _get_cartones_index_cached(*args, **kwargs):
        """
        Wrapper de correcciones de boletos SIN romper la firma original.
        Soporta tanto la versión optimizada (6 args) como una versión simple (2 args).
        Ahora reutiliza caché corregida para no reconstruir todos los cartones en cada consulta/recálculo.
        """
        tickets, by_num = _orig_get_cartones_index_cached(*args, **kwargs)

        fecha_iso = kwargs.get("fecha_iso") if isinstance(kwargs, dict) else None
        serie_archivo = kwargs.get("serie_archivo") if isinstance(kwargs, dict) else None
        merged = kwargs.get("merged") if isinstance(kwargs, dict) else None
        mtime = kwargs.get("mtime") if isinstance(kwargs, dict) else None
        if fecha_iso is None and len(args) >= 1:
            fecha_iso = args[0]
        if serie_archivo is None and len(args) >= 2:
            serie_archivo = args[1]
        if merged is None and len(args) >= 3:
            merged = args[2]
        if mtime is None and len(args) >= 6:
            mtime = args[5]

        try:
            corr_all = ((_read_correcciones().get(str(fecha_iso), {}) or {}).get(str(serie_archivo), {}) or {})
            if not corr_all:
                return tickets, by_num

            merged_sig = tuple((int(s), int(e)) for s, e in (merged or [])) if merged is not None else ()
            corr_key = (str(fecha_iso), str(serie_archivo), merged_sig, float(mtime or 0.0), int(_CORR_VERSION))
            try:
                with _CARTONES_CORR_LOCK:
                    cc = _CARTONES_CORR_CACHE.get(corr_key)
                    if cc:
                        return cc["tickets"], cc["by_num"]
            except Exception:
                pass

            new_tickets = []
            new_by = {}
            for idx, t in enumerate(tickets or []):
                tc = dict(t)
                cid = str(tc.get("carton_id", "")).strip()
                corr = corr_all.get(cid) or {}
                if corr:
                    base_grid = tc.get("grid") or []
                    base_pos = tc.get("pos_map") or {}
                    g2, pm = _corr_apply_to_grid(base_grid, base_pos, corr)
                    tc["grid"] = g2
                    tc["pos_map"] = pm
                    tc["nums"] = _ticket_nums_from_grid(g2)
                    tc["__corregido__"] = True
                new_tickets.append(tc)
                for n in (tc.get("nums") or set()):
                    try:
                        nn = int(n)
                    except Exception:
                        continue
                    new_by.setdefault(nn, []).append(idx)

            try:
                with _CARTONES_CORR_LOCK:
                    _CARTONES_CORR_CACHE[corr_key] = {"tickets": new_tickets, "by_num": new_by}
                    if len(_CARTONES_CORR_CACHE) > 20:
                        _CARTONES_CORR_CACHE.clear()
            except Exception:
                pass

            return new_tickets, new_by
        except Exception as _corr_e:
            print("[HOTFIX CORR] error aplicando correcciones sobre cache de cartones:", _corr_e)
            return tickets, by_num
except Exception as _e:
    print("[HOTFIX CORR] wrap _get_cartones_index_cached:", _e)

def _juego_series_en_juego(fecha):
    out = []
    seen = set()
    try:
        for rg in (_get_rangos_en_juego(fecha) or []):
            s = str((rg or {}).get("serie_archivo") or "").strip()
            if s and s not in seen:
                seen.add(s); out.append(s)
    except Exception:
        pass
    for fn_name in ("_series_impresas_en_fecha", "series_impresas_en_fecha"):
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                vals = fn(fecha)
                if isinstance(vals, set):
                    vals = sorted([str(x) for x in vals if str(x).strip()])
                for s in (vals or []):
                    s = str(s).strip()
                    if s and s not in seen:
                        seen.add(s); out.append(s)
        except Exception:
            pass
    return out

def _ticket_en_rangos_impresos(fecha_iso, serie_archivo, carton_id) -> bool:
    """Valida que el boleto pertenezca realmente a los rangos impresos de ESA fecha."""
    cid = str(carton_id or "").strip()
    if not cid:
        return False
    try:
        cid_num = int(re.sub(r"\D", "", cid) or 0)
    except Exception:
        cid_num = None

    for rg in (_get_rangos_en_juego(str(fecha_iso)) or []):
        s = str((rg or {}).get("serie_archivo") or "").strip()
        if s and serie_archivo and not _serie_equal(s, serie_archivo):
            continue
        try:
            a = int(re.sub(r"\D", "", str((rg or {}).get("desde") or "")) or 0)
            b = int(re.sub(r"\D", "", str((rg or {}).get("hasta") or "")) or 0)
        except Exception:
            continue
        if cid_num is not None and a <= cid_num <= b:
            return True
    return False

def _rangos_merge_para_serie(fecha_iso, serie_archivo, total_ids):
    rangos = []
    for rg in (_get_rangos_en_juego(str(fecha_iso)) or []):
        s = str((rg or {}).get("serie_archivo") or "").strip()
        if s and serie_archivo and not _serie_equal(s, serie_archivo):
            continue
        try:
            a = int((rg or {}).get("desde") or 0)
            b = int((rg or {}).get("hasta") or 0)
        except Exception:
            continue
        if a <= 0 or b <= 0:
            continue
        # índices 0-based, fin exclusivo
        s0 = max(0, min(total_ids, a - 1))
        e0 = max(0, min(total_ids, b))
        if e0 <= s0:
            continue
        rangos.append((s0, e0))

    if not rangos:
        return []

    rangos.sort(key=lambda x: (x[0], x[1]))
    merged = []
    cs, ce = rangos[0]
    for s0, e0 in rangos[1:]:
        if s0 <= ce:
            ce = max(ce, e0)
        else:
            merged.append((cs, ce))
            cs, ce = s0, e0
    merged.append((cs, ce))
    return merged

def _juego_ticket_info(fecha, serie_archivo, carton_id):
    cid = str(carton_id).strip()
    if not cid:
        return None, "Cartón vacío"

    # MUY IMPORTANTE: solo permitimos consultar/corregir boletos impresos para esa fecha.
    if not _ticket_en_rangos_impresos(str(fecha), str(serie_archivo), cid):
        return None, "Ese boleto no pertenece a los boletos impresos de esa fecha"

    try:
        df, idcol, ids, id_to_idx, mtime = _get_series_meta_cached(serie_archivo)
    except Exception:
        df = _read_df_for_series(serie_archivo)
        if df is None or getattr(df, "empty", True):
            return None, "No se pudo leer la serie"
        try:
            idcol = str(df.columns[0])
        except Exception:
            return None, "Serie inválida"
        ids = df[idcol].astype(str).tolist()
        mtime = 0.0

    merged = _rangos_merge_para_serie(str(fecha), str(serie_archivo), len(ids))
    if not merged:
        return None, "No hay boletos impresos para esa fecha/serie"

    found = None
    try:
        tickets, _ = _get_cartones_index_cached(str(fecha), str(serie_archivo), merged, df, idcol, mtime)
        cache_key = (str(fecha), str(serie_archivo), tuple((int(s), int(e)) for s, e in merged), float(mtime))
        idx = None
        try:
            with _CARTONES_INDEX_LOCK:
                base_cache = _CARTONES_INDEX_CACHE.get(cache_key) or {}
                idx = (base_cache.get("by_id_exact") or {}).get(cid)
                if idx is None:
                    try:
                        idx = (base_cache.get("by_id_num") or {}).get(int(re.sub(r"\D", "", cid) or 0))
                    except Exception:
                        idx = None
        except Exception:
            idx = None
        if idx is not None and 0 <= idx < len(tickets or []):
            found = tickets[idx]
        else:
            for t in (tickets or []):
                tid = str(t.get("carton_id", "")).strip()
                if tid == cid:
                    found = t
                    break
                try:
                    if int(re.sub(r"\D", "", tid) or 0) == int(re.sub(r"\D", "", cid) or 0):
                        found = t
                        break
                except Exception:
                    pass
    except Exception:
        found = None

    if found is not None:
        grid = _copy_mod.deepcopy(found.get("grid") or []) if _copy_mod else [list(r) for r in (found.get("grid") or [])]
        pos_map = dict(found.get("pos_map") or {})
        corr = _corr_get(fecha, serie_archivo, cid)
        grid, pos_map = _corr_apply_to_grid(grid, pos_map, corr)
    else:
        # fallback ultra-seguro
        try:
            m = df[df[idcol].astype(str).str.strip() == cid]
        except Exception:
            m = None
        if m is None or m.empty:
            try:
                n = int(re.sub(r"\D", "", cid) or 0)
                m = df[pd.to_numeric(df[idcol], errors="coerce").fillna(-1).astype(int) == n]
            except Exception:
                pass
        if m is None or m.empty:
            return None, "Boleto no encontrado entre los impresos de esa fecha"
        row = m.iloc[0]
        row_lower = {str(c).strip().lower(): row[c] for c in df.columns}
        grid, pos_map = _build_grid_from_row(row_lower)
        corr = _corr_get(fecha, serie_archivo, cid)
        grid, pos_map = _corr_apply_to_grid(grid, pos_map, corr)

    stack = _read_stack() or []
    marked = set()
    for n in stack:
        try:
            marked.add(int(n))
        except Exception:
            pass

    marcadas_count = 0
    for r in range(5):
        for c in range(5):
            v = str(grid[r][c]).strip()
            if (r == 2 and c == 2) and (not v or v.upper() in ("0","F","FREE","LIBRE","QR","X")):
                marcadas_count += 1
                continue
            if v.isdigit() and int(v) in marked:
                marcadas_count += 1

    info_b = buscar_info_por_boleto(str(fecha), cid, str(serie_archivo)) or {}
    payload = {
        "ok": True,
        "fecha": str(fecha),
        "serie_archivo": str(serie_archivo),
        "serie": str((info_b.get("serie") or info_b.get("serie_archivo") or serie_archivo)),
        "tabla": cid,
        "boleto": cid,
        "carton_id": cid,
        "grid": grid,
        "vendedor": str(info_b.get("vendedor","") or "—"),
        "planilla": str(info_b.get("planilla","") or "—"),
        "rango": str(info_b.get("rango","") or "—"),
        "ultimo_numero": int(stack[-1]) if stack else "",
        "marcadas": int(marcadas_count),
        "stack": stack,
        "has_correction": bool(corr),
        "motivo": str(corr.get("motivo","") if isinstance(corr, dict) else ""),
        "updated_at": str(corr.get("updated_at","") if isinstance(corr, dict) else ""),
    }
    return payload, None

@app.get("/juego/figuras/shapes")
def _hf_juego_figuras_shapes():
    try:
        shapes = _load_shapes() if callable(globals().get("_load_shapes")) else {}
        return jsonify(ok=True, shapes=shapes or {})
    except Exception as e:
        return jsonify(ok=False, error=str(e), shapes={}), 500

@app.get("/juego/boletos/series")
def _hf_juego_boletos_series():
    fecha = str(request.args.get("fecha") or "").strip()
    if not fecha:
        fecha = _get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else datetime.now().strftime("%Y-%m-%d")
    try:
        series = _juego_series_en_juego(fecha)
        return jsonify(ok=True, fecha=fecha, series=series)
    except Exception as e:
        return jsonify(ok=False, fecha=fecha, series=[], error=str(e)), 500

@app.post("/juego/boletos/consultar")
def _hf_juego_boletos_consultar():
    data = request.get_json(silent=True) or request.form or {}
    fecha = str(data.get("fecha") or "").strip()
    if not fecha:
        fecha = _get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else datetime.now().strftime("%Y-%m-%d")
    serie_archivo = str(data.get("serie_archivo") or data.get("serie") or "").strip()
    carton_id = str(data.get("carton_id") or data.get("boleto") or data.get("tabla") or "").strip()
    if not serie_archivo:
        series = _juego_series_en_juego(fecha)
        if len(series) == 1:
            serie_archivo = series[0]
    if not serie_archivo:
        return jsonify(ok=False, error="Selecciona una serie"), 400
    if not carton_id:
        return jsonify(ok=False, error="Ingresa número de boleto/cartón"), 400
    payload, err = _juego_ticket_info(fecha, serie_archivo, carton_id)
    if err:
        return jsonify(ok=False, error=err), 404
    return jsonify(payload)

def _hf_admin_check_key(key):
    real = str(os.getenv("GL_SUPERADMIN_KEY") or os.getenv("SUPERADMIN_KEY") or "TLA1299")
    return str(key or "") == real


def _hf_programar_tl_key_ok(key):
    try:
        ok, _msg = _verify_scope_password('programar_tablas', key)
        if ok:
            return True
    except Exception:
        pass
    try:
        if _hf_admin_check_key(key):
            return True
    except Exception:
        pass
    return False


def _juego_by_series_from_rangos(fecha_iso: str) -> dict:
    by_series = {}
    for rg in (_get_rangos_en_juego(str(fecha_iso)) or []):
        serie = str((rg or {}).get('serie_archivo') or '').strip()
        desde = _norm_tabla_id((rg or {}).get('desde') or '')
        hasta = _norm_tabla_id((rg or {}).get('hasta') or '')
        if not serie or not desde or not hasta:
            continue
        by_series.setdefault(serie, []).append((desde, hasta))
    return by_series


def _sorteo_tl_programadas_payload(cfg: dict | None, fecha_iso: str) -> dict:
    cfg = dict(cfg or {})
    slots = _tl_prog_build_slots(cfg)
    resolved = {}
    try:
        resolved = _resolve_tl_programadas_for_day(str(fecha_iso), _juego_by_series_from_rangos(str(fecha_iso))) or {}
    except Exception:
        resolved = {}

    def _slot(slot_code: str, carton_key: str, objetivo_key: str, serie_key: str):
        raw_serie = str(cfg.get(serie_key) or '').strip()
        raw_carton = _tl_prog_norm_carton(cfg.get(carton_key))
        raw_obj = _tl_prog_parse_int(cfg.get(objetivo_key), 0)
        resolved_item = dict(resolved.get(slot_code) or {})
        serie_final = raw_serie or str(resolved_item.get('serie') or '').strip()
        return {
            'serie_archivo': serie_final,
            'carton_id': raw_carton,
            'objetivo': raw_obj,
            'carton_resuelto': str(resolved_item.get('carton_id') or '').strip(),
        }

    return {
        'activas': '1' if _tl_prog_on(cfg.get('tl_programadas_activas')) else '0',
        'llena': _slot('TL1', 'tl_programada_llena', 'tl_objetivo_llena', 'tl_serie_llena'),
        'rellena': _slot('TL2', 'tl_programada_rellena', 'tl_objetivo_rellena', 'tl_serie_rellena'),
        'yapa': _slot('TL3', 'tl_programada_yapa', 'tl_objetivo_yapa', 'tl_serie_yapa'),
    }

@app.post("/juego/admin/boletos/meta")
def _hf_admin_boletos_meta():
    data = request.get_json(silent=True) or request.form or {}
    key = data.get("key")
    if not _hf_admin_check_key(key):
        return jsonify(ok=False, error="Clave inválida"), 403
    fecha = str(data.get("fecha") or "").strip()
    if not fecha:
        fecha = _get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else datetime.now().strftime("%Y-%m-%d")
    series = _juego_series_en_juego(fecha)
    return jsonify(ok=True, fecha=fecha, series=series)


@juego_bp.post("/admin/programacion_manual/meta")
def _hf_programacion_manual_meta():
    data = request.get_json(silent=True) or request.form or {}
    key = data.get('key')
    if not _hf_programar_tl_key_ok(key):
        return jsonify(ok=False, error='Clave inválida'), 403
    fecha = str(data.get('fecha') or '').strip() or _get_sorteo_fecha()
    cfg = _sorteo_read_config(fecha) if callable(globals().get('_sorteo_read_config')) else {}
    series = _juego_series_en_juego(fecha)
    return jsonify(
        ok=True,
        fecha=fecha,
        series=series,
        programacion=_sorteo_tl_programadas_payload(cfg, fecha),
        sorteo={
            'nombre_sorteo': str((cfg or {}).get('nombre_sorteo') or f'Sorteo {fecha}').strip(),
            'estado': str((cfg or {}).get('estado') or '').strip(),
            'activo': str((cfg or {}).get('activo') or '0').strip(),
        },
    )


@juego_bp.post("/admin/programacion_manual/save")
def _hf_programacion_manual_save():
    data = request.get_json(silent=True) or request.form or {}
    key = data.get('key')
    if not _hf_programar_tl_key_ok(key):
        return jsonify(ok=False, error='Clave inválida'), 403
    fecha = str(data.get('fecha') or '').strip() or _get_sorteo_fecha()
    prev = _sorteo_read_config(fecha) if callable(globals().get('_sorteo_read_config')) else {}
    cfg = dict(prev or {})

    def _clean_carton(v):
        return _tl_prog_norm_carton(v)

    def _clean_obj(v):
        n = _tl_prog_parse_int(v, 0)
        return str(n) if n > 0 else ''

    def _clean_serie(v):
        return str(v or '').strip()

    activas_raw = data.get('activas')
    if activas_raw in (None, ''):
        activas_raw = '1' if any(str(data.get(k) or '').strip() for k in (
            'llena_carton', 'rellena_carton', 'yapa_carton',
            'llena_objetivo', 'rellena_objetivo', 'yapa_objetivo',
        )) else '0'

    cfg['tl_programadas_activas'] = '1' if _tl_prog_on(activas_raw) else '0'
    cfg['tl_programada_llena'] = _clean_carton(data.get('llena_carton'))
    cfg['tl_programada_rellena'] = _clean_carton(data.get('rellena_carton'))
    cfg['tl_programada_yapa'] = _clean_carton(data.get('yapa_carton'))
    cfg['tl_objetivo_llena'] = _clean_obj(data.get('llena_objetivo'))
    cfg['tl_objetivo_rellena'] = _clean_obj(data.get('rellena_objetivo'))
    cfg['tl_objetivo_yapa'] = _clean_obj(data.get('yapa_objetivo'))
    cfg['tl_serie_llena'] = _clean_serie(data.get('llena_serie')) if cfg['tl_programada_llena'] else ''
    cfg['tl_serie_rellena'] = _clean_serie(data.get('rellena_serie')) if cfg['tl_programada_rellena'] else ''
    cfg['tl_serie_yapa'] = _clean_serie(data.get('yapa_serie')) if cfg['tl_programada_yapa'] else ''
    cfg['tl_programadas_cartones'] = ','.join([x for x in [
        cfg.get('tl_programada_llena') or '',
        cfg.get('tl_programada_rellena') or '',
        cfg.get('tl_programada_yapa') or '',
    ] if x])

    saved = _sorteo_save_config(fecha, cfg, activar=False, finalizar=False)
    return jsonify(
        ok=True,
        fecha=fecha,
        series=_juego_series_en_juego(fecha),
        programacion=_sorteo_tl_programadas_payload(saved, fecha),
        sorteo={
            'nombre_sorteo': str((saved or {}).get('nombre_sorteo') or f'Sorteo {fecha}').strip(),
            'estado': str((saved or {}).get('estado') or '').strip(),
            'activo': str((saved or {}).get('activo') or '0').strip(),
        },
    )


@juego_bp.post("/admin/programacion_manual/clear")
def _hf_programacion_manual_clear():
    data = request.get_json(silent=True) or request.form or {}
    key = data.get('key')
    if not _hf_programar_tl_key_ok(key):
        return jsonify(ok=False, error='Clave inválida'), 403
    fecha = str(data.get('fecha') or '').strip() or _get_sorteo_fecha()
    prev = _sorteo_read_config(fecha) if callable(globals().get('_sorteo_read_config')) else {}
    cfg = dict(prev or {})
    for k in (
        'tl_programadas_cartones',
        'tl_programada_llena', 'tl_programada_rellena', 'tl_programada_yapa',
        'tl_objetivo_llena', 'tl_objetivo_rellena', 'tl_objetivo_yapa',
        'tl_serie_llena', 'tl_serie_rellena', 'tl_serie_yapa',
    ):
        cfg[k] = ''
    cfg['tl_programadas_activas'] = '0'
    saved = _sorteo_save_config(fecha, cfg, activar=False, finalizar=False)
    return jsonify(
        ok=True,
        fecha=fecha,
        series=_juego_series_en_juego(fecha),
        programacion=_sorteo_tl_programadas_payload(saved, fecha),
        sorteo={
            'nombre_sorteo': str((saved or {}).get('nombre_sorteo') or f'Sorteo {fecha}').strip(),
            'estado': str((saved or {}).get('estado') or '').strip(),
            'activo': str((saved or {}).get('activo') or '0').strip(),
        },
    )


# ============================================================
#  REGISTRO BP + INICIALIZACIÓN
# ============================================================
def register_juego(app):
    app.register_blueprint(juego_bp)
    _ensure_bingo_xml()
    _ensure_hist()
    _ensure_vmix_xml()
    _write_spinner_state(running=False, locked=False, overlay_on=False)
    try:
        _refresh_vmix_figuras_panel_for_fecha()
    except Exception:
        pass

try:
    app  # noqa
    if "juego" not in [bp.name for bp in app.blueprints.values()]:
        register_juego(app)
except Exception:
    pass

def _ticket_original_grid_fast(serie_archivo, carton_id):
    """Obtiene la grilla ORIGINAL del boleto usando la caché de la serie, sin tocar el motor de juego."""
    cid = str(carton_id or "").strip()
    if not cid:
        return None
    try:
        df, idcol, ids, id_to_idx, _mtime = _get_series_meta_cached(serie_archivo)
        idx = id_to_idx.get(cid)
        if idx is None:
            try:
                cid_num = int(re.sub(r"\D", "", cid) or 0)
            except Exception:
                cid_num = None
            if cid_num is not None:
                for i, vv in enumerate(ids or []):
                    try:
                        if int(re.sub(r"\D", "", str(vv)) or 0) == cid_num:
                            idx = i
                            break
                    except Exception:
                        continue
        if idx is None:
            return None
        row = df.iloc[int(idx)]
        row_lower = {str(c).strip().lower(): row[c] for c in df.columns}
        grid, _ = _build_grid_from_row(row_lower)
        return grid
    except Exception:
        return None


def _ticket_has_winner_for_day(fecha_iso, serie_archivo, carton_id):
    """True si ese boleto ya figura como ganador hoy."""
    fecha_iso = str(fecha_iso)
    serie_archivo = str(serie_archivo or "").strip()
    tabla = _norm_tabla_id(carton_id)
    try:
        data = _safe_json_read(GANADORES_JSON) or {}
        for g in (data.get(fecha_iso) or []):
            if not isinstance(g, dict):
                continue
            try:
                gserie = str(g.get('serie') or '').strip()
                gtabla = _norm_tabla_id(g.get('tabla') or g.get('boleto') or '')
                if gtabla == tabla and (_serie_equal(gserie, serie_archivo) if gserie and serie_archivo else gserie == serie_archivo):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False

@app.post("/juego/admin/boletos/get")
def _hf_admin_boletos_get():
    data = request.get_json(silent=True) or request.form or {}
    key = data.get("key")
    if not _hf_admin_check_key(key):
        return jsonify(ok=False, error="Clave inválida"), 403
    fecha = str(data.get("fecha") or "").strip()
    if not fecha:
        fecha = _get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else datetime.now().strftime("%Y-%m-%d")
    serie_archivo = str(data.get("serie_archivo") or "").strip()
    carton_id = str(data.get("carton_id") or data.get("boleto") or "").strip()
    if not serie_archivo:
        return jsonify(ok=False, error="Selecciona una serie"), 400
    if not carton_id:
        return jsonify(ok=False, error="Ingresa número de boleto/cartón"), 400
    payload, err = _juego_ticket_info(fecha, serie_archivo, carton_id)
    if err:
        return jsonify(ok=False, error=err), 404
    corr = _corr_get(fecha, serie_archivo, carton_id) or {}
    try:
        orig_grid = _ticket_original_grid_fast(serie_archivo, carton_id) or payload.get("grid")
    except Exception:
        orig_grid = payload.get("grid")
    stack = _read_stack() or []
    payload["original_grid"] = orig_grid
    payload["grid"] = payload.get("grid") or orig_grid
    payload["has_correction"] = bool(corr)
    payload["motivo"] = str(corr.get("motivo","") or "")
    payload["corregido_por"] = str(corr.get("user","") or "")
    payload["stack"] = stack
    payload["last"] = (stack[-1] if stack else None)
    payload["total"] = len(stack)
    payload["ultimos5"] = list(reversed(stack[-5:]))
    payload["panel_numeros"] = {
        "stack": stack,
        "last": (stack[-1] if stack else None),
        "total": len(stack),
        "ultimos5": list(reversed(stack[-5:])),
    }
    return jsonify(payload)

@app.post("/juego/admin/boletos/save")
def _hf_admin_boletos_save():
    data = request.get_json(silent=True) or request.form or {}
    key = data.get("key")
    if not _hf_admin_check_key(key):
        return jsonify(ok=False, error="Clave inválida"), 403

    fecha = str(data.get("fecha") or "").strip()
    if not fecha:
        fecha = _get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else datetime.now().strftime("%Y-%m-%d")
    serie_archivo = str(data.get("serie_archivo") or "").strip()
    carton_id = str(data.get("carton_id") or data.get("boleto") or "").strip()
    motivo = str(data.get("motivo") or data.get("nota") or "").strip()
    grid = data.get("grid")

    if not serie_archivo:
        return jsonify(ok=False, error="Selecciona una serie"), 400
    if not carton_id:
        return jsonify(ok=False, error="Ingresa número de boleto/cartón"), 400
    if grid is None:
        return jsonify(ok=False, error="No llegó la cuadrícula"), 400
    try:
        grid = _corr_norm_grid5(grid)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

    usern = "superadmin"
    try:
        usern = str(session.get("usuario") or session.get("username") or session.get("user") or "superadmin")
    except Exception:
        pass

    prev_corr = _corr_get(fecha, serie_archivo, carton_id) or {}
    old_grid = prev_corr.get("grid") if isinstance(prev_corr, dict) else None
    if not old_grid:
        old_grid = _ticket_original_grid_fast(serie_archivo, carton_id)

    payload = {
        "grid": grid,
        "motivo": motivo,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": usern,
    }
    _corr_set(fecha, serie_archivo, carton_id, payload)

    # Fast path seguro: si no cambió ningún número YA marcado del boleto y ese boleto no figura
    # hoy como ganador, no hace falta recalcular todo el juego.
    try:
        old_nums = _ticket_nums_from_grid(old_grid or [])
        new_nums = _ticket_nums_from_grid(grid or [])
        stack = _read_stack() or []
        marked_now = set()
        for _n in (stack or []):
            try:
                _ni = int(str(_n).strip())
                if 1 <= _ni <= 75:
                    marked_now.add(_ni)
            except Exception:
                pass
        touched_marked = bool((old_nums ^ new_nums) & marked_now)
        impacted_winner = _ticket_has_winner_for_day(str(fecha), str(serie_archivo), str(carton_id))
        if (not touched_marked) and (not impacted_winner):
            return jsonify(ok=True, msg="Corrección guardada", fecha=fecha, fast_path=True)
    except Exception:
        stack = _read_stack() or []

    # No limpiamos las caches base de series/cartones: las correcciones se aplican por overlay
    # y eso evita reconstruir miles de cartones innecesariamente en cada guardado.
    try:
        stack = stack if 'stack' in locals() else (_read_stack() or [])
        ultimo = int(stack[-1]) if stack else 0
        ganadores_total, _ = _recalcular_ganadores(str(fecha), stack, ultimo)
        _sync_resultados_from_juego(str(fecha), ganadores_total)
        # Reinicia el índice del XML de cartón ganador para que el primer ganador vuelva a mostrarse.
        try:
            if callable(globals().get("_vmix_carton_state_read")) and callable(globals().get("_vmix_carton_state_write")):
                _st = _vmix_carton_state_read() or {}
                _por = _st.get("por_fecha") if isinstance(_st.get("por_fecha"), dict) else {}
                _por[str(fecha)] = 1 if (ganadores_total or []) else 0
                _st["por_fecha"] = _por
                _st["fecha"] = str(fecha)
                _st["actual"] = 1 if (ganadores_total or []) else 0
                _st["total"] = len(ganadores_total or [])
                _vmix_carton_state_write(_st)
        except Exception:
            pass
    except Exception as _e:
        return jsonify(ok=True, warning=f"Corrección guardada, pero no se pudo recalcular: {_e}")

    return jsonify(ok=True, msg="Corrección guardada y juego recalculado", fecha=fecha, fast_path=False)

@app.get("/juego/admin/boletos/estado")
def _hf_admin_boletos_estado():
    stack = _read_stack()
    last = (stack[-1] if stack else None)
    return jsonify(
        ok=True,
        stack=stack,
        last=last,
        total=len(stack),
        ultimos5=list(reversed(stack[-5:])),
    )

@app.post("/juego/admin/boletos/marcar")
def _hf_admin_boletos_marcar():
    return juego_marcar()

@app.post("/juego/admin/boletos/reversa")
def _hf_admin_boletos_reversa():
    return juego_reversa()

@app.post("/juego/admin/boletos/reset")
def _hf_admin_boletos_reset():
    return juego_reset()

print("[HOTFIX FINAL] APIs de juego y sincronización activadas")


# ============================================================
# HOTFIX SPINNERS COMPATIBILIDAD (SORTEO -> JUEGO -> VMIX)
# - No toca la configuración del sorteo en vmix_spinners.xml
# - Expone /juego/spinners/list para el modal
# - Expone /juego/spinners/base_url para copiar URL correcta (192.168.0.7)
# - Expone /juego/spinners/overlay/off compatible con el botón del modal
# ============================================================
def _sp_hotfix_fecha():
    try:
        fn = globals().get("_get_sorteo_fecha")
        if callable(fn):
            v = str(fn() or "").strip()
            if v:
                return v
    except Exception:
        pass
    try:
        return datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return date.today().isoformat()

def _sp_hotfix_norm4(v):
    s = re.sub(r"\D", "", str(v or ""))[:4]
    return s.zfill(4) if s else ""

def _sp_hotfix_parse_n_values(path_):
    out = []
    try:
        if not path_ or not os.path.exists(path_):
            return []
        root = ET.parse(path_).getroot()
        for n in root.findall(".//n"):
            val = ""
            try:
                val = n.attrib.get("v") or (n.text or "")
            except Exception:
                val = n.text or ""
            out.append(_sp_hotfix_norm4(val))
        out = [x for x in out]
    except Exception:
        out = []
    return (out + [""] * 20)[:20] if out else []

def _sp_hotfix_parse_state_rows(path_):
    rows = []
    try:
        if not path_ or not os.path.exists(path_):
            return []
        root = ET.parse(path_).getroot()
        for node in root.findall(".//spinner"):
            idx = int(node.get("index", "0") or 0)
            if idx < 1 or idx > 20:
                continue
            rows.append({
                "index": idx,
                "value": _sp_hotfix_norm4(node.get("value", "")),
                "locked": str(node.get("locked", "0")) == "1",
                "used": str(node.get("used", "0")) == "1",
            })
    except Exception:
        rows = []
    rows.sort(key=lambda x: x["index"])
    return rows

def _sp_hotfix_history_path():
    try:
        return os.path.join(DB_DIR, "spinners", f"{_sp_hotfix_fecha()}.xml")
    except Exception:
        return ""

def _sp_hotfix_read_config_values():
    # prioridad: vmix_spinners.xml del sorteo -> histórico del día -> helper existente -> spinners.xml con <n>
    candidates = []
    try:
        candidates.append(VMIX_SPINNERS_XML)
    except Exception:
        pass
    hp = _sp_hotfix_history_path()
    if hp:
        candidates.append(hp)
    try:
        helper = globals().get("read_spinners_current")
        if callable(helper):
            vals = helper()
            if isinstance(vals, list) and any(str(x or "").strip() for x in vals):
                return [_sp_hotfix_norm4(x) for x in (vals + [""] * 20)[:20]]
    except Exception:
        pass
    try:
        candidates.append(SPINNERS_XML)
    except Exception:
        pass
    for p in candidates:
        vals = _sp_hotfix_parse_n_values(p)
        if vals and any(vals):
            return vals
    # fallback final: si existe estado con valores, úsalos
    try:
        rows = _sp_hotfix_parse_state_rows(SPINNERS_XML)
        if rows:
            vals = []
            for i in range(1, 21):
                row = next((r for r in rows if r["index"] == i), None)
                vals.append(_sp_hotfix_norm4((row or {}).get("value", "")))
            if any(vals):
                return vals
    except Exception:
        pass
    return [""] * 20

def _sp_hotfix_read_rows():
    cfg = _sp_hotfix_read_config_values()
    state_rows = _sp_hotfix_parse_state_rows(globals().get("SPINNERS_XML", ""))
    state_by_idx = {r["index"]: r for r in state_rows}
    rows = []
    for i in range(1, 21):
        st = state_by_idx.get(i, {})
        cfg_val = cfg[i - 1] if i - 1 < len(cfg) else ""
        state_val = _sp_hotfix_norm4(st.get("value", ""))
        rows.append({
            "index": i,
            "value": cfg_val or state_val or "0000",
            "locked": bool(st.get("locked", False)),
            "used": bool(st.get("used", False)),
        })
    return rows

def _sp_hotfix_write_rows(rows):
    try:
        root = ET.Element("spinners")
        for row in sorted(rows, key=lambda x: int(x.get("index", 0))):
            ET.SubElement(
                root,
                "spinner",
                index=str(int(row.get("index", 0))),
                value=_sp_hotfix_norm4(row.get("value", "")) or "0000",
                locked="1" if row.get("locked") else "0",
                used="1" if row.get("used") else "0",
            )
        ET.indent(root, space="  ")
        ET.ElementTree(root).write(SPINNERS_XML, encoding="utf-8", xml_declaration=True)
    except Exception:
        pass

def _sp_hotfix_base_url():
    env_url = str(os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env_url:
        return env_url
    try:
        root = request.url_root.rstrip("/")
    except Exception:
        root = ""
    try:
        host = request.host.split(":")[0].strip().lower()
    except Exception:
        host = ""
    if not root or host in ("127.0.0.1", "localhost"):
        return "http://192.168.0.7:5000"
    return root

@app.get("/juego/spinners/list")
def _sp_hotfix_list():
    rows = _sp_hotfix_read_rows()
    resp = jsonify(rows)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.get("/juego/spinners/base_url")
def _sp_hotfix_base_url_route():
    return jsonify(ok=True, base_url=_sp_hotfix_base_url())

@app.post("/juego/spinners/overlay/off")
def _sp_hotfix_overlay_off_route():
    ok = True
    msg = "ok"
    try:
        ofn = globals().get("_overlay_off")
        if callable(ofn):
            res = ofn()
            if isinstance(res, tuple) and len(res) >= 2:
                ok, msg = bool(res[0]), str(res[1])
        else:
            call = globals().get("_vmix_call")
            if callable(call):
                try:
                    res = call(f"OverlayInput{globals().get('VMIX_OVERLAY_INDEX', 1)}Off", Input=globals().get("VMIX_SPINNER_INPUT", ""))
                except TypeError:
                    res = call(f"OverlayInput{globals().get('VMIX_OVERLAY_INDEX', 1)}Off")
                if isinstance(res, tuple) and len(res) >= 2:
                    ok, msg = bool(res[0]), str(res[1])
                elif isinstance(res, dict):
                    ok, msg = bool(res.get("ok", False)), str(res.get("msg") or res.get("status") or "")
    except Exception as e:
        ok, msg = False, str(e)

    # Mantener control visual sincronizado
    try:
        rows = _sp_hotfix_read_rows()
        _sp_hotfix_write_rows(rows)
    except Exception:
        pass
    return jsonify(ok=bool(ok), msg=msg)


def _sp_hotfix_parse_vmix_result(res):
    ok, msg = True, ""
    try:
        if isinstance(res, tuple):
            ok = bool(res[0])
            msg = str(res[1]) if len(res) > 1 else ""
        elif isinstance(res, dict):
            ok = bool(res.get("ok", False))
            msg = str(res.get("msg") or res.get("status") or "")
        elif isinstance(res, bool):
            ok = res
            msg = "ok" if res else "error"
    except Exception as e:
        ok, msg = False, str(e)
    return ok, msg

def _sp_hotfix_call_overlay_on(input_name=""):
    input_name = str(input_name or "").strip()
    try:
        if input_name:
            call = globals().get("_vmix_call")
            if callable(call):
                try:
                    return _sp_hotfix_parse_vmix_result(call(f"OverlayInput{globals().get('VMIX_OVERLAY_INDEX', 1)}On", Input=input_name))
                except TypeError:
                    return _sp_hotfix_parse_vmix_result(call(f"OverlayInput{globals().get('VMIX_OVERLAY_INDEX', 1)}On"))
        fn = globals().get("_overlay_on")
        if callable(fn):
            return _sp_hotfix_parse_vmix_result(fn())
        call = globals().get("_vmix_call")
        if callable(call):
            try:
                return _sp_hotfix_parse_vmix_result(call(f"OverlayInput{globals().get('VMIX_OVERLAY_INDEX', 1)}On", Input=globals().get("VMIX_SPINNER_INPUT", "")))
            except TypeError:
                return _sp_hotfix_parse_vmix_result(call(f"OverlayInput{globals().get('VMIX_OVERLAY_INDEX', 1)}On"))
    except Exception as e:
        return False, str(e)
    return True, "ok"

def _sp_hotfix_write_event(op, index1, target):
    seq = int(datetime.utcnow().timestamp() * 1000)
    ev = {
        "ok": True,
        "seq": seq,
        "t": seq,
        "op": str(op or ""),
        "index": int(index1),
        "target": _sp_hotfix_norm4(target) if str(target or "").strip() else "",
    }
    try:
        _json_write(os.path.join(DB_DIR, "spinners_event.json"), ev)
    except Exception:
        pass
    return ev

def _sp_hotfix_norm_index(raw, base=None):
    """
    Normaliza el índice del spinner sin desplazarlo por error.
    - base='one'  => espera 1..20
    - base='zero' => espera 0..19 y convierte a 1..20
    - sin base    => compatibilidad segura: 0 -> 1; cualquier otro valor se trata como 1..20

    Nota: no se puede adivinar de forma fiable si un "1" significa spinner #1
    (base 1) o el segundo spinner (base 0). Por eso el frontend ahora envía
    index_base explícito y aquí lo respetamos.
    """
    try:
        idx = int(raw)
    except Exception:
        idx = 1

    base = str(base or "").strip().lower()

    if base in ("zero", "0", "zero-based", "cero"):
        if idx < 0:
            return 1
        if idx > 19:
            return 20
        return idx + 1

    if base in ("one", "1", "one-based", "uno"):
        if idx < 1:
            return 1
        if idx > 20:
            return 20
        return idx

    # Fallback seguro: favorece base 1 (modal principal).
    # Solo 0 se interpreta como el primer spinner en base 0.
    if idx <= 0:
        return 1
    if idx > 20:
        return 20
    return idx

def _sp_hotfix_generate_impl():
    data = request.get_json(silent=True) or {}
    idx1 = _sp_hotfix_norm_index(data.get("index", 1), data.get("index_base"))
    rows = _sp_hotfix_read_rows()
    if 1 <= idx1 <= len(rows):
        rows[idx1 - 1]["used"] = False
        rows[idx1 - 1]["locked"] = False
        _sp_hotfix_write_rows(rows)
    ev = _sp_hotfix_write_event("gen", idx1, "0000")
    try:
        fn = globals().get("_write_spinner_state")
        if callable(fn):
            fn(running=True, locked=False, overlay_on=True)
    except Exception:
        pass
    return jsonify(ok=True, index=idx1, target="0000", seq=ev["seq"], event=ev)

def _sp_hotfix_launch_impl():
    data = request.get_json(silent=True) or {}
    idx1 = _sp_hotfix_norm_index(data.get("index", 1), data.get("index_base"))
    rows = _sp_hotfix_read_rows()
    row = rows[idx1 - 1] if 1 <= idx1 <= len(rows) else {"index": idx1, "value": "0000", "used": False, "locked": False}
    if row.get("locked"):
        return jsonify(ok=False, error="Este spinner está bloqueado"), 409

    raw_target = data.get("target") or row.get("value") or ""
    target = _sp_hotfix_norm4(raw_target)
    # 0000 / vacío = no asignado
    if not target or target == "0000":
        return jsonify(ok=False, error="Este spinner no tiene valor asignado en Sorteo"), 400

    row["used"] = True
    row["locked"] = True
    row["value"] = target
    if 1 <= idx1 <= len(rows):
        rows[idx1 - 1] = row
    _sp_hotfix_write_rows(rows)

    overlay_on = bool(data.get("overlay_on", True))
    input_name = str(data.get("vmix_input") or data.get("input") or "").strip()
    vmix_ok, vmix_msg = True, "ok"
    if overlay_on:
        vmix_ok, vmix_msg = _sp_hotfix_call_overlay_on(input_name)
        try:
            fn = globals().get("_write_spinner_state")
            if callable(fn):
                fn(running=True, locked=False, overlay_on=True)
        except Exception:
            pass

    ev = _sp_hotfix_write_event("launch", idx1, target)
    return jsonify(ok=True, index=idx1, target=target, seq=ev["seq"], event=ev, vmix_ok=vmix_ok, vmix_msg=vmix_msg)

def _sp_hotfix_event_impl():
    ev = {}
    try:
        ev = _json_read(os.path.join(DB_DIR, "spinners_event.json")) or {}
    except Exception:
        ev = {}
    seq = int(ev.get("seq") or ev.get("t") or 0) if isinstance(ev, dict) else 0
    data = {
        "ok": True,
        "seq": seq,
        "op": (ev or {}).get("op", ""),
        "index": (ev or {}).get("index", 1),
        "target": (ev or {}).get("target", ""),
        "event": ev or {},
    }
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

try:
    if "juego.juego_spinners_generate" in app.view_functions:
        app.view_functions["juego.juego_spinners_generate"] = _sp_hotfix_generate_impl
    if "juego.juego_spinners_launch" in app.view_functions:
        app.view_functions["juego.juego_spinners_launch"] = _sp_hotfix_launch_impl
    if "juego.juego_spinners_event" in app.view_functions:
        app.view_functions["juego.juego_spinners_event"] = _sp_hotfix_event_impl
except Exception:
    pass


# ============================
#  GANADORES DETALLE XML (vMix)
# ============================
try:
    VMIX_GANADORES_DETALLE_XML = globals().get("VMIX_GANADORES_DETALLE_XML") or _persist("static", "db", "vmix_ganadores_detalle.xml")
except Exception:
    VMIX_GANADORES_DETALLE_XML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "db", "vmix_ganadores_detalle.xml")

try:
    VMIX_GANADORES_DETALLE_XML_PUBLIC = globals().get("VMIX_GANADORES_DETALLE_XML_PUBLIC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "db", "vmix_ganadores_detalle.xml")
except Exception:
    VMIX_GANADORES_DETALLE_XML_PUBLIC = VMIX_GANADORES_DETALLE_XML

_GDX_FIELDS = [
    "numero_figura", "figura", "valor_figura", "boleto", "vendedor", "planilla", "rango",
    "sector", "nombre", "cliente_nombre", "cabala", "celular", "serie", "scan_at",
    "ultima_bola", "texto_completo"
]

_GDX_LINE_SPECS = [
    ("boleto", "BOLETO"),
    ("vendedor", "VENDEDOR"),
    ("valor_figura", "VALOR PREMIO"),
    ("figura", "FIGURA"),
    ("numero_figura", "NRO FIGURA"),
    ("planilla", "PLANILLA"),
    ("rango", "RANGO"),
    ("sector", "SECTOR"),
    ("cabala", "NOMBRE/CABALA"),
    ("celular", "CELULAR"),
    ("serie", "SERIE"),
    ("scan_at", "SCAN"),
    ("ultima_bola", "ULTIMA BOLA"),
]

def _gdx_str(v):
    try:
        return str(v or "").strip()
    except Exception:
        return ""

def _gdx_dash(v):
    s = _gdx_str(v)
    return s if s else "—"

def _gdx_safe_float(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0

def _gdx_num_fig_map(fecha_iso: str) -> dict:
    out = {}
    try:
        figs = _figuras_de_fecha(str(fecha_iso)) or []
        idx = 0
        for f in figs:
            nombre = _gdx_str((f or {}).get("nombre") or (f or {}).get("figura"))
            if not nombre:
                continue
            idx += 1
            out.setdefault(nombre.lower(), idx)
    except Exception:
        pass
    return out

def _gdx_resultado_nombre(fecha_iso: str, figura: str, boleto: str) -> str:
    figura_key = _gdx_str(figura).lower()
    boleto_key = _norm_tabla_id(boleto) if "_norm_tabla_id" in globals() else _gdx_str(boleto)
    try:
        data = _cargar_resultados(str(fecha_iso)) or {}
        for item in (data.get("items") or []):
            nom = _gdx_str((item or {}).get("figura"))
            if not nom or nom.lower() != figura_key:
                continue
            for g in ((item or {}).get("ganadores") or []):
                b = _norm_tabla_id((g or {}).get("boleto") or "") if "_norm_tabla_id" in globals() else _gdx_str((g or {}).get("boleto"))
                if boleto_key and b and b != boleto_key:
                    continue
                nombre = _gdx_str((g or {}).get("nombre"))
                if nombre:
                    return nombre
    except Exception:
        pass
    return ""

def _gdx_winners_from_json(fecha_iso: str) -> list:
    out = []
    try:
        data = _safe_json_read(GANADORES_JSON) or {}
        raw = data.get(str(fecha_iso)) or []
        if isinstance(raw, list):
            for w in raw:
                if isinstance(w, dict):
                    out.append(dict(w))
    except Exception:
        pass
    return out

def _gdx_winners_from_xml(fecha_iso: str) -> list:
    out = []
    try:
        path = GANADORES_XML if os.path.exists(GANADORES_XML) else GANADORES_XML_PUBLIC
        if not path or not os.path.exists(path):
            return out
        root = ET.parse(path).getroot()
        root_fecha = _gdx_str(root.attrib.get("fecha"))
        if root_fecha and str(root_fecha) != str(fecha_iso):
            return out
        for n in root.findall("ganador"):
            out.append({
                "fecha": str(fecha_iso),
                "figura": _gdx_str(n.attrib.get("figura")),
                "fig_code": _gdx_str(n.attrib.get("fig_code")),
                "valor": _gdx_safe_float(n.attrib.get("valor")),
                "serie": _gdx_str(n.attrib.get("serie")),
                "tabla": _gdx_str(n.attrib.get("tabla")),
                "boleto": _gdx_str(n.attrib.get("tabla")),
                "ultima_bola": _gdx_str(n.attrib.get("ultima_bola")),
            })
    except Exception:
        pass
    return out

def _gdx_winners_from_resultados(fecha_iso: str) -> list:
    out = []
    try:
        data = _cargar_resultados(str(fecha_iso)) or {}
        for item in (data.get("items") or []):
            figura = _gdx_str((item or {}).get("figura"))
            if not figura:
                continue
            for g in ((item or {}).get("ganadores") or []):
                out.append({
                    "fecha": str(fecha_iso),
                    "figura": figura,
                    "valor": _gdx_safe_float((g or {}).get("premio")),
                    "tabla": _gdx_str((g or {}).get("boleto")),
                    "boleto": _gdx_str((g or {}).get("boleto")),
                    "vendedor": _gdx_str((g or {}).get("vendedor")),
                    "sector": _gdx_str((g or {}).get("sector")),
                    "nombre": _gdx_str((g or {}).get("nombre")),
                })
    except Exception:
        pass
    return out

def _gdx_pick_winners(fecha_iso: str) -> list:
    winners = _gdx_winners_from_json(fecha_iso)
    if winners:
        return winners
    winners = _gdx_winners_from_xml(fecha_iso)
    if winners:
        return winners
    return _gdx_winners_from_resultados(fecha_iso)

def _gdx_qr_lookup(fecha_iso: str, serie: str, boleto: str) -> dict:
    try:
        qr = _qr_buscar_registro_ticket(str(fecha_iso), serie, boleto) or {}
        if qr:
            return qr
    except Exception:
        pass
    try:
        _qr_ensure_xml(QR_REGISTROS_XML, "registros_qr")
        root = ET.parse(QR_REGISTROS_XML).getroot()
        boleto_key = _gdx_str(boleto)
        serie_key = os.path.basename(_gdx_str(serie)).lower()
        fallback = None
        for r in root.findall("registro"):
            fecha_r = _gdx_str(r.attrib.get("fecha_sorteo"))
            boleto_r = _gdx_str(r.attrib.get("boleto"))
            if fecha_r != _gdx_str(fecha_iso) or boleto_r != boleto_key:
                continue
            serie_r = os.path.basename(_gdx_str(r.attrib.get("serie"))).lower()
            item = {
                "cliente_nombre": r.attrib.get("cliente_nombre", ""),
                "sector": r.attrib.get("sector", ""),
                "celular": r.attrib.get("celular", ""),
                "vendedor": r.attrib.get("vendedor", ""),
                "planilla": r.attrib.get("planilla", ""),
                "scan_at": r.attrib.get("scan_at", ""),
            }
            if serie_key and serie_r and serie_r == serie_key:
                return item
            if fallback is None:
                fallback = item
        return fallback or {}
    except Exception:
        return {}

def _gdx_enrich_winner(fecha_iso: str, w: dict, idx_map: dict) -> dict:
    figura = _gdx_str((w or {}).get("figura") or (w or {}).get("nombre_figura"))
    boleto = _norm_tabla_id((w or {}).get("boleto") or (w or {}).get("tabla") or "") if "_norm_tabla_id" in globals() else _gdx_str((w or {}).get("boleto") or (w or {}).get("tabla"))
    serie = _gdx_str((w or {}).get("serie") or (w or {}).get("serie_archivo"))
    valor_raw = (w or {}).get("valor")
    if valor_raw in (None, ""):
        valor_raw = (w or {}).get("premio")
    valor_figura = _gdx_safe_float(valor_raw)

    info_b = {}
    try:
        info_b = buscar_info_por_boleto(str(fecha_iso), boleto, serie) or {}
    except Exception:
        info_b = {}
    if not info_b:
        try:
            info_b = buscar_info_por_boleto(str(fecha_iso), boleto) or {}
        except Exception:
            info_b = {}

    qr = _gdx_qr_lookup(str(fecha_iso), serie, boleto) or {}

    nombre_boletin = _gdx_resultado_nombre(str(fecha_iso), figura, boleto)
    cliente_nombre = _gdx_str(qr.get("cliente_nombre") or nombre_boletin or (w or {}).get("nombre") or (w or {}).get("nota"))
    vendedor = _gdx_str((w or {}).get("vendedor") or qr.get("vendedor") or info_b.get("vendedor"))
    planilla = _gdx_str((w or {}).get("planilla") or qr.get("planilla") or info_b.get("planilla"))
    rango = _gdx_str((w or {}).get("rango") or info_b.get("rango"))
    sector = _gdx_str(qr.get("sector") or (w or {}).get("sector") or info_b.get("sector"))
    celular = _gdx_str(qr.get("celular"))
    scan_at = _gdx_str(qr.get("scan_at"))
    ultima_bola = _gdx_str((w or {}).get("ultima_bola") or (w or {}).get("numero_ganador"))
    numero_figura = str(idx_map.get(figura.lower(), "")) if figura else ""

    nombre = cliente_nombre
    cabala = cliente_nombre

    texto_completo = " | ".join([
        f"BOLETO {_gdx_dash(boleto)}",
        f"FIGURA {_gdx_dash(figura)}",
        f"NRO FIGURA {_gdx_dash(numero_figura)}",
        f"VALOR ${valor_figura:.2f}",
        f"VENDEDOR {_gdx_dash(vendedor)}",
        f"PLANILLA {_gdx_dash(planilla)}",
        f"RANGO {_gdx_dash(rango)}",
        f"SECTOR {_gdx_dash(sector)}",
        f"NOMBRE/CABALA {_gdx_dash(cliente_nombre)}",
        f"CELULAR {_gdx_dash(celular)}",
        f"SERIE {_gdx_dash(serie)}",
        f"SCAN {_gdx_dash(scan_at)}",
        f"ULTIMA BOLA {_gdx_dash(ultima_bola)}",
    ])

    return {
        "numero_figura": numero_figura,
        "figura": figura,
        "valor_figura": f"{valor_figura:.2f}",
        "boleto": boleto,
        "vendedor": vendedor,
        "planilla": planilla,
        "rango": rango,
        "sector": sector,
        "nombre": nombre,
        "cliente_nombre": cliente_nombre,
        "cabala": cabala,
        "celular": celular,
        "serie": serie,
        "scan_at": scan_at,
        "ultima_bola": ultima_bola,
        "texto_completo": texto_completo,
    }

def _gdx_build_line_rows(row: dict, has_winner: bool) -> list:
    line_rows = []
    if not has_winner:
        line_rows.append({"campo": "estado", "texto": "SIN GANADOR AUN"})
    for field, label in _GDX_LINE_SPECS:
        val = _gdx_str((row or {}).get(field))
        if field == "valor_figura":
            try:
                txt = f"${float(val or 0):.2f}"
            except Exception:
                txt = "$0.00"
        elif field in ("boleto", "vendedor", "figura", "ultima_bola"):
            txt = _gdx_dash(val)
        elif field == "cabala":
            txt = f"ESCANEADA: {_gdx_dash(val)}"
        else:
            txt = f"{label}: {_gdx_dash(val)}"
        line_rows.append({"campo": field, "texto": txt})
    return line_rows

def _gdx_current_row_from_state(rows: list, fecha_iso: str, action=None, index_override=None) -> dict:
    """Mantiene el XML de planillas sincronizado con el mismo índice usado por cartón ganador."""
    if not rows:
        return {f: "" for f in _GDX_FIELDS}

    idx0 = len(rows) - 1
    try:
        if "_vmix_carton_pick_index" in globals() and callable(_vmix_carton_pick_index):
            idx0, _idx1 = _vmix_carton_pick_index(len(rows), str(fecha_iso), action=action, index_override=index_override)
        elif "_vmix_carton_state_read" in globals() and callable(_vmix_carton_state_read):
            state = _vmix_carton_state_read() or {}
            by_fecha = state.get("por_fecha") if isinstance(state.get("por_fecha"), dict) else {}
            raw = by_fecha.get(str(fecha_iso), state.get("actual", len(rows)))
            try:
                idx1 = int(raw)
            except Exception:
                idx1 = len(rows)
            if idx1 < 1:
                idx1 = 1
            if idx1 > len(rows):
                idx1 = len(rows)
            idx0 = idx1 - 1
    except Exception:
        idx0 = len(rows) - 1

    if idx0 < 0:
        idx0 = 0
    if idx0 >= len(rows):
        idx0 = len(rows) - 1
    return rows[idx0]


def _gdx_build_root(fecha_iso: str = "") -> ET.Element:
    fecha_iso = _gdx_str(fecha_iso) or (_get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else date.today().isoformat())
    idx_map = _gdx_num_fig_map(fecha_iso)
    raw_winners = _gdx_pick_winners(fecha_iso)
    rows = []
    seen = set()
    for w in (raw_winners or []):
        if not isinstance(w, dict):
            continue
        row = _gdx_enrich_winner(fecha_iso, w, idx_map)
        key = (row.get("figura", "").lower(), row.get("serie", ""), row.get("boleto", ""))
        if key in seen:
            continue
        seen.add(key)
        if any(_gdx_str(row.get(k)) for k in ("figura", "boleto", "vendedor", "cliente_nombre", "sector")):
            rows.append(row)

    action = _gdx_str(request.args.get("accion") or request.args.get("a") or request.args.get("action")) if request else ""
    idx_raw = _gdx_str(request.args.get("index") or request.args.get("idx")) if request else ""
    try:
        idx_override = int(idx_raw) if idx_raw else None
    except Exception:
        idx_override = None

    last = _gdx_current_row_from_state(rows, fecha_iso, action=action, index_override=idx_override) if rows else {f: "" for f in _GDX_FIELDS}
    if not _gdx_str(last.get("texto_completo")):
        last["texto_completo"] = "SIN GANADOR AUN"

    line_rows = _gdx_build_line_rows(last, bool(rows))
    root = ET.Element("ganadores_detalle", {"fecha": str(fecha_iso), "total": str(len(rows))})

    # vMix Table: una sola columna (#text) y varias filas.
    # Repetimos nodos directos <linea>texto</linea> para que el Data Source
    # muestre una sola columna con varias filas separadas.
    for item in line_rows:
        ET.SubElement(root, "linea").text = _gdx_str(item.get("texto"))

    ultimo = ET.SubElement(root, "ultimo")
    for f in _GDX_FIELDS:
        ET.SubElement(ultimo, f).text = _gdx_str(last.get(f))

    detalles = ET.SubElement(root, "detalles")
    for idx, row in enumerate(rows, start=1):
        fila_attrs = {"index": str(idx)}
        for f in _GDX_FIELDS:
            fila_attrs[f] = _gdx_str(row.get(f))
        fila = ET.SubElement(detalles, "fila", fila_attrs)
        for f in _GDX_FIELDS:
            ET.SubElement(fila, f).text = _gdx_str(row.get(f))

    return root

def _gdx_write_files(root_elem: ET.Element):
    xml_bytes = ET.tostring(root_elem, encoding="utf-8")
    for path in [VMIX_GANADORES_DETALLE_XML, VMIX_GANADORES_DETALLE_XML_PUBLIC]:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
                f.write(xml_bytes)
        except Exception:
            pass

def _gdx_response_impl():
    fecha = _gdx_str(request.args.get("fecha")) or (_get_sorteo_fecha() if callable(globals().get("_get_sorteo_fecha")) else date.today().isoformat())
    root = _gdx_build_root(fecha)
    try:
        _gdx_write_files(root)
    except Exception:
        pass
    return _vmix_xml_response(root)

def _gdx_alias_impl():
    return _gdx_response_impl()

try:
    app.add_url_rule("/juego/ganadores_detalle.xml", "juego_ganadores_detalle_xml", _gdx_response_impl, methods=["GET"])
except Exception:
    pass

try:
    app.add_url_rule("/juego/xml/ganadores_detalle", "juego_xml_ganadores_detalle", _gdx_alias_impl, methods=["GET"])
except Exception:
    pass

# Agrega el link al JSON de enlaces vMix sin romper la ruta existente
def _gdx_patch_links_json():
    endpoint_name = None
    for name in ("juego.juego_vmix_links_json", "juego_vmix_links_json"):
        if name in app.view_functions:
            endpoint_name = name
            break
    if not endpoint_name:
        return

    original = app.view_functions.get(endpoint_name)
    if not callable(original):
        return

    def _wrapped():
        resp = original()
        try:
            data = resp.get_json(silent=True) if hasattr(resp, "get_json") else None
        except Exception:
            data = None
        if not isinstance(data, dict):
            return resp
        try:
            base = data.get("base_url") or _vmix_base_url()
        except Exception:
            base = _vmix_base_url()
        links = data.get("links") or {}
        links["ganadores_detalle"] = f"{base}/juego/ganadores_detalle.xml"
        data["links"] = links
        new_resp = jsonify(data)
        for k, v in getattr(resp, "headers", {}).items():
            if k.lower() not in ("content-length", "content-type"):
                new_resp.headers[k] = v
        return new_resp

    app.view_functions[endpoint_name] = _wrapped

try:
    _gdx_patch_links_json()
except Exception:
    pass

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)






