
BEGIN;

ALTER TABLE equipos
ALTER COLUMN empresa_id SET NOT NULL;

ALTER TABLE usuarios
ALTER COLUMN empresa_id SET NOT NULL;

ALTER TABLE mantenimientos
ALTER COLUMN empresa_id SET NOT NULL;

ALTER TABLE fallas
ALTER COLUMN empresa_id SET NOT NULL;

ALTER TABLE equipos
DROP CONSTRAINT IF EXISTS equipos_codigo_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_equipos_empresa_codigo'
          AND conrelid = 'public.equipos'::regclass
    ) THEN
        ALTER TABLE equipos
        ADD CONSTRAINT uq_equipos_empresa_codigo
        UNIQUE (empresa_id, codigo);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_usuarios_empresa_usuario'
          AND conrelid = 'public.usuarios'::regclass
    ) THEN
        ALTER TABLE usuarios
        ADD CONSTRAINT uq_usuarios_empresa_usuario
        UNIQUE (empresa_id, usuario);
    END IF;
END $$;

COMMIT;
