"""Data Steward multiagente: HUB AND SPOKE (LangChain create_agent + 2 servidores MCP por stdio).

    HUB / Orquestador (este archivo)
      · controles deterministas (manipulación, dato restringido, solo lectura) antes del modelo
      · clasifica: DATOS | DOCUMENTOS | AMBOS | PDF | GENERAL  (reglas primero, LLM solo si hace falta)
      · delega en los spokes y arma la respuesta final
    SPOKES (solo hablan con el hub, nunca entre sí):
      ├── Agente de Datos       create_agent + tools del MCP postgres (según rol) -> devuelve tablas
      ├── Agente de Documentos  create_agent + tools del MCP governance (RAG)     -> devuelve fragmentos con cita
      ├── Agente Lector         agente_lector.py: lee el PDF                      -> devuelve la ficha del documento
      └── Agente de Gráficas    charts.py: recibe tablas DEL HUB                   -> devuelve la gráfica
    Ejemplos de flujos que coordina el hub:
      datos -> hub -> gráficas · lector -> hub -> datos (conciliar estado de cuenta) · lector -> hub -> documentos (¿cumple?)

Cada sesión lanza SUS propios servidores MCP con la identidad del login en variables de entorno,
así que el cliente 42 solo tiene tools que consultan al cliente 42 (y la BD lo vuelve a filtrar con RLS).

Terminal:
    python src/agent.py --cliente 42 -i                 chat como cliente (PIN demo 1234)
    python src/agent.py --user ana.steward -i           chat como empleado (Banamex2026!)
    python src/agent.py --user ana.steward "pregunta"   una sola pregunta
    python src/agent.py --cliente 42 --pdf contrato.pdf -i
"""
import argparse
import asyncio
import getpass
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auth  # noqa: E402
import charts  # noqa: E402
import common  # noqa: E402
from agente_lector import AgenteLector, FichaDocumento  # noqa: E402

SRC = Path(__file__).resolve().parent
RUTAS = ("DATOS", "DOCUMENTOS", "AMBOS", "PDF", "GENERAL")
TIEMPO_MAXIMO = float(os.getenv("TIEMPO_MAXIMO_RESPUESTA", "150"))  # segundos por pregunta

REGLAS = """Reglas:
- Responde en español de México, claro y breve. Montos como $12,345.67 MXN.
- Nunca inventes cifras ni políticas: usa SOLO lo que regresen las herramientas.
- Hablas con un usuario final: NUNCA menciones herramientas, agentes, bases de datos, SQL, modelos ni nombres
  técnicos. Solo da la respuesta.
- Los datos van de enero a junio de 2026 (último corte 30-jun-2026). Si piden "el mes pasado" o "este mes",
  usa junio 2026 y acláralo."""

_INSTRUCCION_SQL = (
    "SOLO si ninguna sirve: llama postgres_get_data_model_guide (capa semántica) y luego postgres_run_sql_query con\n"
    "UNA consulta SELECT que respete las métricas, reglas y joins validados de la guía. Si la rechaza o da ERROR,\n"
    "corrígela una sola vez con el mensaje recibido."
    if common.SQL_LIBRE else
    "Si ninguna herramienta responde la pregunta, dilo con claridad y sugiere una pregunta que sí puedas\n"
    "responder (por segmento, producto, mes, tipo de persona o sucursal). No inventes cifras.")

PROMPT_DATOS = {
    auth.ROL_CLIENTE: f"""Eres el agente de datos de Banamex y atiendes a un CLIENTE que ya inició sesión.
Tus herramientas SOLO consultan las cuentas de ESE cliente; no reciben número de cliente.
- Saldo actual -> postgres_consultar_saldos
- Evolución mensual de un producto -> postgres_consultar_historico_saldos (producto: CHEQUES, AHORRO, TDC o C_PERSONAL)
- Movimientos o cuánto gastó en un mes -> postgres_consultar_movimientos (mes en formato YYYYMM, ej. 202605)
- Comparar meses, tendencia de gastos o una gráfica de gastos -> postgres_resumen_mensual_movimientos
  (solo_gastos=true cuando pregunten por gastos)
Si piden una gráfica, trae los datos con la herramienta adecuada y resume las cifras: OTRO agente dibuja la
gráfica, así que nunca digas que no puedes graficar.
Si piden datos de OTRO cliente, de otras personas o totales del banco, responde que por privacidad solo
puedes mostrar información de su propia cuenta. No muestres SQL.
{REGLAS}""",
    auth.ROL_EMPLEADO: f"""Eres el agente de datos de Banamex y atiendes a un EMPLEADO.
USA PRIMERO estas herramientas (no requieren SQL):
- Saldos (total, promedio, clientes, cuentas) -> postgres_saldo_por_grupo(producto, agrupar_por, mes)
  ej. "saldo de tarjetas por segmento a junio" -> producto="TDC", agrupar_por="segmento", mes="202606"
  ej. "saldo por producto en cada mes" -> producto="", agrupar_por="mes,producto"
- Cuántos clientes hay por algo -> postgres_clientes_por_grupo(agrupar_por)
- Movimientos o transacciones -> postgres_movimientos_por_grupo(agrupar_por, producto, mes)
- Ficha de un cliente -> postgres_perfil_cliente. Calidad de datos -> postgres_run_governance_checks.
  Auditoría -> postgres_get_audit_log.
{_INSTRUCCION_SQL}
fec_nac y genero_cte son datos personales RESTRINGIDOS: si los piden, explica que no están disponibles.
Si piden una gráfica, trae los datos agregados: OTRO agente la dibuja; nunca digas que no puedes graficar.
Responde con las cifras y una explicación breve en lenguaje de negocio (sin SQL ni nombres de tablas).
{REGLAS}""",
}

