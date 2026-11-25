"""Agente de Gráficas: elige UNO de 5 tipos de gráfica según la pregunta y los datos, y la dibuja con Plotly.

Tipos (pensados para las preguntas reales de clientes y colaboradores):
  barras            comparar una cifra entre categorías        "saldo por segmento", "gasto por tipo"
  barras_agrupadas  dos categorías a la vez                    "gasto por mes y por tipo", "saldo por producto y segmento"
  lineas            evolución en el tiempo (2+ periodos)       "¿cómo ha cambiado mi deuda?", "saldo mes a mes"
  pastel            proporción de un total (máx. 8 partes)     "proporción de clientes por segmento"
  indicador         una sola cifra destacada                   "saldo total de TDC a junio"

Orden de decisión (determinista; el modelo solo sugiere):
  1. Tipo pedido EXPLÍCITAMENTE por el usuario ("de pastel", "de barras", "de líneas")  <- siempre gana si es posible
  2. Sugerencia del modelo (JSON), si es válida
  3. Reglas según la forma de los datos
Después se normaliza: se ignoran columnas constantes (p. ej. una sola fecha de corte), se elige la métrica
correcta (total vs. promedio vs. conteo) y, si el tipo pedido no es posible, se usa el más cercano con un aviso.
"""
import json
import re
from dataclasses import dataclass, field

TIPOS = {
    "barras": "comparar una cifra entre categorías",
    "barras_agrupadas": "comparar dos categorías a la vez (necesita columna de serie/color)",
    "lineas": "evolución en el tiempo con 2 o más periodos",
    "pastel": "proporción de un total, máximo 8 partes",
    "indicador": "una sola cifra destacada (una fila de resultado)",
}

PIDE_GRAFICA = re.compile(r"gr[aá]fic|chart|visualiz|plot|diagrama|dib[uú]ja|histograma|pastel|pay\b|pie\b|dona|"
                          r"circular|barras|l[ií]neas?\b|l[ií]nea de tiempo|tendencia|evoluci[oó]n|compar", re.IGNORECASE)
_TIPO_PEDIDO = [
    ("pastel", re.compile(r"pastel|\bpay\b|\bpie\b|\bdona\b|circular", re.IGNORECASE)),
    ("barras_agrupadas", re.compile(r"barras? (agrupad|apilad)|agrupad", re.IGNORECASE)),
    ("lineas", re.compile(r"\bl[ií]neas?\b|lineal|l[ií]nea de tiempo", re.IGNORECASE)),
    ("barras", re.compile(r"\bbarras?\b|columnas", re.IGNORECASE)),
    ("dispersion", re.compile(r"dispersi[oó]n|scatter|de puntos|histograma", re.IGNORECASE)),
]
_NOMBRE_TIEMPO = re.compile(r"^(mes|fecha|corte|periodo|anio|año|dia|día)", re.IGNORECASE)
_VALOR_FECHA = re.compile(r"20\d{2}-?(0[1-9]|1[0-2])(-?\d{2})?")


def pide_grafica(pregunta: str) -> bool:
    return bool(PIDE_GRAFICA.search(pregunta))


def tipo_pedido(pregunta: str) -> str | None:
    for tipo, rx in _TIPO_PEDIDO:
        if rx.search(pregunta):
            return tipo
    return None


