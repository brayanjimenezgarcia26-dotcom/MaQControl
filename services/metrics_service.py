from sqlalchemy import text
from database import db_session

def calculate_fleet_metrics(company_id):
    with db_session() as db:
        equipment = db.execute(text("SELECT COUNT(*) AS total,COUNT(*) FILTER (WHERE estado='Operativo') AS operativos,COUNT(*) FILTER (WHERE estado='En mantenimiento') AS mantenimiento,COUNT(*) FILTER (WHERE estado='Fuera de servicio') AS fuera_servicio FROM equipos WHERE empresa_id=:company_id"), {'company_id': company_id}).mappings().one()
        failures = db.execute(text("SELECT COUNT(*) AS total,COUNT(*) FILTER (WHERE estado <> 'Resuelta') AS activas,COUNT(*) FILTER (WHERE prioridad IN ('Critica','Crítica')) AS criticas FROM fallas WHERE empresa_id=:company_id"), {'company_id': company_id}).mappings().one()
        maintenance = db.execute(text("SELECT COUNT(*) AS total,COUNT(*) FILTER (WHERE estado <> 'Completado') AS pendientes,COUNT(*) FILTER (WHERE estado='Completado') AS completados FROM mantenimientos WHERE empresa_id=:company_id"), {'company_id': company_id}).mappings().one()
        availability = round(equipment['operativos'] * 100 / equipment['total'], 1) if equipment['total'] else 0
        return {'total': equipment['total'], 'operativos': equipment['operativos'], 'en_mantenimiento': equipment['mantenimiento'], 'fuera_servicio': equipment['fuera_servicio'], 'disponibilidad': availability, 'fallas_total': failures['total'], 'fallas_activas': failures['activas'], 'fallas_criticas': failures['criticas'], 'mantenimientos_total': maintenance['total'], 'mantenimientos_pendientes': maintenance['pendientes'], 'mantenimientos_completados': maintenance['completados'], 'mtbf_horas': None, 'mttr_horas': None, 'metricas_confiabilidad_disponibles': False}
