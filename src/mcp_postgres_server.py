"""Servidor MCP #1: datos (PostgreSQL). Se lanza por stdio, UNO POR SESIÓN, con la identidad en env:
STEWARD_ROLE, STEWARD_USER y (si es cliente) STEWARD_NUM_CTE.

Expone tools distintas según el rol:
  cliente : consultar_saldos, consultar_historico_saldos, consultar_movimientos, resumen_mensual_movimientos
            (SIN argumento de cliente)
  empleado: saldo_por_grupo, clientes_por_grupo, movimientos_por_grupo (indicadores sin SQL libre),
            perfil_cliente, run_governance_checks, get_audit_log,
            get_data_model_guide, list_tables, run_sql_query (SQL libre, último recurso)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP  # noqa: E402

import auth  # noqa: E402
import common  # noqa: E402
import db_config as db  # noqa: E402
import semantica  # noqa: E402

IDENT = auth.identidad_desde_env()
mcp = FastMCP("postgres")

GUIA_MODELO = """MODELO DE DATOS (PostgreSQL, datos sintéticos ene-jun 2026)
dim.dim_cliente(num_cte PK, fec_alta, tipo_persona 'PF'|'PM', segmento_cte 'MASIVO'|'PREFERENTE'|'PREMIUM',
                giro_empresa, cve_territorio, cve_dir, cve_subdir, cve_sucursal, cve_promotor)
   * fec_nac y genero_cte son RESTRINGIDAS: no se pueden leer (ni con SELECT *). Usa columnas explícitas.
dim.dim_producto(cve_producto PK: CHEQUES|AHORRO|C_PERSONAL|TDC, cve_dominio, grupo_producto, descripcion)
dim.dim_txn(cve_producto, cve_txn, desc_txn)  -- SIN PK: unir SIEMPRE por (cve_producto, cve_txn)
cfg.fact_sdos_captacoloca_m (num_cta, num_cte, cve_producto, fec_alta, cve_mes_alta, saldo_apertura, saldo_mes,
                             fec_informacion INT YYYYMMDD, dominio)   -- saldo mensual por cuenta
cfg.fact_txn_captacoloca_d (num_cta, num_cte, cve_producto, fec_txn, cve_mes_txn INT YYYYMM, saldo_txn, cve_txn,
                            desc_txn, fec_informacion, dominio)       -- movimientos feb-jun 2026