@dataclass
class Tabla:
    columnas: list[str]
    filas: list[list]
    origen: str = ""

    def _col(self, c):
        i = self.columnas.index(c)
        return [f[i] for f in self.filas]

    def numericas(self) -> list[str]:
        return [c for i, c in enumerate(self.columnas)
                if self.filas and all(isinstance(f[i], (int, float)) for f in self.filas if f[i] not in (None, ""))]

    def categoricas(self) -> list[str]:
        num = set(self.numericas())
        return [c for c in self.columnas if c not in num]

    def constantes(self) -> list[str]:
        return [c for c in self.categoricas() if len(set(map(str, self._col(c)))) <= 1 and len(self.filas) > 1]

    def temporales(self) -> list[str]:
        out = []
        for c in self.categoricas():
            if _NOMBRE_TIEMPO.search(c) or all(_VALOR_FECHA.fullmatch(str(v)) for v in self._col(c)):
                out.append(c)
        return out

    def dimensiones(self) -> list[str]:
        """Categorías útiles para un eje: varían entre filas y no son identificadores enmascarados."""
        dims = []
        for c in self.categoricas():
            if c in self.constantes() or all(str(v).startswith("****") for v in self._col(c)):
                continue
            # descarta columnas que solo repiten a otra ya elegida (p. ej. descripcion <-> producto)
            if any(len(set(zip(map(str, self._col(d)), map(str, self._col(c))))) == len(set(map(str, self._col(d))))
                   == len(set(map(str, self._col(c)))) for d in dims):
                continue
            dims.append(c)
        return dims

    def resumen(self) -> str:
        return f"columnas={self.columnas} filas={len(self.filas)} ejemplo={self.filas[:3]}"


@dataclass
class Grafica:
    tipo: str
    titulo: str
    x: str | None
    y: str
    color: str | None = None
    tabla: Tabla = field(default=None, repr=False)
    decidido_por: str = "llm"  # usuario | llm | reglas
    aviso: str = ""            # se muestra al usuario si no se pudo hacer exactamente lo pedido

    def a_dict(self) -> dict:
        return {"tipo": self.tipo, "titulo": self.titulo, "x": self.x, "y": self.y, "color": self.color,
                "decidido_por": self.decidido_por, "aviso": self.aviso,
                "columnas": self.tabla.columnas, "filas": self.tabla.filas}


# ------------------------------------------------------------------ tablas markdown -> datos
def _valor(celda: str):
    t = celda.strip().replace("$", "").replace("MXN", "").strip()
    if re.fullmatch(r"-?[\d,]+(\.\d+)?", t) and not _VALOR_FECHA.fullmatch(t):
        return float(t.replace(",", ""))
    return celda.strip()  # fechas YYYYMM / YYYYMMDD y cuentas enmascaradas quedan como texto


def extraer_tablas(texto: str, origen: str = "") -> list[Tabla]:
    tablas, actual = [], []
    for linea in texto.splitlines() + [""]:
        if linea.strip().startswith("|"):
            actual.append(linea.strip())
            continue
        if len(actual) >= 3 and re.fullmatch(r"\|(\s*-+\s*\|)+", actual[1].replace(":", "")):
            cols = [c.strip() for c in actual[0].strip("|").split("|")]
            filas = [[_valor(c) for c in f.strip("|").split("|")] for f in actual[2:]]
            filas = [f for f in filas if len(f) == len(cols)]
            if filas:
                tablas.append(Tabla(cols, filas, origen))
        actual = []
    return tablas


# ------------------------------------------------------------------ decisión
_MONTO = re.compile(r"total|saldo|monto|mxn|gasto|importe|suma", re.IGNORECASE)
_PROMEDIO = re.compile(r"promedio|media\b|en promedio", re.IGNORECASE)
_PIDE_TIEMPO = re.compile(r"\bmes\b|meses|mensual|cada mes|evoluci|tendencia|en el tiempo|hist[oó]ric|ha cambiado|"
                          r"a lo largo", re.IGNORECASE)
_PIDE_COMPOSICION = re.compile(r"proporci|porcentaje|composici|reparto|particip|distribuci|%", re.IGNORECASE)
_PIDE_GASTO = re.compile(r"gast", re.IGNORECASE)
_NO_GASTO = {"DEPOSITO", "PAGOS"}
_PIDE_CONTEO = re.compile(r"cu[aá]nt[oa]s\s+(movimientos|transacciones|operaciones|clientes|cuentas|veces)|"
                          r"n[uú]mero de|conteo|cantidad de|clientes por|cuentas por|proporci[oó]n de clientes", re.IGNORECASE)
_SUSTANTIVO_CONTEO = re.compile(r"(movimientos|transacciones|operaciones|clientes|cuentas)", re.IGNORECASE)


