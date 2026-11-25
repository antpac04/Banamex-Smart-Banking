-- Catalogo inicial de las cinco tablas del DWH.
-- UPSERT: permite volver a ejecutar la carga sin duplicar registros.

INSERT INTO semantic.sem_tablas
(nombre_tabla,nombre_negocio,descripcion_negocio,tipo_tabla,dominio_negocio,
 granularidad,periodicidad,entidad_principal,fecha_referencia,alias_negocio,
 preguntas_soportadas,restricciones)
VALUES
('dim_cliente','Maestro de clientes',
 'Atributos demograficos, comerciales y organizacionales de los clientes.',
 'DIMENSION','CLIENTES','Un registro por cliente (supuesto por validar).',
 'VIGENTE','CLIENTE','fec_alta',
 '["clientes","maestro de clientes","cartera de clientes"]',
 '["clientes por segmento","clientes por tipo de persona","clientes por sucursal","antiguedad de clientes"]',
 'Confirmar unicidad de num_cte y si la dimension conserva historico o solo estado vigente.'),

('dim_producto','Catalogo de productos financieros',
 'Clasificacion de productos, dominios, grupos y subproductos.',
 'DIMENSION','PRODUCTOS','Un registro por producto (supuesto por validar).',
 'VIGENTE','PRODUCTO',NULL,
 '["productos","catalogo de productos","productos bancarios"]',
 '["productos por dominio","productos por grupo","productos activos"]',
 'Confirmar unicidad de cve_producto y significado/codigos de dominio y grupo.'),

('dim_txn','Catalogo de tipos de transaccion',
 'Clasificacion y descripcion de los tipos de movimientos financieros.',
 'DIMENSION','TRANSACCIONES',
 'Un registro por tipo de transaccion; unicidad de cve_txn pendiente.',
 'VIGENTE','TIPO_TRANSACCION',NULL,
 '["movimientos","tipos de movimiento","operaciones financieras"]',
 '["movimientos por tipo","clasificacion de transacciones"]',
 'Confirmar si cve_txn es unica o si la llave es compuesta, por ejemplo con cve_producto.'),

('fact_sdos_captacoloca_m','Saldos mensuales de captacion y colocacion',
 'Saldos de apertura y cierre por cuenta, producto y mes.',
 'FACT','CAPTACION_COLOCACION',
 'Una fila por cuenta, producto y mes (confirmado por el usuario).',
 'MENSUAL','CUENTA','fec_informacion',
 '["saldos","saldos mensuales","cartera","balance de cuentas"]',
 '["saldo al cierre","saldo de apertura","saldos por cliente","saldos por producto","evolucion de saldos"]',
 'Saldo snapshot: no sumar periodos mensuales entre si. fec_informacion es INTEGER AAAAMMDD.'),

('fact_txn_captacoloca_d','Transacciones diarias de captacion y colocacion',
 'Movimientos financieros con fecha, importe y tipo de transaccion.',
 'FACT','CAPTACION_COLOCACION',
 'Una fila por movimiento (propuesto; validar identificador unico de transaccion).',
 'DIARIA','TRANSACCION','fec_txn',
 '["transacciones","movimientos","operaciones","depositos","retiros"]',
 '["importe de movimientos","transacciones por cliente","movimientos por producto","actividad transaccional"]',
 'saldo_txn es el importe monetario del movimiento. Validar signo y llave unica del movimiento.')
ON CONFLICT (nombre_tabla) DO UPDATE SET
 nombre_negocio=EXCLUDED.nombre_negocio,
 descripcion_negocio=EXCLUDED.descripcion_negocio,
 tipo_tabla=EXCLUDED.tipo_tabla,
 dominio_negocio=EXCLUDED.dominio_negocio,
 granularidad=EXCLUDED.granularidad,
 periodicidad=EXCLUDED.periodicidad,
 entidad_principal=EXCLUDED.entidad_principal,
 fecha_referencia=EXCLUDED.fecha_referencia,
 alias_negocio=EXCLUDED.alias_negocio,
 preguntas_soportadas=EXCLUDED.preguntas_soportadas,
 restricciones=EXCLUDED.restricciones,
 fecha_actualizacion=CURRENT_TIMESTAMP;
