-- Consultas de validacion del repositorio semantico.
-- Ejecutar despues de los scripts de carga.

-- 1. Conteo de metadatos por tabla fisica
SELECT t.nombre_tabla, COUNT(c.columna_id) AS columnas_catalogadas
FROM semantic.sem_tablas t
LEFT JOIN semantic.sem_columnas c ON c.tabla_id=t.tabla_id
GROUP BY t.nombre_tabla
ORDER BY t.nombre_tabla;

-- 2. Columnas sin descripcion o sin nivel de confianza confirmado
SELECT t.nombre_tabla,c.nombre_columna,c.tipo_dato_fisico,
       c.nombre_negocio,c.nivel_confianza
FROM semantic.sem_columnas c
JOIN semantic.sem_tablas t ON t.tabla_id=c.tabla_id
WHERE c.descripcion_negocio IS NULL
   OR c.nivel_confianza <> 'CONFIRMADO'
ORDER BY t.nombre_tabla,c.nombre_columna;

-- 3. Metricas registradas
SELECT m.codigo_metrica,m.nombre_metrica,t.nombre_tabla,
       m.formula_sql,m.tipo_metrica,m.comportamiento_temporal,
       m.nivel_confianza
FROM semantic.sem_metricas m
JOIN semantic.sem_tablas t ON t.tabla_id=m.tabla_origen
ORDER BY m.codigo_metrica;

-- 4. Reglas activas
SELECT codigo_regla,nombre_regla,ambito,obligatoriedad,
       prioridad,nivel_confianza
FROM semantic.sem_reglas_negocio
WHERE activo
ORDER BY prioridad;

-- 5. Relaciones candidatas y estado de validacion
SELECT r.nombre_relacion,
       a.nombre_tabla AS tabla_origen,r.campo_origen,
       b.nombre_tabla AS tabla_destino,r.campo_destino,
       r.cardinalidad,r.relacion_validada,r.restricciones
FROM semantic.sem_relaciones r
JOIN semantic.sem_tablas a ON a.tabla_id=r.tabla_origen
JOIN semantic.sem_tablas b ON b.tabla_id=r.tabla_destino
WHERE r.activo
ORDER BY r.nombre_relacion;

-- 6. Relaciones que el agente SI podria utilizar (inicialmente ninguna)
SELECT *
FROM semantic.sem_relaciones
WHERE activo AND relacion_validada=TRUE;

-- 7. Verificar valores de fec_informacion en el DWH.
-- Ejecutar solo si las tablas fisicas estan en search_path o ajustar esquema.
-- SELECT fec_informacion, TO_DATE(fec_informacion::text,'YYYYMMDD')
-- FROM fact_sdos_captacoloca_m
-- WHERE fec_informacion IS NOT NULL
-- LIMIT 20;

-- 8. Verificar unicidad candidata de dimensiones.
-- Ajustar esquema fisico si no estan en search_path.
-- SELECT num_cte, COUNT(*) FROM dim_cliente GROUP BY num_cte HAVING COUNT(*) > 1;
-- SELECT cve_producto, COUNT(*) FROM dim_producto GROUP BY cve_producto HAVING COUNT(*) > 1;
-- SELECT cve_txn, COUNT(*) FROM dim_txn GROUP BY cve_txn HAVING COUNT(*) > 1;
-- SELECT cve_txn, cve_producto, COUNT(*) FROM dim_txn
-- GROUP BY cve_txn,cve_producto HAVING COUNT(*) > 1;

-- 9. Verificar precision/escala reales de campos monetarios.
-- SELECT table_name,column_name,data_type,numeric_precision,numeric_scale
-- FROM information_schema.columns
-- WHERE table_name IN ('fact_sdos_captacoloca_m','fact_txn_captacoloca_d')
--   AND column_name IN ('saldo_apertura','saldo_mes','saldo_txn');

-- 10. Verificar convencion de signo de movimientos.
-- SELECT cve_txn,desc_txn,MIN(saldo_txn),MAX(saldo_txn),COUNT(*)
-- FROM fact_txn_captacoloca_d
-- GROUP BY cve_txn,desc_txn ORDER BY cve_txn;
