import csv
import io
import os
import re
import secrets
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, abort
from flask.cli import with_appcontext
import click
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from database import engine, db_session, initialize_database, database_health
from services.maintenance_service import validate_horometer, record_horometer, list_due_maintenances
from services.alert_service import build_maintenance_alerts, persist_new_alerts
from services.subscription_service import get_company_subscription, validate_equipment_limit, validate_feature, create_trial
from services.metrics_service import calculate_fleet_metrics

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)
PAGES = {'dashboard': 'dashboard.html', 'equipos': 'equipos.html', 'mantenimientos': 'mantenimientos.html', 'fallas': 'fallas.html', 'reportes': 'reportes.html'}
TABLES = {
    'equipos': {'fields': ['codigo', 'nombre', 'marca', 'modelo', 'serie', 'horometro', 'ubicacion', 'estado'], 'required': ['codigo', 'nombre'], 'numbers': ['horometro']},
    'mantenimientos': {'fields': ['equipo_id', 'tipo', 'descripcion', 'fecha', 'horometro_objetivo', 'responsable', 'estado'], 'required': ['equipo_id', 'tipo', 'descripcion', 'fecha'], 'numbers': ['equipo_id', 'horometro_objetivo']},
    'fallas': {'fields': ['equipo_id', 'descripcion', 'prioridad', 'fecha', 'responsable', 'estado', 'observaciones'], 'required': ['equipo_id', 'descripcion', 'fecha'], 'numbers': ['equipo_id']}
}
ESTADOS = {'equipos': ['Operativo', 'En mantenimiento', 'Fuera de servicio'], 'mantenimientos': ['Pendiente', 'En proceso', 'Completado'], 'fallas': ['Abierta', 'En revisión', 'Resuelta']}

@app.context_processor
def inject_csrf():
    return {'csrf_token': generate_csrf}

def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value

def rows_to_dict(rows):
    return [{key: json_value(value) for key, value in dict(row).items()} for row in rows]

def current_company_id():
    value = session.get('empresa_id')
    if not value:
        abort(403)
    return int(value)

def audit(action, entity, entity_id=None, detail=''):
    company_id = session.get('empresa_id')
    if not company_id:
        return
    try:
        with db_session() as db:
            db.execute(text('INSERT INTO auditoria (empresa_id,usuario_id,accion,entidad,entidad_id,detalle,ip) VALUES (:company_id,:user_id,:action,:entity,:entity_id,:detail,:ip)'), {'company_id': company_id, 'user_id': session.get('user_id'), 'action': action, 'entity': entity, 'entity_id': entity_id, 'detail': str(detail)[:2000], 'ip': request.headers.get('X-Forwarded-For', request.remote_addr)})
    except SQLAlchemyError:
        app.logger.exception('No se pudo registrar auditoria')

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get('user_id') or not session.get('empresa_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Sesion no iniciada'}), 401
            return redirect(url_for('login'))
        return function(*args, **kwargs)
    return wrapper

def roles_required(*roles):
    def decorator(function):
        @wraps(function)
        @login_required
        def wrapper(*args, **kwargs):
            if session.get('rol') not in roles:
                return jsonify({'error': 'No tienes permisos para realizar esta operacion'}), 403
            return function(*args, **kwargs)
        return wrapper
    return decorator

@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else 'no-cache'
    return response

@app.errorhandler(413)
def too_large(error):
    return jsonify({'error': 'El archivo o solicitud supera el limite permitido'}), 413

@app.errorhandler(500)
def internal_error(error):
    app.logger.exception('Error interno: %s', error)
    return jsonify({'error': 'Ocurrio un error interno. Revisa los registros del servidor.'}), 500

@app.route('/')
def home():
    return redirect(url_for('dashboard_home') if session.get('user_id') else url_for('login'))

@app.route('/login')
def login():
    return redirect(url_for('dashboard_home')) if session.get('user_id') else render_template('login.html')

@app.route('/<page>')
@login_required
def dashboard(page=None):
    if page not in PAGES:
        return redirect(url_for('dashboard_home'))
    return render_template(PAGES[page])

@app.route('/dashboard')
@login_required
def dashboard_home():
    return render_template('dashboard.html')