def _elegir_tabla(tablas: list[Tabla], sugerida: int | None) -> Tabla:
    if sugerida is not None and 0 <= sugerida < len(tablas):
        return tablas[sugerida]
    candidatas = [t for t in tablas if t.numericas() and len(t.filas) >= 2] or tablas
    return max(candidatas, key=lambda t: (len(t.dimensiones()) >= 1, -abs(len(t.filas) - 12)))


def _elegir_y(t: Tabla, pregunta: str, sugerida: str | None) -> str:
    nums = t.numericas()
    if _PIDE_CONTEO.search(pregunta):
        m = _SUSTANTIVO_CONTEO.search(pregunta)
        exacta = [c for c in nums if m and m.group(1).lower().rstrip("s")[:6] in c.lower()]
        conteos = exacta or [c for c in nums if not _MONTO.search(c)]
        if conteos:
            return conteos[0]
    montos = [c for c in nums if _MONTO.search(c)]
    if _PROMEDIO.search(pregunta):
        prom = [c for c in montos if "promedio" in c]
        if prom:
            return prom[0]
    if sugerida in montos and "promedio" not in sugerida and "apertura" not in sugerida:
        return sugerida
    preferidas = [c for c in montos if "promedio" not in c and "apertura" not in c] or montos or nums
    return next((c for c in preferidas if "total" in c), preferidas[0])


def _filtrar_gastos(t: Tabla, pregunta: str) -> Tabla:
    if not _PIDE_GASTO.search(pregunta):
        return t
    for c in t.categoricas():
        vals = set(map(str, t._col(c)))
        if vals & _NO_GASTO and not vals <= _NO_GASTO:
            i = t.columnas.index(c)
            return Tabla(t.columnas, [f for f in t.filas if str(f[i]) not in _NO_GASTO], t.origen)
    return t


def _ultimo_periodo(t: Tabla, tiempo: str) -> Tabla:
    """Saldos = fotografías: si no se grafica por tiempo, se usa solo el último periodo (regla R001)."""
    i = t.columnas.index(tiempo)
    ultimo = max(map(str, t._col(tiempo)))
    return Tabla(t.columnas, [f for f in t.filas if str(f[i]) == ultimo], t.origen)


def _agregar(t: Tabla, x: str, y: str) -> Tabla:
    """Suma y por categoría x (para pastel o barras sin serie)."""
    ix, iy, acum = t.columnas.index(x), t.columnas.index(y), {}
    for f in t.filas:
        acum[str(f[ix])] = acum.get(str(f[ix]), 0.0) + float(f[iy] or 0)
    return Tabla([x, y], [[k, v] for k, v in acum.items()], t.origen)


def _top_otros(t: Tabla, x: str, y: str, n: int = 7) -> Tabla:
    filas = sorted(t.filas, key=lambda f: -f[1])
    if len(filas) <= n + 1:
        return t
    return Tabla([x, y], filas[:n] + [["Otros", sum(f[1] for f in filas[n:])]], t.origen)


