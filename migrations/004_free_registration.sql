BEGIN;

INSERT INTO planes (codigo,nombre,precio_mensual,max_equipos,indicadores,reportes_exportables,multiples_sedes,soporte_prioritario,activo)
VALUES ('free','FREE',0,2,FALSE,FALSE,FALSE,FALSE,TRUE)
ON CONFLICT (codigo) DO UPDATE SET nombre=EXCLUDED.nombre,precio_mensual=0,max_equipos=2,indicadores=FALSE,reportes_exportables=FALSE,multiples_sedes=FALSE,soporte_prioritario=FALSE,activo=TRUE;

INSERT INTO suscripciones (empresa_id,plan_id,estado,inicio,fin_prueba,proximo_cobro)
SELECT e.id,p.id,'activa',CURRENT_TIMESTAMP,NULL,NULL
FROM empresas e CROSS JOIN planes p
WHERE p.codigo='free' AND NOT EXISTS (SELECT 1 FROM suscripciones s WHERE s.empresa_id=e.id);

CREATE INDEX IF NOT EXISTS ix_suscripciones_empresa_reciente ON suscripciones(empresa_id,id DESC);

COMMIT;