@app.post('/api/login')
def api_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('usuario', '')).strip()
    password = str(data.get('password', ''))
    empresa_slug = str(data.get('empresa', '')).strip().lower()
    if not username or not password:
        return jsonify({'error': 'Ingresa usuario y contrasena'}), 400
    with db_session() as db:
        query = text("""
            SELECT
                u.id,
                u.nombre,
                u.usuario,
                u.password_hash,
                u.rol,
                u.empresa_id,
                u.activo,
                e.nombre AS empresa_nombre,
                e.slug AS empresa_slug
            FROM usuarios u
            INNER JOIN empresas e ON e.id = u.empresa_id
            WHERE LOWER(u.usuario) = LOWER(:username)
              AND e.activa = TRUE
            ORDER BY u.id
        """)
        users = db.execute(
            query,
            {'username': username}
        ).mappings().all()
        if empresa_slug:
            users = [
                user for user in users
                if user['empresa_slug'].lower() == empresa_slug or user['empresa_nombre'].strip().lower() == empresa_slug
            ]
        if not users:
            return jsonify({
                'error': 'Usuario, empresa o contrasena incorrectos'
            }), 401
        if len(users) > 1:
            return jsonify({
                'error': 'Este usuario pertenece a varias empresas. Ingresa el identificador de tu empresa.',
                'requiere_empresa': True
            }), 409
        user = users[0]
        if not user['activo']:
            return jsonify({
                'error': 'La cuenta se encuentra desactivada'
            }), 403
        if not check_password_hash(user['password_hash'], password):
            return jsonify({
                'error': 'Usuario o contrasena incorrectos'
            }), 401
        db.execute(
            text("""
                UPDATE usuarios
                SET ultimo_acceso = CURRENT_TIMESTAMP
                WHERE id = :id
                  AND empresa_id = :empresa_id
            """),
            {
                'id': user['id'],
                'empresa_id': user['empresa_id']
            }
        )
    session.clear()
    session.permanent = True
    session['user_id'] = int(user['id'])
    session['empresa_id'] = int(user['empresa_id'])
    session['nombre'] = user['nombre']
    session['rol'] = user['rol']
    session['empresa_nombre'] = user['empresa_nombre']
    session['empresa_slug'] = user['empresa_slug']
    audit('inicio_sesion', 'usuarios', user['id'])
    return jsonify({
        'message': 'Bienvenido a MAQCONTROL',
        'redirect': '/dashboard'
    })