def normalizar(pregunta: str, tablas: list[Tabla], spec: dict | None = None) -> Grafica | None:
    """Decide la gráfica final. spec = sugerencia del modelo (puede ser None o inválida)."""
    spec = spec or {}
    tablas = [t for t in tablas if t.numericas()]
    if not tablas:
        return None
    try:
        idx = int(spec["tabla"]) if spec.get("tabla") is not None else None
    except (TypeError, ValueError):
        idx = None
    t = _filtrar_gastos(_elegir_tabla(tablas, idx), pregunta)
    if not t.filas:
        return None
    y = _elegir_y(t, pregunta, spec.get("y"))
    pedido = tipo_pedido(pregunta)
    sugerido = spec.get("tipo") if spec.get("tipo") in TIPOS else None
    origen = "usuario" if pedido else ("llm" if sugerido else "reglas")
    aviso = ""

    dims = t.dimensiones()
    tiempo = [d for d in t.temporales() if d in dims]          # tiempo con 2+ periodos
    otras = [d for d in dims if d not in tiempo]
    quiere_tiempo = bool(_PIDE_TIEMPO.search(pregunta)) or pedido == "lineas" or sugerido == "lineas"

    if pedido == "dispersion":
        aviso = "Este tipo de gráfica no aplica a estos datos; se muestra la opción más clara."
        pedido = None

    # 1. una sola cifra -> indicador
    if len(t.filas) == 1 or not dims:
        if pedido and pedido != "indicador":
            aviso = "El resultado es una sola cifra, por eso se muestra como indicador."
        return Grafica("indicador", spec.get("titulo") or y.replace("_", " ").capitalize(), None, y, None, t, origen, aviso)

    # 2. ejes
    if tiempo and (quiere_tiempo or not otras):
        x, color = tiempo[0], (otras[0] if otras else None)
    else:
        if tiempo:  # hay varios periodos pero no se pidió evolución -> último corte
            t = _ultimo_periodo(t, tiempo[0])
            tiempo = []
        x = otras[0] if otras else dims[0]
        color = otras[1] if len(otras) > 1 else None

    # 3. tipo
    tipo = pedido or sugerido
    if tipo is None:
        if tiempo and x in tiempo:
            tipo = "barras_agrupadas" if (color and re.search(r"compar|barras", pregunta, re.IGNORECASE)) else "lineas"
        elif _PIDE_COMPOSICION.search(pregunta) and not color:
            tipo = "pastel"
        else:
            tipo = "barras_agrupadas" if color else "barras"
        origen = "reglas" if not sugerido else origen

    # 4. hacer posible el tipo elegido
    if tipo == "lineas" and (x not in tiempo or len(set(map(str, t._col(x)))) < 2):
        tipo = "barras_agrupadas" if color else "barras"
        aviso = aviso or "La gráfica de líneas necesita varios periodos; con estos datos se muestra en barras."
    if tipo == "pastel":
        if color:  # pastel = una sola dimensión
            if x in tiempo:
                if "saldo" in y:  # saldos = fotografías: no se suman meses (R001), se toma el último corte
                    t = _ultimo_periodo(t, x)
                x, color = color, None  # movimientos = flujos: sí se suman los meses
            else:
                color = None
        if "promedio" in y:
            aviso = aviso or "Un pastel muestra partes de un total; se usó el total en lugar del promedio."
            y = next((c for c in t.numericas() if _MONTO.search(c) and "promedio" not in c), y)
        t = _top_otros(_agregar(t, x, y), x, y)
        if any(f[1] < 0 for f in t.filas):
            tipo, aviso = "barras", "Hay valores negativos, por eso se muestra en barras."
    if tipo == "barras_agrupadas" and not color:
        tipo = "barras"
    if tipo == "barras" and color:  # dos categorías: agrupadas (lado a lado), no apiladas
        tipo = "barras_agrupadas"
    if tipo == "barras" and not color and len(set(map(str, t._col(x)))) < len(t.filas):
        t = _agregar(t, x, y)
    titulo = str(spec.get("titulo") or "").strip()[:90] or _titulo(y, x, color)
    return Grafica(tipo, titulo, x, y, color, t, origen, aviso)


def _titulo(y: str, x: str | None, color: str | None) -> str:
    nombre = y.replace("_mxn", "").replace("_", " ").capitalize()
    partes = [p.replace("_", " ") for p in (x, color) if p]
    return f"{nombre} por {' y '.join(partes)}" if partes else nombre


