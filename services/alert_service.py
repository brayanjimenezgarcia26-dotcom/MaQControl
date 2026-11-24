from sqlalchemy import text
from database import db_session
from services.maintenance_service import list_due_maintenances

def build_maintenance_alerts(company_id):
    alerts = []
    for item in list_due_maintenances(company_id):
        if item['status'] in ('Vencido', 'Proximo'):
            alerts.append({'tipo': 'mantenimiento_vencido' if item['status'] == 'Vencido' else 'mantenimiento_proximo', 'equipo_id': item['equipo_id'], 'equipo_codigo': item['equipo_codigo'], 'titulo': f"Servicio {item['status'].lower()}", 'mensaje': f"{item['equipo_codigo']}: {item['descripcion']}. Horas restantes: {item['remaining_hours']}; dias restantes: {item['remaining_days']}"})
    return alerts

def persist_new_alerts(company_id):
    alerts = build_maintenance_alerts(company_id)
    created = 0
    with db_session() as db:
        for alert in alerts:
            exists = db.execute(text("SELECT id FROM notificaciones WHERE empresa_id=:company_id AND equipo_id=:equipment_id AND tipo=:kind AND leida=FALSE AND creada_en > CURRENT_TIMESTAMP - INTERVAL '1 day' LIMIT 1"), {'company_id': company_id, 'equipment_id': alert['equipo_id'], 'kind': alert['tipo']}).first()
            if not exists:
                db.execute(text('INSERT INTO notificaciones (empresa_id,equipo_id,tipo,titulo,mensaje) VALUES (:company_id,:equipment_id,:kind,:title,:message)'), {'company_id': company_id, 'equipment_id': alert['equipo_id'], 'kind': alert['tipo'], 'title': alert['titulo'], 'message': alert['mensaje']})
                created += 1
    return created
