"""Subagente Lector de Documentos.

Responsabilidad única: LEER el PDF que sube el usuario y entregarle al orquestador (hub) una
"ficha" estructurada del documento. El lector NO compara: el hub decide contra qué comparar
(normativa del RAG o registros de la base de datos) y llama al agente correspondiente.

    PDF ──> texto por página (PyMuPDF / OCR) ──> tipo de documento
                                              ──> cláusulas (contratos y acuerdos)
                                              ──> saldos, movimientos y totales (estados de cuenta)
                                              ──> fragmentos relevantes para cada pregunta

La extracción es determinista (reglas sobre el texto) para no depender del modelo. El modelo solo
se usa si el documento es de un tipo no reconocido y se pide un resumen.
"""
import re
from dataclasses import dataclass, field

from pdf_reader import DocumentoUsuario

PRODUCTOS = "AHORRO|CHEQUES|TDC|C_PERSONAL"
TIPOS_MOV = "DEPOSITO|RETIRO|COMPRAS|DISPOSICIONES|PAGOS"
MESES = {"enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06", "julio": "07",
         "agosto": "08", "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"}
_MONTO = r"\$\s?([\d,]+\.\d{2})"

# Temas de pregunta -> palabras que deben aparecer en el título o texto de la cláusula
TEMAS = {
    "costos": re.compile(r"penaliz|comisi|cobr[ao]|costo|cuota|anualidad|cargos? (por|de)|multa|tard[ií]o|moratori|"
                         r"tasa|cat\b|prepago|anticipad|seguro|apertura", re.IGNORECASE),
    "datos": re.compile(r"dato|privacidad|lfpdppp|arco|consentimiento|tercero|compart|transfer|conserv|retenci|"
                        r"secreto|confidencial|extranjero|cifra|elimin|protecci", re.IGNORECASE),
    "pagos": re.compile(r"pago m[ií]nimo|fecha l[ií]mite|plazo|amortizaci|mensualidad|pago", re.IGNORECASE),
    "terminacion": re.compile(r"cancel|terminaci|vencimiento|incumplimiento|rescisi", re.IGNORECASE),
}


def _monto(s: str) -> float:
    return float(s.replace(",", ""))


@dataclass
class Clausula:
    numero: int
    titulo: str
    texto: str

    def __str__(self):
        return f"CLÁUSULA {self.numero}. {self.titulo}: {self.texto}"


@dataclass
class FichaDocumento:
    nombre: str
    tipo: str                    # estado_de_cuenta | contrato | acuerdo_datos | otro
    metricas: dict
    texto: str
    clausulas: list[Clausula] = field(default_factory=list)
    estado_cuenta: dict | None = None  # num_cte, periodo, saldos, movimientos, totales

    def descripcion(self) -> str:
        """Lo que el lector le reporta al hub (corto)."""
        base = {"estado_de_cuenta": "estado de cuenta", "contrato": "contrato", "acuerdo_datos": "acuerdo de datos",
                "otro": "documento"}[self.tipo]
        if self.estado_cuenta:
            e = self.estado_cuenta
            return (f"{base} del cliente {e['num_cte']}, periodo {e['periodo']}, {len(e['saldos'])} productos y "
                    f"{len(e['movimientos'])} movimientos")
        if self.clausulas:
            return f"{base} con {len(self.clausulas)} cláusulas"
        return f"{base} de {self.metricas['paginas']} páginas"


