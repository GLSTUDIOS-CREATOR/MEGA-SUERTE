# ====== PARCHE DE ARRANQUE (PÉGALO AL INICIO DE app.py) ======
# Evita NameError en 'mm' aunque el import real no esté disponible
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
import shutil
import random
import pandas as pd
import qrcode
import xml.etree.ElementTree as ET
from datetime import date, datetime
from io import BytesIO
from flask import Flask, request, render_template, send_file, redirect, url_for, flash, session
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

# Unidades seguras: evita reimportar mm (ya con fallback) y crea cm/inch si falta reportlab
try:
    from reportlab.lib.units import cm as _cm, inch as _inch
    cm, inch = _cm, _inch
except Exception:
    cm, inch = 10 * mm, 25.4 * mm

app = Flask(__name__)
app.secret_key = 'super_secreto_bingo_2025'

# ===== DEBUG PROVISORIO (puedes borrarlo cuando termine la depuración) =====
import traceback, json

@app.route("/debug_persist")
def debug_persist():
    try:
        info = {
            "DATA_DIR_env": os.environ.get("DATA_DIR"),
            "USUARIOS_XML": USUARIOS_XML if 'USUARIOS_XML' in globals() else None,
            "usuarios_exists": os.path.exists(USUARIOS_XML) if 'USUARIOS_XML' in globals() else None,
            "cwd": os.getcwd(),
        }
        return "<pre>" + json.dumps(info, indent=2) + "</pre>"
    except Exception:
        return "<pre>debug_persist error:\n" + traceback.format_exc() + "</pre>", 500

@app.errorhandler(Exception)
def all_errors(e):
    return "<pre>" + traceback.format_exc() + "</pre>", 500
# ===== FIN DEBUG PROVISORIO =====

from functools import wraps
from flask import session, redirect, url_for

def require_session(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'usuario' not in session:
            # ⚠️ tu endpoint real de login se llama _login_demo (según el error)
            return redirect(url_for('_login_demo'))
        return f(*args, **kwargs)
    return wrapper

# ─── ARCHIVOS Y DIRECTORIOS ────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ❗️NO definas USUARIOS_XML aquí. Se define más abajo en “Persistencia”.
AVATAR_DIR = os.path.join('static', 'avatars')

# ==== PERSISTENCIA (Render / Local) ====
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "DATA"))
os.makedirs(DATA_DIR, exist_ok=True)
REINTEGROS_DIR = os.path.join(DATA_DIR, "REINTEGROS")
os.makedirs(REINTEGROS_DIR, exist_ok=True)

def _persist(*rel):
    path = os.path.join(DATA_DIR, *rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

def _seed(src_rel, dst_abs):
    src_abs = os.path.join(BASE_DIR, src_rel)
    if not os.path.exists(dst_abs) and os.path.exists(src_abs):
        shutil.copy2(src_abs, dst_abs)

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
LOGS_CAJA_XML           = _persist('static', 'LOGS', 'caja.xml')
LOGS_IMPRESIONES_XML    = _persist('static', 'LOGS', 'impresiones.xml')
CONTAB_BANCOS_XML       = _persist('static', 'CONTABILIDAD', 'bancos.xml')
CONTAB_GASTOS_XML       = _persist('static', 'CONTABILIDAD', 'gastos.xml')
CONTAB_SUELDOS_XML      = _persist('static', 'CONTABILIDAD', 'sueldos.xml')
CONTAB_VENTAS_XML       = _persist('static', 'CONTABILIDAD', 'ventas.xml')

VENDEDORES_XML  = _persist('static', 'db', 'vendedores.xml')
IMPRESIONES_XML = LOGS_IMPRESIONES_XML

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
    ('static/LOGS/caja.xml',                LOGS_CAJA_XML),
    ('static/LOGS/impresiones.xml',         LOGS_IMPRESIONES_XML),
    ('static/CONTABILIDAD/bancos.xml',      CONTAB_BANCOS_XML),
    ('static/CONTABILIDAD/gastos.xml',      CONTAB_GASTOS_XML),
    ('static/CONTABILIDAD/sueldos.xml',     CONTAB_SUELDOS_XML),
    ('static/CONTABILIDAD/ventas.xml',      CONTAB_VENTAS_XML),
]:
    _seed(src, dst)