@app.post('/api/register')
def api_register():
    data = request.get_json(silent=True) or {}
    company_name = str(data.get('empresa', '')).strip()
    email = str(data.get('correo', '')).strip().lower()
    admin_name = str(data.get('nombre', '')).strip()
    username = str(data.get('usuario', '')).strip()
    password = str(data.get('password', ''))
    if not all((company_name, email, admin_name, username, password)):
        return jsonify({'error': 'Completa todos los campos para crear tu cuenta.'}), 400
    if len(company_name) > 160 or len(admin_name) > 160 or len(username) > 100:
        return jsonify({'error': 'Uno de los campos supera la longitud permitida.'}), 400
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 180:
        return jsonify({'error': 'Ingresa un correo electronico valido.'}), 400
    if len(password) < 12:
        return jsonify({'error': 'La contrasena debe tener al menos 12 caracteres.'}), 400
    if not re.fullmatch(r'[A-Za-z0-9._-]{3,100}', username):
        return jsonify({'error': 'El usuario debe tener entre 3 y 100 caracteres y solo puede incluir letras, numeros, punto, guion o guion bajo.'}), 400
    normalized = unicodedata.normalize('NFKD', company_name).encode('ascii', 'ignore').decode().lower()
    base_slug = re.sub(r'[^a-z0-9]+', '-', normalized).strip('-')[:145] or 'empresa'
    company_slug = f"{base_slug}-{secrets.token_hex(3)}"
    try:
        with db_session() as db:
            free_plan_id = db.execute(text("SELECT id FROM planes WHERE codigo='free' AND activo=TRUE")).scalar_one_or_none()
            if not free_plan_id:
                return jsonify({'error': 'El plan FREE aun no esta configurado. Ejecuta la migracion 004 y vuelve a intentarlo.'}), 503
            existing_user = db.execute(text('SELECT 1 FROM usuarios WHERE LOWER(usuario)=LOWER(:username) LIMIT 1'), {'username': username}).first()
            if existing_user:
                return jsonify({'error': 'Ese nombre de usuario ya esta registrado. Elige otro.'}), 409
            company_id = db.execute(text('INSERT INTO empresas (nombre,slug,correo,activa) VALUES (:nombre,:slug,:correo,TRUE) RETURNING id'), {'nombre': company_name, 'slug': company_slug, 'correo': email}).scalar_one()
            user_id = db.execute(text("INSERT INTO usuarios (empresa_id,nombre,usuario,password_hash,rol,activo) VALUES (:empresa_id,:nombre,:usuario,:password_hash,'Administrador',TRUE) RETURNING id"), {'empresa_id': company_id, 'nombre': admin_name, 'usuario': username, 'password_hash': generate_password_hash(password)}).scalar_one()
            db.execute(text("INSERT INTO suscripciones (empresa_id,plan_id,estado,inicio,fin_prueba,proximo_cobro) VALUES (:empresa_id,:plan_id,'activa',CURRENT_TIMESTAMP,NULL,NULL)"), {'empresa_id': company_id, 'plan_id': free_plan_id})
    except IntegrityError:
        return jsonify({'error': 'No se pudo crear la cuenta porque la empresa o el usuario ya existen. Verifica los datos e intenta nuevamente.'}), 409
    session.clear()
    session.permanent = True
    session['user_id'] = int(user_id)
    session['empresa_id'] = int(company_id)
    session['nombre'] = admin_name
    session['rol'] = 'Administrador'
    session['empresa_nombre'] = company_name
    session['empresa_slug'] = company_slug
    audit('registro_empresa', 'empresas', company_id, f'Plan FREE; administrador {username}')
    return jsonify({'message': 'Tu cuenta y empresa fueron creadas. Ya puedes comenzar con el plan FREE.', 'empresa_slug': company_slug, 'redirect': '/dashboard'}), 201

@app.post('/api/logout')
@login_required
def api_logout():
    audit('cierre_sesion', 'usuarios', session.get('user_id'))
    session.clear()
    return jsonify({'message': 'Sesion cerrada'})

@app.get('/api/me')
@login_required
def api_me():
    subscription = get_company_subscription(current_company_id())
    return jsonify({'nombre': session.get('nombre'), 'rol': session.get('rol'), 'empresa': session.get('empresa_nombre'), 'empresa_slug': session.get('empresa_slug'), 'suscripcion': subscription})

def validate_payload(table, data, company_id, record_id=None):
    config = TABLES[table]
    cleaned = {}
    for field in config['fields']:
        value = data.get(field)
        if field in config['numbers']:
            if value in (None, ''):
                value = None if field == 'horometro_objetivo' else 0
            try:
                value = float(value) if value is not None else None
            except (TypeError, ValueError):
                raise ValueError(f'Valor numerico invalido: {field}')
            if value is not None and value < 0:
                raise ValueError(f'{field} no puede ser negativo')
            if field == 'equipo_id':
                if not value or not value.is_integer():
                    raise ValueError('Selecciona un equipo valido')
                value = int(value)
        else:
            value = str(value or '').strip()
            if len(value) > 2000:
                raise ValueError(f'El campo {field} supera la longitud permitida')
        cleaned[field] = value
    for field in config['required']:
        if cleaned[field] is None or cleaned[field] == '':
            raise ValueError(f'El campo {field} es obligatorio')
    if table == 'equipos':
        cleaned['estado'] = cleaned['estado'] or 'Operativo'
        if cleaned['estado'] not in ESTADOS[table]:
            raise ValueError('Estado de equipo no permitido')
        if cleaned['horometro'] is None:
            cleaned['horometro'] = 0
    if table == 'mantenimientos':
        cleaned['estado'] = cleaned['estado'] or 'Pendiente'
        if cleaned['estado'] not in ESTADOS[table]:
            raise ValueError('Estado de mantenimiento no permitido')
        if cleaned['tipo'] not in ('Preventivo', 'Correctivo'):
            raise ValueError('Tipo de mantenimiento invalido')
    if table == 'fallas':
        cleaned['estado'] = cleaned['estado'] or 'Abierta'
        cleaned['prioridad'] = cleaned['prioridad'] or 'Media'
        if cleaned['estado'] not in ESTADOS[table]:
            raise ValueError('Estado de falla no permitido')
        if cleaned['prioridad'] not in ('Baja', 'Media', 'Alta', 'Crítica', 'Critica'):
            raise ValueError('Prioridad invalida')
    if table in ('mantenimientos', 'fallas'):
        try:
            date.fromisoformat(cleaned['fecha'])
        except (TypeError, ValueError):
            raise ValueError('Fecha invalida')
        with db_session() as db:
            equipment = db.execute(text('SELECT id FROM equipos WHERE id=:id AND empresa_id=:company_id'), {'id': cleaned['equipo_id'], 'company_id': company_id}).first()
            if not equipment:
                raise ValueError('El equipo seleccionado no existe en tu empresa')
    return cleaned