class AgenteLector:
    def __init__(self):
        self.ficha: FichaDocumento | None = None
        self._doc: DocumentoUsuario | None = None

    # ------------------------------------------------------------ lectura
    def leer(self, nombre: str, contenido: bytes) -> FichaDocumento:
        self._doc = DocumentoUsuario(nombre, contenido)  # PyMuPDF + OCR + fragmentos
        texto = limpiar_texto(self._doc.texto_completo)
        tipo = clasificar(texto)
        self.ficha = FichaDocumento(nombre, tipo, self._doc.metricas, texto)
        if tipo == "estado_de_cuenta":
            self.ficha.estado_cuenta = extraer_estado_cuenta(texto)
        if tipo in ("contrato", "acuerdo_datos"):
            self.ficha.clausulas = extraer_clausulas(texto)
        return self.ficha

    def olvidar(self):
        self.ficha, self._doc = None, None

    # ------------------------------------------------------------ lo que el hub le pide
    def fragmentos_para(self, pregunta: str, max_chars: int = 6000) -> str:
        """Partes del documento relevantes para la pregunta (cláusulas por tema o fragmentos por similitud)."""
        f = self.ficha
        if f.clausulas:
            elegidas = clausulas_relevantes(f.clausulas, pregunta)
            texto = "\n".join(str(c) for c in elegidas)
            return texto[:max_chars]
        if f.estado_cuenta:
            return resumen_estado_cuenta(f.estado_cuenta) + "\n\nTEXTO:\n" + f.texto[:max_chars // 2]
        return self._doc.contexto_para(pregunta, max_chars)

    def temas_para_normativa(self, pregunta: str) -> list[str]:
        """Consultas para el RAG: una por cláusula relevante (mejor recuperación que una consulta genérica)."""
        f = self.ficha
        if f.clausulas:
            return [f"{c.titulo.lower()}: {c.texto[:220]}" for c in clausulas_relevantes(f.clausulas, pregunta)[:4]]
        return [pregunta, f.texto[:300]]


# ================================================================ reglas de extracción
_PIE = re.compile(r"DOCUMENTO DE PRUEBA|DOCUMENTO SINT[ÉE]TICO PARA PRUEBAS[^·]*·[^·]*·|\bp[áa]g(?:ina)?\.?\s*\d+\b",
                  re.IGNORECASE)


def limpiar_texto(texto: str) -> str:
    """Quita encabezados/pies repetidos (marca de agua, número de página) y normaliza espacios."""
    return re.sub(r"\s+", " ", _PIE.sub(" ", texto)).strip()



def clasificar(texto: str) -> str:
    t = texto.upper()
    if "ESTADO DE CUENTA" in t and re.search(rf"\b({PRODUCTOS})\b.*?{_MONTO}", texto):
        return "estado_de_cuenta"
    if re.search(r"CL[ÁA]USULA\s+\d", t):
        if re.search(r"ACUERDO|CONVENIO", t) and re.search(r"DATOS|INFORMACI[ÓO]N", t):
            return "acuerdo_datos"
        return "contrato"
    return "otro"


def extraer_clausulas(texto: str) -> list[Clausula]:
    partes = re.split(r"CL[ÁA]USULA\s+(\d+)\s*[.:\-]\s*", texto)
    salida = []
    for i in range(1, len(partes) - 1, 2):
        cuerpo = partes[i + 1].strip()
        # el título es la racha inicial en MAYÚSCULAS (hasta la primera palabra con minúsculas)
        m = re.match(r"((?:[A-ZÁÉÍÓÚÑ0-9(),/\-]+\s+)+?)(?=[A-ZÁÉÍÓÚÑ][a-záéíóúñ])", cuerpo + " ")
        titulo = m.group(1).strip() if m else cuerpo.split(".")[0][:60]
        texto_c = cuerpo[len(m.group(1)):].strip() if m else cuerpo
        texto_c = re.split(r"\bFirma del cliente\b", texto_c)[0].strip()
        salida.append(Clausula(int(partes[i]), titulo, texto_c))
    return salida


def clausulas_relevantes(clausulas: list[Clausula], pregunta: str) -> list[Clausula]:
    temas = [rx for rx in TEMAS.values() if rx.search(pregunta)]
    if re.search(r"cumpl|ley|norma|pol[ií]tica|legal|regul|riesgo|problema|abusiv", pregunta, re.IGNORECASE):
        temas.append(TEMAS["datos"])  # "¿cumple?" -> revisar sobre todo cláusulas de datos
    if not temas:
        return clausulas  # pregunta general ("¿de qué trata?")
    elegidas = [c for c in clausulas if any(rx.search(c.titulo) or rx.search(c.texto) for rx in temas)]
    return elegidas or clausulas


def extraer_estado_cuenta(texto: str) -> dict:
    cte = re.search(r"Cliente:?\s*(\d{1,6})", texto)
    per = re.search(r"Periodo:?\s*([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{4})", texto)
    periodo = f"{per.group(2)}{MESES.get(per.group(1).lower(), '00')}" if per else ""
    saldos = [{"producto": p, "cuenta": f"****{c}", "saldo_inicial": _monto(a), "saldo_corte": _monto(b)}
              for p, c, a, b in re.findall(rf"\b({PRODUCTOS})\b\s+[^$*]{{0,60}}?\*{{4}}(\d{{4}})\s+{_MONTO}\s+{_MONTO}", texto)]
    movimientos = [{"fecha": f, "producto": p, "tipo": t, "monto": _monto(m)}
                   for f, p, t, m in re.findall(rf"(\d{{4}}-\d{{2}}-\d{{2}})\s+({PRODUCTOS})\s+({TIPOS_MOV})\s+{_MONTO}", texto)]
    cargos = re.search(rf"Total de cargos[^$]*{_MONTO}", texto)
    abonos = re.search(rf"Total de abonos[^$]*{_MONTO}", texto)
    pago_min = re.search(rf"Pago m[ií]nimo[^$]*?\$200\)?\s*{_MONTO}|Pago m[ií]nimo[^$]*{_MONTO}", texto)
    return {"num_cte": int(cte.group(1)) if cte else None, "periodo": periodo, "saldos": saldos,
            "movimientos": movimientos,
            "total_cargos": _monto(cargos.group(1)) if cargos else None,
            "total_abonos": _monto(abonos.group(1)) if abonos else None,
            "pago_minimo": _monto(next(g for g in pago_min.groups() if g)) if pago_min else None}


def resumen_estado_cuenta(e: dict) -> str:
    lineas = [f"Estado de cuenta del cliente {e['num_cte']}, periodo {e['periodo']}"]
    lineas += [f"- {s['producto']} {s['cuenta']}: saldo inicial ${s['saldo_inicial']:,.2f}, al corte ${s['saldo_corte']:,.2f}"
               for s in e["saldos"]]
    if e.get("total_cargos") is not None:
        lineas.append(f"- Total de cargos ${e['total_cargos']:,.2f}; total de abonos ${e['total_abonos'] or 0:,.2f}")
    if e.get("pago_minimo") is not None:
        lineas.append(f"- Pago mínimo de tarjeta ${e['pago_minimo']:,.2f}")
    return "\n".join(lineas)