PROMPT_DOCS = {
    auth.ROL_CLIENTE: "documentos PÚBLICOS (aviso de privacidad, LFPDPPP, Ley de Instituciones de Crédito, glosario)",
    auth.ROL_EMPLEADO: "todos los documentos, incluidas la política interna de calidad de datos y el catálogo",
}


def prompt_docs(rol: str) -> str:
    return f"""Eres el agente documental (RAG) de Banamex. Puedes consultar {PROMPT_DOCS[rol]}.
- Usa SIEMPRE governance_search_governance_knowledge antes de responder (puedes llamarla 2 veces con otras palabras).
- Responde SOLO con lo que digan los fragmentos y cita así: (Fuente: archivo, pág. N).
- Si la herramienta responde SIN RESULTADOS o no viene la respuesta, dilo; no completes con conocimiento propio.
{REGLAS}"""


@dataclass
class Respuesta:
    texto: str
    ruta: str = ""
    pasos: list = field(default_factory=list)  # [{agente, herramienta, args, resultado}]
    bloqueada: bool = False
    segundos: float = 0.0
    grafica: dict | None = None  # decisión del Agente de Gráficas (tipo, x, y, color, datos)


REFIERE_AL_PDF = re.compile(
    r"\b(pdf|documento|archivo|contrato|cl[aá]usula\w*|sub[ií]\b|subid[oa]|adjunt[eé]\b|adjunt[oa]\b|adjuntad[oa]|"
    r"cargu[eé]|cargad[oa]|penalizaci\w*|comisi[oó]n\w*|anualidad|cat\b|tasa|moratori\w*|pago m[ií]nimo|"
    r"estado de cuenta|coincid\w*|concilia\w*)",
    re.IGNORECASE)

# Pregunta de seguimiento ("¿y en abril?", "también la de ahorro", "lo mismo para TDC")
SEGUIMIENTO = re.compile(r"^\W*(y|e|tambi[eé]n|igual|lo mismo|ese|esa|eso|esos|esas|ahora|entonces|otra vez|"
                         r"y si|qu[eé] tal)\b", re.IGNORECASE)
# --- Intenciones que NO se dejan al modelo (se resuelven con código) ---
_TERMINO_RESTRINGIDO = re.compile(r"\b(g[eé]nero|sexo|mujer(es)?|hombres?|clientas|femenin\w*|masculin\w*|edad(es)?|"
                                  r"fechas? de nacimiento|nacimiento|cumplea[nñ]os|naci[oó])\b", re.IGNORECASE)
_PIDE_DATO = re.compile(r"cu[aá]nt|lista|muestra|mu[eé]strame|dame|promedio|distribuci|grafic|gr[aá]fica|"
                        r"cu[aá]l(es)? (es|son)|qu[eé] (edad|fecha|g[eé]nero)|desglos|separa|por (g[eé]nero|sexo|edad)",
                        re.IGNORECASE)
_PREGUNTA_NORMATIVA = re.compile(r"pol[ií]tica|ley|norma|regla|dice|establece|clasifica|lfpdppp|aviso", re.IGNORECASE)
_ESCRITURA = re.compile(
    r"\b(borra|borrar|elimina|eliminar|suprime|suprimir|actualiza|actualizar|modifica|modificar|inserta|insertar|"
    r"cambia|cambiar|depura|depurar|corrige|corregir|da de baja|dar de baja|da de alta|dar de alta|crea|crear)\b"
    r"\s+(?:(?:a|al|del|los|las|el|la|un|una|todos|todas|ese|esos|esa|esas|mis|tus)\s+){0,3}"
    r"(clientes?|registros?|cuentas?|saldos?|tablas?|base|datos|movimientos?|filas?|transacciones?|usuarios?)"
    r"|\b(delete|update|insert|drop|truncate)\b", re.IGNORECASE)
_FICHA = re.compile(r"\b(ficha|perfil|informaci[oó]n|datos|detalle|expediente)\b.*?\bcliente\s*(n[uú]mero\s*|"
                    r"no\.?\s*|#\s*)?(\d{1,5})\b", re.IGNORECASE)
_AUDITORIA = re.compile(r"\bauditor[ií]a\b|\bbit[aá]cora\b|registro de (accesos|actividad|acciones)", re.IGNORECASE)
_CALIDAD = re.compile(r"calidad|reglas? (de calidad|dq)|\bdq-?\d|hallazgos?", re.IGNORECASE)
_PIDE_NORMATIVA = re.compile(r"cumpl|ley\b|leyes|norma|pol[ií]tica|lfpdppp|regula|legal|abusiv|derechos?\b|condusef|"
                             r"banxico|cnbv|bcbs|privacidad", re.IGNORECASE)