@app.get('/api/<table>')
@login_required
def list_records(table):
    if table not in TABLES:
        return jsonify({'error': 'Modulo no encontrado'}), 404
    company_id = current_company_id()
    with db_session() as db:
        if table == 'equipos':
            rows = db.execute(text('SELECT * FROM equipos WHERE empresa_id=:company_id ORDER BY id DESC'), {'company_id': company_id}).mappings().all()
        else:
            rows = db.execute(text(f'SELECT t.*,e.codigo AS equipo_codigo,e.nombre AS equipo_nombre FROM {table} t JOIN equipos e ON e.id=t.equipo_id AND e.empresa_id=t.empresa_id WHERE t.empresa_id=:company_id ORDER BY t.id DESC'), {'company_id': company_id}).mappings().all()
    return jsonify(rows_to_dict(rows))

@app.post('/api/<table>')
@login_required
def create_record(table):
    if table not in TABLES:
        return jsonify({'error': 'Modulo no encontrado'}), 404
    data = request.get_json(silent=True) or {}
    company_id = current_company_id()
    try:
        cleaned = validate_payload(table, data, company_id)
        fields = list(cleaned)
        columns = ','.join(fields + ['empresa_id'])
        value_parts = [f'CAST(:{field} AS DATE)' if field == 'fecha' and table in ('mantenimientos', 'fallas') else ':' + field for field in fields]
        params = ','.join(value_parts + [':company_id'])
        with db_session() as db:
            if table == 'equipos':
                db.execute(text('SELECT id FROM empresas WHERE id=:company_id FOR UPDATE'), {'company_id': company_id}).first()
                validate_equipment_limit(company_id, db=db)
            result = db.execute(text(f'INSERT INTO {table} ({columns}) VALUES ({params}) RETURNING id'), {**cleaned, 'company_id': company_id})
            record_id = result.scalar_one()
            if table == 'mantenimientos':
                db.execute(text('INSERT INTO ordenes_trabajo (empresa_id,equipo_id,mantenimiento_id,codigo,titulo,descripcion,tecnico,estado,fecha_programada) VALUES (:company_id,:equipment_id,:maintenance_id,:code,:title,:description,:technician,:state,CAST(:scheduled AS DATE))'), {'company_id': company_id, 'equipment_id': cleaned['equipo_id'], 'maintenance_id': record_id, 'code': f'OT-{datetime.now().strftime("%Y%m%d")}-{record_id}', 'title': cleaned['tipo'] + ' - ' + cleaned['descripcion'][:100], 'description': cleaned['descripcion'], 'technician': cleaned['responsable'], 'state': cleaned['estado'], 'scheduled': cleaned['fecha']})
        audit('crear', table, record_id)
        return jsonify({'message': 'Registro guardado correctamente', 'id': record_id}), 201
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    except PermissionError as error:
        return jsonify({'error': str(error), 'upgrade_required': True}), 402
    except IntegrityError:
        return jsonify({'error': 'Codigo duplicado o referencia invalida'}), 409