TRAMPAS
- saldo_txn SIEMPRE es positivo; el tipo lo da desc_txn (DEPOSITO, RETIRO, PAGOS, COMPRAS, DISPOSICIONES).
- Cortes: fec_informacion IN (20260131,20260228,20260331,20260430,20260531,20260630). Último: 20260630.
- 'dominio' es inconsistente (enero CAPTACION/COLOCACION, después DEPOSITS/LENDING/TDC): agrupa por cve_producto.
- En CHEQUES/AHORRO saldo_mes es dinero del cliente; en TDC/C_PERSONAL es deuda.
EJEMPLO: SELECT c.segmento_cte, SUM(s.saldo_mes) FROM cfg.fact_sdos_captacoloca_m s
         JOIN dim.dim_cliente c ON c.num_cte = s.num_cte
         WHERE s.cve_producto = 'TDC' AND s.fec_informacion = 20260630 GROUP BY 1"""


def _q(sql: str, params=None, rol: str | None = None) -> str:
    rol = rol or (db.ROL_BD_CLIENTE if IDENT.es_cliente else db.ROL_BD_EMPLEADO)
    try:
        cols, filas, trunc = db.consultar(sql, params, rol=rol, num_cte=IDENT.num_cte)
        return db.a_markdown(cols, filas, trunc)
    except Exception as e:  # noqa: BLE001
        msg = str(e).strip()
        if "permission denied" in msg:
            msg += " | Usaste SELECT * o una columna restringida (fec_nac, genero_cte)."
        auth.auditar(IDENT, "error_sql", False, sql=" ".join(sql.split()), error=msg)
        return f"ERROR: {msg}"


def _mes(mes: str) -> str:
    m = (mes or "").strip().replace("-", "")
    return m if m in common.MESES_CON_DATOS else common.MESES_CON_DATOS[-1]


# =============================================================== CLIENTE
@auth.guarded(auth.ROL_CLIENTE)
def consultar_saldos() -> str:
    """Saldo actual (último corte) de cada producto del cliente que inició sesión.
    CHEQUES/AHORRO = dinero disponible; TDC/C_PERSONAL = deuda. No recibe argumentos."""
    return _q("""
        SELECT s.cve_producto AS producto, p.descripcion, '****' || RIGHT(s.num_cta::text, 4) AS cuenta,
               s.saldo_mes AS saldo_mxn, s.fec_informacion AS fecha_corte
        FROM cfg.fact_sdos_captacoloca_m s JOIN dim.dim_producto p USING (cve_producto)
        WHERE s.num_cte = %s AND s.fec_informacion = (SELECT MAX(fec_informacion)
              FROM cfg.fact_sdos_captacoloca_m WHERE num_cte = %s)
        ORDER BY s.cve_producto""", (IDENT.num_cte, IDENT.num_cte))


@auth.guarded(auth.ROL_CLIENTE)
def consultar_historico_saldos(producto: str = "") -> str:
    """Saldos mensuales (ene-jun 2026) del cliente que inició sesión.
    producto: opcional, uno de CHEQUES, AHORRO, TDC, C_PERSONAL. Vacío = todos."""
    p = (producto or "").strip().upper()
    return _q("""
        SELECT fec_informacion AS fecha_corte, cve_producto AS producto, saldo_apertura, saldo_mes
        FROM cfg.fact_sdos_captacoloca_m
        WHERE num_cte = %s AND (%s::text = '' OR cve_producto = %s::text)
        ORDER BY cve_producto, fec_informacion""", (IDENT.num_cte, p, p))


@auth.guarded(auth.ROL_CLIENTE)
def consultar_movimientos(mes: str = "") -> str:
    """Movimientos de un mes del cliente que inició sesión, resumen por tipo y gasto total.
    Gasto = COMPRAS + RETIRO + DISPOSICIONES.
    mes: formato YYYYMM (202602 a 202606). Vacío o fuera de rango = 202606 (último con datos)."""
    m = _mes(mes)
    p = (IDENT.num_cte, int(m))
    nota = "" if (mes or "").replace("-", "") == m else f" (se pidió '{mes}'; se usó el último mes con datos)"
    detalle = _q("""SELECT fec_txn AS fecha, cve_producto AS producto, desc_txn AS tipo, saldo_txn AS monto_mxn
        FROM cfg.fact_txn_captacoloca_d WHERE num_cte = %s AND cve_mes_txn = %s ORDER BY fec_txn, cve_producto""", p)
    resumen = _q("""SELECT cve_producto AS producto, desc_txn AS tipo, COUNT(*) AS movimientos, SUM(saldo_txn) AS total_mxn
        FROM cfg.fact_txn_captacoloca_d WHERE num_cte = %s AND cve_mes_txn = %s GROUP BY 1, 2 ORDER BY 1, 2""", p)
    gasto = _q("""SELECT COALESCE(SUM(saldo_txn), 0) AS gasto_total_mxn FROM cfg.fact_txn_captacoloca_d
        WHERE num_cte = %s AND cve_mes_txn = %s AND desc_txn IN ('COMPRAS', 'RETIRO', 'DISPOSICIONES')""", p)
    return f"Mes: {m}{nota}\n\nDETALLE\n{detalle}\n\nRESUMEN POR TIPO\n{resumen}\n\nGASTO DEL MES\n{gasto}"


@auth.guarded(auth.ROL_CLIENTE)
def resumen_mensual_movimientos(solo_gastos: bool = True) -> str:
    """Totales por MES y por TIPO de movimiento (feb-jun 2026) del cliente que inició sesión.
    Úsala para comparar meses o graficar gastos mes a mes.
    solo_gastos: True = solo COMPRAS, RETIRO y DISPOSICIONES; False = todos los tipos (incluye depósitos y pagos)."""
    return _q("""
        SELECT cve_mes_txn AS mes, desc_txn AS tipo, COUNT(*) AS movimientos, SUM(saldo_txn) AS total_mxn
        FROM cfg.fact_txn_captacoloca_d
        WHERE num_cte = %s AND (NOT %s OR desc_txn IN ('COMPRAS', 'RETIRO', 'DISPOSICIONES'))
        GROUP BY 1, 2 ORDER BY 1, 2""", (IDENT.num_cte, bool(solo_gastos)))


# =============================================================== EMPLEADO
def _catalogo():
    """Capa semántica del socio (esquema semantic). None si no está instalada."""
    return semantica.cargar_catalogo(lambda sql: db.consultar(sql, rol=db.ROL_BD_EMPLEADO, max_filas=500))


@auth.guarded(auth.ROL_EMPLEADO)
def get_data_model_guide() -> str:
    """Modelo de datos desde la capa semántica: tablas, columnas, métricas oficiales, reglas obligatorias y
    joins validados. Úsala ANTES de escribir SQL."""
    cat = _catalogo()
    return semantica.guia_desde_catalogo(cat) if cat else GUIA_MODELO


@auth.guarded(auth.ROL_EMPLEADO)
def list_tables() -> str:
    """Tablas disponibles y su número de filas."""
    return _q("""SELECT 'dim.dim_cliente' AS tabla, COUNT(*) AS filas FROM dim.dim_cliente
        UNION ALL SELECT 'dim.dim_producto', COUNT(*) FROM dim.dim_producto
        UNION ALL SELECT 'dim.dim_txn', COUNT(*) FROM dim.dim_txn
        UNION ALL SELECT 'cfg.fact_sdos_captacoloca_m', COUNT(*) FROM cfg.fact_sdos_captacoloca_m
        UNION ALL SELECT 'cfg.fact_txn_captacoloca_d', COUNT(*) FROM cfg.fact_txn_captacoloca_d""")


@auth.guarded(auth.ROL_EMPLEADO)
def run_sql_query(query: str) -> str:
    """Ejecuta UNA consulta SELECT de solo lectura y devuelve una tabla markdown (máx. 200 filas).
    Prefiere agregados (SUM, COUNT, AVG). query: sentencia SELECT o WITH ... SELECT."""
    try:
        sql = auth.validar_sql(query)
    except auth.SQLRechazado as e:
        auth.auditar(IDENT, "sql_rechazado", False, sql=query, error=str(e))
        return f"CONSULTA RECHAZADA: {e}"
    cat = _catalogo()
    if cat:  # reglas de la capa semántica: tablas/columnas del catálogo, joins validados, R001, R007, R011
        try:
            semantica.validar_contra_catalogo(sql, cat)
        except semantica.ViolacionSemantica as e:
            auth.auditar(IDENT, "sql_rechazado", False, sql=query, error=str(e))
            return f"CONSULTA RECHAZADA: {e} Corrige la consulta usando la guía del modelo de datos."
    return f"SQL ejecutado:\n{sql}\n\nResultado:\n{_q(sql)}"


# ---------------------------------------------------------------- indicadores sin SQL libre
# Las preguntas típicas del colaborador se resuelven con estas tools: el modelo solo elige parámetros
# y el SQL lo arma el código con listas blancas (rápido, correcto y sin depender del modelo).
_DIM_SALDOS = {"segmento": "c.segmento_cte", "tipo_persona": "c.tipo_persona", "producto": "s.cve_producto",
               "mes": "(s.fec_informacion / 100)", "sucursal": "c.cve_sucursal"}
_DIM_MOVS = {"tipo": "t.desc_txn", "producto": "t.cve_producto", "mes": "t.cve_mes_txn",
             "segmento": "c.segmento_cte", "tipo_persona": "c.tipo_persona"}
_DIM_CLIENTES = {"segmento": "segmento_cte", "tipo_persona": "tipo_persona", "sucursal": "cve_sucursal",
                 "giro": "giro_empresa"}
_SINONIMOS = {"segmentos": "segmento", "persona": "tipo_persona", "tipo de persona": "tipo_persona",
              "productos": "producto", "meses": "mes", "mensual": "mes", "sucursales": "sucursal",
              "tipo de movimiento": "tipo", "movimiento": "tipo", "tipos": "tipo"}
_PRODUCTOS = {"tdc": "TDC", "tarjeta": "TDC", "tarjetas": "TDC", "tarjeta de credito": "TDC", "tarjeta de crédito": "TDC",
              "tarjetas de credito": "TDC", "tarjetas de crédito": "TDC", "cheques": "CHEQUES", "ahorro": "AHORRO",
              "c_personal": "C_PERSONAL", "credito personal": "C_PERSONAL", "crédito personal": "C_PERSONAL",
              "prestamo": "C_PERSONAL", "préstamo": "C_PERSONAL", "prestamos": "C_PERSONAL"}


def _dims(agrupar_por: str, permitidas: dict) -> list[str]:
    salida = []
    for d in re.split(r"[,;/]| y ", (agrupar_por or "").lower()):
        d = _SINONIMOS.get(d.strip(), d.strip())
        if d in permitidas and d not in salida:
            salida.append(d)
    return salida[:2]


def _producto(producto: str) -> str:
    p = (producto or "").strip().lower()
    return _PRODUCTOS.get(p, p.upper() if p.upper() in ("TDC", "CHEQUES", "AHORRO", "C_PERSONAL") else "")


def sql_saldo_por_grupo(producto: str, agrupar_por: str, mes: str) -> tuple[str, list]:
    dims = _dims(agrupar_por, _DIM_SALDOS) or ["producto"]
    prod = _producto(producto)
    filtros, params = [], []
    if prod:
        filtros.append("s.cve_producto = %s")
        params.append(prod)
    if "mes" not in dims:  # una foto en un corte; si se agrupa por mes, se usan todos los meses
        m = (mes or "").replace("-", "").strip()
        filtros.append("s.fec_informacion / 100 = %s")
        params.append(int(m if m in common.MESES_CON_DATOS else common.MESES_CON_DATOS[-1]))
    cols = ", ".join(f"{_DIM_SALDOS[d]} AS {d}" for d in dims)
    sql = f"""SELECT {cols}, COUNT(DISTINCT s.num_cte) AS clientes, COUNT(*) AS cuentas,
                     SUM(s.saldo_mes) AS saldo_total_mxn, ROUND(AVG(s.saldo_mes), 2) AS saldo_promedio_mxn
              FROM cfg.fact_sdos_captacoloca_m s JOIN dim.dim_cliente c ON c.num_cte = s.num_cte
              {"WHERE " + " AND ".join(filtros) if filtros else ""}
              GROUP BY {", ".join(str(i + 1) for i in range(len(dims)))} ORDER BY {", ".join(str(i + 1) for i in range(len(dims)))}"""
    return sql, params


def sql_movimientos_por_grupo(agrupar_por: str, producto: str, mes: str) -> tuple[str, list]:
    dims = _dims(agrupar_por, _DIM_MOVS) or ["tipo"]
    prod = _producto(producto)
    filtros, params = [], []
    if prod:
        filtros.append("t.cve_producto = %s")
        params.append(prod)
    m = (mes or "").replace("-", "").strip()
    if m in common.MESES_CON_DATOS and "mes" not in dims:
        filtros.append("t.cve_mes_txn = %s")
        params.append(int(m))
    cols = ", ".join(f"{_DIM_MOVS[d]} AS {d}" for d in dims)
    join = " JOIN dim.dim_cliente c ON c.num_cte = t.num_cte" if any(d in ("segmento", "tipo_persona") for d in dims) else ""
    sql = f"""SELECT {cols}, COUNT(*) AS movimientos, SUM(t.saldo_txn) AS total_mxn
              FROM cfg.fact_txn_captacoloca_d t{join}
              {"WHERE " + " AND ".join(filtros) if filtros else ""}
              GROUP BY {", ".join(str(i + 1) for i in range(len(dims)))} ORDER BY {", ".join(str(i + 1) for i in range(len(dims)))}"""
    return sql, params


@auth.guarded(auth.ROL_EMPLEADO)
def saldo_por_grupo(producto: str = "", agrupar_por: str = "segmento", mes: str = "202606") -> str:
    """Saldo total, promedio, número de clientes y de cuentas, agrupado. ÚSALA para preguntas de saldos.
    producto: TDC, CHEQUES, AHORRO, C_PERSONAL (acepta 'tarjeta de crédito', 'préstamo') o vacío = todos.
    agrupar_por: uno o dos de segmento, tipo_persona, producto, mes, sucursal, separados por coma
                 (ej. 'segmento' o 'mes,producto'). Con 'mes' se devuelven todos los meses ene-jun 2026.
    mes: YYYYMM del corte (202601 a 202606). Vacío = 202606 (último corte)."""
    sql, params = sql_saldo_por_grupo(producto, agrupar_por, mes)
    return _q(sql, tuple(params))


@auth.guarded(auth.ROL_EMPLEADO)
def clientes_por_grupo(agrupar_por: str = "segmento") -> str:
    """Número de clientes agrupado. ÚSALA para '¿cuántos clientes hay por ...?'.
    agrupar_por: uno o dos de segmento, tipo_persona, sucursal, giro, separados por coma.
    (El género y la fecha de nacimiento NO están disponibles: son datos personales restringidos.)"""
    dims = _dims(agrupar_por, _DIM_CLIENTES) or ["segmento"]
    cols = ", ".join(f"{_DIM_CLIENTES[d]} AS {d}" for d in dims)
    orden = ", ".join(str(i + 1) for i in range(len(dims)))
    return _q(f"SELECT {cols}, COUNT(*) AS clientes FROM dim.dim_cliente GROUP BY {orden} ORDER BY {orden}")


@auth.guarded(auth.ROL_EMPLEADO)
def movimientos_por_grupo(agrupar_por: str = "tipo", producto: str = "", mes: str = "") -> str:
    """Número de movimientos y monto total (feb-jun 2026), agrupado. ÚSALA para preguntas de transacciones.
    agrupar_por: uno o dos de tipo, producto, mes, segmento, tipo_persona, separados por coma (ej. 'mes,tipo').
    producto: TDC, CHEQUES, AHORRO, C_PERSONAL o vacío = todos.
    mes: YYYYMM para un solo mes, o vacío = todos los meses."""
    sql, params = sql_movimientos_por_grupo(agrupar_por, producto, mes)
    return _q(sql, tuple(params))


@auth.guarded(auth.ROL_EMPLEADO)
def perfil_cliente(num_cte: int) -> str:
    """Ficha de un cliente: segmento, tipo de persona, sucursal y saldos al 20260630.
    Sin datos personales restringidos. num_cte: número de cliente (1 a 5000)."""
    ficha = _q("""SELECT num_cte, tipo_persona, segmento_cte, fec_alta, cve_sucursal, cve_promotor
        FROM dim.dim_cliente WHERE num_cte = %s""", (int(num_cte),))
    saldos = _q("""SELECT cve_producto AS producto, '****' || RIGHT(num_cta::text, 4) AS cuenta, saldo_mes AS saldo_mxn
        FROM cfg.fact_sdos_captacoloca_m WHERE num_cte = %s AND fec_informacion = 20260630 ORDER BY 1""", (int(num_cte),))
    return f"FICHA\n{ficha}\n\nSALDOS AL 20260630\n{saldos}"


# Reglas alineadas 1 a 1 con la sección 4 de rag_documents/politica_calidad_datos_sintetica.md
# (mismo número, dimensión y severidad), para que la política y los hallazgos se puedan cruzar.
REGLAS_DQ = [
    ("DQ-01", "Unicidad", "Alta", "Una cuenta no tiene dos saldos para el mismo mes",
     """SELECT COUNT(*) FROM (SELECT num_cta, cve_producto, fec_informacion FROM cfg.fact_sdos_captacoloca_m
        GROUP BY 1, 2, 3 HAVING COUNT(*) > 1) x"""),
    ("DQ-02", "Completitud", "Alta", "Saldos de apertura y cierre informados",
     "SELECT COUNT(*) FROM cfg.fact_sdos_captacoloca_m WHERE saldo_apertura IS NULL OR saldo_mes IS NULL"),
    ("DQ-03", "Validez", "Alta", "Saldo de cierre no negativo",
     "SELECT COUNT(*) FROM cfg.fact_sdos_captacoloca_m WHERE saldo_mes < 0"),
    ("DQ-04", "Validez", "Alta", "Importe de transacción mayor que cero",
     "SELECT COUNT(*) FROM cfg.fact_txn_captacoloca_d WHERE saldo_txn IS NULL OR saldo_txn <= 0"),
    ("DQ-05", "Consistencia", "Alta", "Toda cuenta pertenece a un cliente existente",
     """SELECT COUNT(DISTINCT s.num_cta) FROM cfg.fact_sdos_captacoloca_m s
        LEFT JOIN dim.dim_cliente c ON c.num_cte = s.num_cte WHERE c.num_cte IS NULL"""),
    ("DQ-06", "Consistencia", "Media", "Toda transacción existe en el catálogo (producto + clave)",
     """SELECT COUNT(*) FROM cfg.fact_txn_captacoloca_d t LEFT JOIN dim.dim_txn d
        ON d.cve_producto = t.cve_producto AND d.cve_txn = t.cve_txn WHERE d.cve_txn IS NULL"""),
    ("DQ-07", "Consistencia", "Media", "Cada producto usa un único valor de dominio en todos los meses",
     """SELECT COUNT(*) FROM (SELECT cve_producto FROM cfg.fact_sdos_captacoloca_m
        GROUP BY 1 HAVING COUNT(DISTINCT dominio) > 1) x"""),
    ("DQ-08", "Consistencia", "Media", "El dominio de los saldos coincide con el catálogo oficial de productos",
     """SELECT COUNT(*) FROM cfg.fact_sdos_captacoloca_m s JOIN dim.dim_producto p USING (cve_producto)
        WHERE s.dominio <> p.cve_dominio"""),
    ("DQ-09", "Validez", "Alta", "Clientes persona física mayores de 18 años (se evalúa sin exponer fechas)",
     "SELECT dim.dq09_pf_menores_de_edad()"),
    ("DQ-10", "Completitud", "Media", "Territorio, sucursal y promotor del cliente informados",
     """SELECT COUNT(*) FROM dim.dim_cliente
        WHERE cve_territorio IS NULL OR cve_sucursal IS NULL OR cve_promotor IS NULL"""),
    ("DQ-11", "Exactitud", "Alta", "El saldo de cierre concilia con apertura más movimientos (tolerancia 0.01)",
     """SELECT COUNT(*) FROM (SELECT s.saldo_mes - s.saldo_apertura - COALESCE(SUM(CASE
            WHEN t.desc_txn IN ('DEPOSITO', 'COMPRAS', 'DISPOSICIONES') THEN t.saldo_txn
            WHEN t.desc_txn IN ('RETIRO', 'PAGOS') THEN -t.saldo_txn ELSE 0 END), 0) AS dif
        FROM cfg.fact_sdos_captacoloca_m s LEFT JOIN cfg.fact_txn_captacoloca_d t
          ON t.num_cta = s.num_cta AND t.cve_producto = s.cve_producto AND t.cve_mes_txn = s.fec_informacion / 100
        WHERE s.fec_informacion >= 20260228
        GROUP BY s.num_cta, s.cve_producto, s.saldo_mes, s.saldo_apertura) x WHERE ABS(dif) > 0.01"""),
]


@auth.guarded(auth.ROL_EMPLEADO)
def run_governance_checks() -> str:
    """Corre las 11 reglas de calidad de la política interna (DQ-01 a DQ-11) y devuelve una tabla con
    dimensión, severidad, número de registros con hallazgo y estado."""
    filas = ["| regla | dimension | severidad | descripcion | registros_con_hallazgo | estado |", "|---|---|---|---|---|---|"]
    for regla, dim, sev, desc, sql in REGLAS_DQ:
        try:
            _, r, _ = db.consultar(sql, rol=db.ROL_BD_EMPLEADO)
            n = int(r[0][0] or 0)
            estado = "Cumple" if n == 0 else "Con hallazgos"
            filas.append(f"| {regla} | {dim} | {sev} | {desc} | {n:,} | {estado} |")
        except Exception as e:  # noqa: BLE001
            msg = "No evaluada (corre .\\run.ps1 load-db)" if "dq09" in str(e) else "No evaluada"
            filas.append(f"| {regla} | {dim} | {sev} | {desc} | - | {msg} |")
    return "\n".join(filas)


_ACCIONES = {
    "inicio_sesion": "Inicio de sesión", "respuesta": "Consulta respondida", "entrada_bloqueada": "Solicitud bloqueada",
    "dato_restringido": "Dato restringido solicitado", "escritura_rechazada": "Modificación rechazada",
    "error_sql": "Consulta con error", "sql_rechazado": "Consulta rechazada", "subir_pdf": "Documento cargado",
    "quitar_pdf": "Documento retirado", "grafica": "Gráfica generada", "tiempo_agotado": "Tiempo agotado",
    "consultar_saldos": "Consulta de saldos", "consultar_historico_saldos": "Consulta de histórico",
    "consultar_movimientos": "Consulta de movimientos", "resumen_mensual_movimientos": "Resumen mensual",
    "saldo_por_grupo": "Indicador de saldos", "clientes_por_grupo": "Indicador de clientes",
    "movimientos_por_grupo": "Indicador de movimientos", "perfil_cliente": "Ficha de cliente",
    "run_governance_checks": "Revisión de calidad", "get_audit_log": "Consulta de auditoría",
    "run_sql_query": "Consulta avanzada", "search_governance_knowledge": "Búsqueda en normativa",
}


@auth.guarded(auth.ROL_EMPLEADO)
def get_audit_log(n: int = 15) -> str:
    """Últimas n acciones registradas (fecha, usuario, rol, acción, resultado y detalle) como tabla."""
    if not common.AUDIT_FILE.exists():
        return "Sin registros."
    filas = ["| fecha | usuario | rol | accion | resultado | detalle |", "|---|---|---|---|---|---|"]
    for linea in common.AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines()[-int(n):]:
        try:
            r = json.loads(linea)
        except json.JSONDecodeError:
            continue
        detalle = r.get("pregunta") or r.get("documento") or r.get("patron") or ""
        if not detalle and isinstance(r.get("args"), dict):
            detalle = ", ".join(f"{k}={v}" for k, v in r["args"].items() if k != "query")
        detalle = str(detalle).replace("|", "/").replace("\n", " ")[:90]
        accion = _ACCIONES.get(r.get("accion", ""), str(r.get("accion", "")).replace("_", " ").capitalize())
        filas.append(f"| {r.get('ts', '').replace('T', ' ')} | {r.get('usuario', '')} | {r.get('rol', '')} | "
                     f"{accion} | {'Permitido' if r.get('permitido') else 'Denegado'} | {detalle} |")
    return "\n".join(filas)


@auth.guarded(auth.ROL_EMPLEADO)
def historico_cliente(num_cte: int) -> str:
    """Saldos de cada mes (ene-jun 2026) y resumen de movimientos por mes y tipo de UN cliente.
    Sirve para revisar o conciliar el estado de cuenta de un cliente. num_cte: número de cliente."""
    saldos = _q("""SELECT fec_informacion AS fecha_corte, cve_producto AS producto, saldo_apertura, saldo_mes
        FROM cfg.fact_sdos_captacoloca_m WHERE num_cte = %s ORDER BY cve_producto, fec_informacion""", (int(num_cte),))
    movs = _q("""SELECT cve_mes_txn AS mes, cve_producto AS producto, desc_txn AS tipo, COUNT(*) AS movimientos,
               SUM(saldo_txn) AS total_mxn
        FROM cfg.fact_txn_captacoloca_d WHERE num_cte = %s GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", (int(num_cte),))
    return f"SALDOS\n{saldos}\n\nMOVIMIENTOS\n{movs}"


# SQL libre: la capa semántica del socio indica que "el LLM no debe ejecutar SQL directamente".
# Por eso viene APAGADO; las preguntas típicas se resuelven con las herramientas de indicadores.
# Para desarrollo:  SQL_LIBRE=1 en .env  (aun así cada consulta se valida contra la capa semántica).
SQL_LIBRE = [get_data_model_guide, list_tables, run_sql_query] if common.SQL_LIBRE else []

HERRAMIENTAS = {
    auth.ROL_CLIENTE: [consultar_saldos, consultar_historico_saldos, consultar_movimientos, resumen_mensual_movimientos],
    auth.ROL_EMPLEADO: [saldo_por_grupo, clientes_por_grupo, movimientos_por_grupo, perfil_cliente, historico_cliente,
                        run_governance_checks, get_audit_log] + SQL_LIBRE,
}
for _fn in HERRAMIENTAS[IDENT.rol]:  # el cliente ni siquiera VE las tools del empleado
    mcp.tool(_fn)

if __name__ == "__main__":
    db.ensure_db_silencioso()
    mcp.run()  # stdio