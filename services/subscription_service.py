from datetime import datetime, timezone
from sqlalchemy import text
from database import db_session

def get_company_subscription(company_id, db=None):
    query = text("SELECT s.id AS subscription_id,s.estado,s.inicio,s.fin_prueba,s.proximo_cobro,p.codigo AS plan_codigo,p.nombre AS plan_nombre,p.precio_mensual,p.max_equipos,p.indicadores,p.reportes_exportables,p.multiples_sedes,p.soporte_prioritario FROM suscripciones s JOIN planes p ON p.id=s.plan_id WHERE s.empresa_id=:company_id ORDER BY CASE WHEN s.estado='activa' THEN 0 ELSE 1 END,s.id DESC LIMIT 1")
    if db is not None:
        row = db.execute(query, {'company_id': company_id}).mappings().first()
    else:
        with db_session() as current_db:
            row = current_db.execute(query, {'company_id': company_id}).mappings().first()
    if not row:
        return None
    result = dict(row)
    if result.get('precio_mensual') is not None:
        result['precio_mensual'] = float(result['precio_mensual'])
    return result

def subscription_is_active(subscription):
    if not subscription:
        return False
    if subscription.get('plan_codigo') == 'free':
        return subscription.get('estado') == 'activa'
    if subscription.get('estado') == 'activa':
        return True
    if subscription.get('estado') == 'prueba' and subscription.get('fin_prueba'):
        end = subscription['fin_prueba']
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return end >= datetime.now(timezone.utc)
    return False

def validate_equipment_limit(company_id, db=None):
    subscription = get_company_subscription(company_id, db=db)
    if not subscription or not subscription_is_active(subscription):
        raise PermissionError('La suscripcion no esta activa. Contacta con MAQCONTROL para revisar tu plan.')
    query = text('SELECT COUNT(*) FROM equipos WHERE empresa_id=:company_id')
    if db is not None:
        count = db.execute(query, {'company_id': company_id}).scalar_one()
    else:
        with db_session() as current_db:
            count = current_db.execute(query, {'company_id': company_id}).scalar_one()
    maximum = int(subscription['max_equipos'])
    if count >= maximum:
        if subscription['plan_codigo'] == 'free':
            raise PermissionError('Tu plan FREE permite registrar hasta 2 maquinas. Para ampliar tu capacidad, contacta al equipo comercial por WhatsApp: 947232206.')
        raise PermissionError(f"Tu plan {subscription['plan_nombre']} permite hasta {maximum} maquinas. Contacta a MAQCONTROL para ampliar tu capacidad.")
    return {'used': count, 'maximum': maximum, 'available': maximum-count, 'plan': subscription['plan_codigo']}

def validate_feature(company_id, feature):
    subscription = get_company_subscription(company_id)
    if not subscription or not subscription_is_active(subscription):
        raise PermissionError('La suscripcion no esta activa')
    if not subscription.get(feature, False):
        raise PermissionError('Esta funcion requiere un plan superior. Contacta al 947232206.')
    return subscription

def create_trial(company_id, plan_code='free', days=30):
    with db_session() as db:
        plan_id = db.execute(text('SELECT id FROM planes WHERE codigo=:code AND activo=TRUE'), {'code': plan_code}).scalar_one_or_none()
        if not plan_id:
            raise ValueError('Plan no encontrado')
        existing = db.execute(text('SELECT id FROM suscripciones WHERE empresa_id=:company_id ORDER BY id DESC LIMIT 1'), {'company_id': company_id}).first()
        if existing:
            return existing.id
        if plan_code == 'free':
            return db.execute(text("INSERT INTO suscripciones (empresa_id,plan_id,estado,inicio,fin_prueba) VALUES (:company_id,:plan_id,'activa',CURRENT_TIMESTAMP,NULL) RETURNING id"), {'company_id': company_id, 'plan_id': plan_id}).scalar_one()
        return db.execute(text("INSERT INTO suscripciones (empresa_id,plan_id,estado,inicio,fin_prueba) VALUES (:company_id,:plan_id,'prueba',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP + (:days * INTERVAL '1 day')) RETURNING id"), {'company_id': company_id, 'plan_id': plan_id, 'days': days}).scalar_one()
