"""Pruebas del servidor MCP de SQL con un cliente MCP real (sin LLM). Requieren la BD cargada."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
pytest.importorskip("fastmcp")
pytest.importorskip("psycopg")
from fastmcp import Client  # noqa: E402
from fastmcp.client.transports import StdioTransport  # noqa: E402

import db_config  # noqa: E402

os.environ["STEWARD_AUDIT_FILE"] = str(Path(tempfile.mkdtemp()) / "audit.jsonl")
SERVER = str(ROOT / "src" / "mcp_postgres_server.py")


def sesion(rol, num_cte=None, sql_libre=None):
    env = {**os.environ, "STEWARD_ROLE": rol, "STEWARD_USER": f"pytest-{rol}"}
    if sql_libre is not None:  # el .env no sobreescribe variables ya definidas, así la prueba controla el modo
        env["SQL_LIBRE"] = "1" if sql_libre else "0"
    if num_cte:
        env["STEWARD_NUM_CTE"] = str(num_cte)
    return Client(StdioTransport(command=sys.executable, args=[SERVER], env=env))


def tools(rol, num_cte=None, sql_libre=None):
    async def go():
        async with sesion(rol, num_cte, sql_libre) as c:
            return {t.name for t in await c.list_tools()}
    return asyncio.run(go())


def call(rol, tool, num_cte=None, sql_libre=None, **args):
    async def go():
        async with sesion(rol, num_cte, sql_libre) as c:
            return (await c.call_tool(tool, args, raise_on_error=False)).content[0].text
    return asyncio.run(go())


@pytest.fixture(scope="module", autouse=True)
def _db():
    db_config.ensure_db()


def test_cliente_no_ve_tools_de_empleado():
    t = tools("cliente", 42)
    assert t == {"consultar_saldos", "consultar_historico_saldos", "consultar_movimientos", "resumen_mensual_movimientos"}


def test_cliente_solo_ve_lo_suyo():
    r = call("cliente", "consultar_saldos", 42)
    assert "****0041" in r and "****0042" not in r


def test_rls_directo():
    assert db_config.consultar("SELECT COUNT(*) FROM cfg.fact_sdos_captacoloca_m WHERE num_cte=43",
                               rol=db_config.ROL_BD_CLIENTE, num_cte=42)[1] == [(0,)]


def test_sql_libre_apagado_por_defecto():
    """Como pide la capa semántica del socio: el modelo no ejecuta SQL directo salvo que se active SQL_LIBRE=1."""
    t = tools("empleado", sql_libre=False)
    assert "run_sql_query" not in t and "saldo_por_grupo" in t


def test_empleado_sql_libre_valida_y_protege_pii():
    """Con SQL_LIBRE=1 (solo desarrollo) cada consulta pasa por los validadores."""
    q = lambda sql: call("empleado", "run_sql_query", sql_libre=True, query=sql)  # noqa: E731
    assert "5000" in q("SELECT COUNT(*) AS n FROM dim.dim_cliente").replace(",", "")
    r = q("SELECT genero_cte, COUNT(*) FROM dim.dim_cliente GROUP BY 1")
    assert "RECHAZADA" in r or "ERROR" in r  # la capa semántica la rechaza antes; la BD también la negaría
    assert "RECHAZADA" in q("DELETE FROM dim.dim_cliente")
    assert "RECHAZADA" in q("SELECT segmento, SUM(saldo) FROM tarjetas_credito GROUP BY segmento")
    assert "R001" in q("SELECT cve_producto, SUM(saldo_mes) FROM cfg.fact_sdos_captacoloca_m GROUP BY 1")


def test_reglas_dq():
    r = call("empleado", "run_governance_checks")
    assert "DQ-01" in r and "DQ-07" in r and "DQ-11" in r and "No evaluada" not in r


def test_resumen_mensual_cliente():
    r = call("cliente", "resumen_mensual_movimientos", 42)
    assert "202602" in r and "202606" in r and "DEPOSITO" not in r


def test_indicadores_sin_sql_libre():
    r = call("empleado", "saldo_por_grupo", producto="tarjeta de crédito", agrupar_por="segmento", mes="202606")
    assert "MASIVO" in r and "PREMIUM" in r and "ERROR" not in r
    r = call("empleado", "saldo_por_grupo", agrupar_por="mes,producto")
    assert "202601" in r and "202606" in r and "TDC" in r
    r = call("empleado", "clientes_por_grupo", agrupar_por="tipo_persona")
    assert "4800" in r.replace(",", "") and "200" in r
    r = call("empleado", "movimientos_por_grupo", agrupar_por="mes,tipo", producto="TDC")
    assert "COMPRAS" in r and "ERROR" not in r


def test_cliente_no_ve_indicadores():
    assert "saldo_por_grupo" not in tools("cliente", 42)