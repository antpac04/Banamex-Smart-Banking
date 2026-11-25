# Capa Semantica Financiera v1.0

## Contenido
- `01_create_schema.sql`: crea el esquema PostgreSQL `semantic`.
- `02_create_tables.sql`: crea los cinco catalogos semanticos.
- `03_load_tables.sql`: registra las cinco tablas del DWH compartidas.
- `04_load_columns.sql`: carga el diccionario enriquecido de columnas.
- `05_load_metrics.sql`: registra metricas iniciales.
- `06_load_business_rules.sql`: registra reglas de negocio y SQL.
- `07_load_relationships.sql`: registra relaciones candidatas no validadas.
- `08_validation.sql`: consultas de control y validacion.

## Orden de ejecucion
Ejecutar en PostgreSQL, en este orden:
1. `01_create_schema.sql`
2. `02_create_tables.sql`
3. `03_load_tables.sql`
4. `04_load_columns.sql`
5. `05_load_metrics.sql`
6. `06_load_business_rules.sql`
7. `07_load_relationships.sql`
8. `08_validation.sql`

Los scripts de carga utilizan `ON CONFLICT` y pueden volver a ejecutarse para actualizar metadatos. Se recomienda probar primero en una base de desarrollo y respaldar el esquema si ya existe.

## Supuestos y decisiones
- Se conserva el modelo fisico del usuario; estos scripts crean solamente metadatos.
- `fact_sdos_captacoloca_m` tiene granularidad confirmada de una fila por cuenta, producto y mes.
- `saldo_txn` es el importe monetario de cada movimiento.
- `fec_informacion` es INTEGER con representacion AAAAMMDD (ejemplo 20260930).
- Los campos tipo DATE se representan en formato ISO `YYYY-MM-DD`.
- Los tipos NUMERIC de los tres importes se registran como `NUMERIC(?)` en el catalogo porque la precision/escala completa no fue proporcionada.
- Las descripciones de negocio y algunos granos de dimensiones son propuestas y deben validarse.
- Las relaciones se cargan con `relacion_validada = FALSE`. El agente debe ignorarlas para JOIN hasta que un proceso de validacion las apruebe.
- `cve_txn` no se asume unica. Puede requerir una llave compuesta.
- La granularidad de `fact_txn_captacoloca_d` como una fila por movimiento es propuesta; no se proporciono una llave unica de transaccion.
- `saldo_txn` puede sumarse como importe/flujo, pero no debe interpretarse como deposito o retiro hasta confirmar signo y clasificacion.
- Los campos `fec_alta` y `fec_mes_alta` en el hecho mensual requieren confirmacion semantica.
- No se presupone que `dominio` en hechos sea exactamente equivalente a `cve_dominio` de dimensiones.

## Validaciones pendientes antes de habilitar SQL automatico
1. Confirmar PK/UK reales de `dim_cliente`, `dim_producto` y `dim_txn`.
2. Confirmar precision y escala de `saldo_apertura`, `saldo_mes`, `saldo_txn`.
3. Confirmar la llave de `dim_txn` y la relacion con el hecho de transacciones.
4. Confirmar convencion de signo y codificacion de `cve_txn`.
5. Confirmar si las dimensiones son historizadas (SCD) o contienen solo el estado vigente.
6. Confirmar si `num_cta` es globalmente unica o requiere una llave compuesta.
7. Confirmar el significado de `fec_alta` y `cve_mes_alta` en el hecho mensual.

## Seguridad y operacion
- El LLM no debe ejecutar SQL directamente.
- Validar nombres de tablas/columnas contra `sem_tablas` y `sem_columnas`.
- Permitir solo relaciones con `relacion_validada = TRUE`.
- Aplicar un parser/validador SQL y permitir solo consultas de lectura.
- Aplicar limites de filas, timeout y permisos de solo lectura en el usuario de base de datos.
- La metadata no sustituye controles de acceso a datos sensibles.

## Rollback
En una base de pruebas, para eliminar todo el repositorio semantico:
```sql
DROP SCHEMA semantic CASCADE;
```
No ejecutar este comando en produccion sin respaldo y autorizacion.
