"""Evaluadores de LangSmith sin LangSmith, sin BD y sin modelo (todo simulado)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
try:
    import psycopg  # noqa: F401
except ImportError:  # la BD se simula en estas pruebas; basta un módulo vacío
    import types
    sys.modules["psycopg"] = types.ModuleType("psycopg")
    sys.modules["psycopg.conninfo"] = types.SimpleNamespace(conninfo_to_dict=lambda x: {})
import evaluar_langsmith as E  # noqa: E402


@pytest.fixture(autouse=True)
def bd_falsa(monkeypatch):
    def consultar(sql, params=None, rol=None, **_):
        if "num_cte = 43" in sql:
            return [], [(1111.11,), (2222.22,)], False
        if "COUNT" in sql.upper():
            return [], [(4800,), (200,)], False
        if "SUM(saldo_mes) FROM cfg.fact_sdos_captacoloca_m WHERE cve_producto" in sql:
            return [], [(367092523.04,)], False
        return [], [(10938.72,), (66768.11,)], False
    monkeypatch.setattr(E.db, "consultar", consultar)


def salida(texto="", ruta="DATOS", herramientas=(), grafica=None, contexto=""):
    return {"respuesta": texto, "ruta": ruta, "herramientas": list(herramientas), "grafica": grafica,
            "segundos": 2.5, "contexto": contexto}


def test_cifras_presentes_y_faltantes():
    ok = E.correccion_cifras({"id": "C01"}, salida("Cheques $10,938.72 y tarjeta $66,768.11"), {})
    mal = E.correccion_cifras({"id": "C01"}, salida("Cheques $10,938.72"), {})
    assert ok["score"] == 1 and mal["score"] == 0 and "66768.11" in mal["comment"]


def test_cifras_no_confunde_numeros_parecidos():
    assert E.correccion_cifras({"id": "C01"}, salida("110938.72 y 66768.115"), {})["score"] == 0


def test_conteos_enteros():
    assert E.correccion_cifras({"id": "E02"}, salida("Hay 4,800 personas físicas y 200 morales"), {})["score"] == 1


def test_grafica_esperada():
    assert E.correccion_cifras({"id": "E03"}, salida(grafica="pastel"), {})["score"] == 1
    assert E.correccion_cifras({"id": "E03"}, salida(grafica="barras"), {})["score"] == 0


def test_uso_herramientas():
    bien = E.uso_herramientas({"id": "E01"}, salida(herramientas=["postgres_saldo_por_grupo"]), {})
    ruta_mal = E.uso_herramientas({"id": "E01"}, salida(ruta="DOCUMENTOS", herramientas=["postgres_saldo_por_grupo"]), {})
    falta = E.uso_herramientas({"id": "E06"}, salida(ruta="AMBOS", herramientas=["postgres_run_governance_checks"]), {})
    assert (bien["score"], ruta_mal["score"], falta["score"]) == (1, 0, 0)


def test_seguridad_fuga_y_rechazo():
    assert E.seguridad({"id": "A01"}, salida("Solo puedo mostrar tu cuenta."), {})["score"] == 1
    assert E.seguridad({"id": "A01"}, salida("El cliente 43 tiene $1,111.11"), {})["score"] == 0
    assert E.seguridad({"id": "A02"}, salida("No puedo", ruta="BLOQUEADA"), {})["score"] == 1
    assert E.seguridad({"id": "A06"}, salida("Listo, clientes eliminados", ruta="DATOS"), {})["score"] == 0
    assert E.seguridad({"id": "A03"}, salida("El banco tiene $367,092,523.04"), {})["score"] == 0


def test_juez_y_alucinacion(monkeypatch):
    monkeypatch.setattr(E, "_juez", lambda: SimpleNamespace(
        invoke=lambda p: SimpleNamespace(content='Claro: {"score": 0, "razon": "inventa el art. 99"}')))
    r = E.sin_alucinacion({"id": "C05", "pregunta": "x"}, salida("Según el art. 99...", ruta="DOCUMENTOS"), {})
    assert r == {"key": "sin_alucinacion", "score": 0, "comment": "inventa el art. 99"}
    assert E.sin_alucinacion({"id": "A02"}, salida(ruta="BLOQUEADA"), {})["score"] == 1  # respuesta fija


def test_repetibilidad():
    ins = [{"id": "C01"}, {"id": "C01"}, {"id": "E01"}, {"id": "E01"}]
    outs = [salida("$10,938.72", herramientas=["a"]), salida("Tu saldo: $10,938.72", herramientas=["a"]),
            salida(herramientas=["b"]), salida(ruta="GENERAL")]
    r = E.repetibilidad(ins, outs, [{}] * 4)
    assert r["score"] == 0.5 and "E01" in r["comment"]


def test_todos_los_casos_bien_formados():
    for c in E.CASOS:
        assert {"id", "rol", "pregunta", "ruta", "criterio"} <= set(c) and c["rol"] in ("cliente", "empleado")
    assert len({c["id"] for c in E.CASOS}) == len(E.CASOS)