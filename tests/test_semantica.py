"""Validador de SQL contra la capa semántica del socio (catálogo de prueba, sin BD)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import semantica as S  # noqa: E402

COLS = {
    "dim_cliente": ["num_cte", "fec_alta", "fec_nac", "tipo_persona", "genero_cte", "segmento_cte", "cve_sucursal"],
    "dim_producto": ["cve_producto", "cve_dominio", "grupo_producto", "descripcion"],
    "dim_txn": ["cve_producto", "cve_txn", "desc_txn"],
    "fact_sdos_captacoloca_m": ["num_cta", "num_cte", "cve_producto", "saldo_apertura", "saldo_mes", "fec_informacion", "dominio"],
    "fact_txn_captacoloca_d": ["num_cta", "num_cte", "cve_producto", "fec_txn", "cve_mes_txn", "saldo_txn", "cve_txn", "desc_txn"],
}
CAT = {
    "tablas": {t: {"negocio": t, "grano": "", "restricciones": ""} for t in COLS},
    "columnas": {t: {c: {"tipo": "", "negocio": c, "sensibilidad": "", "hint": "", "ejemplos": "[]", "confianza": ""}
                     for c in cs} for t, cs in COLS.items()},
    "metricas": [("M001", "Saldo de cierre", "fact_sdos_captacoloca_m", "SUM(saldo_mes)", "SNAPSHOT", "")],
    "reglas": [("R001", "No sumar snapshots mensuales", "Filtrar un solo fec_informacion")],
    "relaciones": [("fact_sdos_captacoloca_m", "dim_cliente", "num_cte"), ("fact_txn_captacoloca_d", "dim_cliente", "num_cte"),
                   ("fact_sdos_captacoloca_m", "dim_producto", "cve_producto"),
                   ("fact_txn_captacoloca_d", "dim_txn", "cve_producto AND cve_txn")],
}

VALIDAS = [
    "SELECT c.segmento_cte, SUM(s.saldo_mes) total FROM cfg.fact_sdos_captacoloca_m s JOIN dim.dim_cliente c "
    "ON c.num_cte = s.num_cte WHERE s.fec_informacion = 20260630 GROUP BY 1",
    "SELECT s.fec_informacion, SUM(s.saldo_mes) FROM cfg.fact_sdos_captacoloca_m s GROUP BY s.fec_informacion",
    "SELECT d.desc_txn, COUNT(*) FROM cfg.fact_txn_captacoloca_d t JOIN dim.dim_txn d "
    "ON d.cve_producto = t.cve_producto AND d.cve_txn = t.cve_txn GROUP BY 1",
    "WITH t AS (SELECT num_cta, cve_mes_txn, SUM(saldo_txn) total FROM cfg.fact_txn_captacoloca_d GROUP BY 1, 2) "
    "SELECT s.fec_informacion, SUM(t.total) FROM cfg.fact_sdos_captacoloca_m s JOIN t ON t.num_cta = s.num_cta "
    "GROUP BY s.fec_informacion",
    "SELECT codigo_regla FROM semantic.sem_reglas_negocio",
]
INVALIDAS = {
    "tabla inventada": ("SELECT segmento, SUM(saldo) FROM tarjetas_credito GROUP BY segmento", "no existe en la capa"),
    "R001": ("SELECT cve_producto, SUM(saldo_mes) FROM cfg.fact_sdos_captacoloca_m GROUP BY 1", "R001"),
    "R005 cve_txn sola": ("SELECT d.desc_txn FROM cfg.fact_txn_captacoloca_d t JOIN dim.dim_txn d ON d.cve_txn = t.cve_txn", "R005"),
    "R005 sin relación": ("SELECT p.descripcion FROM dim.dim_producto p JOIN dim.dim_cliente c ON c.num_cte = 1", "R005"),
    "R007": ("SELECT SUM(t.saldo_txn) FROM cfg.fact_sdos_captacoloca_m s JOIN cfg.fact_txn_captacoloca_d t "
             "ON t.num_cta = s.num_cta WHERE s.fec_informacion = 20260630", "R007"),
    "R011": ("SELECT dominio, COUNT(*) FROM cfg.fact_sdos_captacoloca_m GROUP BY dominio", "R011"),
    "columna inventada": ("SELECT c.saldo_total FROM dim.dim_cliente c", "no existe"),
    "restringida": ("SELECT c.genero_cte, COUNT(*) FROM dim.dim_cliente c GROUP BY 1", "restringido"),
}


@pytest.mark.parametrize("sql", VALIDAS)
def test_consultas_validas(sql):
    S.validar_contra_catalogo(sql, CAT)


@pytest.mark.parametrize("caso", INVALIDAS)
def test_consultas_invalidas(caso):
    sql, mensaje = INVALIDAS[caso]
    with pytest.raises(S.ViolacionSemantica, match=mensaje):
        S.validar_contra_catalogo(sql, CAT)


def test_guia_oculta_restringidas_y_lista_joins():
    g = S.guia_desde_catalogo(CAT)
    assert "genero_cte: RESTRINGIDA" in g and "fec_nac: RESTRINGIDA" in g
    assert "JOINS PERMITIDOS" in g and "fact_txn_captacoloca_d -> dim_txn" in g and "R001" in g