@app.put('/api/<table>/<int:record_id>')
@login_required
def update_record(table, record_id):
    if table not in TABLES:
        return jsonify({'error': 'Modulo no encontrado'}), 404
    data = request.get_json(silent=True) or {}
    company_id = current_company_id()
    try:
        cleaned = validate_payload(table, data, company_id, record_id)
        assignments = ','.join(f"{field}=CAST(:{field} AS DATE)" if field == 'fecha' and table in ('mantenimientos', 'fallas') else f'{field}=:{field}' for field in cleaned)
        with db_session() as db:
            result = db.execute(text(f'UPDATE {table} SET {assignments} WHERE id=:record_id AND empresa_id=:company_id'), {**cleaned, 'record_id': record_id, 'company_id': company_id})
            if result.rowcount == 0:
                return jsonify({'error': 'Registro no encontrado'}), 404
            if table == 'mantenimientos':
                db.execute(text('UPDATE ordenes_trabajo SET estado=:state,tecnico=:technician,fecha_programada=CAST(:scheduled AS DATE) WHERE mantenimiento_id=:maintenance_id AND empresa_id=:company_id'), {'state': cleaned['estado'], 'technician': cleaned['responsable'], 'scheduled': cleaned['fecha'], 'maintenance_id': record_id, 'company_id': company_id})
        audit('actualizar', table, record_id)
        return jsonify({'message': 'Registro actualizado'})
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    except IntegrityError:
        return jsonify({'error': 'Codigo duplicado o referencia invalida'}), 409

@app.delete('/api/<table>/<int:record_id>')
@login_required
def delete_record(table, record_id):
    if table not in TABLES:
        return jsonify({'error': 'Modulo no encontrado'}), 404
    try:
        with db_session() as db:
            if table == 'mantenimientos':
                db.execute(text('DELETE FROM ordenes_trabajo WHERE mantenimiento_id=:record_id AND empresa_id=:company_id'), {'record_id': record_id, 'company_id': current_company_id()})
            result = db.execute(text(f'DELETE FROM {table} WHERE id=:record_id AND empresa_id=:company_id'), {'record_id': record_id, 'company_id': current_company_id()})
            if result.rowcount == 0:
                return jsonify({'error': 'Registro no encontrado'}), 404
    except IntegrityError:
        return jsonify({'error': 'El registro tiene informacion relacionada y no puede eliminarse'}), 409
    audit('eliminar', table, record_id)
    return jsonify({'message': 'Registro eliminado'})

@app.get('/api/resumen')
@login_required
def summary():
    company_id = current_company_id()
    metrics = calculate_fleet_metrics(company_id)
    with db_session() as db:
        upcoming = db.execute(text("SELECT m.*,e.codigo AS equipo_codigo,e.nombre AS equipo_nombre,e.horometro AS horometro_actual FROM mantenimientos m JOIN equipos e ON e.id=m.equipo_id AND e.empresa_id=m.empresa_id WHERE m.empresa_id=:company_id AND m.estado <> 'Completado' ORDER BY m.fecha ASC LIMIT 6"), {'company_id': company_id}).mappings().all()
        latest_faults = db.execute(text('SELECT f.*,e.codigo AS equipo_codigo,e.nombre AS equipo_nombre FROM fallas f JOIN equipos e ON e.id=f.equipo_id AND e.empresa_id=f.empresa_id WHERE f.empresa_id=:company_id ORDER BY f.id DESC LIMIT 5'), {'company_id': company_id}).mappings().all()
    metrics['proximos'] = rows_to_dict(upcoming)
    metrics['ultimas_fallas'] = rows_to_dict(latest_faults)
    metrics['alertas_mantenimiento'] = build_maintenance_alerts(company_id)
    metrics['suscripcion'] = get_company_subscription(company_id)
    return jsonify(metrics)

@app.get('/api/exportar/<table>')
@login_required
def export_csv(table):
    if table not in TABLES:
        return jsonify({'error': 'Modulo no encontrado'}), 404
    try:
        validate_feature(current_company_id(), 'reportes_exportables')
    except PermissionError as error:
        return jsonify({'error': str(error), 'upgrade_required': True}), 402
    with db_session() as db:
        rows = db.execute(text(f'SELECT * FROM {table} WHERE empresa_id=:company_id ORDER BY id DESC'), {'company_id': current_company_id()}).mappings().all()
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow([json_value(value) for value in row.values()])
    else:
        writer.writerow(['Sin registros'])
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=maqcontrol_{table}.csv'})

