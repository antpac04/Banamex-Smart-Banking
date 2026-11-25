"""Interfaz de usuario.   .\\run.ps1 web
Interfaz para clientes y colaboradores: no muestra detalles técnicos.
Para depurar (ver ruta, herramientas y SQL):  $env:STEWARD_DEBUG="1"; .\\run.ps1 web
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

import auth  # noqa: E402
import charts  # noqa: E402
from agent import Steward  # noqa: E402

DEBUG = os.getenv("STEWARD_DEBUG") == "1"
AZUL, ROJO = "#00205B", "#C8102E"
PALETA = [AZUL, ROJO, "#3A6EA5", "#8C96A3", "#9DB7D5", "#7A0A1C"]

st.set_page_config(page_title="Banamex | Asistente", layout="centered", initial_sidebar_state="expanded")

st.markdown(f"""
<style>
  #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], .stDeployButton,
  [data-testid="stStatusWidget"] {{ display: none !important; }}
  header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
  .block-container {{ padding-top: 1.6rem; max-width: 860px; }}

  .barra {{ background: {AZUL}; color: #fff; padding: 16px 24px; border-bottom: 4px solid {ROJO};
           border-radius: 4px; display: flex; justify-content: space-between; align-items: center;
           margin-bottom: 1.4rem; }}
  .barra .marca {{ font-size: 1.35rem; font-weight: 700; letter-spacing: .4px; }}
  .barra .sub {{ font-size: .85rem; opacity: .85; }}

  h1, h2, h3 {{ color: {AZUL}; font-weight: 600; }}
  .titulo {{ color: {AZUL}; font-size: 1.15rem; font-weight: 600; margin: .2rem 0 .8rem 0; }}
  .pie {{ color: #8C96A3; font-size: .72rem; text-align: center; margin-top: 2.5rem; }}

  section[data-testid="stSidebar"] {{ background: #F4F6F9; border-right: 1px solid #E1E5EB; }}
  section[data-testid="stSidebar"] .titulo {{ font-size: .95rem; margin-top: .6rem; }}

  .stButton > button, .stFormSubmitButton > button {{ border-radius: 4px; border: 1px solid {AZUL};
           color: {AZUL}; background: #fff; font-weight: 500; }}
  .stButton > button:hover, .stFormSubmitButton > button:hover {{ background: {AZUL}; color: #fff;
           border-color: {AZUL}; }}
  .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"],
  [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
           background: {ROJO}; border-color: {ROJO}; color: #fff; }}
  section[data-testid="stSidebar"] .stButton > button {{ text-align: left; justify-content: flex-start;
           font-size: .85rem; border-color: #C9D1DC; }}

  .stTabs [data-baseweb="tab"] {{ font-weight: 600; color: #4B5563; }}
  .stTabs [aria-selected="true"] {{ color: {AZUL}; }}
  .stTabs [data-baseweb="tab-highlight"] {{ background-color: {ROJO}; }}
  [data-testid="stChatMessage"] {{ background: #fff; border: 1px solid #E5E9F0; border-radius: 6px; }}
</style>
""", unsafe_allow_html=True)

SUGERENCIAS = {
    auth.ROL_CLIENTE: ["¿Cuál es mi saldo actual?", "¿Cuánto gasté en mayo?",
                       "Compara mis gastos de cada mes en una gráfica", "¿Cómo ha cambiado la deuda de mi tarjeta?",
                       "¿Qué derechos tengo sobre mis datos personales?"],
    auth.ROL_EMPLEADO: ["Saldo total de tarjetas de crédito por segmento a junio 2026",
                        "Proporción de clientes por segmento en una gráfica",
                        "Saldo total por producto en cada mes de 2026", "Revisa la calidad de los datos",
                        "¿Qué establece la política interna sobre la corrección de hallazgos?"],
}

# Preguntas sugeridas según el tipo de documento que reconoció el lector
SUGERENCIAS_DOC = {
    "estado_de_cuenta": ["¿Mi estado de cuenta coincide con los registros del banco?", "¿Cuál es mi pago mínimo?"],
    "contrato": ["¿Qué comisiones y penalizaciones tiene el contrato?", "¿Este contrato cumple con la LFPDPPP?"],
    "acuerdo_datos": ["¿Este acuerdo cumple con nuestra política de datos?", "¿Qué datos se comparten y con quién?"],
    "otro": ["¿De qué trata este documento?"],
}

# Nombres internos que nunca deben verse en la interfaz.
# Solo se BORRA la oración si menciona una herramienta (postgres_..., governance_...); los demás términos
# se REEMPLAZAN para no perder contenido útil (antes se borraban oraciones con la respuesta).
_HERRAMIENTA = re.compile(r"\b(postgres|governance)_[a-z_]+\b", re.IGNORECASE)
_REEMPLAZOS = [
    (r"\s*\((RAG|MCP|SQL|LLM)\)", ""),
    (r"\b(los |las )?(fragmentos|resultados) (del|de la) (RAG|base documental|base vectorial)\b", "la normativa"),
    (r"\b(el |la )?(RAG|base vectorial|Pinecone)\b", "la normativa"),
    (r"\b(la |una )?consulta SQL\b", "la consulta"),
    (r"\b(el |un )?(agente|orquestador|LLM|Ollama|MCP)( de (datos|documentos|gr[aá]ficas))?\b", "el asistente"),
]


def limpiar(texto: str) -> str:
    sin_codigo = re.sub(r"```.*?```", "", texto, flags=re.DOTALL)
    lineas = []
    for linea in sin_codigo.split("\n"):
        if _HERRAMIENTA.search(linea) and not linea.lstrip().startswith("|"):
            linea = " ".join(o for o in re.split(r"(?<=[.!?])\s+", linea) if not _HERRAMIENTA.search(o))
        for patron, nuevo in _REEMPLAZOS:
            linea = re.sub(patron, nuevo, linea, flags=re.IGNORECASE)
        lineas.append(linea)
    limpio = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()
    return limpio or texto


def barra(subtitulo: str = ""):
    st.markdown(f'<div class="barra"><span class="marca">Banamex</span><span class="sub">{subtitulo}</span></div>',
                unsafe_allow_html=True)


def pie():
    st.markdown('<div class="pie">Prototipo académico con información ficticia.</div>', unsafe_allow_html=True)


def estilo_grafica(fig):
    fig.update_layout(colorway=PALETA, piecolorway=PALETA, plot_bgcolor="#fff", paper_bgcolor="#fff",
                      font=dict(color="#1F2937", size=12), title_font=dict(color=AZUL, size=15))
    fig.update_xaxes(showgrid=False, linecolor="#C9D1DC")
    fig.update_yaxes(gridcolor="#EEF1F5", linecolor="#C9D1DC")
    for tr in fig.data:  # px fija colores por traza; se reasignan con la paleta institucional
        if tr.type in ("bar", "scatter", "histogram") and not getattr(tr.marker, "colors", None):
            idx = list(fig.data).index(tr)
            tr.marker.color = PALETA[idx % len(PALETA)]
            if tr.type == "scatter":
                tr.line.color = PALETA[idx % len(PALETA)]
        if tr.type == "pie":
            tr.marker.colors = PALETA
        if tr.type == "indicator":
            tr.number.font.color = AZUL
            tr.title.font.color = "#4B5563"
    return fig


# ------------------------------------------------------------------ acceso
def iniciar_sesion(ident):
    if not ident:
        st.error("Los datos de acceso son incorrectos.")
        return
    try:
        with st.spinner("Ingresando..."):
            st.session_state.steward = Steward(ident)
        st.session_state.chat = []
        st.rerun()
    except Exception:  # noqa: BLE001
        st.error("El servicio no está disponible en este momento. Intenta más tarde.")


def pantalla_acceso():
    barra("Asistente de información")
    st.markdown('<div class="titulo">Inicia sesión</div>', unsafe_allow_html=True)
    tab_cliente, tab_colaborador = st.tabs(["Clientes", "Colaboradores"])
    with tab_cliente, st.form("acceso_cliente"):
        num = st.number_input("Número de cliente", min_value=1, max_value=5000, value=None, step=1,
                              placeholder="Ej. 42")
        nip = st.text_input("NIP", type="password", max_chars=6)
        if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
            iniciar_sesion(auth.login_cliente(int(num), nip) if num else None)
    with tab_colaborador, st.form("acceso_colaborador"):
        usuario = st.text_input("Usuario")
        pwd = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
            iniciar_sesion(auth.login_empleado(usuario.strip(), pwd))
    pie()


# ------------------------------------------------------------------ conversación
def mostrar_grafica(g, clave):
    if not g:
        return
    try:
        st.plotly_chart(estilo_grafica(charts.figura(g)), use_container_width=True, key=clave,
                        config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
        if g.get("aviso"):
            st.caption(g["aviso"])
    except Exception:  # noqa: BLE001
        pass


def mostrar_detalle(r):
    """Solo con STEWARD_DEBUG=1."""
    if not (DEBUG and r):
        return
    with st.expander("Detalle técnico"):
        st.caption(f"Ruta: {r['ruta']} · {r['segundos']} s")
        for p in r["pasos"]:
            st.markdown(f"`{p['agente']}` → `{p['herramienta']}`")
            st.code(p.get("resultado", "")[:1500])


def pantalla_chat():
    s: Steward = st.session_state.steward
    es_cliente = s.ident.es_cliente
    nombre = f"Cliente {s.ident.num_cte}" if es_cliente else s.ident.nombre.split(" (")[0]

    with st.sidebar:
        st.markdown(f'<div class="titulo">{nombre}</div>', unsafe_allow_html=True)
        st.caption("Banca personal" if es_cliente else "Colaborador")
        st.markdown('<div class="titulo">Consultar un documento</div>', unsafe_allow_html=True)
        pdf = st.file_uploader("Adjunta un PDF (contrato, estado de cuenta)", type=["pdf"],
                               label_visibility="collapsed")
        if pdf is None and st.session_state.get("pdf"):  # el usuario quitó el documento
            s.quitar_pdf()
            st.session_state.pdf = None
        if pdf and st.session_state.get("pdf") != pdf.name:
            try:
                info = s.cargar_pdf(pdf.name, pdf.getvalue())
                st.session_state.pdf = pdf.name
                st.session_state.pdf_info = info
            except Exception:  # noqa: BLE001
                s.quitar_pdf()
                st.session_state.pdf = None
                st.error("No fue posible leer el documento.")
        if st.session_state.get("pdf"):
            info = st.session_state.get("pdf_info") or {}
            st.caption(f"Documento disponible: {st.session_state.pdf}"
                       + (f" ({info['descripcion']})" if info.get("descripcion") else ""))
            for i, e in enumerate(SUGERENCIAS_DOC.get(info.get("tipo"), SUGERENCIAS_DOC["otro"])):
                if st.button(e, key=f"doc{i}", use_container_width=True):
                    st.session_state.pendiente = e
        st.markdown('<div class="titulo">Preguntas frecuentes</div>', unsafe_allow_html=True)
        for i, e in enumerate(SUGERENCIAS[s.ident.rol]):
            if st.button(e, key=f"sug{i}", use_container_width=True):
                st.session_state.pendiente = e
        st.divider()
        if st.button("Cerrar sesión", use_container_width=True):
            s.cerrar()
            st.session_state.clear()
            st.rerun()

    barra(nombre)
    if not st.session_state.chat:
        st.markdown(f'<div class="titulo">¿En qué te podemos ayudar?</div>', unsafe_allow_html=True)
        st.caption("Consulta tus saldos, movimientos y documentos." if es_cliente
                   else "Consulta indicadores, información de clientes, calidad de datos y políticas.")

    for i, m in enumerate(st.session_state.chat):
        with st.chat_message(m["rol"]):
            st.markdown(m["texto"])
            if m.get("r"):
                mostrar_grafica(m["r"].get("grafica"), f"g{i}")
                mostrar_detalle(m["r"])

    q = st.chat_input("Escribe tu consulta") or st.session_state.pop("pendiente", None)
    if q:
        st.session_state.chat.append({"rol": "user", "texto": q})
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            datos = None
            with st.spinner(""):
                try:
                    r = s.preguntar(q)
                    texto = limpiar(r.texto)
                    datos = {"ruta": r.ruta, "pasos": r.pasos, "segundos": r.segundos, "grafica": r.grafica}
                except Exception:  # noqa: BLE001
                    texto = "No fue posible atender tu consulta en este momento. Intenta de nuevo."
            st.markdown(texto)
            if datos:
                mostrar_grafica(datos["grafica"], f"g{len(st.session_state.chat)}")
                mostrar_detalle(datos)
        st.session_state.chat.append({"rol": "assistant", "texto": texto, "r": datos})
    pie()


if "steward" in st.session_state:
    pantalla_chat()
else:
    pantalla_acceso()