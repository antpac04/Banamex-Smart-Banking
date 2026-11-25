"""Subagente lector + decisiones del hub sobre documentos (sin PDF real, sin BD, sin modelo)."""
import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ["STEWARD_AUDIT_FILE"] = str(Path(tempfile.mkdtemp()) / "audit.jsonl")
import agente_lector as L  # noqa: E402
from agent import Steward  # noqa: E402

ESTADO = L.limpiar_texto("""DOCUMENTO DE PRUEBA Banco Ficticio del Reto, S.A. ESTADO DE CUENTA
Cliente: 42 Periodo: junio 2026 Fecha de corte: último día de junio 2026 RESUMEN DE PRODUCTOS
Producto Descripción Cuenta Saldo inicial Saldo al corte
AHORRO Cuenta de ahorro ****0041 $25,000.00 $25,840.10
CHEQUES Cuenta de cheques ****0041 $9,850.00 $10,938.72
TDC Tarjeta de crédito ****0041 $64,000.00 $66,768.11
Pago mínimo (5% del saldo, mínimo $200) $3,338.41
2026-06-03 CHEQUES DEPOSITO $15,000.00 2026-06-08 CHEQUES RETIRO $3,000.00
2026-06-12 TDC COMPRAS $1,306.62 2026-06-15 TDC DISPOSICIONES $3,500.00 2026-06-25 TDC PAGOS $2,500.00
Total de cargos (compras, retiros y disposiciones): $7,806.62 Total de abonos (depósitos y pagos): $17,500.00
DOCUMENTO SINTÉTICO PARA PRUEBAS ACADÉMICAS · NO ES UN DOCUMENTO DE BANAMEX NI TIENE VALIDEZ · pág. 1""")
CONTRATO = L.limpiar_texto("""CONTRATO DE APERTURA DE CRÉDITO (TARJETA DE CRÉDITO CLÁSICA)
CLÁUSULA 1. OBJETO El Banco otorga una línea de crédito.
CLÁUSULA 2. COMISIONES Anualidad: $750.00 + IVA. Pago tardío: $450.00 + IVA.
CLÁUSULA 3. USO DE DATOS PERSONALES El Cliente autoriza que sus datos sean compartidos con terceros sin consentimiento.
CLÁUSULA 4. CONSERVACIÓN DE LA INFORMACIÓN El Banco conservará los datos de manera indefinida.
Firma del cliente: ____""")

HIST = """| fecha_corte | producto | saldo_apertura | saldo_mes |
|---|---|---|---|
| 20260630 | AHORRO | 25,000.00 | 25,840.10 |
| 20260630 | CHEQUES | 9,850.00 | 10,938.72 |
| 20260630 | TDC | 64,000.00 | 66,768.11 |
| 20260531 | TDC | 60,000.00 | 64,000.00 |"""
MOVS = """Mes: 202606

RESUMEN POR TIPO
| producto | tipo | movimientos | total_mxn |
|---|---|---|---|
| CHEQUES | DEPOSITO | 1 | 15,000.00 |
| CHEQUES | RETIRO | 1 | 3,000.00 |
| TDC | COMPRAS | 1 | 1,306.62 |
| TDC | DISPOSICIONES | 1 | 3,500.00 |
| TDC | PAGOS | 1 | 2,500.00 |"""


# ------------------------------------------------------------------ extracción
def test_clasifica_y_extrae_estado_de_cuenta():
    assert L.clasificar(ESTADO) == "estado_de_cuenta"
    e = L.extraer_estado_cuenta(ESTADO)
    assert (e["num_cte"], e["periodo"], len(e["saldos"]), len(e["movimientos"])) == (42, "202606", 3, 5)
    assert e["saldos"][1] == {"producto": "CHEQUES", "cuenta": "****0041", "saldo_inicial": 9850.0, "saldo_corte": 10938.72}
    assert (e["total_cargos"], e["total_abonos"], e["pago_minimo"]) == (7806.62, 17500.0, 3338.41)


def test_extrae_clausulas_sin_pie_de_pagina():
    cl = L.extraer_clausulas(CONTRATO)
    assert [c.titulo for c in cl] == ["OBJETO", "COMISIONES", "USO DE DATOS PERSONALES", "CONSERVACIÓN DE LA INFORMACIÓN"]
    assert "Firma" not in cl[-1].texto and "pág." not in ESTADO


