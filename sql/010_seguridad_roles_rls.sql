/*
Script: 010_seguridad_roles_rls.sql  (aporte del equipo, NO es del socio formador)
Idempotente. Crea los roles de BD de la aplicación y la seguridad a nivel de fila (RLS).

  steward_cliente  -> solo SELECT en hechos y catálogos; RLS: solo ve filas con num_cte = app.num_cte
  steward_empleado -> SELECT en todo, EXCEPTO columnas personales de dim_cliente (fec_nac, genero_cte)

Así, aunque una herramienta o el LLM fallaran, la BASE no devuelve datos de otro cliente
ni columnas personales. El superusuario (dueño de las tablas) no está sujeto a RLS.
*/
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'steward_cliente') THEN
    CREATE ROLE steward_cliente LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'steward_empleado') THEN
    CREATE ROLE steward_empleado LOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA dim, cfg TO steward_cliente, steward_empleado;
REVOKE ALL ON ALL TABLES IN SCHEMA dim, cfg FROM steward_cliente, steward_empleado;

-- Cliente: solo lo necesario para su estado de cuenta
GRANT SELECT ON cfg.fact_sdos_captacoloca_m, cfg.fact_txn_captacoloca_d, dim.dim_producto, dim.dim_txn
  TO steward_cliente;
GRANT SELECT (num_cte, fec_alta, tipo_persona, segmento_cte) ON dim.dim_cliente TO steward_cliente;

-- Empleado: todo menos columnas personales (clasificación "Restringida")
GRANT SELECT ON cfg.fact_sdos_captacoloca_m, cfg.fact_txn_captacoloca_d, dim.dim_producto, dim.dim_txn
  TO steward_empleado;
DO $$
DECLARE cols text;
BEGIN
  SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
  FROM information_schema.columns
  WHERE table_schema = 'dim' AND table_name = 'dim_cliente'
    AND column_name NOT IN ('fec_nac', 'genero_cte');
  EXECUTE format('GRANT SELECT (%s) ON dim.dim_cliente TO steward_empleado', cols);
END $$;

-- Row Level Security
ALTER TABLE cfg.fact_sdos_captacoloca_m ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfg.fact_txn_captacoloca_d  ENABLE ROW LEVEL SECURITY;
ALTER TABLE dim.dim_cliente             ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_cliente  ON cfg.fact_sdos_captacoloca_m;
DROP POLICY IF EXISTS p_empleado ON cfg.fact_sdos_captacoloca_m;
DROP POLICY IF EXISTS p_cliente  ON cfg.fact_txn_captacoloca_d;
DROP POLICY IF EXISTS p_empleado ON cfg.fact_txn_captacoloca_d;
DROP POLICY IF EXISTS p_cliente  ON dim.dim_cliente;
DROP POLICY IF EXISTS p_empleado ON dim.dim_cliente;

CREATE POLICY p_cliente ON cfg.fact_sdos_captacoloca_m FOR SELECT TO steward_cliente
  USING (num_cte = NULLIF(current_setting('app.num_cte', true), '')::int);
CREATE POLICY p_cliente ON cfg.fact_txn_captacoloca_d FOR SELECT TO steward_cliente
  USING (num_cte = NULLIF(current_setting('app.num_cte', true), '')::int);
CREATE POLICY p_cliente ON dim.dim_cliente FOR SELECT TO steward_cliente
  USING (num_cte = NULLIF(current_setting('app.num_cte', true), '')::int);

CREATE POLICY p_empleado ON cfg.fact_sdos_captacoloca_m FOR SELECT TO steward_empleado USING (true);
CREATE POLICY p_empleado ON cfg.fact_txn_captacoloca_d  FOR SELECT TO steward_empleado USING (true);
CREATE POLICY p_empleado ON dim.dim_cliente             FOR SELECT TO steward_empleado USING (true);

ALTER ROLE steward_cliente  SET default_transaction_read_only = on;
ALTER ROLE steward_empleado SET default_transaction_read_only = on;
ALTER ROLE steward_cliente  SET statement_timeout = '15s';
ALTER ROLE steward_empleado SET statement_timeout = '15s';

-- Índices para que las consultas por cliente sean instantáneas
CREATE INDEX IF NOT EXISTS ix_sdos_cte ON cfg.fact_sdos_captacoloca_m (num_cte, fec_informacion);
CREATE INDEX IF NOT EXISTS ix_txn_cte  ON cfg.fact_txn_captacoloca_d  (num_cte, cve_mes_txn);
ANALYZE;

-- Regla DQ-09 (PF mayores de 18) sin exponer fec_nac: la función corre con permisos del dueño
-- y SOLO devuelve un conteo. El colaborador puede evaluar la regla sin ver ninguna fecha de nacimiento.
CREATE OR REPLACE FUNCTION dim.dq09_pf_menores_de_edad(fecha_ref date DEFAULT DATE '2026-06-30')
RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path = dim, pg_temp AS $$
  SELECT COUNT(*) FROM dim.dim_cliente
  WHERE tipo_persona = 'PF' AND fec_nac > fecha_ref - INTERVAL '18 years'
$$;
REVOKE ALL ON FUNCTION dim.dq09_pf_menores_de_edad(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION dim.dq09_pf_menores_de_edad(date) TO steward_empleado;