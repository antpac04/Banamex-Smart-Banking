-- Metricas iniciales. Las metricas propuestas deben validarse con negocio.
-- CORRECCION (equipo): en la version original M004 y M005 tenian 16 valores en lugar de 15
-- (un '[]' sobrante y dimensiones/filtros intercambiados), lo que hacia fallar todo el script
-- y, en cascada, 06_load_business_rules.sql. Se dejo dimensiones -> filtros -> sinonimos.
INSERT INTO semantic.sem_metricas
(codigo_metrica,nombre_metrica,descripcion,tabla_origen,campo_origen,
 formula_sql,agregacion,tipo_metrica,unidad_medida,dimensiones_permitidas,
 filtros_obligatorios,sinonimos,comportamiento_temporal,restricciones,nivel_confianza)
SELECT v.codigo,v.nombre,v.descripcion,t.tabla_id,v.campo,v.formula,v.agregacion,
       v.tipo,v.unidad,v.dimensiones::jsonb,v.filtros::jsonb,v.sinonimos::jsonb,
       v.temporal,v.restricciones,v.confianza
FROM (VALUES
 ('M001','Saldo de cierre','Importe agregado de saldos al cierre de un unico periodo mensual.','fact_sdos_captacoloca_m','saldo_mes','SUM(saldo_mes)','SUM','SEMI_ADITIVA','MONEDA','["cliente","producto","dominio","segmento","sucursal","promotor"]','["Definir un unico corte mensual"]','["saldo al cierre","saldo mensual","balance"]','SNAPSHOT','No sumar saldos de distintos meses. Confirmar moneda y tratamiento de cuentas duplicadas.','PROPUESTO'),
 ('M002','Saldo de apertura','Importe agregado de saldos al inicio del periodo mensual.','fact_sdos_captacoloca_m','saldo_apertura','SUM(saldo_apertura)','SUM','SEMI_ADITIVA','MONEDA','["cliente","producto","dominio","segmento"]','["Definir un unico periodo mensual"]','["saldo inicial","saldo de inicio"]','SNAPSHOT','No acumular saldos de apertura entre meses.','PROPUESTO'),
 ('M003','Importe de transacciones','Suma de importes monetarios de movimientos en el periodo.','fact_txn_captacoloca_d','saldo_txn','SUM(saldo_txn)','SUM','ADITIVA','MONEDA','["cliente","producto","tipo_transaccion","fecha","segmento","sucursal"]','[]','["importe transaccional","monto de movimientos","volumen transaccional"]','FLUJO','Confirmar convencion de signo, moneda y si se requiere importe bruto o neto.','CONFIRMADO'),
 ('M004','Clientes unicos con saldo','Cantidad de clientes distintos presentes en el hecho mensual para el corte consultado.','fact_sdos_captacoloca_m','num_cte','COUNT(DISTINCT num_cte)','COUNT DISTINCT','DERIVADA','CLIENTES','["producto","dominio","segmento","sucursal","promotor"]','["Definir corte mensual"]','["clientes unicos","numero de clientes"]','SNAPSHOT','No sumar conteos entre grupos que puedan contener clientes repetidos.','PROPUESTO'),
 ('M005','Cuentas unicas','Cantidad de cuentas distintas presentes en el hecho mensual para el corte consultado.','fact_sdos_captacoloca_m','num_cta','COUNT(DISTINCT num_cta)','COUNT DISTINCT','DERIVADA','CUENTAS','["cliente","producto","dominio"]','["Definir corte mensual"]','["cuentas unicas","numero de cuentas"]','SNAPSHOT','Confirmar si num_cta es globalmente unica o requiere otra clave.','PROPUESTO')
) AS v(codigo,nombre,descripcion,tabla,campo,formula,agregacion,tipo,unidad,dimensiones,filtros,sinonimos,temporal,restricciones,confianza)
JOIN semantic.sem_tablas t ON t.nombre_tabla=v.tabla
ON CONFLICT (codigo_metrica) DO UPDATE SET
 nombre_metrica=EXCLUDED.nombre_metrica, descripcion=EXCLUDED.descripcion,
 tabla_origen=EXCLUDED.tabla_origen, campo_origen=EXCLUDED.campo_origen,
 formula_sql=EXCLUDED.formula_sql, agregacion=EXCLUDED.agregacion,
 tipo_metrica=EXCLUDED.tipo_metrica, unidad_medida=EXCLUDED.unidad_medida,
 dimensiones_permitidas=EXCLUDED.dimensiones_permitidas,
 filtros_obligatorios=EXCLUDED.filtros_obligatorios,
 sinonimos=EXCLUDED.sinonimos,
 comportamiento_temporal=EXCLUDED.comportamiento_temporal,
 restricciones=EXCLUDED.restricciones,
 nivel_confianza=EXCLUDED.nivel_confianza,
 fecha_actualizacion=CURRENT_TIMESTAMP;