def test_clausulas_relevantes_por_tema():
    cl = L.extraer_clausulas(CONTRATO)
    assert [c.numero for c in L.clausulas_relevantes(cl, "¿Qué penalizaciones tiene?")] == [2]
    assert [c.numero for c in L.clausulas_relevantes(cl, "¿Cumple con la LFPDPPP?")] == [3, 4]
    assert len(L.clausulas_relevantes(cl, "¿De qué trata?")) == 4


# ------------------------------------------------------------------ hub
class Tool:
    def __init__(self, name, salida):
        self.name, self.salida, self.llamadas = name, salida, []

    async def ainvoke(self, args):
        self.llamadas.append(args)
        return self.salida


def hub(texto_doc, rol="cliente", num_cte=42, hist=HIST, movs=MOVS):
    lector = L.AgenteLector()
    tipo = L.clasificar(texto_doc)
    lector.ficha = L.FichaDocumento("doc.pdf", tipo, {"paginas": 1}, texto_doc,
                                    clausulas=L.extraer_clausulas(texto_doc) if tipo != "estado_de_cuenta" else [],
                                    estado_cuenta=L.extraer_estado_cuenta(texto_doc) if tipo == "estado_de_cuenta" else None)
    s = SimpleNamespace(ident=SimpleNamespace(es_cliente=rol == "cliente", num_cte=num_cte if rol == "cliente" else None,
                                              usuario="t", rol=rol),
                        lector=lector, doc=lector.ficha,
                        tools_datos=[Tool("postgres_consultar_historico_saldos", hist),
                                     Tool("postgres_consultar_movimientos", movs),
                                     Tool("postgres_historico_cliente", f"SALDOS\n{hist}\n\nMOVIMIENTOS\n| mes | producto | tipo | movimientos | total_mxn |\n|---|---|---|---|---|\n| 202606 | TDC | COMPRAS | 1 | 1,306.62 |")],
                        tools_docs=[Tool("governance_search_governance_knowledge", "[1] Fuente: LFPDPPP.pdf (pág. 4)\nconsentimiento")])
    for m in ("_tool", "_llamar", "_flujo_documento", "_responder_con_documento", "_documento_vs_normativa", "_documento_vs_base"):
        setattr(s, m, types.MethodType(getattr(Steward, m), s))

    async def llm(prompt):
        s.prompt = prompt
        return "respuesta del modelo"
    s._llm = llm
    return s


def correr(s, q):
    pasos = []
    return asyncio.run(s._flujo_documento(q, pasos)), pasos


def test_estado_de_cuenta_coincide_con_la_base():
    texto, pasos = correr(hub(ESTADO), "¿Mi estado de cuenta coincide con lo que tiene el banco?")
    assert "todos los conceptos coinciden" in texto and "Diferente" not in texto
    assert pasos[0]["agente"] == "lector" and any(p["herramienta"].endswith("consultar_historico_saldos") for p in pasos)


def test_detecta_diferencias():
    texto, _ = correr(hub(ESTADO, hist=HIST.replace("10,938.72", "10,900.00")), "¿Está correcto mi estado de cuenta?")
    assert "1 concepto(s) no coinciden" in texto and "Cheques: saldo al corte" in texto


def test_cliente_no_puede_conciliar_documento_de_otro():
    texto, pasos = correr(hub(ESTADO, num_cte=7), "¿Coincide con mis registros?")
    assert "corresponde a otro cliente" in texto and not any("historico" in p["herramienta"] for p in pasos)


def test_colaborador_concilia_al_cliente_del_documento():
    s = hub(ESTADO, rol="empleado")
    texto, _ = correr(s, "Verifica este estado de cuenta contra los registros")
    assert s.tools_datos[2].llamadas == [{"num_cte": 42}] and "Registros del banco" in texto


def test_contrato_contra_normativa_busca_por_clausula():
    s = hub(CONTRATO)
    texto, pasos = correr(s, "¿Este contrato cumple con la LFPDPPP?")
    busquedas = s.tools_docs[0].llamadas
    assert len(busquedas) == 2 and "uso de datos personales" in busquedas[0]["query"]
    assert "Fuente: LFPDPPP.pdf" in s.prompt and "USO DE DATOS PERSONALES" in s.prompt


def test_pregunta_de_contenido_no_busca_en_normativa_ni_base():
    s = hub(CONTRATO)
    correr(s, "¿Qué comisiones tiene el contrato?")
    assert s.tools_docs[0].llamadas == [] and all(t.llamadas == [] for t in s.tools_datos)
    assert "COMISIONES" in s.prompt