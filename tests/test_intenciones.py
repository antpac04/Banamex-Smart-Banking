"""Intenciones que se resuelven con código (sin modelo): dato restringido, escritura, ficha, auditoría, calidad."""
import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import agent  # noqa: E402
from agent import Steward  # noqa: E402

FICHA = """FICHA
| num_cte | tipo_persona | segmento_cte | fec_alta | cve_sucursal | cve_promotor |
|---|---|---|---|---|---|
| 42 | PF | MASIVO | 2019-03-02 | 0101 | P-12 |

SALDOS AL 20260630
| producto | cuenta | saldo_mxn |
|---|---|---|
| CHEQUES | ****0041 | 10,938.72 |
| TDC | ****0041 | 66,768.11 |"""
CALIDAD = """| regla | dimension | severidad | descripcion | registros_con_hallazgo | estado |
|---|---|---|---|---|---|
| DQ-01 | Unicidad | Alta | Una cuenta no tiene dos saldos para el mismo mes | 0 | Cumple |
| DQ-07 | Consistencia | Media | Cada producto usa un único valor de dominio en todos los meses | 4 | Con hallazgos |
| DQ-10 | Completitud | Media | Territorio, sucursal y promotor del cliente informados | 5,000 | Con hallazgos |"""
AUDIT = """| fecha | usuario | rol | accion | resultado | detalle |
|---|---|---|---|---|---|
| 2026-11-18 17:00:31 | cliente-42 | cliente | Solicitud bloqueada | Denegado | saldo del cliente 43 |"""


class Tool:
    def __init__(self, name, salida):
        self.name, self.salida, self.llamadas = name, salida, []

    async def ainvoke(self, args):
        self.llamadas.append(args)
        return self.salida


def sesion(rol="empleado"):
    s = SimpleNamespace(ident=SimpleNamespace(es_cliente=(rol == "cliente")),
                        tools_datos=[Tool("postgres_perfil_cliente", FICHA), Tool("postgres_get_audit_log", AUDIT),
                                     Tool("postgres_run_governance_checks", CALIDAD)],
                        tools_docs=[Tool("governance_search_governance_knowledge",
                                         "[1] Fuente: politica_calidad_datos_sintetica.md (pág. 1)\nhomologar dominio")])
    for m in ("_tool", "_llamar", "_intencion_directa", "_politica_para"):
        setattr(s, m, types.MethodType(getattr(Steward, m), s))

    async def llm(prompt):
        s.prompt = prompt
        return "Según la política, homologar al catálogo (Fuente: politica_calidad_datos_sintetica.md, pág. 1)."
    s._llm = llm
    return s


def directa(q, rol="empleado"):
    s = sesion(rol)
    return asyncio.run(s._intencion_directa(q, [])), s


# --- dato restringido y escritura (antes del modelo)
def restringido(q):
    return agent.pide_dato_restringido(q)


def test_detecta_datos_restringidos():
    for q in ["¿Cuántas clientas mujeres hay?", "Dame la distribución por género", "¿Cuál es la edad promedio?",
              "Muéstrame la fecha de nacimiento del cliente 42", "Grafica los clientes por sexo"]:
        assert restringido(q), q


def test_no_bloquea_preguntas_normativas_ni_normales():
    for q in ["¿Qué dice la política sobre la fecha de nacimiento?", "¿Cuántos clientes hay por segmento?",
              "¿Cuál es la antigüedad de mi cuenta?", "¿Cuánto gasté en mayo?"]:
        assert not restringido(q), q


def test_detecta_escritura():
    for q in ["Borra los clientes inactivos de la base", "Elimina el cliente 42", "Actualiza el saldo del cliente 7",
              "Da de baja a los clientes PREMIUM", "delete from dim_cliente"]:
        assert agent.pide_escritura(q), q
    for q in ["¿Cómo ha cambiado la deuda de mi tarjeta?", "¿Qué dice la política sobre borrar datos?",
              "¿Cuánto gasté en mayo?"]:
        assert not agent.pide_escritura(q), q


# --- flujos directos del colaborador
def test_ficha_directa_y_legible():
    (texto, ruta), s = directa("Dame la ficha del cliente 42")
    assert ruta == "DATOS" and s.tools_datos[0].llamadas == [{"num_cte": 42}]
    assert "Persona física" in texto and "$10,938.72" in texto and "num_cte" not in texto


def test_cliente_no_usa_flujos_directos():
    assert directa("Dame la ficha del cliente 42", rol="cliente")[0] is None


def test_auditoria_directa_no_inventa():
    (texto, _), s = directa("Muéstrame la auditoría reciente")
    assert "Solicitud bloqueada" in texto and "Denegado" in texto and "borr" not in texto.lower()


def test_calidad_resumen_exacto():
    (texto, ruta), _ = directa("Revisa la calidad de los datos")
    assert ruta == "DATOS" and "2 tienen hallazgos" in texto and "DQ-07" in texto and "DQ-10" in texto


def test_calidad_con_politica_usa_fragmentos():
    (texto, ruta), s = directa("¿Qué reglas de calidad tienen hallazgos y qué dice la política sobre cómo corregirlos?")
    assert ruta == "AMBOS" and "Fuente: politica_calidad_datos_sintetica.md" in texto
    assert "EXCLUSIVAMENTE" in s.prompt and "DQ-07" in s.prompt


def test_pregunta_de_politica_sola_no_corre_reglas():
    assert directa("¿Qué dice la política de calidad sobre los roles?")[0] is None