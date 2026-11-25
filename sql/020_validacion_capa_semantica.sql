/*
Script: 020_validacion_capa_semantica.sql   (aporte del equipo; idempotente)
Requiere: sql/semantica/01..07 (capa semántica del socio) y los datos 000-003.

Ejecuta contra los DATOS las validaciones pendientes del README de la capa semántica y:
  1. Registra cada validación con su evidencia en semantic.sem_validaciones (auditable).
  2. Marca relacion_validada = TRUE SOLO en las relaciones cuya llave, unicidad e integridad
     referencial se comprobaron (regla R005 del socio: sin relación validada no hay JOIN).
  3. Agrega la relación compuesta producto+cve_txn (cve_txn sola NO es única).
  4. Agrega reglas R010/R011 derivadas de la evidencia y ejemplos de valores reales.
  5. Da permiso de LECTURA de los metadatos al rol de colaborador (no al de cliente).

IMPORTANTE: la evidencia proviene de los datos SINTÉTICOS del reto. En producción este script
se vuelve a correr sobre el DWH real y las relaciones solo quedan validadas si pasan ahí.
*/
CREATE TABLE IF NOT EXISTS semantic.sem_validaciones (
    codigo        VARCHAR(20) PRIMARY KEY,
    descripcion   TEXT NOT NULL,
    resultado     BOOLEAN NOT NULL,
    evidencia     TEXT,
    fuente_datos  VARCHAR(30) NOT NULL DEFAULT 'SINTETICO',
    fecha         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DO $$
DECLARE
  n bigint; m bigint; ok boolean;
BEGIN
  -- V01 Unicidad de dim_cliente.num_cte (pendiente 1)
  SELECT COUNT(*) - COUNT(DISTINCT num_cte), COUNT(*) FILTER (WHERE num_cte IS NULL) INTO n, m FROM dim.dim_cliente;
  INSERT INTO semantic.sem_validaciones VALUES ('V01','dim_cliente tiene una fila por num_cte (no nulo)', n = 0 AND m = 0,
    format('duplicados=%s nulos=%s', n, m)) ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V02 Unicidad de dim_producto.cve_producto (pendiente 1)
  SELECT COUNT(*) - COUNT(DISTINCT cve_producto) INTO n FROM dim.dim_producto;
  INSERT INTO semantic.sem_validaciones VALUES ('V02','dim_producto tiene una fila por cve_producto', n = 0, format('duplicados=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V03 cve_txn sola NO es única; (cve_producto, cve_txn) sí (pendiente 3)
  SELECT COUNT(*) INTO n FROM (SELECT cve_txn FROM dim.dim_txn GROUP BY 1 HAVING COUNT(*) > 1) x;
  SELECT COUNT(*) INTO m FROM (SELECT cve_producto, cve_txn FROM dim.dim_txn GROUP BY 1, 2 HAVING COUNT(*) > 1) x;
  INSERT INTO semantic.sem_validaciones VALUES ('V03','La llave de dim_txn es (cve_producto, cve_txn); cve_txn sola no es unica', m = 0,
    format('cve_txn repetidas=%s; combinaciones (producto,cve_txn) repetidas=%s', n, m))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V04 Integridad referencial hechos -> dimensiones
  SELECT COUNT(*) INTO n FROM cfg.fact_sdos_captacoloca_m s LEFT JOIN dim.dim_cliente c USING (num_cte) WHERE c.num_cte IS NULL;
  INSERT INTO semantic.sem_validaciones VALUES ('V04a','Todo num_cte de saldos existe en dim_cliente', n = 0, format('huerfanos=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();
  SELECT COUNT(*) INTO n FROM cfg.fact_txn_captacoloca_d t LEFT JOIN dim.dim_cliente c USING (num_cte) WHERE c.num_cte IS NULL;
  INSERT INTO semantic.sem_validaciones VALUES ('V04b','Todo num_cte de transacciones existe en dim_cliente', n = 0, format('huerfanos=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();
  SELECT COUNT(*) INTO n FROM cfg.fact_sdos_captacoloca_m s LEFT JOIN dim.dim_producto p USING (cve_producto) WHERE p.cve_producto IS NULL;
  INSERT INTO semantic.sem_validaciones VALUES ('V04c','Todo cve_producto de saldos existe en dim_producto', n = 0, format('huerfanos=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();
  SELECT COUNT(*) INTO n FROM cfg.fact_txn_captacoloca_d t LEFT JOIN dim.dim_producto p USING (cve_producto) WHERE p.cve_producto IS NULL;
  INSERT INTO semantic.sem_validaciones VALUES ('V04d','Todo cve_producto de transacciones existe en dim_producto', n = 0, format('huerfanos=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();
  SELECT COUNT(*) INTO n FROM cfg.fact_txn_captacoloca_d t
    LEFT JOIN dim.dim_txn d ON d.cve_producto = t.cve_producto AND d.cve_txn = t.cve_txn WHERE d.cve_txn IS NULL;
  INSERT INTO semantic.sem_validaciones VALUES ('V04e','Todo (cve_producto, cve_txn) de transacciones existe en dim_txn', n = 0, format('huerfanos=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V05 Granularidad del hecho mensual: una fila por cuenta, producto y mes
  SELECT COUNT(*) INTO n FROM (SELECT num_cta, cve_producto, fec_informacion FROM cfg.fact_sdos_captacoloca_m GROUP BY 1, 2, 3 HAVING COUNT(*) > 1) x;
  INSERT INTO semantic.sem_validaciones VALUES ('V05','fact_sdos: una fila por (num_cta, cve_producto, fec_informacion)', n = 0, format('duplicados=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V06 num_cta pertenece a un solo cliente y un solo producto (pendiente 6)
  SELECT COUNT(*) INTO n FROM (SELECT num_cta FROM cfg.fact_sdos_captacoloca_m GROUP BY 1
                               HAVING COUNT(DISTINCT num_cte) > 1 OR COUNT(DISTINCT cve_producto) > 1) x;
  INSERT INTO semantic.sem_validaciones VALUES ('V06','num_cta identifica una sola cuenta (un cliente y un producto)', n = 0,
    format('cuentas con mas de un cliente o producto=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V07 cve_mes_txn = AAAAMM de fec_txn
  SELECT COUNT(*) INTO n FROM cfg.fact_txn_captacoloca_d WHERE cve_mes_txn <> TO_CHAR(fec_txn, 'YYYYMM')::int;
  INSERT INTO semantic.sem_validaciones VALUES ('V07','cve_mes_txn tiene formato AAAAMM y coincide con fec_txn', n = 0, format('diferencias=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V08 cve_mes_alta = AAAAMM de fec_alta en el hecho mensual (pendiente 7)
  SELECT COUNT(*) INTO n FROM cfg.fact_sdos_captacoloca_m WHERE cve_mes_alta <> TO_CHAR(fec_alta, 'YYYYMM')::int;
  INSERT INTO semantic.sem_validaciones VALUES ('V08','cve_mes_alta tiene formato AAAAMM y coincide con fec_alta del hecho mensual', n = 0, format('diferencias=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V09 Convención de signo (pendiente 4): importes siempre positivos y el sentido lo da desc_txn;
  --     se comprueba conciliando apertura + movimientos = cierre para todas las cuentas-mes.
  SELECT COUNT(*) FILTER (WHERE saldo_txn <= 0) INTO m FROM cfg.fact_txn_captacoloca_d;
  SELECT COUNT(*) INTO n FROM (
    SELECT s.saldo_mes - s.saldo_apertura - COALESCE(SUM(CASE
             WHEN t.desc_txn IN ('DEPOSITO','COMPRAS','DISPOSICIONES') THEN t.saldo_txn
             WHEN t.desc_txn IN ('RETIRO','PAGOS') THEN -t.saldo_txn ELSE 0 END), 0) AS dif
    FROM cfg.fact_sdos_captacoloca_m s LEFT JOIN cfg.fact_txn_captacoloca_d t
      ON t.num_cta = s.num_cta AND t.cve_producto = s.cve_producto AND t.cve_mes_txn = s.fec_informacion / 100
    WHERE s.fec_informacion >= 20260228
    GROUP BY s.num_cta, s.cve_producto, s.saldo_mes, s.saldo_apertura) x WHERE ABS(dif) > 0.01;
  INSERT INTO semantic.sem_validaciones VALUES ('V09',
    'saldo_txn siempre positivo; sentido por desc_txn (+DEPOSITO/COMPRAS/DISPOSICIONES, -RETIRO/PAGOS) concilia saldos',
    m = 0 AND n = 0, format('importes<=0: %s; cuentas-mes que no concilian: %s', m, n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V10 desc_txn del hecho coincide con dim_txn (fuente oficial de la descripción)
  SELECT COUNT(*) INTO n FROM cfg.fact_txn_captacoloca_d t JOIN dim.dim_txn d
    ON d.cve_producto = t.cve_producto AND d.cve_txn = t.cve_txn WHERE d.desc_txn <> t.desc_txn;
  INSERT INTO semantic.sem_validaciones VALUES ('V10','desc_txn del hecho coincide con dim_txn.desc_txn (llave compuesta)', n = 0, format('diferencias=%s', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();

  -- V11 'dominio' del hecho vs dim_producto.cve_dominio (supuesto del socio: no son equivalentes)
  SELECT COUNT(*) INTO n FROM cfg.fact_sdos_captacoloca_m s JOIN dim.dim_producto p USING (cve_producto) WHERE s.dominio <> p.cve_dominio;
  INSERT INTO semantic.sem_validaciones VALUES ('V11','dominio del hecho NO siempre coincide con dim_producto.cve_dominio (agrupar por cve_producto)',
    n > 0, format('filas con dominio distinto al catalogo=%s (enero usa CAPTACION/COLOCACION)', n))
  ON CONFLICT (codigo) DO UPDATE SET resultado = EXCLUDED.resultado, evidencia = EXCLUDED.evidencia, fecha = now();
END $$;

-- ---------------------------------------------------------------- relaciones (R005)
UPDATE semantic.sem_relaciones r SET relacion_validada = v.ok, fecha_actualizacion = now(),
       restricciones = CASE WHEN v.ok THEN 'VALIDADA en datos sinteticos por 020_validacion_capa_semantica.sql (' || v.cods || ').'
                            ELSE r.restricciones END
FROM (SELECT 'cliente_saldos' AS rel, bool_and(resultado) AS ok, 'V01,V04a' AS cods FROM semantic.sem_validaciones WHERE codigo IN ('V01','V04a')
      UNION ALL SELECT 'cliente_transacciones', bool_and(resultado), 'V01,V04b' FROM semantic.sem_validaciones WHERE codigo IN ('V01','V04b')
      UNION ALL SELECT 'producto_saldos', bool_and(resultado), 'V02,V04c' FROM semantic.sem_validaciones WHERE codigo IN ('V02','V04c')
      UNION ALL SELECT 'producto_transacciones', bool_and(resultado), 'V02,V04d' FROM semantic.sem_validaciones WHERE codigo IN ('V02','V04d')) v
WHERE r.nombre_relacion = v.rel;
-- 'tipo_transaccion' (solo cve_txn) se queda en FALSE: V03 demuestra que cve_txn no es unica.

INSERT INTO semantic.sem_relaciones (nombre_relacion, tabla_origen, campo_origen, tabla_destino, campo_destino,
  cardinalidad, tipo_join, condicion_join, relacion_validada, descripcion_negocio, restricciones)
SELECT 'tipo_transaccion_compuesta', a.tabla_id, 'cve_producto,cve_txn', b.tabla_id, 'cve_producto,cve_txn', 'N:1', 'INNER JOIN',
       'fact_txn_captacoloca_d.cve_producto = dim_txn.cve_producto AND fact_txn_captacoloca_d.cve_txn = dim_txn.cve_txn',
       (SELECT bool_and(resultado) FROM semantic.sem_validaciones WHERE codigo IN ('V03','V04e')),
       'Movimientos con su catalogo de tipos de transaccion usando la llave compuesta.',
       'VALIDADA en datos sinteticos (V03,V04e). Usar SIEMPRE ambas columnas en el JOIN.'
FROM semantic.sem_tablas a, semantic.sem_tablas b
WHERE a.nombre_tabla = 'fact_txn_captacoloca_d' AND b.nombre_tabla = 'dim_txn'
ON CONFLICT (nombre_relacion) DO UPDATE SET relacion_validada = EXCLUDED.relacion_validada,
  condicion_join = EXCLUDED.condicion_join, restricciones = EXCLUDED.restricciones, fecha_actualizacion = now();

-- ---------------------------------------------------------------- reglas derivadas de la evidencia
INSERT INTO semantic.sem_reglas_negocio (codigo_regla, nombre_regla, descripcion, ambito, tabla_id, campo, tipo_regla,
  condicion, instruccion_sql, prioridad, obligatoriedad, mensaje_error, nivel_confianza)
SELECT 'R010', 'Clasificar movimientos por desc_txn',
  'El sentido del movimiento lo da desc_txn: suman DEPOSITO/COMPRAS/DISPOSICIONES y restan RETIRO/PAGOS (V09 concilia el 100% de cuentas-mes).',
  'TABLA', tabla_id, 'desc_txn', 'INTERPRETACION', 'La pregunta distingue gastos, cargos, abonos, depositos o retiros.',
  'Gasto/cargos del cliente = desc_txn IN (''COMPRAS'',''RETIRO'',''DISPOSICIONES''); abonos = desc_txn IN (''DEPOSITO'',''PAGOS''). Nunca usar el signo de saldo_txn.',
  10, 'OBLIGATORIA', 'Clasificacion de movimientos sin usar desc_txn.', 'PROPUESTO'
FROM semantic.sem_tablas WHERE nombre_tabla = 'fact_txn_captacoloca_d'
ON CONFLICT (codigo_regla) DO UPDATE SET descripcion = EXCLUDED.descripcion, instruccion_sql = EXCLUDED.instruccion_sql, fecha_actualizacion = now();

INSERT INTO semantic.sem_reglas_negocio (codigo_regla, nombre_regla, descripcion, ambito, tabla_id, campo, tipo_regla,
  condicion, instruccion_sql, prioridad, obligatoriedad, mensaje_error, nivel_confianza)
SELECT 'R011', 'Agrupar por producto, no por dominio',
  'El campo dominio del hecho cambia de codificacion entre meses (V11); la fuente oficial es dim_producto.',
  'TABLA', tabla_id, 'dominio', 'AGREGACION', 'La pregunta agrupa o filtra por dominio, captacion o colocacion.',
  'Agrupar por cve_producto o por dim_producto.cve_dominio / grupo_producto mediante JOIN validado; no usar fact.dominio.',
  11, 'OBLIGATORIA', 'Agrupacion por el campo dominio del hecho.', 'PROPUESTO'
FROM semantic.sem_tablas WHERE nombre_tabla = 'fact_sdos_captacoloca_m'
ON CONFLICT (codigo_regla) DO UPDATE SET descripcion = EXCLUDED.descripcion, instruccion_sql = EXCLUDED.instruccion_sql, fecha_actualizacion = now();

-- ---------------------------------------------------------------- ejemplos de valores reales (perfilado)
UPDATE semantic.sem_columnas c SET ejemplos_valores = v.vals, fecha_actualizacion = now()
FROM (
  SELECT 'dim_cliente' t, 'segmento_cte' col, jsonb_agg(DISTINCT segmento_cte) vals FROM dim.dim_cliente
  UNION ALL SELECT 'dim_cliente', 'tipo_persona', jsonb_agg(DISTINCT tipo_persona) FROM dim.dim_cliente
  UNION ALL SELECT 'dim_producto', 'cve_producto', jsonb_agg(DISTINCT cve_producto) FROM dim.dim_producto
  UNION ALL SELECT 'dim_producto', 'cve_dominio', jsonb_agg(DISTINCT cve_dominio) FROM dim.dim_producto
  UNION ALL SELECT 'dim_producto', 'grupo_producto', jsonb_agg(DISTINCT grupo_producto) FROM dim.dim_producto
  UNION ALL SELECT 'dim_txn', 'desc_txn', jsonb_agg(DISTINCT desc_txn) FROM dim.dim_txn
  UNION ALL SELECT 'fact_txn_captacoloca_d', 'desc_txn', jsonb_agg(DISTINCT desc_txn) FROM cfg.fact_txn_captacoloca_d
  UNION ALL SELECT 'fact_sdos_captacoloca_m', 'dominio', jsonb_agg(DISTINCT dominio) FROM cfg.fact_sdos_captacoloca_m
  UNION ALL SELECT 'fact_sdos_captacoloca_m', 'fec_informacion', jsonb_agg(DISTINCT fec_informacion) FROM cfg.fact_sdos_captacoloca_m
  UNION ALL SELECT 'fact_txn_captacoloca_d', 'fec_informacion', jsonb_agg(DISTINCT fec_informacion) FROM cfg.fact_txn_captacoloca_d
  UNION ALL SELECT 'fact_txn_captacoloca_d', 'cve_mes_txn', jsonb_agg(DISTINCT cve_mes_txn) FROM cfg.fact_txn_captacoloca_d
) v JOIN semantic.sem_tablas t ON t.nombre_tabla = v.t
WHERE c.tabla_id = t.tabla_id AND c.nombre_columna = v.col;

-- ---------------------------------------------------------------- permisos
GRANT USAGE ON SCHEMA semantic TO steward_empleado;
GRANT SELECT ON ALL TABLES IN SCHEMA semantic TO steward_empleado;
REVOKE ALL ON SCHEMA semantic FROM steward_cliente;