async def elegir_grafica(llm, pregunta: str, tablas: list[Tabla]) -> Grafica | None:
    """El modelo sugiere (tipo, tabla, ejes); normalizar() decide respetando lo que pidió el usuario."""
    tablas = [t for t in tablas if t.numericas()]
    if not tablas:
        return None
    spec = None
    if not tipo_pedido(pregunta):  # si el usuario ya dijo el tipo, no hace falta preguntarle al modelo
        catalogo = "\n".join(f"- {k}: {v}" for k, v in TIPOS.items())
        datos = "\n".join(f"tabla {i}: {t.resumen()}" for i, t in enumerate(tablas))
        prompt = f"""Eres el agente de gráficas de un banco. Elige la gráfica MÁS clara para la petición.
Tipos permitidos:
{catalogo}

Petición del usuario: {pregunta}

Tablas disponibles:
{datos}

Responde SOLO un JSON, sin texto extra:
{{"tipo": "<uno de los tipos>", "tabla": <número>, "y": "<columna numérica a graficar>", "titulo": "<título corto en español>"}}"""
        try:
            from common import texto_de

            salida = texto_de((await llm.ainvoke(prompt)).content)
            m = re.search(r"\{.*\}", salida, re.DOTALL)
            spec = json.loads(m.group(0)) if m else None
        except Exception:  # noqa: BLE001
            spec = None
    return normalizar(pregunta, tablas, spec)


# ------------------------------------------------------------------ dibujo
def figura(g: Grafica | dict):
    """Figura de Plotly a partir de la decisión (objeto Grafica o su dict, como se guarda en la sesión)."""
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go

    d = g.a_dict() if isinstance(g, Grafica) else g
    df = pd.DataFrame(d["filas"], columns=d["columnas"])
    es_monto = bool(_MONTO.search(d["y"]))
    fmt = "$,.0f" if es_monto else ",.0f"
    etiqueta_y = d["y"].replace("_mxn", " (MXN)").replace("_", " ").capitalize()
    if d["tipo"] == "indicador":
        valor = float(df[d["y"]].sum()) if len(df) > 1 else float(df[d["y"]].iloc[0])
        fig = go.Figure(go.Indicator(mode="number", value=valor, title={"text": d["titulo"]},
                                     number={"prefix": "$" if es_monto else "", "valueformat": ",.2f" if es_monto else ",.0f"}))
        fig.update_layout(height=260, margin=dict(t=60, l=10, r=10, b=10))
        return fig
    for c in (d["x"], d["color"]):
        if c:
            df[c] = df[c].astype(str)  # meses/fechas como categorías ordenadas, no como números
    etiquetas = {d["y"]: etiqueta_y}
    if d["tipo"] == "pastel":
        fig = px.pie(df, names=d["x"], values=d["y"], title=d["titulo"], hole=0.4)
        fig.update_traces(textinfo="percent+label", hovertemplate="%{label}: %{value:" + fmt + "} (%{percent})")
    elif d["tipo"] == "lineas":
        df = df.sort_values(d["x"])
        fig = px.line(df, x=d["x"], y=d["y"], color=d["color"], markers=True, title=d["titulo"], labels=etiquetas)
    else:
        horizontal = d["tipo"] == "barras" and (df[d["x"]].nunique() > 6 or df[d["x"]].str.len().max() > 14)
        if d["tipo"] == "barras_agrupadas" and d["x"]:
            df = df.sort_values(d["x"])
        kw = dict(color=d["color"], title=d["titulo"], labels=etiquetas,
                  barmode="group" if d["tipo"] == "barras_agrupadas" else "relative")
        if horizontal:
            df = df.sort_values(d["y"])
            fig = px.bar(df, x=d["y"], y=d["x"], orientation="h", text_auto=fmt, **kw)
        else:
            fig = px.bar(df, x=d["x"], y=d["y"], text_auto=fmt if d["tipo"] == "barras" else False, **kw)
    if d["tipo"] in ("barras", "barras_agrupadas", "lineas"):
        eje_num = fig.update_xaxes if (d["tipo"] == "barras" and fig.data and fig.data[0].orientation == "h") else fig.update_yaxes
        eje_num(tickformat=fmt)
    fig.update_layout(margin=dict(t=60, l=10, r=10, b=10), legend_title_text="")
    return fig


def guardar_html(g: Grafica | dict, ruta) -> str:
    figura(g).write_html(str(ruta), include_plotlyjs="cdn")
    return str(ruta)