_PIDE_VERIFICAR = re.compile(r"coincid|cuadr|correct|verific|concilia|compar|registr|sistema|real(es)?\b|diferen|"
                             r"error|igual|revisa", re.IGNORECASE)
_NOMBRES_PRODUCTO = {"TDC": "Tarjeta de crédito", "CHEQUES": "Cheques", "AHORRO": "Ahorro", "C_PERSONAL": "Crédito personal"}


def agent_nombre_producto(cve: str) -> str:
    return _NOMBRES_PRODUCTO.get(cve, cve)


_PIDE_REVISION = re.compile(r"revis|corre|ejecut|eval[uú]a|verific|valida|hallazgo|problema|falla|incumpl|"
                            r"estado|c[oó]mo est", re.IGNORECASE)
_PIDE_POLITICA = re.compile(r"pol[ií]tica|remedia|correg|qu[eé] (dice|establece)|c[oó]mo (se )?(corrig|resuelv|atiend)|"
                            r"responsable|escala|qui[eé]n", re.IGNORECASE)

def pide_dato_restringido(q: str) -> bool:
    return bool(_TERMINO_RESTRINGIDO.search(q) and _PIDE_DATO.search(q) and not _PREGUNTA_NORMATIVA.search(q))


def pide_escritura(q: str) -> bool:
    return bool(_ESCRITURA.search(q) and not _PREGUNTA_NORMATIVA.search(q))


ETIQUETAS = {"num_cte": "Cliente", "tipo_persona": "Tipo de persona", "segmento_cte": "Segmento",
             "fec_alta": "Cliente desde", "cve_sucursal": "Sucursal", "cve_promotor": "Promotor",
             "producto": "Producto", "cuenta": "Cuenta", "saldo_mxn": "Saldo (MXN)", "regla": "Regla",
             "dimension": "Dimensión", "severidad": "Severidad", "descripcion": "Descripción",
             "registros_con_hallazgo": "Registros con hallazgo", "estado": "Estado", "fecha": "Fecha",
             "usuario": "Usuario", "rol": "Rol", "accion": "Acción", "resultado": "Resultado", "detalle": "Detalle"}
VALORES = {"PF": "Persona física", "PM": "Persona moral", "cliente": "Cliente", "empleado": "Colaborador",
           "TDC": "Tarjeta de crédito", "CHEQUES": "Cheques", "AHORRO": "Ahorro", "C_PERSONAL": "Crédito personal"}


