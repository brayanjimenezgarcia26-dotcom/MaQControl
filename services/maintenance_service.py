from datetime import date
from sqlalchemy import text
from database import db_session

def validate_horometer(value, previous=None):
    try:
        reading = float(value)
    except (TypeError, ValueError):
        raise ValueError('La lectura del horometro debe ser numerica')
    if reading < 0 or (previous is not None and reading < float(previous)):
        raise ValueError('La lectura debe ser positiva y no menor que la anterior')
    return reading

def maintenance_status(current_hours, target_hours=None, due_date=None, warning_hours=25, warning_days=7):
    result = {'status': 'Sin programacion', 'remaining_hours': None, 'remaining_days': None}
    if target_hours is not None:
        remaining = float(target_hours) - float(current_hours or 0)
        result['remaining_hours'] = round(remaining, 1)
        result['status'] = 'Vencido' if remaining <= 0 else 'Proximo' if remaining <= warning_hours else 'Programado'
    if due_date:
        if isinstance(due_date, str):
            due_date = date.fromisoformat(due_date)
        days = (due_date - date.today()).days
        result['remaining_days'] = days
        if days < 0:
            result['status'] = 'Vencido'
        elif days <= warning_days and result['status'] != 'Vencido':
            result['status'] = 'Proximo'
    return result

def record_horometer(company_id, equipment_id, reading, user_id=None, observation=''):
    with db_session() as db:
        equipment = db.execute(text('SELECT id, horometro FROM equipos WHERE id=:id AND empresa_id=:company_id FOR UPDATE'), {'id': equipment_id, 'company_id': company_id}).mappings().first()
        if not equipment:
            raise LookupError('Equipo no encontrado en esta empresa')
        value = validate_horometer(reading, equipment['horometro'])
        db.execute(text('UPDATE equipos SET horometro=:reading WHERE id=:id AND empresa_id=:company_id'), {'reading': value, 'id': equipment_id, 'company_id': company_id})
        db.execute(text('INSERT INTO lecturas_horometro (empresa_id,equipo_id,lectura,observacion,registrado_por) VALUES (:company_id,:equipment_id,:reading,:observation,:user_id)'), {'company_id': company_id, 'equipment_id': equipment_id, 'reading': value, 'observation': observation[:1000], 'user_id': user_id})
        return value

def list_due_maintenances(company_id):
    with db_session() as db:
        rows = db.execute(text("SELECT m.*, e.codigo AS equipo_codigo, e.nombre AS equipo_nombre, e.horometro AS horometro_actual FROM mantenimientos m JOIN equipos e ON e.id=m.equipo_id AND e.empresa_id=m.empresa_id WHERE m.empresa_id=:company_id AND m.estado <> 'Completado' ORDER BY m.fecha ASC"), {'company_id': company_id}).mappings().all()
        result = []
        for row in rows:
            item = dict(row)
            item.update(maintenance_status(item['horometro_actual'], item.get('horometro_objetivo'), item.get('fecha')))
            result.append(item)
        return result