@app.get('/api/ordenes')
@login_required
def api_work_orders():
    with db_session() as db:
        rows = db.execute(text('SELECT o.*,e.codigo AS equipo_codigo,e.nombre AS equipo_nombre FROM ordenes_trabajo o JOIN equipos e ON e.id=o.equipo_id AND e.empresa_id=o.empresa_id WHERE o.empresa_id=:company_id ORDER BY o.id DESC'), {'company_id': current_company_id()}).mappings().all()
    return jsonify(rows_to_dict(rows))

@app.post('/api/horometro')
@login_required
def api_horometer():
    data = request.get_json(silent=True) or {}
    try:
        equipment_id = int(data.get('equipo_id'))
        value = record_horometer(current_company_id(), equipment_id, data.get('lectura'), session.get('user_id'), str(data.get('observacion', '')))
        audit('registrar_horometro', 'equipos', equipment_id, value)
        return jsonify({'message': 'Lectura de horometro guardada', 'lectura': value})
    except (ValueError, LookupError, TypeError) as error:
        return jsonify({'error': str(error) or 'Datos de horometro invalidos'}), 400

@app.get('/api/suscripcion')
@login_required
def api_subscription():
    return jsonify({'suscripcion': get_company_subscription(current_company_id())})

@app.get('/api/planes')
@login_required
def api_plans():
    with db_session() as db:
        rows = db.execute(text('SELECT codigo,nombre,precio_mensual,max_equipos,indicadores,reportes_exportables,multiples_sedes,soporte_prioritario FROM planes WHERE activo=TRUE ORDER BY precio_mensual')).mappings().all()
    return jsonify(rows_to_dict(rows))

@app.post('/api/notificaciones/generar')
@login_required
def api_generate_notifications():
    created = persist_new_alerts(current_company_id())
    return jsonify({'message': 'Revision de alertas completada', 'creadas': created})

@app.get('/api/notificaciones')
@login_required
def api_notifications():
    with db_session() as db:
        rows = db.execute(text('SELECT * FROM notificaciones WHERE empresa_id=:company_id ORDER BY creada_en DESC LIMIT 100'), {'company_id': current_company_id()}).mappings().all()
    return jsonify(rows_to_dict(rows))

@app.post('/api/suscripcion/seleccionar')
@roles_required('Administrador', 'Gerente')
def api_select_plan():
    data = request.get_json(silent=True) or {}
    code = str(data.get('plan', '')).strip().lower()
    company_id = current_company_id()
    with db_session() as db:
        plan = db.execute(text('SELECT id FROM planes WHERE codigo=:code AND activo=TRUE'), {'code': code}).scalar_one_or_none()
        if not plan:
            return jsonify({'error': 'Plan no encontrado'}), 404
        if code == 'free':
            return jsonify({'error': 'El plan FREE se asigna al crear la cuenta y permanece disponible. Para consultar otros planes, comunicate al 947232206.'}), 400
        subscription_id = db.execute(text("INSERT INTO suscripciones (empresa_id,plan_id,estado,inicio,fin_prueba,proximo_cobro) VALUES (:company_id,:plan_id,'pendiente_pago',CURRENT_TIMESTAMP,NULL,NULL) RETURNING id"), {'company_id': company_id, 'plan_id': plan}).scalar_one()
    audit('seleccionar_plan', 'suscripciones', subscription_id, code)
    return jsonify({'message': 'Plan seleccionado. Registra el comprobante de pago para solicitar activacion.', 'subscription_id': subscription_id}), 201

@app.post('/api/pagos')
@roles_required('Administrador', 'Gerente')
def api_create_payment():
    data = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(data.get('monto', '0')))
    except Exception:
        return jsonify({'error': 'Monto invalido'}), 400
    if amount <= 0:
        return jsonify({'error': 'El monto debe ser mayor que cero'}), 400
    company_id = current_company_id()
    with db_session() as db:
        subscription = db.execute(text('SELECT id FROM suscripciones WHERE empresa_id=:company_id ORDER BY id DESC LIMIT 1'), {'company_id': company_id}).scalar_one_or_none()
        if not subscription:
            return jsonify({'error': 'La empresa no tiene una suscripcion registrada'}), 400
        result = db.execute(text('INSERT INTO pagos (empresa_id,suscripcion_id,monto,metodo,referencia,estado,pagado_en) VALUES (:company_id,:subscription,:amount,:method,:reference,:status,:paid_at) RETURNING id'), {'company_id': company_id, 'subscription': subscription, 'amount': amount, 'method': str(data.get('metodo', 'Transferencia'))[:40], 'reference': str(data.get('referencia', ''))[:120], 'status': 'pendiente', 'paid_at': None})
        payment_id = result.scalar_one()
    audit('registrar_pago', 'pagos', payment_id, amount)
    return jsonify({'message': 'Pago registrado', 'id': payment_id}), 201