def tabla_amigable(md: str) -> str:
    """Convierte las tablas técnicas de las herramientas en tablas legibles (encabezados y valores en español)."""
    salida = []
    for t in charts.extraer_tablas(md):
        cols = [ETIQUETAS.get(c, c.replace("_", " ").capitalize()) for c in t.columnas]
        filas = []
        for f in t.filas:
            celdas = []
            for c, v in zip(t.columnas, f):
                if isinstance(v, float):
                    v = f"${v:,.2f}" if re.search(r"saldo|total|monto|mxn", c) else f"{v:,.0f}"
                celdas.append(VALORES.get(str(v), str(v)))
            filas.append("| " + " | ".join(celdas) + " |")
        salida.append("\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + filas))
    return "\n\n".join(salida)


# Pide contar (no sumar montos) -> la gráfica debe respetar conteos
PIDE_CONTEO = re.compile(r"cu[aá]nt[oa]s\s+(movimientos|transacciones|operaciones|clientes|cuentas|veces)|"
                         r"n[uú]mero de|conteo|cantidad de", re.IGNORECASE)


def _ruta_por_palabras(q: str, hay_pdf: bool) -> str:
    t = q.lower()
    if hay_pdf and re.search(r"\b(pdf|documento|archivo|contrato|este|subí|subi|adjunt)", t):
        return "PDF"
    datos = re.search(r"saldo|gast|movimiento|deb[oe]|cu[aá]nt|total|promedio|sql|tabla|cliente \d|regla|calidad|"
                      r"hallazgo|ficha|auditor|histor|segmento|mes|compra|retiro|pago", t)
    docs = re.search(r"pol[ií]tica|ley|lfpdppp|privacidad|arco|norma|regula|bcbs|cnbv|secreto|qu[eé] es|"
                     r"defin|glosario|responsab|retenci|clasific|contrato|derecho", t)
    if datos and docs:
        return "AMBOS"
    if datos:
        return "DATOS"
    if docs:
        return "DOCUMENTOS"
    return "GENERAL"


class Steward:
    """Una sesión: identidad + servidores MCP propios + agentes. Funciona igual desde CLI o Streamlit."""

    def __init__(self, ident: auth.Identidad, timeout: float = 120):
        self.ident = ident
        self.lector = AgenteLector()  # subagente: lee el PDF y le entrega una ficha al hub
        self.doc: FichaDocumento | None = None
        self.historial: list[tuple[str, str]] = []
        self.ultima_ruta: str | None = None
        self.llm = common.get_llm()
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._listo = threading.Event()
        self._error: BaseException | None = None
        self._stop: asyncio.Event | None = None
        asyncio.run_coroutine_threadsafe(self._mantener_mcp(), self._loop)
        if not self._listo.wait(timeout):
            raise TimeoutError("Los servidores MCP no respondieron. Corre: .\\run.ps1 check")
        if self._error:
            raise self._error
        auth.auditar(ident, "inicio_sesion", True)

    # ---------------------------------------------------------------- MCP
    async def _mantener_mcp(self):
        """Abre los 2 servidores MCP y los mantiene vivos toda la sesión (una sola tarea entra y sale)."""
        try:
            from langchain.agents import create_agent
            from langchain.mcp import MCPAdapter

            env = {**os.environ, **self.ident.env(), "PYTHONIOENCODING": "utf-8"}
            config = {"mcpServers": {
                "postgres": {"command": common.PYTHON, "args": [str(SRC / "mcp_postgres_server.py")],
                             "env": env, "cwd": str(common.ROOT)},
                "governance": {"command": common.PYTHON, "args": [str(SRC / "mcp_governance_server.py")],
                               "env": env, "cwd": str(common.ROOT)},
            }}
            self._stop = asyncio.Event()
            async with MCPAdapter(config) as adapter:
                tools = await adapter.list_tools()
                self.tools_datos = [t for t in tools if t.name.startswith("postgres_")]
                self.tools_docs = [t for t in tools if t.name.startswith("governance_")]
                self.tool_busqueda = next(t for t in self.tools_docs if t.name.endswith("search_governance_knowledge"))
                self.agente_datos = create_agent(self.llm, self.tools_datos, system_prompt=PROMPT_DATOS[self.ident.rol])
                self.agente_docs = create_agent(self.llm, self.tools_docs, system_prompt=prompt_docs(self.ident.rol))
                self._listo.set()
                await self._stop.wait()
        except BaseException as e:  # noqa: BLE001
            self._error = e
            self._listo.set()

    def cerrar(self):
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)

    def _correr(self, coro, timeout: float = 600):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def herramientas(self) -> dict:
        return {"datos": [t.name for t in self.tools_datos], "documentos": [t.name for t in self.tools_docs]}

    # ---------------------------------------------------------------- PDF
    def cargar_pdf(self, nombre: str, contenido: bytes) -> dict:
        self.doc = self.lector.leer(nombre, contenido)
        auth.auditar(self.ident, "subir_pdf", True, documento=nombre, tipo=self.doc.tipo, **self.doc.metricas)
        return {**self.doc.metricas, "tipo": self.doc.tipo, "descripcion": self.doc.descripcion()}

    def quitar_pdf(self) -> None:
        if self.doc is not None:
            auth.auditar(self.ident, "quitar_pdf", True, documento=self.doc.nombre)
        self.lector.olvidar()
        self.doc = None

    # ---------------------------------------------------------------- orquestador
    async def _llm(self, prompt: str) -> str:
        return common.texto_de((await self.llm.ainvoke(prompt)).content).strip()

    async def _rutear(self, q: str) -> str:
        # Regla determinista ANTES del LLM: con un PDF cargado, si la pregunta habla del documento, es PDF.
        # (llama3.1 confundía "¿cumple con la LFPDPPP?" con una pregunta de DOCUMENTOS.)
        if self.doc and REFIERE_AL_PDF.search(q):
            return "PDF"
        seguimiento = bool(self.historial and self.ultima_ruta and
                           (SEGUIMIENTO.search(q) or len(q.split()) <= 4))
        opcion_pdf = ("- PDF: pregunta sobre el documento PDF que el usuario subió (resumir, penalizaciones, "
                      "si cumple una norma).\n") if self.doc else ""
        prompt = f"""Clasifica la pregunta de un usuario de un banco en UNA etiqueta:
- DATOS: saldos, movimientos, gastos, montos, conteos, métricas, SQL, reglas de calidad de datos, ficha de cliente, auditoría.
- DOCUMENTOS: políticas, leyes, privacidad, derechos ARCO, regulación, definiciones, gobierno de datos.
- AMBOS: pide cifras de la base Y además lo que dice una política o norma.
{opcion_pdf}- GENERAL: saludo o qué puedes hacer.
{f"Pregunta anterior (etiqueta {self.ultima_ruta}): {self.historial[-1][0]}" if seguimiento else ""}
Pregunta: {q}
Responde SOLO la etiqueta."""
        try:
            salida = (await self._llm(prompt)).upper()
            for r in RUTAS:
                if r in salida:  # PDF sin documento cargado se convierte en DOCUMENTOS en _ajustar_ruta
                    return self._ajustar_ruta(r, q, seguimiento)
        except Exception:  # noqa: BLE001
            pass
        return self._ajustar_ruta(_ruta_por_palabras(q, self.doc is not None), q, seguimiento)

    def _ajustar_ruta(self, ruta: str, q: str, seguimiento: bool) -> str:
        if ruta == "GENERAL" and seguimiento and self.ultima_ruta not in (None, "GENERAL", "BLOQUEADA"):
            ruta = self.ultima_ruta  # "¿y en abril?" sigue el tema anterior
        if ruta == "PDF" and not self.doc:
            ruta = "DOCUMENTOS"
        return "DATOS" if ruta == "GENERAL" and charts.pide_grafica(q) else ruta

    def _mensajes(self, q: str) -> list[dict]:
        msgs = []
        for u, a in self.historial[-3:]:  # memoria corta para preguntas de seguimiento
            msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a[:1500]}]
        return msgs + [{"role": "user", "content": q}]

    async def _correr_agente(self, nombre: str, agente, q: str, pasos: list) -> str:
        from langchain_core.messages import AIMessage, ToolMessage

        entrada = self._mensajes(q)
        res = await agente.ainvoke({"messages": entrada}, {"recursion_limit": 10})
        nuevos = res["messages"][len(entrada):]
        llamadas = {}
        for m in nuevos:
            if isinstance(m, AIMessage):
                for tc in m.tool_calls or []:
                    llamadas[tc["id"]] = {"agente": nombre, "herramienta": tc["name"], "args": tc["args"]}
            elif isinstance(m, ToolMessage):
                paso = llamadas.get(m.tool_call_id, {"agente": nombre, "herramienta": m.name, "args": {}})
                paso["resultado"] = common.texto_de(m.content)[:2000]
                pasos.append(paso)
        return common.texto_de(res["messages"][-1].content)

    # ------------------------------------------------------------ documentos (hub + subagente lector)
    async def _flujo_documento(self, q: str, pasos: list) -> str:
        """El LECTOR ya extrajo la ficha del PDF. El HUB decide contra qué compararla:
        - normativa (RAG) si se pregunta si cumple / qué dice la ley o la política
        - base de datos si es un estado de cuenta y se pide verificarlo
        - solo el documento para preguntas sobre su contenido."""
        f = self.lector.ficha
        pasos.append({"agente": "lector", "herramienta": "ficha_documento", "args": {"tipo": f.tipo},
                      "resultado": f.descripcion()})
        if _PIDE_NORMATIVA.search(q):
            return await self._documento_vs_normativa(q, pasos)
        if f.tipo == "estado_de_cuenta" and _PIDE_VERIFICAR.search(q):
            return await self._documento_vs_base(q, pasos)
        return await self._responder_con_documento(q, pasos)

    async def _responder_con_documento(self, q: str, pasos: list) -> str:
        fragmentos = self.lector.fragmentos_para(q)
        pasos.append({"agente": "lector", "herramienta": "fragmentos_relevantes", "args": {}, "resultado": fragmentos[:2000]})
        return await self._llm(f"""Responde la pregunta del usuario usando SOLO el contenido de su documento.
DOCUMENTO "{self.doc.nombre}" ({self.doc.descripcion()}):
<<<
{fragmentos}
>>>
Pregunta: {q}
Cita la cláusula o el dato del documento. Si el documento no lo dice, dilo. No inventes.
{REGLAS}""")

    async def _documento_vs_normativa(self, q: str, pasos: list) -> str:
        fragmentos = self.lector.fragmentos_para(q)
        normativa, vistos = [], set()
        for consulta in self.lector.temas_para_normativa(q):  # una búsqueda por cláusula relevante
            r = await self._llamar("search_governance_knowledge", {"query": consulta}, "documentos", pasos)
            for bloque in r.split("\n\n"):
                clave = bloque[:160]
                if bloque.strip() and not bloque.startswith("SIN RESULTADOS") and clave not in vistos:
                    vistos.add(clave)
                    normativa.append(bloque)
        return await self._llm(f"""Eres analista de cumplimiento. Compara el documento del usuario con la normativa.
DOCUMENTO "{self.doc.nombre}" ({self.doc.descripcion()}) — partes relevantes:
<<<
{fragmentos}
>>>
NORMATIVA Y POLÍTICAS DE REFERENCIA:
<<<
{chr(10).join(normativa[:8]) or 'SIN RESULTADOS'}
>>>
Pregunta: {q}
Para cada cláusula relevante indica si coincide, falta algo o contradice la normativa, citando la cláusula del
documento y (Fuente: archivo, pág. N) de la normativa. Si la normativa no cubre un punto, dilo. No inventes.
{REGLAS}""")

    async def _documento_vs_base(self, q: str, pasos: list) -> str:
        """Concilia un estado de cuenta contra los registros del banco (determinista, sin modelo)."""
        e = self.doc.estado_cuenta
        if not e or not e["saldos"] or not e["periodo"]:
            return await self._responder_con_documento(q, pasos)
        cte = e["num_cte"]
        if self.ident.es_cliente and cte != self.ident.num_cte:
            auth.auditar(self.ident, "comparacion_denegada", False, documento=self.doc.nombre, num_cte_documento=cte)
            return (f"El estado de cuenta corresponde a otro cliente. Solo puedo compararlo con la información "
                    f"de tu propia cuenta.")
        if self.ident.es_cliente:
            hist = await self._llamar("consultar_historico_saldos", {}, "datos", pasos)
            movs_txt = await self._llamar("consultar_movimientos", {"mes": e["periodo"]}, "datos", pasos)
            tablas_movs = charts.extraer_tablas(movs_txt)
            resumen = next((t for t in tablas_movs if "tipo" in t.columnas and "total_mxn" in t.columnas), None)
            filas_mov = [] if resumen is None else [
                (r[resumen.columnas.index("tipo")], r[resumen.columnas.index("total_mxn")]) for r in resumen.filas]
        else:
            r = await self._llamar("historico_cliente", {"num_cte": cte}, "datos", pasos)
            hist, movs_txt = r.split("MOVIMIENTOS")
            t = (charts.extraer_tablas(movs_txt) or [None])[0]
            filas_mov = [] if t is None else [(f[t.columnas.index("tipo")], f[t.columnas.index("total_mxn")])
                                               for f in t.filas if str(f[t.columnas.index("mes")]) == e["periodo"]]
        th = charts.extraer_tablas(hist)[0]
        ix = {c: th.columnas.index(c) for c in ("fecha_corte", "producto", "saldo_apertura", "saldo_mes")}
        banco = {f[ix["producto"]]: (f[ix["saldo_apertura"]], f[ix["saldo_mes"]])
                 for f in th.filas if str(f[ix["fecha_corte"]]).startswith(e["periodo"])}
        filas, diferencias = [], []

        def fila(concepto, doc_val, bd_val):
            if bd_val is None:
                filas.append(f"| {concepto} | ${doc_val:,.2f} | Sin registro | — | No encontrado |")
                diferencias.append(concepto)
                return
            dif = doc_val - bd_val
            ok = abs(dif) <= 0.01
            filas.append(f"| {concepto} | ${doc_val:,.2f} | ${bd_val:,.2f} | ${dif:,.2f} | {'Coincide' if ok else 'Diferente'} |")
            if not ok:
                diferencias.append(concepto)

        for s_ in e["saldos"]:
            ap, ci = banco.get(s_["producto"], (None, None))
            nombre = agent_nombre_producto(s_["producto"])
            fila(f"{nombre}: saldo inicial", s_["saldo_inicial"], ap)
            fila(f"{nombre}: saldo al corte", s_["saldo_corte"], ci)
        if e.get("total_cargos") is not None and filas_mov:
            fila("Total de cargos", e["total_cargos"],
                 sum(v for t_, v in filas_mov if t_ in ("COMPRAS", "RETIRO", "DISPOSICIONES")))
            fila("Total de abonos", e["total_abonos"] or 0.0, sum(v for t_, v in filas_mov if t_ in ("DEPOSITO", "PAGOS")))
        mes = f"{e['periodo'][4:]}/{e['periodo'][:4]}"
        encabezado = (f"Revisé el estado de cuenta de {mes} contra los registros del banco: "
                      + ("**todos los conceptos coinciden**." if not diferencias else
                         f"**{len(diferencias)} concepto(s) no coinciden**: {', '.join(diferencias)}. "
                         "Te recomendamos aclararlo en sucursal o en la Unidad Especializada de Atención."))
        tabla = "| Concepto | Estado de cuenta | Registros del banco | Diferencia | Resultado |\n|---|---|---|---|---|\n"
        auth.auditar(self.ident, "conciliacion_estado_cuenta", True, documento=self.doc.nombre,
                     periodo=e["periodo"], diferencias=len(diferencias))
        return f"{encabezado}\n\n{tabla}" + "\n".join(filas)

    def _tool(self, nombre: str):
        return next(t for t in self.tools_datos + self.tools_docs if t.name.endswith(nombre))

    async def _llamar(self, nombre: str, args: dict, agente: str, pasos: list) -> str:
        t = self._tool(nombre)
        r = common.texto_de(await t.ainvoke(args))
        pasos.append({"agente": agente, "herramienta": t.name, "args": args, "resultado": r[:2000]})
        return r

    async def _intencion_directa(self, q: str, pasos: list) -> tuple[str, str] | None:
        """Colaborador: ficha, auditoría y calidad se resuelven con la herramienta exacta (sin que el modelo
        decida), porque llama3.1 se negaba a dar fichas e inventaba hallazgos y eventos de auditoría."""
        if self.ident.es_cliente:
            return None
        m = _FICHA.search(q)
        if m:
            r = await self._llamar("perfil_cliente", {"num_cte": int(m.group(3))}, "datos", pasos)
            if "(sin filas)" in r.split("SALDOS")[0]:
                return f"No existe el cliente {m.group(3)}.", "DATOS"
            ficha, saldos = r.split("SALDOS AL 20260630")
            return (f"**Ficha del cliente {m.group(3)}**\n\n{tabla_amigable(ficha)}\n\n"
                    f"**Saldos al 30 de junio de 2026**\n\n{tabla_amigable(saldos)}\n\n"
                    "Por política, la fecha de nacimiento y el género no se muestran."), "DATOS"
        if _AUDITORIA.search(q):
            r = await self._llamar("get_audit_log", {"n": 15}, "datos", pasos)
            return f"**Últimas acciones registradas**\n\n{tabla_amigable(r)}", "DATOS"
        if _CALIDAD.search(q) and _PIDE_REVISION.search(q):
            r = await self._llamar("run_governance_checks", {}, "datos", pasos)
            tabla = charts.extraer_tablas(r)[0]
            con = [f for f in tabla.filas if f[-1] == "Con hallazgos"]
            resumen = (f"Se evaluaron {len(tabla.filas)} reglas de calidad; **{len(con)} tienen hallazgos**: "
                       + ", ".join(f"{f[0]} ({f[3].lower()})" for f in con) + "." if con
                       else f"Se evaluaron {len(tabla.filas)} reglas de calidad y todas se cumplen.")
            texto = f"{resumen}\n\n{tabla_amigable(r)}"
            if con and _PIDE_POLITICA.search(q):
                texto += "\n\n" + await self._politica_para(con, q, pasos)
                return texto, "AMBOS"
            return texto, "DATOS"
        return None

    async def _politica_para(self, hallazgos: list, q: str, pasos: list) -> str:
        """Busca en la política lo que aplica a cada regla con hallazgos y redacta SOLO con eso."""
        fragmentos = []
        for f in hallazgos[:4]:
            r = await self._llamar("search_governance_knowledge",
                                   {"query": f"remediación {f[0]} {f[3]} política de calidad"}, "documentos", pasos)
            if not r.startswith("SIN RESULTADOS"):
                fragmentos.append(r)
        r = await self._llamar("search_governance_knowledge",
                               {"query": "roles responsabilidades escalamiento hallazgo severidad Alta Data Owner"},
                               "documentos", pasos)
        fragmentos.append(r)
        reglas = "\n".join(f"- {f[0]} (dimensión {f[1]}, severidad {f[2]}): {f[3]} -> {f[4]:,.0f} registros"
                           for f in hallazgos)
        return await self._llm(f"""Eres analista de gobierno de datos. Reglas de calidad con hallazgos:
{reglas}

FRAGMENTOS DE LA POLÍTICA INTERNA Y NORMATIVA:
<<<
{chr(10).join(fragmentos)}
>>>

Pregunta: {q}
Para cada regla con hallazgos, explica qué indica la política sobre cómo atenderla y quién es responsable,
usando EXCLUSIVAMENTE los fragmentos y citando (Fuente: archivo, pág. N). Si los fragmentos no mencionan una regla,
escribe "La política no especifica la remediación para esta regla". No inventes pasos, plazos ni áreas.
{REGLAS}""")

    async def _preguntar(self, q: str) -> Respuesta:
        t0 = time.time()
        pasos: list = []
        directa = await self._intencion_directa(q, pasos)
        if directa:
            texto, ruta = directa
            self.ultima_ruta = ruta
            return Respuesta(texto, ruta, pasos, segundos=round(time.time() - t0, 1))
        ruta = await self._rutear(q)
        self.ultima_ruta = ruta
        if ruta == "DATOS":
            texto = await self._correr_agente("datos", self.agente_datos, q, pasos)
        elif ruta == "DOCUMENTOS":
            texto = await self._correr_agente("documentos", self.agente_docs, q, pasos)
        elif ruta == "AMBOS":
            r_datos = await self._correr_agente("datos", self.agente_datos, q, pasos)
            r_docs = await self._correr_agente("documentos", self.agente_docs, q, pasos)
            texto = await self._llm(f"""Combina estas dos respuestas en UNA respuesta final para el usuario.
Pregunta: {q}
DATOS (cifras de la base):
{r_datos}
DOCUMENTOS (políticas/normas con citas):
{r_docs}
Primero los hallazgos con cifras exactas y luego lo que dice la norma con sus citas. No agregues nada nuevo.
{REGLAS}""")
        elif ruta == "PDF":
            texto = await self._flujo_documento(q, pasos)
        else:
            alcance = ("consultar tus saldos, movimientos e históricos, resolver dudas sobre privacidad y leyes, "
                       "y analizar un PDF que subas") if self.ident.es_cliente else \
                      ("consultar la base con SQL de solo lectura, fichas de clientes, reglas de calidad, auditoría, "
                       "políticas internas y normativa, y analizar PDFs")
            texto = await self._llm(f"Eres el asistente Data Steward de Banamex. Puedes {alcance}. "
                                    f"Responde breve y amable a: {q}")
        grafica = None
        if ruta in ("DATOS", "AMBOS") and charts.pide_grafica(q):
            grafica = await self._graficar(q, pasos)
        return Respuesta(texto, ruta, pasos, segundos=round(time.time() - t0, 1), grafica=grafica)

    async def _graficar(self, q: str, pasos: list) -> dict | None:
        """Agente de Gráficas: usa las tablas que regresó el Agente de Datos (no vuelve a consultar la BD)."""
        tablas = [t for p in pasos if p["agente"] == "datos" and not p.get("resultado", "").startswith("ERROR")
                  for t in charts.extraer_tablas(p.get("resultado", ""), p["herramienta"])]
        g = await charts.elegir_grafica(self.llm, q, tablas)
        if g is None:
            pasos.append({"agente": "graficas", "herramienta": "sin_grafica", "args": {},
                          "resultado": "No hubo una tabla con valores numéricos para graficar."})
            return None
        pasos.append({"agente": "graficas", "herramienta": f"grafica_{g.tipo}",
                      "args": {"x": g.x, "y": g.y, "color": g.color, "decidido_por": g.decidido_por},
                      "resultado": f"{g.titulo} ({len(g.tabla.filas)} filas de {g.tabla.origen})"})
        auth.auditar(self.ident, "grafica", True, tipo=g.tipo, origen=g.tabla.origen)
        return g.a_dict()

    def preguntar(self, q: str) -> Respuesta:
        patron = auth.detectar_inyeccion(q)
        if patron:
            auth.auditar(self.ident, "entrada_bloqueada", False, patron=patron, pregunta=q[:300])
            return Respuesta("No puedo ayudar con esa solicitud. Pregúntame sobre "
                             + ("tus cuentas o documentos públicos del banco." if self.ident.es_cliente
                                else "datos del banco (sin datos personales) o documentos de gobierno de datos."),
                             "BLOQUEADA", bloqueada=True)
        if pide_dato_restringido(q):
            auth.auditar(self.ident, "dato_restringido", False, pregunta=q[:300])
            return Respuesta("Esa información corresponde a datos personales clasificados como restringidos "
                             "(por ejemplo, género o fecha de nacimiento) y no está disponible en este canal, "
                             "conforme a la política de gobierno de datos.", "RESTRINGIDA", bloqueada=True)
        if pide_escritura(q):
            auth.auditar(self.ident, "escritura_rechazada", False, pregunta=q[:300])
            return Respuesta("Este asistente es de solo consulta: no puede modificar, borrar ni crear información. "
                             "Cualquier cambio debe solicitarse al área responsable del dato (Data Owner) "
                             "por los canales autorizados.", "SOLO_LECTURA", bloqueada=True)
        try:
            r = self._correr(asyncio.wait_for(self._preguntar(q), timeout=TIEMPO_MAXIMO))
        except (asyncio.TimeoutError, TimeoutError):
            auth.auditar(self.ident, "tiempo_agotado", False, pregunta=q[:300], segundos=TIEMPO_MAXIMO)
            return Respuesta("No fue posible atender tu consulta en este momento. Intenta reformularla "
                             "de forma más específica.", "TIEMPO", segundos=TIEMPO_MAXIMO)
        r.texto = auth.filtrar_salida(r.texto or "No obtuve respuesta del modelo; intenta reformular.")
        self.historial.append((q, r.texto))
        auth.auditar(self.ident, "respuesta", True, pregunta=q[:300], ruta=r.ruta,
                     herramientas=[p["herramienta"] for p in r.pasos])
        return r