def write_text_atomic(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

ROLES = [
    ('superadmin', 'Super Administrador'),
    ('admin', 'Administrador'),
    ('socio', 'Socio'),
    ('cobrador', 'Cobrador'),
    ('jugador', 'Jugador'),
    ('impresion', 'Impresión'),
]

# ─── UTILIDADES XML (USUARIOS) ─────────────────────────────
def leer_usuarios():
    try:
        if not os.path.exists(USUARIOS_XML):
            seed_src = os.path.join(BASE_DIR, 'usuarios', 'usuarios.xml')
            os.makedirs(os.path.dirname(USUARIOS_XML), exist_ok=True)
            if os.path.exists(seed_src):
                shutil.copy2(seed_src, USUARIOS_XML)
            else:
                root = ET.Element('usuarios')
                ET.ElementTree(root).write(USUARIOS_XML, encoding='utf-8', xml_declaration=True)
                return []
        tree = ET.parse(USUARIOS_XML)
        root = tree.getroot()
        usuarios = []
        for elem in root.findall('usuario'):
            usuarios.append({
                'nombre': elem.findtext('nombre', default=''),
                'clave':  elem.findtext('clave',  default=''),
                'rol':    elem.findtext('rol',    default='jugador'),
                'email':  elem.findtext('email',  default=''),
                'estado': elem.findtext('estado', default='activo'),
                'avatar': elem.findtext('avatar', default='avatar-male.png'),
            })
        return usuarios
    except Exception as e:
        print("ERROR leer_usuarios:", e)
        return []

def guardar_usuarios(lista):
    try:
        root = ET.Element('usuarios')
        for u in lista:
            e = ET.SubElement(root, 'usuario')
            ET.SubElement(e, 'nombre').text = u.get('nombre', '')
            ET.SubElement(e, 'clave') .text = u.get('clave',  '')
            ET.SubElement(e, 'rol')   .text = u.get('rol',    'jugador')
            ET.SubElement(e, 'email') .text = u.get('email',  '')
            ET.SubElement(e, 'estado').text = u.get('estado', 'activo')
            ET.SubElement(e, 'avatar').text = u.get('avatar', 'avatar-male.png')
        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        os.makedirs(os.path.dirname(USUARIOS_XML), exist_ok=True)
        tmp = f"{USUARIOS_XML}.tmp"
        with open(tmp, 'wb') as f:
            f.write(xml_bytes)
        os.replace(tmp, USUARIOS_XML)
        return True
    except Exception as e:
        print("ERROR guardar_usuarios:", e)
        return False





# ===================== DASHBOARD (HOY) =====================
# Bloque auto-contenido. Si tu app ya define constantes o helpers
# (p.ej. CAJA_XML, get_configuracion_dia, _iter_impresiones) se usan tal cual.
# No rompe nada existente.

import os
import xml.etree.ElementTree as ET
from datetime import date, datetime
from flask import render_template, jsonify, request, session, redirect, url_for

# --- Rutas/archivos (respetamos existentes si ya están definidos) -------------
CAJA_XML              = globals().get('CAJA_XML',              os.path.join('static', 'CAJA', 'caja.xml'))
VENDEDORES_XML        = globals().get('VENDEDORES_XML',        os.path.join('static', 'db', 'vendedores.xml'))
ASIGNACIONES_XML      = globals().get('ASIGNACIONES_XML',      os.path.join('static', 'db', 'asignaciones.xml'))
IMPRESION_LOG         = globals().get('IMPRESION_LOG',         os.path.join('static', 'IMPRESION', 'log.xml'))
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
        return redirect(url_for('login'))
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
    return redirect(url_for('login'))

# ─── SECCIÓN DE USUARIOS ──────────────────
@app.route('/usuarios')
def usuarios():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    lista_usuarios = leer_usuarios()
    roles = [r[1] for r in ROLES]
    return render_template(
        'usuarios.html',
        usuarios=lista_usuarios,
        roles=roles,
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
    estado = 'activo'

    usuarios = leer_usuarios()
    existe = False
    for u in usuarios:
        if u['nombre'] == nombre:
            u['clave'] = clave
            u['rol'] = rol
            u['email'] = email
            u['avatar'] = avatar_filename
            u['estado'] = estado
            existe = True
    if not existe:
        usuarios.append({
            'nombre': nombre,
            'clave': clave,
            'rol': rol,
            'email': email,
            'avatar': avatar_filename,
            'estado': estado
        })
    guardar_usuarios(usuarios)
    flash('Usuario guardado correctamente', 'success')
    return redirect(url_for('usuarios'))

@app.route('/usuarios/editar/<nombre>', methods=['GET', 'POST'])
def editar_usuario(nombre):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    user = obtener_usuario(nombre)
    if not user:
        flash(f'Usuario "{nombre}" no encontrado', 'error')
        return redirect(url_for('usuarios'))
    roles = [r[1] for r in ROLES]
    if request.method == 'POST':
        user['clave'] = request.form['password']
        user['rol'] = request.form['rol']
        user['email'] = request.form.get('email', '')
        user['avatar'] = request.form.get('avatar_select', user['avatar'])
        usuarios = leer_usuarios()
        for u in usuarios:
            if u['nombre'] == nombre:
                u.update(user)
        guardar_usuarios(usuarios)
        flash('Usuario editado correctamente', 'success')
        return redirect(url_for('usuarios'))
    return render_template(
        'usuarios_editar.html',
        user=user,
        roles=[r[1] for r in ROLES],
        usuario=session['usuario'],
        rol=session['rol'],
        avatar=session.get('avatar', 'avatar-male.png')
    )




# ================== IMPORTS ==================
# ================== IMPORTS ==================
import os, random, csv, math
from io import BytesIO, StringIO
from datetime import datetime, date
from threading import Lock

import pandas as pd
from flask import (
    request, send_file, render_template, redirect,
    url_for, flash, jsonify, session
)
from PyPDF2 import PdfMerger

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import qrcode
import xml.etree.ElementTree as ET

# Si ya tienes require_session en tu proyecto, se usará ese.
try:
    require_session
except NameError:
    def require_session(fn):
        def _wrap(*a, **k): return fn(*a, **k)
        _wrap.__name__ = fn.__name__
        return _wrap

# ---------- utilidades seguras ----------
def _to_int(v, default=0):
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _read_df_for_series(archivo: str) -> pd.DataFrame:
    """Lee XLSX o CSV como texto; lanza FileNotFoundError si no existe."""
    path = os.path.join(DATA_DIR, archivo)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe el archivo de serie: {archivo}")
    if archivo.lower().endswith(".csv"):
        return pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
    return pd.read_excel(path, dtype=str).fillna("")

def fecha_ddmmyyyy(fecha_iso: str) -> str:
    """YYYY-MM-DD -> 'DD-MM-YYYY'."""
    try:
        return datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return fecha_iso

def format_money(valor) -> str:
    """$1 si es entero; $1.25 si tiene decimales."""
    try:
        v = float(str(valor).replace(",", "."))
        if abs(v - int(v)) < 1e-9:
            return f"${int(v)}"
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"${s}"
    except Exception:
        return f"${valor}"

# ─── CONFIGURACIONES PDF ──────────────────────────────
BLEED    = 5 * mm
w, h     = A4
usable_w = w - 1 * BLEED
usable_h = h - 1 * BLEED

# ── CALIBRACIÓN GLOBAL ──
OFFSET_X = -20
OFFSET_Y = 5

# ── RUTAS y CONSTANTES ──
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR       = os.path.join(BASE_DIR, "DATA")
REINTEGROS_DIR = os.path.join(DATA_DIR, "REINTEGROS")
STATIC_DIR     = os.path.join(BASE_DIR, "static")
LOGS_DIR       = os.path.join(STATIC_DIR, "LOGS")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REINTEGROS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ── Fuente Ultra-Black (si está disponible) ──
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

MARGEN_IZQ     = 20
MARGEN_SUP     = 60
ESPACIO_X      = 60
ESPACIO_Y      = 85
COLUMNAS       = 2
FILAS          = 4

SIZE_NUM       = 24
SIZE_INFO      = 12
SIZE_ID        = 12          # tamaño normal (no usado para el ID grande)
SIZE_ID_BIG    = 18          # ► número de boleto grande y en Ultra-Black
SIZE_VALOR     = 15
REINTEGRO_W    = 41
REINTEGRO_H    = 41

DELTA_Y_FILA_3 = 2
DELTA_Y_FILA_4 = 5

SERIE_MAP = {
    "Srs_ib1.xlsx":   "V",
    "Srs_ib2.xlsx":   "+",
    "Srs_ib3.xlsx":   "&",
    "Srs_Manila.xlsx":"M"
}

# ── OFFSETS EN CÓDIGO (boleto 0…7) ──
# Ajusta aquí X/Y para grid, info y reintegro de cada boleto:
per_cell_offsets = {
    0: {"grid_x": -1, "grid_y": 28,  "info_x": 125,  "info_y": 48, "rein_x": 22,  "rein_y": 55},
    1: {"grid_x": -35, "grid_y": 28,  "info_x": 90,  "info_y": 48, "rein_x": -10, "rein_y": 55},
    2: {"grid_x": -1, "grid_y": 80,  "info_x": 125,  "info_y": 98, "rein_x": 22,  "rein_y": 10},
    3: {"grid_x": -35, "grid_y": 80,  "info_x": 90,  "info_y": 98, "rein_x": -10, "rein_y": 10},
    4: {"grid_x": -1, "grid_y": 130, "info_x": 125,   "info_y":150, "rein_x": 22,  "rein_y": -45},
    5: {"grid_x": -35, "grid_y": 130, "info_x": 90,  "info_y": 150, "rein_x": -10, "rein_y": -45},
    6: {"grid_x": -1, "grid_y": 185, "info_x": 125,  "info_y": 200, "rein_x": 22,  "rein_y": -95},
    7: {"grid_x": -35, "grid_y": 185, "info_x": 90,  "info_y": 200, "rein_x": -10, "rein_y": -95},
}

# ================== LOG DE IMPRESIONES (XML) ==================
IMPRESIONES_XML = os.path.join(LOGS_DIR, "impresiones.xml")
_LOG_LOCK = Lock()

def _ensure_logs_file():
    if not os.path.exists(IMPRESIONES_XML):
        root = ET.Element('impresiones')
        tree = ET.ElementTree(root)
        with open(IMPRESIONES_XML, 'wb') as f:
            tree.write(f, encoding='utf-8', xml_declaration=True)

def _read_logs_root():
    _ensure_logs_file()
    tree = ET.parse(IMPRESIONES_XML)
    return tree, tree.getroot()

def _write_logs_tree(tree):
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(IMPRESIONES_XML, encoding='utf-8', xml_declaration=True)

def _iter_impresiones():
    _, root = _read_logs_root()
    for n in root.findall('impresion'):
        yield n

def _series_impresas_en_fecha(fecha_yyyy_mm_dd):
    """Conjunto de series usadas para imprimir *boletos* en esa fecha."""
    s = set()
    for imp in _iter_impresiones():
        if (imp.get('tipo') or '').lower() != 'boletos':
            continue
        if (imp.findtext('fecha_sorteo') or '') != fecha_yyyy_mm_dd:
            continue
        s.add(imp.get('serie_archivo') or '')
    return s

def _append_log_impresion_boletos(
    *, usuario, serie_archivo, desde, hasta, fecha_sorteo, total_boletos,
    valor, telefono, reintegro_especial, cant_reintegro_especial,
    incluir_aleatorio, excedente=0, lote=''
):
    """Registra boletos impresos; además guarda total_planillas derivado."""
    with _LOG_LOCK:
        tree, root = _read_logs_root()
        elem = ET.Element('impresion', attrib={
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
        # nuevo: total de planillas derivado del tamaño estándar
        try:
            tp = int(math.ceil(int(total_boletos) / 20.0))  # 20 boletos por planilla
        except Exception:
            tp = ''
        add('total_planillas', tp)
        add('excedente', '1' if excedente else '0')
        add('lote', lote)
        root.append(elem)
        _write_logs_tree(tree)

def _append_log_impresion_planilla(
    *, usuario, serie_archivo, desde, hasta, fecha_planilla,
    lote_text='', excedente=0
):
    """Registra cada *planilla* impresa (1 registro por hoja)."""
    with _LOG_LOCK:
        tree, root = _read_logs_root()
        elem = ET.Element('impresion', attrib={
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
        add('total_planillas', 1)  # una hoja por registro
        root.append(elem)
        _write_logs_tree(tree)

def get_printed_ids_for_day(fecha_yyyy_mm_dd, serie_archivo):
    """IDs (strings) ya impresos ese día/serie según logs de 'boletos'."""
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

# ─── LOGS: helpers + rutas (HTML, CSV, JSON) ─────────────────
_LOG_COLS = [
    "fecha_hora","usuario","tipo","serie_archivo","desde","hasta",
    "valor","telefono","fecha_sorteo","reintegro_especial",
    "cant_reintegro_especial","incluir_aleatorio",
    "fecha_planilla","total_boletos","total_planillas",
    "excedente","lote"
]

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

@app.route('/logs-impresion', endpoint='logs_impresion_v2')
def logs_impresion_v2():
    rows = _get_log_rows()
    head = ''.join(f'<th style="padding:6px;border:1px solid #ccc;background:#f5f5f5">{c}</th>' for c in _LOG_COLS)
    trs = []
    for r in rows:
        tds = ''.join(f'<td style="padding:6px;border:1px solid #eee">{r.get(c,"")}</td>' for c in _LOG_COLS)
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
      <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;min-width:1100px">
        <thead><tr>{head}</tr></thead>
        <tbody>{body}</tbody>
      </table>
    </body>
    </html>
    """
    return html

@app.route('/logs-impresion.csv', endpoint='logs_impresion_csv_v2')
def logs_impresion_csv_v2():
    rows = _get_log_rows()
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=_LOG_COLS)
    writer.writeheader()
    writer.writerows(rows)
    csv_data = buf.getvalue()
    buf.close()
    return (
        csv_data,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=logs_impresion.csv",
        },
    )

@app.route('/logs-impresion.json', endpoint='logs_impresion_json_v2')
def logs_impresion_json_v2():
    rows = _get_log_rows()
    return jsonify(rows=rows, count=len(rows))

# ================== GENERADORES PDF ==================
def generar_pdf_boletos_excel(
    ids, registros, valor, telefono,
    nombre, reintegro_especial,
    cant_especial, reintegros,
    incluir_aleatorio, fecha_sorteo
):
    """Genera un PDF con los boletos en páginas de 8 (2x4)."""
    buf = BytesIO()

    c = canvas.Canvas(buf, pagesize=A4)
    c.translate(OFFSET_X, OFFSET_Y)  # aplicar en la primera página

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
                        qr = qrcode.make(f"{ids[pos]}|{fecha_sorteo}")
                        buf_qr = BytesIO(); qr.save(buf_qr, 'PNG'); buf_qr.seek(0)
                        c.drawImage(ImageReader(buf_qr), cx + 2, cy + 2, size - 4, size - 4)
                    else:
                        v = str(row.get(f"{letra}{r+1}", "-"))
                        c.drawCentredString(cx + size / 2, cy + size * 0.28, v)

            # ► Texto inferior: ID grande (Ultra-Black) + fecha dd-mm-YYYY + valor en negritas
            boleto_text = f"{ids[pos]}{SERIE_MAP.get(nombre, nombre)}"
            x_info = x0 + offs['info_x']
            y_info = y0 - size * 5 + offs['info_y']

            # ID grande
            c.setFont(ULTRA_BLACK_FONT, SIZE_ID_BIG)
            c.drawString(x_info, y_info, boleto_text)

            # Un poco pegado (4 pt)
            dx_id = c.stringWidth(boleto_text, ULTRA_BLACK_FONT, SIZE_ID_BIG) + 4

            # Fecha en regular
            c.setFont('Helvetica', SIZE_INFO)
            fecha_str = f"| {fecha_num} | "
            c.drawString(x_info + dx_id, y_info, fecha_str)

            # Valor en negritas
            dx_fecha = c.stringWidth(fecha_str, 'Helvetica', SIZE_INFO)
            c.setFont('Helvetica-Bold', SIZE_INFO)
            c.drawString(x_info + dx_id + dx_fecha, y_info, precio_str)

            # Reintegro
            img = None
            if pos in esp_idx and reintegro_especial:
                img = reintegro_especial
            elif pos in ale_idx and reintegros:
                others = [r for r in reintegros if r != reintegro_especial]
                img = random.choice(others) if others else None

            if img:
                c.drawImage(
                    ImageReader(os.path.join(REINTEGROS_DIR, img)),
                    x0 + offs['rein_x'], y0 - offs['rein_y'],
                    REINTEGRO_W, REINTEGRO_H, mask='auto'
                )

        c.showPage()
        c.translate(OFFSET_X, OFFSET_Y)  # <- re-aplicar en cada nueva hoja

    c.save()
    buf.seek(0)
    return buf

def generar_pdf_planilla(ids, serie_archivo, vendedor, fecha, inicio, fin, serie_map, num_planilla=None):
    from io import BytesIO
    from datetime import datetime
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os, qrcode

    LOGO_LEFT_PAD        = 0.1
    DATE_GAP_AFTER_LOGO  = 1
    DATE_WIDTH_FACTOR    = 0.78
    DATE_MIN_WIDTH       = 220
    QR_HDR_OFFSET_Y      = 5

    PN_W                 = 54
    PN_H                 = 22
    PN_RADIUS            = 6
    PN_UNDER_QR_GAP      = 2
    PN_FONT_SIZE         = 15

    PN_FONT_NAME = "Helvetica-Bold"
    extra_black_candidates = [
        os.path.join("static", "fonts", "Montserrat-ExtraBold.ttf"),
        os.path.join("static", "fonts", "Inter-ExtraBold.ttf"),
        os.path.join("static", "fonts", "Poppins-Black.ttf"),
    ]
    for fp in extra_black_candidates:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("ExtraBlackLocal", fp))
                PN_FONT_NAME = "ExtraBlackLocal"
                break
            except Exception:
                pass

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

    def qr_cadena(tipo, desde, hasta, serie):
        return f"SORTEO{fecha_limpia}{tipo}A{desde}A{hasta}{serie}"

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    ancho, alto = landscape(A4)

    M_LEFT, M_RIGHT, M_BOTTOM = 12, 20, 20
    GUTTER        = 28
    HEADER_H      = 86
    QR_SIZE_HDR   = 56
    QR_SIZE_CENTER= min(GUTTER + 30, 50)

    HALF_W  = (ancho - M_LEFT - M_RIGHT - GUTTER) / 2
    TOP_Y   = alto - HEADER_H - 10
    BOT_Y   = M_BOTTOM
    AVAIL_H = TOP_Y - BOT_Y

    NUM_ROWS = 21
    ROW_H    = AVAIL_H / NUM_ROWS

    X_L, X_R = M_LEFT, M_LEFT + HALF_W + GUTTER
    TABLE_W  = HALF_W - 20
    PAD      = 10

    LOGO_PATH = os.path.join("static", "golpe_suerte_logo.png")
    FB, FR    = "Helvetica-Bold", "Helvetica"

    left_index  = (left_desde  - 1) // 20 + 1
    right_index = (right_desde - 1) // 20 + 1

    def draw_header(x0, sheet_num, tipo, desde, hasta):
        from reportlab.lib import colors
        c.setFillColorRGB(0.92, 0.92, 0.92)
        c.rect(x0, alto - HEADER_H, HALF_W, HEADER_H, fill=1, stroke=0)
        c.setFillColor(colors.black)

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

        gap = DATE_GAP_AFTER_LOGO
        right_reserved = 6 + QR_SIZE_HDR + 6 + PN_W + 6
        avail_for_date = HALF_W - ((logo_x - x0) + dw + gap + right_reserved)
        date_w = max(DATE_MIN_WIDTH, min(avail_for_date, HALF_W * DATE_WIDTH_FACTOR))
        date_h_top = 26
        date_h_bot = 26
        space = 6
        total_h = date_h_top + space + date_h_bot
        bx = logo_x + dw + gap
        by = alto - HEADER_H + (HEADER_H - total_h) / 2

        c.setLineWidth(1.5)
        c.setFillColor(colors.white)
        c.roundRect(bx, by + date_h_bot + space, date_w, date_h_top, 4, stroke=1, fill=1)
        c.roundRect(bx, by,                     date_w, date_h_bot, 4, stroke=1, fill=1)
        c.setFillColor(colors.black)
        c.setFont(FB, 10)
        c.drawCentredString(bx + date_w/2, by + date_h_bot/2 - 4, formatted_date)

        data_qr = qr_cadena(tipo, desde, hasta, serie_letra)
        buf = BytesIO(); qrcode.make(data_qr).save(buf, format="PNG"); buf.seek(0)
        qx = x0 + HALF_W - QR_SIZE_HDR - 4
        qy_base = alto - HEADER_H + (HEADER_H - QR_SIZE_HDR) / 2
        qy_top  = alto - QR_SIZE_HDR - 3
        qy = min(qy_base + 5, qy_top)
        c.drawImage(ImageReader(buf), qx, qy, QR_SIZE_HDR, QR_SIZE_HDR)

        px = qx + (QR_SIZE_HDR - PN_W) / 2
        py = qy - PN_H - 2
        c.setFillColor(colors.white)
        c.setLineWidth(0)
        c.roundRect(px, py, PN_W, PN_H, 6, stroke=0, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 15)
        c.drawCentredString(px + PN_W/2, py + PN_H/2 - 4, str(sheet_num))

    draw_header(X_L, left_index,  "L1", left_desde,  left_hasta)
    draw_header(X_R, right_index, "L2", right_desde, right_hasta)

    c.setLineWidth(2)
    c.line(X_R, TOP_Y, X_R, BOT_Y)

    data_full = qr_cadena("RG", full_desde, full_hasta, serie_letra)
    buf2 = BytesIO(); qrcode.make(data_full).save(buf2, format="PNG"); buf2.seek(0)
    cx = X_R - (GUTTER/2) - (QR_SIZE_CENTER/2)
    cy = BOT_Y + (AVAIL_H/2) - (QR_SIZE_CENTER/2)
    c.drawImage(ImageReader(buf2), cx, cy, QR_SIZE_CENTER, QR_SIZE_CENTER)

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

# ============== RUTA PRINCIPAL: /impresion =================
@app.route('/impresion', methods=['GET', 'POST'], endpoint='impresion')
@require_session
def impresion():
    # Datos para GET
    files = sorted(f for f in os.listdir(DATA_DIR)
                   if f.lower().endswith(('.xlsx', '.csv')))
    series     = [(f, SERIE_MAP.get(f, f)) for f in files]
    reintegros = sorted(f for f in os.listdir(REINTEGROS_DIR)
                        if f.lower().endswith('.png')) if os.path.exists(REINTEGROS_DIR) else []
    fecha_hoy  = date.today().strftime('%Y-%m-%d')

    if request.method != 'POST':
        return render_template(
            'impresion_boletos_excel.html',
            series=series,
            reintegros=reintegros,
            fecha_hoy=fecha_hoy,
            usuario=session.get('usuario',''),
            rol=session.get('rol',''),
            avatar=session.get('avatar','avatar-male.png'),
            permisos=session.get('permisos', [])
        )

    # -------- POST ----------
    form_type = (request.form.get('form_type') or '').strip().lower()

    # ── BOLETOS ─────────────────────────────────────────────
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

        if not serie_archivo:
            flash('Selecciona una serie para imprimir boletos.', 'warning')
            return redirect(url_for('impresion'))

        # Bloqueo: no mezclar series el mismo día
        series_prev = _series_impresas_en_fecha(fecha_str)
        if series_prev and (serie_archivo not in series_prev):
            otra = ', '.join(sorted(series_prev))
            flash(f"Ya se imprimieron boletos para {fecha_str} con la serie: {otra}. "
                  f"No se permite imprimir el mismo día con otra serie.", 'danger')
            return redirect(url_for('impresion'))

        # Cargar IDs
        try:
            df = _read_df_for_series(serie_archivo)
        except Exception as e:
            flash(str(e), 'danger')
            return redirect(url_for('impresion'))

        id_col  = df.columns[0]
        all_ids = df[id_col].astype(str).tolist()
        if not all_ids:
            flash('La serie seleccionada no contiene datos.', 'danger')
            return redirect(url_for('impresion'))

        # Si no envían start/end, usa todo el archivo
        if not start:
            start = all_ids[0]
        if not end:
            end = all_ids[-1]

        if start not in all_ids:
            flash(f'Boleto inicial “{start}” no existe en la serie.', 'danger')
            return redirect(url_for('impresion'))
        if end not in all_ids:
            flash(f'Boleto final “{end}” no existe en la serie.', 'danger')
            return redirect(url_for('impresion'))

        s_idx = all_ids.index(start)
        e_idx = all_ids.index(end) + 1
        ids       = all_ids[s_idx:e_idx]
        registros = df.iloc[s_idx:e_idx].to_dict('records')

        # Log
        try:
            _append_log_impresion_boletos(
                usuario=session.get('usuario', ''),
                serie_archivo=serie_archivo,
                desde=start, hasta=end,
                fecha_sorteo=fecha_str,
                total_boletos=len(ids),
                valor=valor, telefono=telefono,
                reintegro_especial=rein_esp,
                cant_reintegro_especial=cntesp,
                incluir_aleatorio=incA,
            )
        except Exception as e:
            print('[WARN] No se pudo escribir en impresiones.xml (boletos):', e)

        # PDF
        buf_b = generar_pdf_boletos_excel(
            ids, registros, valor, telefono,
            serie_archivo, rein_esp, cntesp,
            reintegros, incA, fecha_str
        )
        return send_file(buf_b, download_name='boletos_bingo.pdf', as_attachment=True)

    # ── PLANILLAS ───────────────────────────────────────────
    if form_type == 'planilla':
        archivo = (request.form.get('serie_archivo_planilla') or '').strip()
        inicio  = _to_int(request.form.get('planilla_inicio'), 0)
        fin     = _to_int(request.form.get('planilla_fin'), 0)
        fecha_p = (request.form.get('fecha_planilla') or fecha_hoy).strip()

        # >>> CORREGIDO: 'or', no 'o r'
        if not archivo or inicio <= 0 or fin < inicio:
            flash('Completa serie e inicio/fin válidos para la planilla.', 'warning')
            return redirect(url_for('impresion'))

        try:
            df2 = _read_df_for_series(archivo)
        except Exception as e:
            flash(str(e), 'danger')
            return redirect(url_for('impresion'))

        id_col  = df2.columns[0]
        all_ids = df2[id_col].astype(str).tolist()
        if not all_ids:
            flash('La serie seleccionada no contiene datos.', 'danger')
            return redirect(url_for('impresion'))

        # Sanea límites contra el tamaño real del archivo
        inicio = max(1, inicio)
        fin    = min(len(all_ids), fin)

        # Ensambla PDF por bloques de 40
        merger = PdfMerger()
        chunk  = 40
        total  = fin - inicio + 1
        for off in range(0, total, chunk):
            page_start = inicio + off
            page_end   = min(page_start + chunk - 1, fin)
            sub_ids    = all_ids[page_start-1:page_end]

            try:
                excedente = 1 if len(sub_ids) < chunk else 0
                _append_log_impresion_planilla(
                    usuario=session.get('usuario',''),
                    serie_archivo=archivo,
                    desde=page_start, hasta=page_end,
                    fecha_planilla=fecha_p,
                    lote_text=f"{page_start}-{page_end}",
                    excedente=excedente
                )
            except Exception as e:
                print('[WARN] No se pudo escribir en impresiones.xml (planilla):', e)

            buf = generar_pdf_planilla(
                sub_ids, archivo, session.get('usuario',''),
                fecha_p, page_start, page_end, SERIE_MAP
            )
            merger.append(buf)

        salida = BytesIO()
        merger.write(salida)
        salida.seek(0)
        return send_file(salida, download_name=f'planilla_{inicio}_a_{fin}.pdf', as_attachment=True)

    # Si llegó un form_type desconocido
    flash('Formulario no reconocido.', 'warning')
    return redirect(url_for('impresion'))

# ============== ZIP combinando boletos + planilla =================
@app.route('/descargar_zip', methods=['POST'])
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

    # 🔒 Bloqueo: no permitir serie diferente el mismo día
    series_prev = _series_impresas_en_fecha(fecha_str)
    if series_prev and (nombre_serie not in series_prev):
        otra = ', '.join(sorted(series_prev))
        flash(f"Ya se imprimieron boletos para {fecha_str} con la serie: {otra}. "
              f"No se permite imprimir el mismo día con otra serie.", 'danger')
        return redirect(url_for('impresion'))

    # Cargar IDs
    try:
        df = _read_df_for_series(nombre_serie)
    except Exception as e:
        flash(str(e), 'danger'); return redirect(url_for('impresion'))

    all_ids = df[df.columns[0]].astype(str).tolist()
    if not all_ids:
        flash('La serie no contiene datos.', 'danger'); return redirect(url_for('impresion'))

    if not start: start = all_ids[0]
    if not end:   end   = all_ids[-1]
    if start not in all_ids:
        flash(f'Boleto inicial “{start}” no existe.', 'danger'); return redirect(url_for('impresion'))
    if end not in all_ids:
        flash(f'Boleto final “{end}” no existe.', 'danger'); return redirect(url_for('impresion'))

    s_idx = all_ids.index(start)
    e_idx = all_ids.index(end) + 1
    ids = all_ids[s_idx:e_idx]
    registros = df.iloc[s_idx:e_idx].to_dict('records')

    # PDFs
    buf_boletos = generar_pdf_boletos_excel(
        ids, registros, valor, telefono,
        nombre_serie, rein_esp, cnt_esp,
        [f for f in os.listdir(REINTEGROS_DIR) if f.lower().endswith('.png')],
        incA, fecha_str
    )
    buf_planilla = generar_pdf_planilla(
        ids, nombre_serie, "Vendedor", fecha_str,
        int(start), int(end), SERIE_MAP
    )

    # 📝 LOGS: boletos + 1 planilla
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

    # ZIP
    from zipfile import ZipFile
    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, 'w') as zipf:
        zipf.writestr('boletos.pdf', buf_boletos.getvalue())
        zipf.writestr('planilla.pdf', buf_planilla.getvalue())
    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        download_name="GLSTUDIOS_BOLETOS_PLANILLA.zip",
        as_attachment=True
    )



# ============== OTROS ==============
@app.route('/usuarios/eliminar/<nombre>', methods=['POST'])
def eliminar_usuario_route(nombre):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    eliminar_usuario(nombre)   # función existente en tu app
    flash('Usuario eliminado correctamente', 'success')
    return redirect(url_for('usuarios'))




#vendedores seccion de listas #




VENDEDORES_XML = os.path.join('static', 'db', 'vendedores.xml')
ASIGNACIONES_XML = os.path.join('static', 'db', 'asignaciones.xml')
BOLETOS_POR_PLANILLA = 40  # Cambia esto según tus necesidades

# ----------- FUNCIONES PARA VENDEDORES -----------

VENDEDORES_XML = 'static/db/vendedores.xml'

def cargar_vendedores_xml():
    vendedores = []
    if not os.path.exists(VENDEDORES_XML):
        return vendedores
    tree = ET.parse(VENDEDORES_XML)
    root = tree.getroot()
    for idx, v in enumerate(root.findall('vendedor')):
        vendedores.append({
            'id': idx,  # Es importante para editar/eliminar por posición
            'nombre': v.find('nombre').text,
            'apellido': v.find('apellido').text,
            'seudonimo': v.find('seudonimo').text
        })
    return vendedores



def guardar_vendedor(nombre, apellido, seudonimo):
    tree = ET.parse(VENDEDORES_XML)
    root = tree.getroot()
    v = ET.SubElement(root, 'vendedor')
    ET.SubElement(v, 'nombre').text = nombre
    ET.SubElement(v, 'apellido').text = apellido
    ET.SubElement(v, 'seudonimo').text = seudonimo
    tree.write(VENDEDORES_XML)

def editar_vendedor(idx, nombre, apellido, seudonimo):
    tree = ET.parse(VENDEDORES_XML)
    root = tree.getroot()
    vendedores = root.findall('vendedor')
    if 0 <= idx < len(vendedores):
        v = vendedores[idx]
        v.find('nombre').text = nombre
        v.find('apellido').text = apellido
        v.find('seudonimo').text = seudonimo
        tree.write(VENDEDORES_XML)

def eliminar_vendedor(idx):
    tree = ET.parse(VENDEDORES_XML)
    root = tree.getroot()
    vendedores = root.findall('vendedor')
    if 0 <= idx < len(vendedores):
        root.remove(vendedores[idx])
        tree.write(VENDEDORES_XML)

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
    # ¡Aquí está el detalle!
    vendedores = cargar_vendedores_xml()
    return render_template('vendedores.html', vendedores=vendedores)


# ----------- FUNCIONES PARA ASIGNACIONES -----------


import os
import re
import xml.etree.ElementTree as ET
from datetime import date
from flask import render_template, request, jsonify, session, redirect, url_for

# === Archivos base ===
VENDEDORES_XML       = globals().get('VENDEDORES_XML',       'static/db/vendedores.xml')
ASIGNACIONES_XML     = globals().get('ASIGNACIONES_XML',     'static/db/asignaciones.xml')
IMPRESIONES_XML      = globals().get('IMPRESIONES_XML',      'static/LOGS/impresiones.xml')  # ← LOG de impresión
BOLETOS_POR_PLANILLA = int(globals().get('BOLETOS_POR_PLANILLA', 20))

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
        vendedores.append({
            'nombre': (v.findtext('nombre') or ""),
            'apellido': (v.findtext('apellido') or ""),
            'seudonimo': (v.findtext('seudonimo') or "")
        })
    return vendedores

def leer_asignaciones():
    t, r = _parse_or_none(ASIGNACIONES_XML)
    if r is None:
        t = ET.ElementTree(ET.Element('asignaciones'))
        r = t.getroot()
        t.write(ASIGNACIONES_XML, encoding='utf-8', xml_declaration=True)
    return t, r

def guardar_asignaciones(tree):
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(ASIGNACIONES_XML, encoding='utf-8', xml_declaration=True)

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
def _armar_asignaciones_mostrar(root, fecha):
    asignaciones_mostrar = []
    dia = root.find(f"./dia[@fecha='{fecha}']")
    if dia is not None:
        for v in dia.findall('vendedor'):
            vendedor_info = {
                "nombre": v.attrib.get('nombre', ''),
                "apellido": v.attrib.get('apellido', ''),
                "seudonimo": v.attrib.get('seudonimo', ''),
                "planillas": []  # [{numero, rango, serie}]
            }
            for p in v.findall('planilla'):
                vendedor_info["planillas"].append({
                    "numero": p.attrib.get('numero', ''),
                    "rango":  p.attrib.get('rango', ''),
                    "serie":  p.attrib.get('serie', ''),  # puede venir vacío si eran antiguas
                })
            asignaciones_mostrar.append(vendedor_info)
    return asignaciones_mostrar

def _contar_asignadas_serie(root, fecha, serie_archivo):
    """Cantidad de planillas asignadas para ese día + serie."""
    cnt = 0
    dia = root.find(f"./dia[@fecha='{fecha}']")
    if dia is None: return 0
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
        return redirect(url_for('login'))

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
        asignaciones_mostrar = _armar_asignaciones_mostrar(root, fecha_form)
        tbody_html = render_template(
            'tabla_asignaciones.html',
            vendedores=vendedores,
            asignaciones_mostrar=asignaciones_mostrar,
            fecha_seleccionada=fecha_form,
            boletos_por_planilla=BOLETOS_POR_PLANILLA
        )
        asignadas_serie = _contar_asignadas_serie(root, fecha_form, serie_archivo)
        blanco_serie = max(impresas_serie - asignadas_serie, 0)

        return jsonify(ok=True,
                       tbody=tbody_html,
                       contadores={
                           "impresas_serie": impresas_serie,
                           "asignadas_serie": asignadas_serie,
                           "blanco_serie": blanco_serie
                       })

    # GET: pintar página
    asignaciones_mostrar = _armar_asignaciones_mostrar(root, fecha_seleccionada)
    impresas_serie = planillas_impresas_por_serie_fecha(serie_param, fecha_seleccionada) if serie_param else 0
    asignadas_serie = _contar_asignadas_serie(root, fecha_seleccionada, serie_param) if serie_param else 0
    blanco_serie = max(impresas_serie - asignadas_serie, 0)

    return render_template(
        'asignar_planillas.html',
        vendedores=vendedores,
        fecha_hoy=fecha_hoy,
        fechas_disponibles=sorted([d.attrib['fecha'] for d in root.findall('dia')] + [fecha_hoy]),
        fecha_seleccionada=fecha_seleccionada,
        series_impresas=series_dia,           # ← para el combo de serie
        serie_seleccionada=serie_param,
        impresas_serie=impresas_serie,
        asignadas_serie=asignadas_serie,
        blanco_serie=blanco_serie,
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
    asignaciones_mostrar = _armar_asignaciones_mostrar(root, fecha)
    tbody_html = render_template(
        'tabla_asignaciones.html',
        vendedores=vendedores,
        asignaciones_mostrar=asignaciones_mostrar,
        fecha_seleccionada=fecha,
        boletos_por_planilla=BOLETOS_POR_PLANILLA
    )

    # Recalcular counters por serie+fecha
    impresas_serie = planillas_impresas_por_serie_fecha(serie_archivo, fecha) if serie_archivo else 0
    asignadas_serie = _contar_asignadas_serie(root, fecha, serie_archivo) if serie_archivo else 0
    blanco_serie = max(impresas_serie - asignadas_serie, 0)

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
CAJA_XML = os.path.join('static', 'CAJA', 'caja.xml')
os.makedirs(os.path.dirname(CAJA_XML), exist_ok=True)
if not os.path.exists(CAJA_XML):
    ET.ElementTree(ET.Element('caja')).write(CAJA_XML, encoding='utf-8', xml_declaration=True)

# Si estos símbolos no existen en este módulo, los definimos aquí
if 'VENDEDORES_XML' not in globals():
    VENDEDORES_XML = os.path.join('static', 'db', 'vendedores.xml')
if 'ASIGNACIONES_XML' not in globals():
    ASIGNACIONES_XML = os.path.join('static', 'db', 'asignaciones.xml')
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
        ET.SubElement(cfg, 'valor_boleto').text = "0.50"
        ET.SubElement(cfg, 'comision_vendedor').text = "30.0"
        ET.SubElement(cfg, 'comision_extra_meta').text = "5.0"
        ET.SubElement(cfg, 'meta_boletos').text = "60"
        _guardar_xml(t, CAJA_XML)

    def ffloat(x, d=0.0):
        try: return float(x)
        except: return d

    def fint(x, d=0):
        try: return int(x)
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
    cfg = dia.find('configuracion') or ET.SubElement(dia, 'configuracion')
    for k in ("valor_boleto", "comision_vendedor", "comision_extra_meta", "meta_boletos"):
        node = cfg.find(k) or ET.SubElement(cfg, k)
        node.text = str(data.get(k, node.text or "0"))
    _guardar_xml(t, CAJA_XML)

# ─── VENDEDORES y ASIGNACIONES (lectura) ────────────────────────────────────
def _cargar_vendedores_base():
    """Devuelve dict por seudónimo: { seudonimo: {nombre, apellido, seudonimo} }"""
    vendedores = {}
    if os.path.exists(VENDEDORES_XML):
        _, r = _leer_xml(VENDEDORES_XML)
        for v in r.findall('vendedor'):
            seud = (v.findtext('seudonimo', '') or '').strip()
            if seud:
                vendedores[seud] = {
                    "nombre":   (v.findtext('nombre', '') or '').strip(),
                    "apellido": (v.findtext('apellido', '') or '').strip(),
                    "seudonimo": seud
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
    return dia.find('cobros') or ET.SubElement(dia, 'cobros')

def _leer_cobros(fecha_str: str):
    """Dict por seudónimo con cobros guardados."""
    _, r = _leer_xml(CAJA_XML)
    dia = _get_dia(r, fecha_str)
    cobros = _get_cobros_node(dia)
    out = {}
    for c in cobros.findall('cobro'):
        seud = c.attrib.get('seudonimo', '')
        out[seud] = {
            "devueltos":     int(c.attrib.get('devueltos', '0')),
            "vendidos":      int(c.attrib.get('vendidos', '0')),
            "total_pagar":   float(c.attrib.get('total_pagar', '0')),
            "transferencia": float(c.attrib.get('transferencia', '0')),
            "efectivo":      float(c.attrib.get('efectivo', '0')),
            "pagado":        c.attrib.get('pagado', '0') == '1',
            "fecha_hora":    c.attrib.get('fecha_hora', '')
        }
    return out

def _upsert_cobro(fecha_str: str, seudonimo: str, datos: dict):
    """Crea/actualiza un <cobro> dentro del día indicado."""
    t, r = _leer_xml(CAJA_XML)
    dia = _get_dia(r, fecha_str)
    cobros = _get_cobros_node(dia)
    node = cobros.find(f"./cobro[@seudonimo='{seudonimo}']") or ET.SubElement(cobros, 'cobro', seudonimo=seudonimo)
    node.set('devueltos',     str(int(datos.get('devueltos', 0))))
    node.set('vendidos',      str(int(datos.get('vendidos', 0))))
    node.set('total_pagar',   f"{float(datos.get('total_pagar', 0)):.2f}")
    node.set('transferencia', f"{float(datos.get('transferencia', 0)):.2f}")
    node.set('efectivo',      f"{float(datos.get('efectivo', 0)):.2f}")
    node.set('pagado',        '1' if datos.get('pagado', True) else '0')
    node.set('fecha_hora',    datos.get('fecha_hora', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    _guardar_xml(t, CAJA_XML)

# ─── AGREGADORES DE TOTALES (para la tabla de “Pagados”) ────────────────────
def _agregar_totales_pagados(lista_vendedores, config):
    tot = {"planillas":0, "entregados":0, "devueltos":0, "vendidos":0,
           "total":0.0, "gan_vendedor":0.0, "a_pagar_caja":0.0, "pago":0.0}

    for v in lista_vendedores:
        if not v.get('pagado'):
            continue
        tot["planillas"]  += len(v.get('planillas', []))
        tot["entregados"] += v.get('boletos_entregados', 0)
        tot["devueltos"]  += v.get('boletos_devueltos', 0)
        tot["vendidos"]   += v.get('boletos_vendidos', 0)

        vendidos    = v.get('boletos_vendidos', 0)
        total_venta = vendidos * float(config["valor_boleto"])
        pct         = float(config["comision_vendedor"])
        if vendidos >= int(config["meta_boletos"]):
            pct += float(config["comision_extra_meta"])
        gan_v = total_venta * pct / 100.0
        caja  = total_venta - gan_v
        pago  = float(v.get("transferencia", 0.0)) + float(v.get("efectivo", 0.0))

        tot["total"]        += total_venta
        tot["gan_vendedor"] += gan_v
        tot["a_pagar_caja"] += caja
        tot["pago"]         += pago

    for k in ("total","gan_vendedor","a_pagar_caja","pago"):
        tot[k] = round(tot[k], 2)
    return tot

# ─── VISTA PRINCIPAL /cobro (con ?fecha=YYYY-MM-DD) ─────────────────────────
@app.route('/cobro', methods=['GET'])
def cobro():
    if 'usuario' not in session:
        # Si tu proyecto ya tiene /login, se usará el tuyo.
        return redirect(url_for('login', _external=False)) if 'login' in app.view_functions else redirect('/_login_demo')

    fecha_actual = (request.args.get('fecha') or date.today().isoformat()).strip()

    config = get_configuracion_dia(fecha_actual)
    base   = _cargar_vendedores_base()
    asign  = _cargar_asignaciones_por_fecha(fecha_actual)
    cobros = _leer_cobros(fecha_actual)

    vendedores_ui = []
    for seud, info in asign.items():
        base_info  = base.get(seud, {"nombre":"", "apellido":"", "seudonimo":seud})
        planillas  = info.get('planillas', [])
        entregados = info.get('boletos_entregados', 0)

        c = cobros.get(seud, {})
        devueltos = c.get('devueltos', 0)
        vendidos  = c.get('vendidos', max(entregados - devueltos, 0))
        pagado    = c.get('pagado', False)

        vendedores_ui.append({
            "nombre_completo": (base_info.get('nombre','') + " " + base_info.get('apellido','')).strip() or seud,
            "seudonimo": seud,
            "planillas": planillas,
            "boletos_entregados": entregados,
            "boletos_devueltos":  devueltos,
            "boletos_vendidos":   vendidos,
            "transferencia": c.get('transferencia', 0.0),
            "efectivo":      c.get('efectivo', 0.0),
            "pagado":        pagado,
        })

    paid_totals = _agregar_totales_pagados(vendedores_ui, config)

    return render_template(
        'cobro.html',
        username=session.get('usuario', 'admin'),
        avatar=session.get('avatar', 'avatar-male.png'),
        config=config,
        fecha_actual=fecha_actual,
        vendedores=vendedores_ui,
        paid_totals=paid_totals
    )

# ─── GUARDAR CONFIGURACIÓN DEL DÍA ──────────────────────────────────────────
@app.route('/guardar_configuracion_caja', methods=['POST'])
def guardar_configuracion_caja():
    try:
        data = request.get_json(force=True) or {}
        fecha_actual = (data.get('fecha') or request.args.get('fecha') or date.today().isoformat()).strip()
        payload = {
            "valor_boleto":        float(data.get('valor_boleto', 0)),
            "comision_vendedor":   float(data.get('comision_vendedor', 0)),
            "comision_extra_meta": float(data.get('comision_extra_meta', 0)),
            "meta_boletos":        int(data.get('meta_boletos', 0)),
        }
        set_configuracion_dia(fecha_actual, payload)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

# ─── GUARDAR COBRO DE UN VENDEDOR ───────────────────────────────────────────
@app.route('/guardar_cobro/<seudonimo>', methods=['POST'])
def guardar_cobro(seudonimo):
    try:
        j = request.get_json(force=True) or {}
        fecha_actual = (j.get('fecha') or request.args.get('fecha') or date.today().isoformat()).strip()

        devueltos     = int(j.get('boletos_devueltos', 0))
        vendidos      = int(j.get('boletos_vendidos', 0))
        total_pagar   = float(j.get('total_pagar', 0))
        transferencia = float(j.get('transferencia', 0))
        efectivo      = float(j.get('efectivo', 0))

        _upsert_cobro(
            fecha_actual,
            seudonimo,
            {
                "devueltos":     devueltos,
                "vendidos":      vendidos,
                "total_pagar":   total_pagar,
                "transferencia": transferencia,
                "efectivo":      efectivo,
                "pagado":        True,
            }
        )
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

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
if __name__ == "__main__":
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

FIGURAS_XML = os.path.join(BASE_DIR, "static", "db", "datos_figuras.xml")
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
        return redirect(url_for('login'))

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

@app.route("/escoger-figuras", methods=["GET"])
def escoger_figuras():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(url_for('login'))
    return render_template("escoger_figuras.html")

@app.route("/figuras/seleccion", methods=["POST"])
def figuras_seleccion():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(url_for('login'))
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

FIGURAS_FECHA_XML = os.path.join(BASE_DIR, "static", "db", "figuras_por_fecha.xml")
os.makedirs(os.path.dirname(FIGURAS_FECHA_XML), exist_ok=True)

def _ensure_agenda_root():
    if not os.path.exists(FIGURAS_FECHA_XML):
        ET.ElementTree(ET.Element("agenda")).write(FIGURAS_FECHA_XML, encoding="utf-8", xml_declaration=True)
        return
    try:
        ET.parse(FIGURAS_FECHA_XML)
    except ET.ParseError:
        ET.ElementTree(ET.Element("agenda")).write(FIGURAS_FECHA_XML, encoding="utf-8", xml_declaration=True)

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
        return redirect(url_for('login'))
    fecha_q = (request.args.get("fecha") or "").strip()
    preseleccion = cargar_figuras_de_fecha(fecha_q) if fecha_q else []
    return render_template("escoger_figuras.html",
                           fecha_inicial=fecha_q,
                           preseleccion=preseleccion)

# Guardar (solo POST)
@app.route("/escoger-figuras/guardar", methods=["POST"])
def escoger_figuras_guardar():
    if 'usuario' not in session and 'login' in current_app.view_functions:
        return redirect(url_for('login'))

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
DB_DIR     = os.path.join(STATIC_DIR, "db")
IMG_DIR    = os.path.join(STATIC_DIR, "img")
FONTS_DIR  = os.path.join(STATIC_DIR, "fonts")
LOGS_DIR   = os.path.join(STATIC_DIR, "LOGS")

for p in (DB_DIR, IMG_DIR, FONTS_DIR):
    os.makedirs(p, exist_ok=True)

# XMLs base
FIGURAS_FECHA_XML  = os.path.join(DB_DIR, "figuras_por_fecha.xml")
DATOS_FIGURAS_XML  = os.path.join(DB_DIR, "datos_figuras.xml")
RESULTADOS_XML     = os.path.join(DB_DIR, "resultados_sorteo.xml")

# Layout JSON (diseñador)
LAYOUT_JSON = os.path.join(DB_DIR, "boletin_layout.json")

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
def _cargar_resultados(fecha_iso):
    data = {"items": [], "extras": {"comodin": {}, "gran_bonus": {}}}
    if not _is_fecha_iso(fecha_iso):
        return data
    _ensure_xml(RESULTADOS_XML, "resultados")
    root = ET.parse(RESULTADOS_XML).getroot()
    dia = None
    for d in root.findall("dia"):
        if d.attrib.get("fecha") == fecha_iso:
            dia = d
            break
    if dia is None:
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
    _ensure_xml(RESULTADOS_XML, "resultados")
    tree = ET.parse(RESULTADOS_XML)
    root = tree.getroot()

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
    tree.write(RESULTADOS_XML, encoding="utf-8", xml_declaration=True)

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
def _parse_spinners(extras: dict):
    """
    Lee extras y extrae lista de spinners (hasta 20) y el valor por spinner.
    Busca en:
      - extras['spinners'] -> {'numeros': '...', 'valor'/'texto': '...'}
      - fallback: extras['comodin'] -> usa 'boletos' como numeros y 'texto' como valor
    """
    extras = extras or {}
    block = extras.get("spinners") or {}
    if not block:
        block = extras.get("comodin") or {}

    raw_nums = (block.get("numeros") or (block.get("boletos") or "")).strip()
    raw_val  = (block.get("valor") or (block.get("texto") or "")).strip()

    tokens = re.findall(r"\d{1,4}", raw_nums)
    nums = [t.zfill(4) for t in tokens][:20]

    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", raw_val)
    valor = None
    if m:
        try:
            valor = float(m.group(1).replace(",", "."))
        except Exception:
            valor = None

    return {"nums": nums, "valor": valor}

def _draw_spinners_card(c, x, y, w, h, nums, valor, font):
    """
    Tarjeta SPINNERS con 'pastillas' de 4 cuadritos.
    - Las filas se **CENTRAN** horizontalmente.
    - Se ajusta tamaño para encajar sin recortar.
    """
    # Tarjeta
    c.setFillColor(colors.HexColor("#F8FAFF"))
    c.setStrokeColor(colors.HexColor("#CBD5F1"))
    c.roundRect(x, y, w, h, 10, stroke=1, fill=1)

    pad = 10
    inner_x = x + pad
    inner_y = y + pad
    inner_w = w - 2*pad
    inner_h = h - 2*pad

    # Título + valor
    c.setFillColor(colors.HexColor("#0F172A")); c.setFont(font, 10)
    c.drawString(inner_x, y + h - pad - 6, "SPINNERS")
    if valor is not None:
        c.setFillColor(colors.HexColor("#334155")); c.setFont(font, 9)
        c.drawRightString(x + w - pad, y + h - pad - 6, f"Valor c/u: {_money(valor)}")

    # Parámetros visuales
    title_h     = 18          # espacio reservado para el título
    spinner_gap = 12          # separación entre spinners
    row_gap     = 8           # separación entre filas
    box_gap     = 3           # separación entre dígitos
    pill_pad    = 6           # padding interno de la pastilla
    grid_h      = max(10, inner_h - title_h)

    n = len(nums)
    if n == 0:
        return

    # Elegimos per_row y tamaño de box maximizando el encaje
    best = None  # (box_size, per_row, rows)
    max_per_row = min(n, 8)
    for per_row in range(max_per_row, 0, -1):
        rows = math.ceil(n / per_row)

        # Ancho disponible -> box por ancho
        max_box_w = ((inner_w - (per_row - 1) * spinner_gap) / per_row - 2 * pill_pad - 3 * box_gap) / 4.0
        # Alto disponible -> box por alto
        max_box_h = ((grid_h - (rows - 1) * row_gap) / rows - 2 * pill_pad)

        box = min(max_box_w, max_box_h, 18)  # límite superior estético
        if box >= 10:  # mínimo legible
            if best is None or box > best[0]:
                best = (box, per_row, rows)

    if best is None:
        best = (8.0, min(n, 6), math.ceil(n / min(n, 6)))

    box, per_row, rows = best
    fs = max(9, min(14, box * 0.70))

    pill_h = 2 * pill_pad + box
    pill_w = 2 * pill_pad + 4 * box + 3 * box_gap

    # Dibujo centrado por fila
    c.setFont(font, fs)
    idx = 0
    for r in range(rows):
        remaining = n - idx
        count = min(per_row, remaining)
        row_w = count * pill_w + (count - 1) * spinner_gap
        start_x = inner_x + max(0, (inner_w - row_w) / 2.0)  # <-- centrado
        y_row = inner_y + grid_h - pill_h - r * (pill_h + row_gap)

        for j in range(count):
            cur_x = start_x + j * (pill_w + spinner_gap)

            # Pastilla
            c.setFillColor(colors.HexColor("#EEF2FF"))
            c.setStrokeColor(colors.HexColor("#C7D2FE"))
            c.roundRect(cur_x, y_row, pill_w, pill_h, 7, stroke=1, fill=1)

            # 4 cuadritos
            s = re.sub(r"\D", "", str(nums[idx]))[:4].rjust(4, "0")
            xx = cur_x + pill_pad
            yy = y_row + pill_pad
            for ch in s:
                c.setFillColor(colors.white)
                c.setStrokeColor(colors.HexColor("#94A3B8"))
                c.roundRect(xx, yy, box, box, 3, stroke=1, fill=1)

                c.setFillColor(colors.HexColor("#111827"))
                tx = xx + (box - pdfmetrics.stringWidth(ch, font, fs)) / 2.0
                ty = yy + (box - fs) / 2.0 - 0.5
                c.drawString(tx, ty, ch)

                xx += box + box_gap

            idx += 1
            if idx >= n:
                break

# ------------------ Rutas Flask ------------------

@app.get("/api/figuras-manana")
def api_figuras_manana():
    base = (request.args.get("fecha") or date.today().isoformat()).strip()
    if not _is_fecha_iso(base):
        base = date.today().isoformat()
    manana = (datetime.fromisoformat(base) + timedelta(days=1)).date().isoformat()
    figs = _figuras_de_fecha(manana)
    total = sum((f.get("valor") or 0.0) for f in figs)
    return jsonify({"ok": True, "fecha": manana, "figuras": figs, "total": total})

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

@app.get("/api/boletin-layout/get")
def api_layout_get():
    fecha = (request.args.get("fecha") or date.today().isoformat()).strip()
    if not _is_fecha_iso(fecha):
        fecha = date.today().isoformat()
    manana = (datetime.fromisoformat(fecha) + timedelta(days=1)).date().isoformat()
    figs = _figuras_de_fecha(manana)
    lay  = _layout_for(fecha, figs, scale=FIG_BLOCK_SCALE, fixed_cols=FIG_FIXED_COLS)
    return jsonify({"ok": True, "layout": lay, "figuras": figs})

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

        # escala de figuras + columnas
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

        # Escalas opcionales
        def _float_arg(name, default):
            v = request.args.get(name)
            if v is None:
                return default
            try:
                return float(v)
            except Exception:
                return default

        LOGO_SCALE = max(0.5, min(2.0, _float_arg("logo_scale", LOGO_SCALE_DEFAULT)))
        REIN_SCALE = max(0.5, min(1.6, _float_arg("rein_scale", 1.05)))
        SPIN_SCALE = max(0.5, min(1.6, _float_arg("spin_scale", 1.00)))

        dt = datetime.fromisoformat(fecha).date()
        manana = (dt + timedelta(days=1)).isoformat()

        figs_manana  = _figuras_de_fecha(manana)
        total_manana = sum((f.get("valor") or 0.0) for f in figs_manana)
        resultados   = _cargar_resultados(fecha)
        shapes       = _load_shapes()
        layout       = _layout_for(fecha, figs_manana, scale=scale, force_autofit=force_autofit, fixed_cols=fixed_cols)

        # Reintegro (por fecha) desde LOGS
        rein_log = _reintegro_from_log_for_date(fecha)

        # SPINNERS (Extras)
        sp_data = _parse_spinners(resultados.get("extras") or {})

        # Backfill posiciones
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

        # Logo
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
            c.drawImage(img, L["x"], H - (L["y"] + draw_h),
                        width=draw_w, height=draw_h,
                        preserveAspectRatio=True, mask="auto")

        # Título + fecha
        c.setFillColor(colors.black)
        c.setFont(FONT, 18)
        c.drawCentredString(W/2, H - 42, T("JUEGO HOY"))
        c.setFont(FONT, 11)
        c.drawCentredString(W/2, H - 58, T(_es_corta(manana).capitalize()))

        # Total a jugar
        TL = layout.get("total", {"x": W - 22, "y": 24, "size": 56, "align": "right"})
        c.setFillColor(colors.white); c.setFont(FONT, 11)
        c.drawRightString(W - 18, H - 22, T("PREMIO TOTAL"))
        amount = T(_money_header(total_manana))
        _draw_ultrablack(c, amount,
                         TL.get("x", W - 22),
                         H - (TL.get("y", 24) + TL.get("size", 56)),
                         TL.get("size", 56), FONT)

        # ---------- Figuras de mañana ----------
        fig_lay = layout.get("figs", {})
        for f in figs_manana:
            name = f["nombre"]; val = f.get("valor") or 0.0
            pos = fig_lay.get(name) or {}
            bx = float(pos.get("x", 50)); by = float(pos.get("y", header_h + 28)); bw = float(pos.get("size", 96))

            _chip(c, bx, H - by, bw, T(_money(val)), FONT, "#1F58FF", 10)
            grid_top = H - by - 22
            mask = shapes.get(name.strip().lower(), [False] * 25)
            _grid5(c, bx, grid_top, bw, mask)
            _bar(c, bx, grid_top - (bw + 8), bw, T(name.upper()), FONT, "#0E2E8E", 10)

        # ---------- Resultados ----------
        block_h_extra = 22 + 8 + 18
        max_depth = header_h
        for f in figs_manana:
            pos = fig_lay.get(f["nombre"]) or {}
            by   = float(pos.get("y", header_h + 28))
            bw   = float(pos.get("size", 96))
            depth = by + (bw + block_h_extra)
            if depth > max_depth:
                max_depth = depth

        depth = max_depth + 28
        y = H - depth
        MIN_Y_FIRST_PAGE = 120
        if y < MIN_Y_FIRST_PAGE:
            y = MIN_Y_FIRST_PAGE

        # Banda compacta
        c.setFillColor(colors.HexColor("#2B2370")); c.rect(0, y, W, 16, 0, 1)
        c.setFillColor(colors.white); c.setFont(FONT, 10)
        c.drawCentredString(W/2, y + 4, T(f"RESULTADOS SORTEO { _es_largo(fecha) }"))
        y -= 4

        agenda = _figuras_de_fecha(fecha)
        premio_map = {a["nombre"].strip().lower(): (a.get("valor") or 0.0) for a in agenda}

        def ensure_space(hmin=70, top_margin=16):
            nonlocal y
            if y - hmin < top_margin:
                c.showPage()
                y = H - top_margin

        def bloque(fig, ganadores, premio_total):
            nonlocal y
            ensure_space(120)
            y -= 16
            c.setFillColor(colors.HexColor("#EDF2FF")); c.rect(14, y, W - 28, 18, 0, 1)
            c.setFillColor(colors.HexColor("#203880")); c.setFont(FONT, 10)
            c.drawCentredString(W / 2, y + 5, T(fig.upper()))
            c.drawRightString(W - 20, y + 5, T(f"Premio total { _money(premio_total) }"))
            y -= 20

            c.setFillColor(colors.HexColor("#6B7280")); c.setFont(FONT, 9)
            c.drawString(20, y, T("Boleto"))
            c.drawString(86, y, T("Nombre (Vendedor)"))
            c.drawString(320, y, T("Sector"))
            c.drawRightString(W - 20, y, T("Premio"))
            y -= 8
            c.setStrokeColor(colors.HexColor("#CBD5F1")); c.line(14, y, W - 14, y)
            y -= 8

            par = True
            for g in (ganadores or []):
                ensure_space(30)
                if par:
                    c.setFillColor(colors.HexColor("#F7F9FF")); c.rect(14, y - 12, W - 28, 14, 0, 1)
                par = not par
                c.setFillColor(colors.black); c.setFont(FONT, 9)
                nombre = g.get("nombre", ""); vendedor = g.get("vendedor", "")
                nomvend = nombre if not vendedor else f"{nombre}  ({vendedor})"
                c.drawString(20, y - 9, T(g.get("boleto", "")))
                c.drawString(86, y - 9, T(nomvend))
                c.drawString(320, y - 9, T(g.get("sector", "")))
                try:
                    prem = float(g.get("premio") or 0.0)
                except Exception:
                    prem = 0.0
                c.drawRightString(W - 20, y - 9, T(_money(prem)))
                y -= 14
            y -= 4

        for item in (resultados.get("items") or []):
            nom = item.get("figura", "")
            gan = item.get("ganadores") or []
            premio = premio_map.get(nom.strip().lower(), 0.0)
            if premio == 0.0:
                premio = sum((g.get("premio") or 0.0) for g in gan)
            bloque(nom, gan, premio)

        # ---------- Tarjetas inferiores ----------
        margin = 12
        espacio_disponible = (y - margin)

        # SPINNERS (izquierda)
        sp_base_h = 86
        sp_base_w = 360
        sp_h = sp_base_h * SPIN_SCALE
        sp_w = sp_base_w * SPIN_SCALE
        if espacio_disponible < (sp_h + 20):
            factor = max(0.40, (espacio_disponible - 20) / max(sp_h, 1))
            sp_h *= factor
            sp_w *= factor
        if sp_data["nums"] or (sp_data["valor"] is not None):
            _draw_spinners_card(c, margin, margin, sp_w, sp_h, sp_data["nums"], sp_data["valor"], FONT)

        # REINTEGRO (derecha)
        rein_base_h = 90
        rein_base_w = int(rein_base_h * 3.75)
        card_h = rein_base_h * REIN_SCALE
        card_w = rein_base_w * REIN_SCALE
        if espacio_disponible < (card_h + 20):
            factor = max(0.40, (espacio_disponible - 20) / max(card_h, 1))
            card_h *= factor
            card_w *= factor

        rein_x = W - margin - card_w
        base_y = margin

        if rein_log.get("imagen"):
            c.setFillColor(colors.HexColor("#D1D5DB"))
            c.roundRect(rein_x+2.5, base_y-2.5, card_w, card_h, 10, stroke=0, fill=1)
            c.setFillColor(colors.white); c.setStrokeColor(colors.HexColor("#CBD5F1"))
            c.roundRect(rein_x, base_y, card_w, card_h, 10, stroke=1, fill=1)

            gap = 25
            label_w = card_w * 0.45
            img_w   = card_w - label_w - gap - 10
            label_x = rein_x + 8
            img_x   = label_x + label_w + gap
            inner_y = base_y + 8
            inner_h = card_h - 16

            c.setFillColor(colors.HexColor("#190042"))
            c.setFont(FONT, max(12, int(16 * REIN_SCALE)))
            text_y = inner_y + (inner_h / 2) - 6
            c.drawString(label_x, text_y, "REINTEGRO")

            c.setStrokeColor(colors.HexColor("#0C8A3E"))
            c.setLineWidth(1)
            c.line(label_x, text_y - 4, label_x + (label_w * 0.60), text_y - 4)

            c.drawImage(
                rein_log["imagen"], img_x, inner_y,
                width=img_w, height=inner_h,
                preserveAspectRatio=True, anchor='sw', mask='auto'
            )

        c.showPage()
        c.save()
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name=f"boletin_{fecha}.pdf",
                         mimetype="application/pdf")

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
DB_DIR     = os.path.join(STATIC_DIR, "db")
IMG_DIR    = os.path.join(STATIC_DIR, "img")

RESULTADOS_XML = os.path.join(DB_DIR, "resultados_sorteo.xml")

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
PAGOS_XML   = os.path.join(DB_DIR, "pagos_premios.xml")
RECIBOS_DIR = os.path.join(STATIC_DIR, "tmp", "recibos")
CFG_JSON    = os.path.join(DB_DIR, "pagos_config.json")

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








# -*- coding: utf-8 -*-
# GL Bingo - Sorteo → genera múltiples XML separados para vMix

# -*- coding: utf-8 -*-
# GL Bingo — Sorteo (solo XML + HTML)
# -*- coding: utf-8 -*-
# GL Bingo — Sorteo (solo XML + HTML)
# -*- coding: utf-8 -*-
# Sorteo (solo XML + HTML) — GL Bingo
# -*- coding: utf-8 -*-
# GL Bingo — Sorteo + XMLs vMix (presentación y tablero 2 columnas, orden fijo B1..O5)

from flask import Flask, render_template, request, jsonify, redirect, url_for
import os, re
from datetime import date, datetime
import xml.etree.ElementTree as ET


app.secret_key = "glbingo"

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_DIR     = os.path.join(STATIC_DIR, "db")
LOGS_DIR   = os.path.join(STATIC_DIR, "LOGS")
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Entradas
FIGS_XML        = os.path.join(DB_DIR,  "figuras_por_fecha.xml")
ASIG_XML        = os.path.join(DB_DIR,  "asignaciones.xml")
IMP_XML         = os.path.join(LOGS_DIR, "impresiones.xml")
CATALOGO_FIGXML = os.path.join(DB_DIR,  "datos_figuras.xml")  # opcional (figuras dibujadas)

# Salidas vMix
VMIX_VENTAS_XML      = os.path.join(DB_DIR, "vmix_ventas.xml")
VMIX_FIG_NOMB_XML    = os.path.join(DB_DIR, "vmix_figuras_nombres.xml")
VMIX_FIG_COLORES_XML = os.path.join(DB_DIR, "vmix_figuras_colores.xml")
VMIX_FIG_GRID_XML    = os.path.join(DB_DIR, "vmix_figuras.xml")          # 25 celdas
VMIX_SPINNERS_XML    = os.path.join(DB_DIR, "vmix_spinners.xml")
VMIX_REINTEGRO_XML   = os.path.join(DB_DIR, "vmix_reintegro.xml")

# NUEVOS pedidos
XML_FIGURAS_LISTA = os.path.join(DB_DIR, "xml_figuras_lista.xml")  # presentación (25 columnas)
XML_FIGURAS_2COL  = os.path.join(DB_DIR, "xml_figuras.xml")        # tablero (2 columnas)

# Colores del tablero
COLOR_ON  = "#ff0037"
COLOR_OFF = "#E8E8E8"

# Orden POS por índice 1..25 (fila-primero) para el catálogo
POS_25_ROW = [
    "B1","I1","N1","G1","O1",
    "B2","I2","N2","G2","O2",
    "B3","I3","N3","G3","O3",
    "B4","I4","N4","G4","O4",
    "B5","I5","N5","G5","O5",
]

# Orden que vMix espera para la tabla: B1..B5, I1..I5, N1..N5, G1..G5, O1..O5 (columna-primero)
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
    n = (name or "").strip().upper()
    if n.startswith("TABLA LLENA 1"): return "TL1"
    if n.startswith("TABLA LLENA 2"): return "TL2"
    if n.startswith("TABLA LLENA 3"): return "TL3"
    if n.startswith("TABLA LLENA 4"): return "TL4"
    return re.sub(r"[^A-Z0-9]", "", n)[:4] or "FIG"

# ---------------- Lecturas ----------------

def get_figuras_del_dia(fecha):
    """TL1..TL4 + resto (nombre/valor) desde figuras_por_fecha.xml."""
    tl = [0.0, 0.0, 0.0, 0.0]
    resto = []
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
    filas = []
    if not os.path.exists(ASIG_XML):
        return filas
    root = ET.parse(ASIG_XML).getroot()
    dia  = root.find(f".//dia[@fecha='{fecha}']")
    if dia is None:
        return filas
    for vend in dia.findall("vendedor"):
        nom = vend.attrib.get("seudonimo") or \
              (" ".join([vend.attrib.get("nombre",""), vend.attrib.get("apellido","")]).strip() or "—")
        for p in vend.findall("planilla"):
            r = (p.attrib.get("rango","") or "").strip()
            if r and "-" in r:
                a,b = r.split("-",1)
                desde, hasta = a.strip(), b.strip()
            else:
                desde = p.attrib.get("desde","") or p.attrib.get("inicio","") or "0"
                hasta = p.attrib.get("hasta","") or p.attrib.get("fin","")    or "0"
            filas.append({"desde":desde, "hasta":hasta, "vendedor":nom})
    return filas

def buscar_vendedor_por_boleto(fecha, boleto):
    try:
        num = int(str(boleto).strip())
    except:
        return ""
    for f in get_asignaciones_del_dia(fecha):
        try:
            a = int(re.sub(r"\D","", f["desde"]) or 0)
            b = int(re.sub(r"\D","", f["hasta"]) or 0)
        except:
            continue
        if a <= num <= b:
            return f["vendedor"]
    return ""

def get_impresiones_info(fecha):
    serie = "—"; primer = 0; ultimo = 0; total_b = 0; valor_b = 0; rein = "—"
    if not os.path.exists(IMP_XML):
        return dict(
            serie_detectada=serie, primer_boleto=str(primer), ultimo_boleto=str(ultimo),
            boletos_impresos=_fmt_int(total_b), valor_boleto=_fmt_int(valor_b), reintegro_dia=rein
        )
    root = ET.parse(IMP_XML).getroot()
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
    ET.ElementTree(root).write(VMIX_VENTAS_XML, encoding="utf-8", xml_declaration=True)

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
    ET.ElementTree(root).write(VMIX_FIG_NOMB_XML, encoding="utf-8", xml_declaration=True)

    root2 = ET.Element("figuras_colores", {"fecha": fecha})
    for f in fig_elegidas:
        ET.SubElement(root2, "fig", {"nombre": f["nombre"], "valor": f["valor"], "codigo": code_for(f["nombre"]), "color": ""})
    ET.ElementTree(root2).write(VMIX_FIG_COLORES_XML, encoding="utf-8", xml_declaration=True)

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
    ET.ElementTree(root).write(VMIX_FIG_GRID_XML, encoding="utf-8", xml_declaration=True)

def write_xml_figuras_lista_presentacion(fecha, figuras_dia, catalogo):
    """
    <juego><filaFiguras> ... 25 columnas en orden B1..B5,I1..I5,N1..N5,G1..G5,O1..O5 </filaFiguras></juego>
    """
    root = ET.Element("juego")
    ident = 1
    for f in figuras_dia:
        nombre = f["nombre"]; valor = f["valor"]; codigo = code_for(nombre)
        fila = ET.SubElement(root, "filaFiguras")
        ET.SubElement(fila, "figuraIDENTIFICADOR").text = str(ident)
        ET.SubElement(fila, "figuraNOMBRE").text        = nombre
        ET.SubElement(fila, "figuraVALOR").text         = valor
        ET.SubElement(fila, "figuraESTADO").text        = "inactivo"

        # colores (lista idx 1..25, fila-primero) -> dict pos->color
        cols = grid_colors_for(codigo, catalogo)
        pos_to_col = {POS_25_ROW[i]: cols[i] for i in range(25)}
        # escribir en el ORDEN que vMix espera (columna-primero)
        for lab in POS_25_COL:
            ET.SubElement(fila, f"figura{lab}").text = pos_to_col[lab]

        ident += 1
    ET.ElementTree(root).write(XML_FIGURAS_LISTA, encoding="utf-8", xml_declaration=True)

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
    ET.ElementTree(root).write(XML_FIGURAS_2COL, encoding="utf-8", xml_declaration=True)

def write_vmix_spinners(fecha, spins):
    root = ET.Element("spinners", {"fecha": fecha})
    for i, v in enumerate((spins or [])[:20], start=1):
        v = re.sub(r"\D","", str(v))[:4].zfill(4)
        ET.SubElement(root, "n", {"i": str(i), "v": v})
    ET.ElementTree(root).write(VMIX_SPINNERS_XML, encoding="utf-8", xml_declaration=True)

def write_vmix_reintegro(fecha, reinteg_name):
    root = ET.Element("reintegro", {"fecha": fecha})
    ET.SubElement(root, "archivo").text = reinteg_name or ""
    ET.SubElement(root, "ruta").text    = "static/REINTEGROS/" + (reinteg_name or "")
    ET.ElementTree(root).write(VMIX_REINTEGRO_XML, encoding="utf-8", xml_declaration=True)

# ---------------- Rutas ----------------

@app.route("/")
def root():
    return redirect(url_for("sorteo", fecha=date.today().isoformat()))

@app.route("/sorteo")
def sorteo():
    fecha = request.args.get("fecha") or date.today().isoformat()
    imp = get_impresiones_info(fecha)
    tl, resto = get_figuras_del_dia(fecha)
    asignaciones = get_asignaciones_del_dia(fecha)
    total_boletos_x_valor = int(_fmt_int(imp["boletos_impresos"])) * int(_fmt_int(imp["valor_boleto"]))
    total_premios = int(round(sum(tl) + sum(_parse_float(f["valor"]) for f in resto)))
    return render_template(
        "sorteo.html",
        fecha=fecha,
        serie_detectada=imp["serie_detectada"],
        primer_boleto=imp["primer_boleto"],
        ultimo_boleto=imp["ultimo_boleto"],
        reintegro_dia=imp["reintegro_dia"],
        valor_boleto=_fmt_int(imp["valor_boleto"]),
        boletos_impresos=_fmt_int(imp["boletos_impresos"]),
        total_a_jugar=_fmt_int(total_boletos_x_valor),
        total_premios=_fmt_int(total_premios),
        tl1=_fmt_int(tl[0]), tl2=_fmt_int(tl[1]), tl3=_fmt_int(tl[2]), tl4=_fmt_int(tl[3]),
        figs_resto=resto,
        asignaciones=asignaciones
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

@app.post("/api/activar-sorteo")
def sorteo_activar():
    data  = request.get_json(silent=True) or {}
    fecha = data.get("fecha")
    spins = data.get("spinners", [])
    if not fecha:
        return jsonify(ok=False, mensaje="Falta la fecha")

    imp = get_impresiones_info(fecha)
    tl, resto = get_figuras_del_dia(fecha)

    # 1) ventas
    write_vmix_ventas(fecha, imp)

    # 2) listas (nombres y códigos)
    figuras_dia = write_vmix_figuras_listas(fecha, tl, resto)

    # 3) grid 25 celdas
    catalogo = load_catalogo_figuras()
    write_vmix_figuras_grid(fecha, figuras_dia, catalogo)

    # 4) PRESENTACIÓN (25 columnas en el orden correcto)
    write_xml_figuras_lista_presentacion(fecha, figuras_dia, catalogo)

    # 5) TABLERO (2 columnas)
    write_xml_figuras_tablero_2columnas(fecha, figuras_dia)

    # 6) spinners y reintegro
    write_vmix_spinners(fecha, spins)
    write_vmix_reintegro(fecha, imp["reintegro_dia"])

    return jsonify(ok=True, mensaje="XMLs generados/reemplazados correctamente.")







# ================= CONTABILIDAD: helpers y rutas =================
# Seguridad por rol, gastos, banco, resumen, y endpoints de curvas por vendedor

import os
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from flask import jsonify, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename

# === Comprobantes (subidas) ===
ALLOWED_EXTS = {"pdf", "png", "jpg", "jpeg", "webp"}
COMPROB_DIR = os.path.join("static", "CONTABILIDAD", "comprobantes")
BANK_FILES  = os.path.join(COMPROB_DIR, "banco")
GASTO_FILES = os.path.join(COMPROB_DIR, "gastos")
os.makedirs(BANK_FILES, exist_ok=True)
os.makedirs(GASTO_FILES, exist_ok=True)

def _ext_ok(filename: str) -> bool:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return ext in ALLOWED_EXTS

def _save_upload(fs, folder: str, base: str) -> str:
    """Guarda archivo y retorna ruta relativa desde /static (ej: CONTABILIDAD/comprobantes/banco/xx.pdf)."""
    fname = secure_filename(fs.filename or "")
    ext = os.path.splitext(fname)[1].lower()
    if not ext or ext.lstrip(".") not in ALLOWED_EXTS:
        raise ValueError("extensión no permitida")
    path = os.path.join(folder, f"{base}{ext}")
    fs.save(path)
    rel = os.path.relpath(path, "static").replace("\\", "/")
    return rel

# ---- Archivo de gastos ----
GASTOS_XML = os.path.join('static', 'CONTABILIDAD', 'gastos.xml')
os.makedirs(os.path.dirname(GASTOS_XML), exist_ok=True)
if not os.path.exists(GASTOS_XML):
    ET.ElementTree(ET.Element('gastos')).write(GASTOS_XML, encoding='utf-8', xml_declaration=True)

def _xml_read(path):
    tree = ET.parse(path)
    return tree, tree.getroot()

def _xml_write(tree, path):
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(path, encoding='utf-8', xml_declaration=True)

# ---- Gastos CRUD ----
def _gasto_row(elem):
    return {
        "id": elem.get("id"),
        "fecha": elem.findtext("fecha", ""),
        "categoria": elem.findtext("categoria", ""),
        "medio": elem.findtext("medio", ""),     # caja | banco
        "monto": float(elem.findtext("monto", "0") or 0),
        "descripcion": elem.findtext("descripcion", ""),
        "creado_por": elem.findtext("creado_por", ""),
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

def _gasto_add(data, usuario, comp_path=None, gid_forced=None, monto_comprobante=None):
    tree, root = _xml_read(GASTOS_XML)
    gid = gid_forced or str(int(datetime.now().timestamp()*1000))
    g = ET.SubElement(root, "gasto", {"id": gid})
    ET.SubElement(g, "fecha").text = (data.get("fecha") or date.today().isoformat())
    ET.SubElement(g, "categoria").text = (data.get("categoria") or "Gasto")
    ET.SubElement(g, "medio").text = (data.get("medio") or "caja")
    ET.SubElement(g, "monto").text = str(float(data.get("monto") or 0))
    ET.SubElement(g, "descripcion").text = (data.get("descripcion") or "")
    ET.SubElement(g, "creado_por").text = (usuario or "sistema")
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
      A) <cobros><cobro vendidos=".." devueltos=".." efectivo=".." transferencia=".." pagado="1" .../></cobros>
      B) <vendedor><vendidos>..</vendidos><devueltos>..</devueltos>...</vendedor>
    """
    # A) Nuevo
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
            }
        return
    # B) Antiguo
    for v in root_dia.findall('vendedor'):
        yield {
            "seudonimo": v.attrib.get('seudonimo', ''),
            "vendidos": _safe_int(v.findtext('vendidos', 0)),
            "devueltos": _safe_int(v.findtext('devueltos', 0)),
            "efectivo": _safe_float(v.findtext('efectivo', 0)),
            "transferencia": _safe_float(v.findtext('transferencia', 0)),
            "pagado": _to_bool(v.findtext('pagado', 'false') or v.attrib.get('pagado')),
        }

# ---- Caja (vendidos/devueltos/recaudo/comisiones, efectivo/transferencia) ----
def _sum_caja(desde_iso, hasta_iso):
    vendidos = devueltos = 0
    total_recaudado = gan_vendedores = a_caja = 0.0
    tot_efectivo = tot_transfer = 0.0

    # Abrimos una sola vez el XML de caja
    _, root = _leer_xml(CAJA_XML)

    for f in _daterange(desde_iso, hasta_iso):
        dia = root.find(f"./dia[@fecha='{f}']")
        if dia is None:
            continue

        cfg = get_configuracion_dia(f)
        valor     = _safe_float(cfg.get("valor_boleto"), 0.0)
        pct_base  = _safe_float(cfg.get("comision_vendedor"), 0.0)
        pct_extra = _safe_float(cfg.get("comision_extra_meta"), 0.0)
        meta      = _safe_int(cfg.get("meta_boletos"), 0)

        for r in _caja_iter_cobros_dia(dia):
            if not r.get('pagado'):
                continue

            vend = _safe_int(r.get('vendidos', 0))
            dev  = _safe_int(r.get('devueltos', 0))

            vendidos  += vend
            devueltos += dev

            total_venta = vend * valor
            pct = pct_base + (pct_extra if vend >= meta else 0.0)

            gan_v = total_venta * pct / 100.0
            caja  = total_venta - gan_v

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
    path_asig = globals().get("ASIGNACIONES_XML", "static/db/asignaciones.xml")
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
                total_pagado += _safe_float(pp.get("premio", premio_val), premio_val)
            else:
                if hoy > caduca:
                    caducados += 1
                elif 0 <= (caduca - hoy).days <= 5:
                    por_caducar += 1

    return {
        "premios_pagados_total": round(total_pagado, 2),
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
        return redirect(url_for('login'))
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

# ========================= BANCO (Empresa) =========================
BANCOS_XML = os.path.join('static', 'CONTABILIDAD', 'bancos.xml')
os.makedirs(os.path.dirname(BANCOS_XML), exist_ok=True)
if not os.path.exists(BANCOS_XML):
    ET.ElementTree(ET.Element('bancos')).write(BANCOS_XML, encoding='utf-8', xml_declaration=True)

def _bank_xml():
    tree = ET.parse(BANCOS_XML)
    return tree, tree.getroot()

def _bank_write(tree):
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        pass
    tree.write(BANCOS_XML, encoding='utf-8', xml_declaration=True)

def _bank_row(e: ET.Element):
    return {
        "id": e.get("id"),
        "fecha": e.findtext("fecha", ""),
        "cuenta": e.findtext("cuenta", "Empresa"),
        "tipo": (e.findtext("tipo", "ingreso") or "").lower(),
        "monto": float(e.findtext("monto", "0") or 0),
        "referencia": e.findtext("referencia", ""),
        "creado_por": e.findtext("creado_por", ""),
        "comprobante": e.findtext("comprobante", ""),
        "locked": (e.findtext("locked", "false") == "true"),
    }

def _bank_get(mid: str):
    tree, root = _bank_xml()
    for e in root.findall("mov"):
        if e.get("id") == mid:
            return tree, root, e
    return tree, root, None

def _bank_add(fecha:str, cuenta:str, tipo:str, monto:float, referencia:str, creado_por:str,
              comprobante:str=None, locked:bool=False, forced_id:str=None, monto_comprobante:float=None):
    tree, root = _bank_xml()
    mid = forced_id or str(int(datetime.now().timestamp()*1000))
    m = ET.SubElement(root, "mov", {"id": mid})
    ET.SubElement(m, "fecha").text = (fecha or date.today().isoformat())
    ET.SubElement(m, "cuenta").text = (cuenta or "Empresa")
    ET.SubElement(m, "tipo").text = (tipo or "ingreso")  # ingreso | egreso | transferencia
    ET.SubElement(m, "monto").text = str(float(monto or 0))
    ET.SubElement(m, "referencia").text = (referencia or "")
    ET.SubElement(m, "creado_por").text = (creado_por or "sistema")
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
        file = request.files.get("comprobante")
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
            monto_comprobante = monto_comp
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
        locked = False
    )
    return jsonify({"ok": True, "id": mid, "saldo": _bank_saldo(data.get("cuenta") or "Empresa")})

@app.delete("/api/banco/movimientos/<mid>")
def api_banco_borrar(mid):
    if not _require_admin():
        return jsonify({"ok": False, "error": "no-autorizado"}), 403
    ok = _bank_delete(mid)
    if not ok:
        return jsonify({"ok": False, "error": "mov-bloqueado-o-inexistente"}), 400
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

        file = request.files.get("comprobante")
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
        _gasto_add(data, session.get('usuario'), comp_rel, gid_forced=gid, monto_comprobante=monto_comp)
        return jsonify({"ok": True, "id": gid})
    else:
        return jsonify({"ok": False, "error": "usar-multipart-con-comprobante"}), 400

@app.delete("/api/gastos/<gid>")
def api_gastos_delete(gid):
    if 'usuario' not in session:
        return jsonify({"ok": False, "error": "no-auth"}), 401
    ok = _gasto_delete(gid)
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

    gan_empresa   = round(caja["total_recaudado"] - caja["gan_vendedores"], 2)
    utilidad_neta = round(gan_empresa - premios["premios_pagados_total"] - gastos_total - sueldos_total, 2)

    saldo_caja  = round(caja["efectivo"]      - gastos_caja, 2)
    saldo_banco = round(caja["transferencia"] - gastos_banco, 2)

    premios_detalle = _premios_pagados_detalle(desde, hasta)

    return jsonify({
        "ok": True,
        "rango": {"desde": desde, "hasta": hasta},
        "planillas_asignadas": planillas_asignadas,
        "boletos_entregados": boletos_entregados,
        "boletos_impresos": impresos,
        "boletos_vendidos": caja["vendidos"],
        "boletos_devueltos": caja["devueltos"],
        "ingresos_brutos": caja["total_recaudado"],
        "ganancia_vendedores": caja["gan_vendedores"],
        "ganancia_empresa": gan_empresa,
        "premios_pagados_total": premios["premios_pagados_total"],
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


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)