@app.get('/health')
def health():
    result = database_health()
    return jsonify(result), 200 if result['status'] == 'ok' else 503

@app.cli.command('create-admin')
def create_admin_command():
    username = Config.BOOTSTRAP_ADMIN_USER or input('Usuario administrador: ').strip()
    password = Config.BOOTSTRAP_ADMIN_PASSWORD or click.prompt('Contrasena segura', hide_input=True, confirmation_prompt=True)
    name = Config.BOOTSTRAP_ADMIN_NAME
    company_name = Config.BOOTSTRAP_COMPANY
    if len(password) < 12:
        raise SystemExit('La contrasena debe tener al menos 12 caracteres')
    slug = re.sub(r'[^a-z0-9]+', '-', unicodedata.normalize('NFKD', company_name).encode('ascii', 'ignore').decode().lower()).strip('-') or secrets.token_hex(4)
    with db_session() as db:
        company_id = db.execute(text('SELECT id FROM empresas WHERE slug=:slug'), {'slug': slug}).scalar_one_or_none()
        if not company_id:
            legacy_company = db.execute(text("SELECT id FROM empresas WHERE slug='maqcontrol-inicial'")).scalar_one_or_none()
            if legacy_company:
                db.execute(text('UPDATE empresas SET nombre=:name,slug=:slug WHERE id=:id'), {'name': company_name, 'slug': slug, 'id': legacy_company})
                company_id = legacy_company
            else:
                company_id = db.execute(text('INSERT INTO empresas (nombre,slug) VALUES (:name,:slug) RETURNING id'), {'name': company_name, 'slug': slug}).scalar_one()
        existing = db.execute(text('SELECT id FROM usuarios WHERE LOWER(usuario)=LOWER(:username) AND empresa_id=:company_id'), {'username': username, 'company_id': company_id}).first()
        if existing:
            raise SystemExit('Ese usuario ya existe en la empresa')
        db.execute(text('INSERT INTO usuarios (empresa_id,nombre,usuario,password_hash,rol,activo) VALUES (:company_id,:name,:username,:password_hash,:role,TRUE)'), {'company_id': company_id, 'name': name, 'username': username, 'password_hash': generate_password_hash(password), 'role': 'Administrador'})
    create_trial(company_id, 'free')
    print(f'Administrador creado para la empresa {company_name}. Guarda las credenciales de forma segura.')

