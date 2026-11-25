-- Reglas iniciales de interpretacion y generacion SQL.
INSERT INTO semantic.sem_reglas_negocio
(codigo_regla,nombre_regla,descripcion,ambito,tabla_id,campo,codigo_metrica,
 tipo_regla,condicion,instruccion_sql,prioridad,obligatoriedad,mensaje_error,nivel_confianza)
VALUES
('R001','No sumar snapshots mensuales','Los saldos son fotografias de un periodo y no flujos acumulables.','TABLA',
 (SELECT tabla_id FROM semantic.sem_tablas WHERE nombre_tabla='fact_sdos_captacoloca_m'),
 'saldo_mes','M001','AGREGACION','La consulta incluye mas de un periodo mensual.',
 'Para saldo puntual filtrar un solo fec_informacion; para tendencias mostrar un saldo por periodo sin sumar meses.',
 1,'OBLIGATORIA','La consulta intenta sumar saldos de distintos meses.','CONFIRMADO'),

('R002','Conteo distinto de clientes','El conteo de clientes debe eliminar duplicados por numero de cliente.','METRICA',NULL,
 'num_cte','M004','AGREGACION','La consulta solicita cantidad de clientes.',
 'Utilizar COUNT(DISTINCT num_cte).',2,'OBLIGATORIA',
 'No se permite contar filas como sustituto de clientes unicos.','PROPUESTO'),

('R003','Conteo distinto de cuentas','El conteo de cuentas debe eliminar duplicados de la cuenta.','TABLA',
 (SELECT tabla_id FROM semantic.sem_tablas WHERE nombre_tabla='fact_sdos_captacoloca_m'),
 'num_cta','M005','AGREGACION','La consulta solicita cantidad de cuentas.',
 'Utilizar COUNT(DISTINCT num_cta), previa validacion de la llave de cuenta.',3,'OBLIGATORIA',
 'No se permite contar filas como sustituto de cuentas unicas.','PROPUESTO'),

('R004','Distinguir fecha de transaccion y fecha de corte','fec_txn indica cuando ocurrio el movimiento; fec_informacion identifica el corte de datos.','GLOBAL',
 NULL,NULL,NULL,'TEMPORAL','La pregunta solicita un periodo de movimientos o un corte de informacion.',
 'Usar fec_txn para periodo transaccional y fec_informacion para seleccionar el corte de carga; no intercambiarlas.',
 4,'OBLIGATORIA','Se detecto una mezcla de fecha de movimiento y fecha de corte.','CONFIRMADO'),

('R005','Validar JOIN antes de usarlo','Solo se permiten relaciones cuya llave y cardinalidad hayan sido verificadas.','GLOBAL',
 NULL,NULL,NULL,'JOIN','La consulta requiere relacionar dos tablas.',
 'Consultar sem_relaciones y usar solo relaciones_validada = TRUE. Si no existe relacion validada, detener generacion o solicitar confirmacion.',
 5,'OBLIGATORIA','No existe una relacion semantica validada para el JOIN solicitado.','CONFIRMADO'),

('R006','No inferir naturaleza por signo sin catalogo','El signo del importe no debe interpretarse como deposito o retiro sin confirmar la convencion.','TABLA',
 (SELECT tabla_id FROM semantic.sem_tablas WHERE nombre_tabla='fact_txn_captacoloca_d'),
 'saldo_txn','M003','INTERPRETACION','La pregunta distingue entradas, salidas, depositos o retiros.',
 'Usar una clasificacion de cve_txn validada o una regla de signo confirmada; en caso contrario no clasificar.',
 6,'OBLIGATORIA','No se puede clasificar el movimiento con las reglas disponibles.','CONFIRMADO'),

('R007','Evitar unir hechos sin preagregacion','La union directa de dos hechos puede multiplicar filas y duplicar importes.','GLOBAL',
 NULL,NULL,NULL,'JOIN','La consulta necesita combinar saldos mensuales y transacciones diarias.',
 'Preagregar cada hecho a la granularidad comun antes de unirlos y validar la cardinalidad resultante.',
 7,'OBLIGATORIA','La combinacion directa de tablas de hechos puede duplicar importes.','CONFIRMADO'),

('R008','Interpretar fec_informacion como AAAAMMDD','El campo es INTEGER con representacion numerica AAAAMMDD.','COLUMNA',
 (SELECT tabla_id FROM semantic.sem_tablas WHERE nombre_tabla='fact_sdos_captacoloca_m'),
 'fec_informacion',NULL,'FORMATO_FECHA','Se requiere filtrar o presentar la fecha de informacion.',
 'Para rangos usar enteros AAAAMMDD. Para funciones de fecha usar TO_DATE(fec_informacion::text, ''YYYYMMDD'').',
 8,'OBLIGATORIA','Formato de fecha de informacion invalido.','CONFIRMADO'),

('R009','Interpretar fec_informacion en transacciones','El campo es INTEGER con representacion numerica AAAAMMDD.','COLUMNA',
 (SELECT tabla_id FROM semantic.sem_tablas WHERE nombre_tabla='fact_txn_captacoloca_d'),
 'fec_informacion',NULL,'FORMATO_FECHA','Se requiere filtrar o presentar la fecha de informacion.',
 'Para rangos usar enteros AAAAMMDD. Para funciones de fecha usar TO_DATE(fec_informacion::text, ''YYYYMMDD'').',
 9,'OBLIGATORIA','Formato de fecha de informacion invalido.','CONFIRMADO')
ON CONFLICT (codigo_regla) DO UPDATE SET
 nombre_regla=EXCLUDED.nombre_regla,descripcion=EXCLUDED.descripcion,
 ambito=EXCLUDED.ambito,tabla_id=EXCLUDED.tabla_id,campo=EXCLUDED.campo,
 codigo_metrica=EXCLUDED.codigo_metrica,tipo_regla=EXCLUDED.tipo_regla,
 condicion=EXCLUDED.condicion,instruccion_sql=EXCLUDED.instruccion_sql,
 prioridad=EXCLUDED.prioridad,obligatoriedad=EXCLUDED.obligatoriedad,
 mensaje_error=EXCLUDED.mensaje_error,nivel_confianza=EXCLUDED.nivel_confianza,
 fecha_actualizacion=CURRENT_TIMESTAMP;