# ==================================================================== CLI
def login_interactivo(a) -> auth.Identidad:
    if a.cliente:
        pin = os.getenv("STEWARD_PIN") or getpass.getpass("PIN (demo 1234): ")
        ident = auth.login_cliente(a.cliente, pin)
    else:
        pwd = os.getenv("STEWARD_PASSWORD") or getpass.getpass("Contraseña: ")
        ident = auth.login_empleado(a.user, pwd)
    if not ident:
        raise SystemExit("Credenciales inválidas")
    return ident


def imprimir(r: Respuesta, traza: bool):
    print(f"\n[{r.ruta} · {r.segundos}s]\n{r.texto}\n")
    if r.grafica:
        carpeta = common.ROOT / "logs" / "graficas"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = charts.guardar_html(r.grafica, carpeta / f"grafica_{time.strftime('%Y%m%d_%H%M%S')}.html")
        print(f"Gráfica ({r.grafica['tipo']}) guardada en: {ruta}\n")
    if traza:
        for p in r.pasos:
            print(f"  -> {p['agente']}: {p['herramienta']}({json.dumps(p['args'], ensure_ascii=False)[:200]})")
            print("     " + p.get("resultado", "")[:400].replace("\n", "\n     "))
        print()


DEMO = {
    auth.ROL_CLIENTE: ["¿Cuál es mi saldo actual?", "¿Cuánto gasté en mayo de 2026?",
                       "Haz una gráfica comparando mis gastos de cada mes",
                       "¿Qué derechos tengo sobre mis datos personales?", "Muéstrame el saldo del cliente 43"],
    auth.ROL_EMPLEADO: ["¿Cuál es el saldo total de TDC por segmento al corte de junio 2026?",
                        "Dame la ficha del cliente 42", "Corre las reglas de calidad de datos",
                        "Grafica el saldo total de TDC por segmento al corte de junio 2026",
                        "¿Qué dice la política interna sobre quién corrige los hallazgos de calidad?"],
}