@app.cli.command('import-sqlite')
def import_sqlite_command():
    source = BASE_DIR / 'maqcontrol.db'
    if not source.exists():
        raise SystemExit('No se encontro maqcontrol.db en la carpeta principal')
    with db_session() as db:
        company_id = db.execute(text('SELECT empresa_id FROM usuarios ORDER BY id LIMIT 1')).scalar_one_or_none()
        if not company_id:
            raise SystemExit('Primero crea el administrador con flask --app app create-admin')
        existing = db.execute(text('SELECT COUNT(*) FROM equipos WHERE empresa_id=:company_id'), {'company_id': company_id}).scalar_one()
        if existing:
            raise SystemExit('La empresa ya tiene equipos. Se cancelo para evitar duplicados.')
    source_db = sqlite3.connect(str(source))
    source_db.row_factory = sqlite3.Row
    try:
        old_equipment = source_db.execute('SELECT * FROM equipos ORDER BY id').fetchall()
        old_maintenance = source_db.execute('SELECT * FROM mantenimientos ORDER BY id').fetchall()
        old_faults = source_db.execute('SELECT * FROM fallas ORDER BY id').fetchall()
    except sqlite3.Error as error:
        source_db.close()
        raise SystemExit(f'No se pudo leer la base SQLite: {error}')
    finally:
        try:
            source_db.close()
        except Exception:
            pass
    equipment_map = {}
    with db_session() as db:
        company_id = db.execute(text('SELECT empresa_id FROM usuarios ORDER BY id LIMIT 1')).scalar_one()
        for item in old_equipment:
            values = dict(item)
            result = db.execute(text('INSERT INTO equipos (empresa_id,codigo,nombre,marca,modelo,serie,horometro,ubicacion,estado) VALUES (:company_id,:codigo,:nombre,:marca,:modelo,:serie,:horometro,:ubicacion,:estado) RETURNING id'), {'company_id': company_id, 'codigo': values.get('codigo') or f"IMP-{values['id']}", 'nombre': values.get('nombre') or 'Equipo importado', 'marca': values.get('marca') or '', 'modelo': values.get('modelo') or '', 'serie': values.get('serie') or values.get('numero_serie') or '', 'horometro': float(values.get('horometro') or 0), 'ubicacion': values.get('ubicacion') or '', 'estado': values.get('estado') or 'Operativo'})
            equipment_map[values['id']] = result.scalar_one()
        for item in old_maintenance:
            values = dict(item)
            new_equipment_id = equipment_map.get(values.get('equipo_id'))
            if not new_equipment_id:
                continue
            db.execute(text('INSERT INTO mantenimientos (empresa_id,equipo_id,tipo,descripcion,fecha,horometro_objetivo,responsable,estado) VALUES (:company_id,:equipment_id,:tipo,:descripcion,CAST(:fecha AS DATE),:target,:responsable,:estado)'), {'company_id': company_id, 'equipment_id': new_equipment_id, 'tipo': values.get('tipo') or 'Preventivo', 'descripcion': values.get('descripcion') or 'Mantenimiento importado', 'fecha': values.get('fecha') or date.today(), 'target': values.get('horometro_objetivo'), 'responsable': values.get('responsable') or '', 'estado': values.get('estado') or 'Pendiente'})
        for item in old_faults:
            values = dict(item)
            new_equipment_id = equipment_map.get(values.get('equipo_id'))
            if not new_equipment_id:
                continue
            db.execute(text('INSERT INTO fallas (empresa_id,equipo_id,descripcion,prioridad,fecha,responsable,estado,observaciones) VALUES (:company_id,:equipment_id,:descripcion,:prioridad,CAST(:fecha AS DATE),:responsable,:estado,:observaciones)'), {'company_id': company_id, 'equipment_id': new_equipment_id, 'descripcion': values.get('descripcion') or 'Falla importada', 'prioridad': values.get('prioridad') or 'Media', 'fecha': values.get('fecha') or date.today(), 'responsable': values.get('responsable') or '', 'estado': values.get('estado') or 'Abierta', 'observaciones': values.get('observaciones') or values.get('causa') or ''})
    print(f'Importacion finalizada: {len(old_equipment)} equipos, {len(old_maintenance)} mantenimientos y {len(old_faults)} fallas procesados.')

@app.cli.command('check-db')
def check_db_command():
    print(database_health())

@app.cli.command('confirm-payment')
@click.argument('payment_id', type=int)
def confirm_payment_command(payment_id):
    with db_session() as db:
        payment = db.execute(text("SELECT id,empresa_id,suscripcion_id,monto FROM pagos WHERE id=:id AND estado='pendiente'"), {'id': payment_id}).mappings().first()
        if not payment:
            raise SystemExit('No existe un pago pendiente con ese ID')
        db.execute(text("UPDATE pagos SET estado='pagado',pagado_en=CURRENT_TIMESTAMP WHERE id=:id"), {'id': payment_id})
        db.execute(text("UPDATE suscripciones SET estado='activa',proximo_cobro=CURRENT_TIMESTAMP + INTERVAL '1 month',fin_prueba=NULL WHERE id=:id AND empresa_id=:company_id"), {'id': payment['suscripcion_id'], 'company_id': payment['empresa_id']})
    print(f'Pago {payment_id} confirmado y suscripcion activada. Verifica el comprobante bancario antes de usar este comando.')

with app.app_context():
    Config.validate()
    initialize_database()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '5000')), debug=Config.DEBUG)
