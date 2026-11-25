"""Enrutamiento del orquestador (sin LLM real: se simula su respuesta)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from agent import Steward  # noqa: E402


def ruta(q, llm_dice="DOCUMENTOS", con_pdf=True, anterior=None, ruta_anterior=None):
    """Devuelve (ruta, prompt que vio el LLM o None si no se le preguntó)."""
    visto = {}
    s = SimpleNamespace(doc=object() if con_pdf else None, historial=[(anterior, "...")] if anterior else [],
                        ultima_ruta=ruta_anterior)

    async def llm(prompt):
        visto["prompt"] = prompt
        return llm_dice
    s._llm = llm
    s._ajustar_ruta = lambda r, qq, seg: Steward._ajustar_ruta(s, r, qq, seg)
    return asyncio.run(Steward._rutear(s, q)), visto.get("prompt")


# --- PDF
def test_pregunta_del_contrato_va_a_pdf_aunque_el_llm_diga_documentos():
    r, prompt = ruta("¿Qué penalizaciones tiene el documento que te subí? ¿Cumple con la LFPDPPP?",
                     anterior="¿Qué derechos tengo sobre mis datos?", ruta_anterior="DOCUMENTOS")
    assert r == "PDF" and prompt is None  # regla determinista, no se consulta al LLM


def test_sin_pdf_cargado_nunca_va_a_pdf():
    assert ruta("¿Qué penalizaciones tiene el documento que te subí?", llm_dice="PDF", con_pdf=False)[0] == "DOCUMENTOS"


def test_subio_no_es_subi():
    assert ruta("¿Por qué subió mi deuda?", llm_dice="DATOS")[0] == "DATOS"
    assert ruta("¿Qué dice el archivo que subí?", llm_dice="DATOS")[0] == "PDF"


def test_saldo_con_pdf_cargado_no_va_a_pdf():
    assert ruta("¿Cuál es mi saldo este mes?", llm_dice="DATOS")[0] == "DATOS"


# --- seguimiento
def test_seguimiento_hereda_tema_si_el_llm_dice_general():
    r, prompt = ruta("¿y en abril?", llm_dice="GENERAL", con_pdf=False,
                     anterior="¿Cuánto gasté en mayo?", ruta_anterior="DATOS")
    assert r == "DATOS" and "¿Cuánto gasté en mayo?" in prompt


def test_pregunta_nueva_no_arrastra_contexto():
    r, prompt = ruta("¿Qué dice la ley sobre el secreto bancario?", con_pdf=False,
                     anterior="¿Cuánto gasté en mayo?", ruta_anterior="DATOS")
    assert r == "DOCUMENTOS" and "¿Cuánto gasté en mayo?" not in prompt


def test_saludo_sigue_siendo_general():
    assert ruta("Hola, buenas tardes, ¿qué puedes hacer por mí?", llm_dice="GENERAL", con_pdf=False)[0] == "GENERAL"