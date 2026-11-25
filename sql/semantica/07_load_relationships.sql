-- Relaciones candidatas, deliberadamente NO validadas.
-- El agente no debe utilizarlas para generar JOIN hasta que relacion_validada=TRUE
-- y se hayan comprobado unicidad, integridad referencial y cardinalidad.

INSERT INTO semantic.sem_relaciones
(nombre_relacion,tabla_origen,campo_origen,tabla_destino,campo_destino,
 cardinalidad,tipo_join,condicion_join,relacion_validada,descripcion_negocio,restricciones)
SELECT v.nombre, a.tabla_id, v.campo_a, b.tabla_id, v.campo_b,
       v.cardinalidad, v.tipo_join, v.condicion, FALSE, v.descripcion, v.restricciones
FROM (VALUES
 ('cliente_saldos','fact_sdos_captacoloca_m','num_cte','dim_cliente','num_cte',
  'N:1','INNER JOIN','fact_sdos_captacoloca_m.num_cte = dim_cliente.num_cte',
  'Relacion candidata entre saldo y maestro de clientes.',
  'Validar que dim_cliente tenga una fila por num_cte y que la integridad referencial sea completa.'),

 ('cliente_transacciones','fact_txn_captacoloca_d','num_cte','dim_cliente','num_cte',
  'N:1','INNER JOIN','fact_txn_captacoloca_d.num_cte = dim_cliente.num_cte',
  'Relacion candidata entre movimientos y maestro de clientes.',
  'Validar unicidad de num_cte y tratamiento historico del maestro.'),

 ('producto_saldos','fact_sdos_captacoloca_m','cve_producto','dim_producto','cve_producto',
  'N:1','INNER JOIN','fact_sdos_captacoloca_m.cve_producto = dim_producto.cve_producto',
  'Relacion candidata entre saldo y catalogo de productos.',
  'Validar unicidad de cve_producto y vigencia historica del catalogo.'),

 ('producto_transacciones','fact_txn_captacoloca_d','cve_producto','dim_producto','cve_producto',
  'N:1','INNER JOIN','fact_txn_captacoloca_d.cve_producto = dim_producto.cve_producto',
  'Relacion candidata entre movimientos y catalogo de productos.',
  'Validar unicidad de cve_producto y vigencia historica del catalogo.'),

 ('tipo_transaccion','fact_txn_captacoloca_d','cve_txn','dim_txn','cve_txn',
  'N:1','INNER JOIN','fact_txn_captacoloca_d.cve_txn = dim_txn.cve_txn',
  'Relacion candidata entre movimientos y catalogo de tipos de transaccion.',
  'NO USAR: cve_txn puede no ser unica. Confirmar si requiere cve_producto, cve_dominio u otra columna.')
) AS v(nombre,tabla_a,campo_a,tabla_b,campo_b,cardinalidad,tipo_join,condicion,descripcion,restricciones)
JOIN semantic.sem_tablas a ON a.nombre_tabla=v.tabla_a
JOIN semantic.sem_tablas b ON b.nombre_tabla=v.tabla_b
ON CONFLICT (nombre_relacion) DO UPDATE SET
 tabla_origen=EXCLUDED.tabla_origen,campo_origen=EXCLUDED.campo_origen,
 tabla_destino=EXCLUDED.tabla_destino,campo_destino=EXCLUDED.campo_destino,
 cardinalidad=EXCLUDED.cardinalidad,tipo_join=EXCLUDED.tipo_join,
 condicion_join=EXCLUDED.condicion_join,relacion_validada=FALSE,
 descripcion_negocio=EXCLUDED.descripcion_negocio,
 restricciones=EXCLUDED.restricciones,fecha_actualizacion=CURRENT_TIMESTAMP;