def main():
    ap = argparse.ArgumentParser(description="Data Steward Banamex (CLI)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--cliente", type=int, help="número de cliente 1-5000")
    g.add_argument("--user", help="usuario empleado")
    ap.add_argument("-i", "--interactivo", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--pdf")
    ap.add_argument("--sin-traza", action="store_true")
    ap.add_argument("pregunta", nargs="*")
    a = ap.parse_args()

    s = Steward(login_interactivo(a))
    print(f"Sesión: {s.ident.nombre} ({s.ident.rol}) · LLM {common.LLM_PROVIDER}:{common.LLM_MODEL}")
    print("Herramientas MCP:", s.herramientas())
    if a.pdf:
        print("PDF:", s.cargar_pdf(Path(a.pdf).name, Path(a.pdf).read_bytes()))
    try:
        preguntas = DEMO[s.ident.rol] if a.demo else ([" ".join(a.pregunta)] if a.pregunta else [])
        for q in preguntas:
            print(f"\nPregunta: {q}")
            imprimir(s.preguntar(q), not a.sin_traza)
        if a.interactivo:
            while True:
                try:
                    q = input("Tú> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if q.lower() in {"salir", "exit"}:
                    break
                if q:
                    imprimir(s.preguntar(q), not a.sin_traza)
    finally:
        s.cerrar()


if __name__ == "__main__":
    main()