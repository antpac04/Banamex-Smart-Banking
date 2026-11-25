"""Agente de Gráficas sin LLM real (se simula) ni BD. Incluye los casos reales que fallaban."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import charts  # noqa: E402

# Tablas tal como las devuelven las herramientas
SALDOS = """| producto | descripcion | cuenta | saldo_mxn | fecha_corte |
|---|---|---|---|---|
| AHORRO | Cuenta de ahorro | ****0041 | 25,840.10 | 20260630 |
| CHEQUES | Cuenta de cheques | ****0041 | 10,938.72 | 20260630 |
| TDC | Tarjeta de crédito | ****0041 | 66,768.11 | 20260630 |"""
SEGMENTOS = """| segmento | clientes | cuentas | saldo_total_mxn | saldo_promedio_mxn |
|---|---|---|---|---|
| MASIVO | 3750 | 3750 | 275,566,672.53 | 73,484.45 |
| PREFERENTE | 1000 | 1000 | 73,959,419.78 | 73,959.42 |
| PREMIUM | 250 | 250 | 17,566,430.73 | 70,265.72 |"""
HISTORICO = """| fecha_corte | producto | saldo_apertura | saldo_mes |
|---|---|---|---|
| 20260131 | TDC | 60,000.00 | 61,000.00 |
| 20260228 | TDC | 61,000.00 | 62,500.00 |
| 20260331 | TDC | 62,500.00 | 64,000.00 |
| 20260131 | CHEQUES | 9,000.00 | 9,500.00 |
| 20260228 | CHEQUES | 9,500.00 | 9,700.00 |
| 20260331 | CHEQUES | 9,700.00 | 9,850.00 |"""
MENSUAL = """| mes | tipo | movimientos | total_mxn |
|---|---|---|---|
| 202602 | COMPRAS | 1 | 1,188.39 |
| 202602 | DEPOSITO | 2 | 15,000.00 |
| 202602 | RETIRO | 2 | 696.92 |
| 202603 | COMPRAS | 1 | 1,224.04 |
| 202603 | PAGOS | 2 | 5,000.00 |
| 202603 | RETIRO | 2 | 710.86 |"""
UNA_CIFRA = """| saldo_total_mxn |
|---|
| 367,092,523.04 |"""


class LLMFalso:
    def __init__(self, respuesta="no sé"):
        self.respuesta = respuesta

    async def ainvoke(self, _):
        return type("M", (), {"content": self.respuesta})()


def elegir(q, texto, respuesta_llm="no sé"):
    return asyncio.run(charts.elegir_grafica(LLMFalso(respuesta_llm), q, charts.extraer_tablas(texto)))


def test_parseo_tabla():
    t = charts.extraer_tablas(MENSUAL)[0]
    assert t.filas[0] == ["202602", "COMPRAS", 1.0, 1188.39]  # el mes queda como texto, el monto como número
    assert t.numericas() == ["movimientos", "total_mxn"] and t.temporales() == ["mes"]


def test_columnas_constantes_y_redundantes_no_son_ejes():
    t = charts.extraer_tablas(SALDOS)[0]
    assert t.dimensiones() == ["producto"]  # fecha_corte constante, cuenta enmascarada, descripcion = producto


# --- bugs reportados
def test_pastel_explicito_se_respeta():
    g = elegir("Haz una gráfica de pastel de mis saldos", SALDOS)
    assert (g.tipo, g.x, g.y, g.decidido_por) == ("pastel", "producto", "saldo_mxn", "usuario")


def test_ya_no_hay_grafica_de_puntos_con_una_sola_fecha():
    g = elegir("Grafica mis saldos", SALDOS)
    assert g.tipo == "barras" and g.x == "producto"


def test_proporcion_de_clientes_usa_clientes_no_promedio():
    g = elegir("Grafica la proporción de clientes por segmento", SEGMENTOS)
    assert (g.tipo, g.y) == ("pastel", "clientes")


def test_pastel_de_saldo_usa_total_no_promedio():
    assert elegir("Gráfica de pastel del saldo por segmento", SEGMENTOS).y == "saldo_total_mxn"


def test_promedio_solo_si_se_pide():
    assert elegir("Grafica el saldo promedio por segmento", SEGMENTOS).y == "saldo_promedio_mxn"


# --- tipos
@pytest.mark.parametrize("q,texto,tipo,x,color", [
    ("Compara mis gastos de cada mes en una gráfica", MENSUAL, "barras_agrupadas", "mes", "tipo"),
    ("Grafica cómo ha cambiado mi deuda", HISTORICO, "lineas", "fecha_corte", "producto"),
    ("Grafica mis saldos por producto", HISTORICO, "barras", "producto", None),
    ("Grafica el saldo total de TDC", UNA_CIFRA, "indicador", None, None),
])
def test_tipo_segun_pregunta_y_datos(q, texto, tipo, x, color):
    g = elegir(q, texto)
    assert (g.tipo, g.x, g.color) == (tipo, x, color)


def test_saldos_sin_evolucion_usan_ultimo_corte():
    g = elegir("Grafica mis saldos por producto", HISTORICO)
    ix, iy = g.tabla.columnas.index("producto"), g.tabla.columnas.index(g.y)
    assert {f[ix]: f[iy] for f in g.tabla.filas} == {"TDC": 64000.0, "CHEQUES": 9850.0}  # no suma meses (R001)


def test_lineas_sin_periodos_se_vuelve_barras_con_aviso():
    g = elegir("Gráfica de líneas de mis saldos", SALDOS)
    assert g.tipo == "barras" and "varios periodos" in g.aviso


def test_tipo_no_disponible_avisa():
    g = elegir("Haz una gráfica de dispersión de mis saldos", SALDOS)
    assert g.tipo == "barras" and g.aviso


def test_gastos_quitan_depositos_y_pagos():
    g = elegir("Compara mis gastos de cada mes en una gráfica", MENSUAL)
    assert {f[1] for f in g.tabla.filas} == {"COMPRAS", "RETIRO"}


def test_respeta_conteos_si_se_piden():
    g = elegir("Grafica cuántos movimientos tuve por mes", MENSUAL)
    assert g.y == "movimientos" and g.x == "mes"


def test_pastel_con_muchas_categorias_agrupa_otros():
    filas = "\n".join(f"| S{i:02d} | {100 - i} |" for i in range(12))
    g = elegir("Pastel del saldo por sucursal", f"| sucursal | saldo_mxn |\n|---|---|\n{filas}")
    assert g.tipo == "pastel" and len(g.tabla.filas) == 8 and g.tabla.filas[-1][0] == "Otros"


# --- el modelo solo sugiere
def test_sugerencia_valida_del_modelo():
    g = elegir("Muestra mis gastos", MENSUAL, '{"tipo": "lineas", "tabla": 0, "y": "total_mxn", "titulo": "Gasto mensual"}')
    assert (g.tipo, g.x, g.color, g.titulo, g.decidido_por) == ("lineas", "mes", "tipo", "Gasto mensual", "llm")


def test_sugerencia_con_columnas_inventadas_no_rompe():
    g = elegir("Compara mis gastos", MENSUAL, '{"tipo": "barras", "tabla": 0, "y": "monto_inventado"}')
    assert g.y == "total_mxn" and g.x in g.tabla.columnas


def test_tipo_pedido_gana_al_modelo():
    g = elegir("Haz un pastel de clientes por segmento", SEGMENTOS, '{"tipo": "barras", "tabla": 0, "y": "clientes"}')
    assert g.tipo == "pastel"


def test_sin_numeros_no_hay_grafica():
    assert elegir("grafica", "| a | b |\n|---|---|\n| x | y |") is None


def test_pide_grafica():
    assert charts.pide_grafica("Haz una gráfica de mis gastos") and charts.pide_grafica("hazme un pastel")
    assert not charts.pide_grafica("¿Cuál es mi saldo?")


@pytest.mark.parametrize("q,texto", [("Grafica mis saldos", SALDOS), ("Pastel de clientes por segmento", SEGMENTOS),
                                     ("Grafica cómo ha cambiado mi deuda", HISTORICO),
                                     ("Compara mis gastos de cada mes", MENSUAL), ("Saldo total", UNA_CIFRA)])
def test_figura(q, texto):
    pytest.importorskip("plotly")
    assert charts.figura(elegir(q, texto)).data