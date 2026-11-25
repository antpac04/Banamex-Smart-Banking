"""Genera PDFs SINTÉTICOS de prueba para el flujo "subir PDF" (todos marcados como documento de prueba).

    python scripts/generar_pdfs_prueba.py                 # todo, estado de cuenta del cliente 42 (junio 2026)
    python scripts/generar_pdfs_prueba.py --cliente 7 --mes 202605
    python scripts/generar_pdfs_prueba.py --sin-bd        # solo contratos (no requiere la base)

Salida en pdfs_prueba/:
  estado_cuenta_<cte>_<mes>.pdf           datos REALES de tu base (cada máquina tiene montos distintos)
  estado_cuenta_<cte>_<mes>_escaneado.pdf el mismo, pero como imagen -> prueba el OCR
  contrato_tarjeta_credito.pdf            comisiones, penalizaciones y cláusulas de datos (algunas problemáticas)
  contrato_credito_personal.pdf           tasa, plazo, mora y prepago
  acuerdo_intercambio_datos_proveedor.pdf para EMPLEADO: comparar contra la política interna de datos
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

SALIDA = ROOT / "pdfs_prueba"
BANCO = "Banco Ficticio del Reto, S.A."
AVISO = "DOCUMENTO SINTÉTICO PARA PRUEBAS ACADÉMICAS · NO ES UN DOCUMENTO DE BANAMEX NI TIENE VALIDEZ"
MESES = {"01": "enero", "02": "febrero", "03": "marzo", "04": "abril", "05": "mayo", "06": "junio"}

est = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=est["Title"], fontSize=15, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=est["Heading2"], fontSize=11.5, spaceBefore=8, spaceAfter=3)
P = ParagraphStyle("p", parent=est["BodyText"], fontSize=9.5, leading=12.5, alignment=4)
CHICO = ParagraphStyle("c", parent=P, fontSize=8, textColor=colors.grey)


def _marca(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 40)
    canvas.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.10))
    canvas.translate(letter[0] / 2, letter[1] / 2)
    canvas.rotate(35)
    canvas.drawCentredString(0, 0, "DOCUMENTO DE PRUEBA")
    canvas.restoreState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(letter[0] / 2, 1.2 * cm, f"{AVISO} · pág. {doc.page}")


def _pdf(nombre: str, elementos: list) -> Path:
    SALIDA.mkdir(exist_ok=True)
    ruta = SALIDA / nombre
    SimpleDocTemplate(str(ruta), pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=2 * cm, title=nombre).build(elementos, onFirstPage=_marca, onLaterPages=_marca)
    print("  ->", ruta.relative_to(ROOT))
    return ruta


def _tabla(filas: list[list], anchos=None) -> Table:
    t = Table(filas, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b63")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5fa")]),
                           ("ALIGN", (-1, 1), (-1, -1), "RIGHT")]))
    return t


def _clausulas(titulo: str, encabezado: str, clausulas: list[tuple[str, str]]) -> list:
    el = [Paragraph(BANCO, CHICO), Paragraph(titulo, H1), Paragraph(encabezado, P), Spacer(1, 6)]
    for i, (t, texto) in enumerate(clausulas, 1):
        el += [Paragraph(f"CLÁUSULA {i}. {t}", H2), Paragraph(texto, P)]
    el += [Spacer(1, 18), Paragraph("Firma del cliente: ______________________ &nbsp;&nbsp;&nbsp; "
                                    "Firma del banco: ______________________", P)]
    return el


def mxn(v) -> str:
    return f"${float(v):,.2f}"


# ===================================================================== estado de cuenta (desde la BD)
def datos_estado_cuenta(num_cte: int, mes: str) -> dict:
    import db_config as db

    db.ensure_db()
    q = lambda sql, p: db.consultar(sql, p, rol=db.ROL_BD_CLIENTE, num_cte=num_cte)[1]  # noqa: E731  (respeta RLS)
    saldos = q("""SELECT s.cve_producto, p.descripcion, '****' || RIGHT(s.num_cta::text, 4), s.saldo_apertura, s.saldo_mes
                  FROM cfg.fact_sdos_captacoloca_m s JOIN dim.dim_producto p USING (cve_producto)
                  WHERE s.num_cte = %s AND s.fec_informacion / 100 = %s ORDER BY 1""", (num_cte, int(mes)))
    movs = q("""SELECT fec_txn, cve_producto, desc_txn, saldo_txn FROM cfg.fact_txn_captacoloca_d
                WHERE num_cte = %s AND cve_mes_txn = %s ORDER BY fec_txn, cve_producto""", (num_cte, int(mes)))
    if not saldos:
        raise SystemExit(f"Sin datos para el cliente {num_cte} en {mes}. Corre antes: .\\run.ps1 load-db")
    return {"num_cte": num_cte, "mes": mes, "saldos": saldos, "movs": movs}


def estado_de_cuenta(d: dict) -> Path:
    mes_txt = f"{MESES[d['mes'][4:]]} {d['mes'][:4]}"
    el = [Paragraph(BANCO, CHICO), Paragraph("ESTADO DE CUENTA", H1),
          Paragraph(f"<b>Cliente:</b> {d['num_cte']} &nbsp;&nbsp; <b>Periodo:</b> {mes_txt} &nbsp;&nbsp; "
                    f"<b>Fecha de corte:</b> último día de {mes_txt}", P),
          Paragraph("RESUMEN DE PRODUCTOS", H2),
          _tabla([["Producto", "Descripción", "Cuenta", "Saldo inicial", "Saldo al corte"]] +
                 [[a, b, c, mxn(x), mxn(y)] for a, b, c, x, y in d["saldos"]],
                 [2.4 * cm, 5.4 * cm, 2.2 * cm, 3 * cm, 3 * cm])]
    tdc = next((s for s in d["saldos"] if s[0] == "TDC"), None)
    if tdc:
        saldo = float(tdc[4])
        el += [Paragraph("TARJETA DE CRÉDITO: PAGOS", H2),
               _tabla([["Concepto", "Monto"], ["Pago para no generar intereses", mxn(saldo)],
                       ["Pago mínimo (5% del saldo, mínimo $200)", mxn(max(saldo * 0.05, 200))],
                       ["Fecha límite de pago", "20 días naturales después del corte"],
                       ["Comisión por pago tardío (ver contrato)", "$450.00 + IVA"]], [10 * cm, 6 * cm])]
    el += [Paragraph("MOVIMIENTOS DEL PERIODO", H2)]
    el += [_tabla([["Fecha", "Producto", "Concepto", "Monto"]] + [[str(f), p, t, mxn(m)] for f, p, t, m in d["movs"]],
                  [3 * cm, 3 * cm, 6 * cm, 4 * cm])] if d["movs"] else [Paragraph("Sin movimientos en el periodo.", P)]
    gasto = sum(float(m) for _, _, t, m in d["movs"] if t in ("COMPRAS", "RETIRO", "DISPOSICIONES"))
    ingreso = sum(float(m) for _, _, t, m in d["movs"] if t in ("DEPOSITO", "PAGOS"))
    el += [Spacer(1, 6), Paragraph(f"<b>Total de cargos (compras, retiros y disposiciones):</b> {mxn(gasto)} &nbsp;&nbsp; "
                                   f"<b>Total de abonos (depósitos y pagos):</b> {mxn(ingreso)}", P),
           Spacer(1, 10), Paragraph("Tiene 90 días naturales a partir de la fecha de corte para objetar cargos no "
                                    "reconocidos. Consulte el aviso de privacidad en la sucursal o sitio del banco.", CHICO)]
    return _pdf(f"estado_cuenta_{d['num_cte']}_{d['mes']}.pdf", el)


def version_escaneada(pdf: Path) -> Path:
    """Convierte cada página en imagen (sin capa de texto): así solo se puede leer con OCR."""
    import fitz  # PyMuPDF (ya está en requirements)

    src, out = fitz.open(str(pdf)), fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=150)
        nueva = out.new_page(width=page.rect.width, height=page.rect.height)
        nueva.insert_image(nueva.rect, pixmap=pix)
    destino = pdf.with_name(pdf.stem + "_escaneado.pdf")
    out.save(str(destino))
    print("  ->", destino.relative_to(ROOT), "(solo imagen: requiere Tesseract para leerlo)")
    return destino


# ===================================================================== contratos (texto fijo)
def contrato_tdc() -> Path:
    return _pdf("contrato_tarjeta_credito.pdf", _clausulas(
        "CONTRATO DE APERTURA DE CRÉDITO EN CUENTA CORRIENTE (TARJETA DE CRÉDITO CLÁSICA)",
        f"Contrato que celebran {BANCO} (\"el Banco\") y la persona cuyos datos aparecen en la solicitud "
        "(\"el Cliente\"), al tenor de las siguientes cláusulas.", [
            ("OBJETO", "El Banco otorga al Cliente una línea de crédito revolvente de hasta $45,000.00 M.N., "
                       "que podrá disponer mediante compras con la tarjeta y disposiciones de efectivo."),
            ("TASA DE INTERÉS Y CAT", "Tasa de interés ordinaria anual variable de 54.0% sin IVA, calculada sobre "
                                      "saldo promedio diario. Costo Anual Total (CAT) promedio: 78.5% sin IVA, "
                                      "para fines informativos y de comparación."),
            ("COMISIONES", "Anualidad: $750.00 + IVA. Disposición de efectivo: 6% del monto dispuesto. Reposición "
                           "de plástico: $150.00 + IVA. Pago tardío: $450.00 + IVA por cada periodo en que no se "
                           "cubra al menos el pago mínimo en la fecha límite."),
            ("PAGO MÍNIMO", "El pago mínimo será el mayor entre el 5% del saldo insoluto y $200.00 M.N. La fecha "
                            "límite de pago será 20 días naturales posteriores a la fecha de corte."),
            ("INTERESES MORATORIOS", "Si el Cliente no cubre el pago mínimo, se cobrarán intereses moratorios a una "
                                     "tasa equivalente a 1.5 veces la tasa ordinaria sobre el monto vencido."),
            ("USO DE DATOS PERSONALES", "El Cliente autoriza que sus datos personales, incluidos datos de "
                                        "identificación, patrimoniales y de comportamiento de pago, sean compartidos "
                                        "con empresas comerciales afiliadas y terceros para fines publicitarios, sin "
                                        "que se requiera un consentimiento adicional ni la puesta a disposición de un "
                                        "aviso de privacidad específico."),
            ("CONSERVACIÓN DE LA INFORMACIÓN", "El Banco conservará los datos del Cliente de manera indefinida, "
                                               "aun después de terminada la relación contractual."),
            ("SECRETO BANCARIO", "El Banco podrá proporcionar información de las operaciones del Cliente a cualquier "
                                 "tercero que lo solicite por escrito, siempre que justifique un interés comercial."),
            ("CANCELACIÓN", "El Cliente podrá solicitar la cancelación en cualquier momento, siempre que no exista "
                            "saldo pendiente. La cancelación surtirá efecto al día hábil siguiente."),
            ("ACLARACIONES", "El Cliente cuenta con 90 días naturales a partir de la fecha de corte para presentar "
                             "aclaraciones sobre cargos no reconocidos en la Unidad Especializada del Banco."),
        ]))


def contrato_credito_personal() -> Path:
    return _pdf("contrato_credito_personal.pdf", _clausulas(
        "CONTRATO DE CRÉDITO PERSONAL SIMPLE",
        f"Contrato de crédito simple entre {BANCO} y el Cliente.", [
            ("MONTO Y DESTINO", "Crédito por $80,000.00 M.N. de libre destino, entregado en la cuenta de cheques del Cliente."),
            ("PLAZO Y AMORTIZACIONES", "Plazo de 36 meses mediante pagos mensuales fijos de $3,512.40, que incluyen "
                                       "capital, intereses e IVA sobre intereses."),
            ("TASA", "Tasa fija anual de 28.0% sin IVA. CAT promedio de 36.9% sin IVA, para fines informativos."),
            ("COMISIONES", "Comisión por apertura: 2% del monto del crédito, cobrada al momento de la disposición. "
                           "Comisión por pago tardío: $350.00 + IVA por cada mensualidad vencida."),
            ("PAGOS ANTICIPADOS", "El Cliente podrá realizar pagos anticipados a capital en cualquier momento. Por cada "
                                  "pago anticipado se cobrará una penalización de 3% sobre el monto adelantado."),
            ("INCUMPLIMIENTO", "Con tres mensualidades vencidas, el Banco podrá dar por vencido anticipadamente el "
                               "crédito y exigir el saldo total, más intereses moratorios de 1.5 veces la tasa ordinaria."),
            ("SEGURO", "El crédito incluye un seguro de vida obligatorio que cubre el saldo insoluto, con costo de "
                       "$45.00 mensuales incluido en la mensualidad."),
            ("DATOS PERSONALES", "Los datos del Cliente serán tratados conforme al aviso de privacidad del Banco, "
                                 "disponible en sucursales. El Cliente puede ejercer sus derechos de acceso, "
                                 "rectificación, cancelación y oposición (ARCO) ante el área de datos personales."),
        ]))


def acuerdo_intercambio_datos() -> Path:
    return _pdf("acuerdo_intercambio_datos_proveedor.pdf", _clausulas(
        "ACUERDO DE INTERCAMBIO DE DATOS CON PROVEEDOR DE ANALÍTICA",
        f"Acuerdo entre {BANCO} (\"el Banco\") y Analítica Global Ficticia, LLC (\"el Proveedor\"), con sede "
        "fuera de México, para el desarrollo de modelos de propensión de compra.", [
            ("DATOS COMPARTIDOS", "El Banco entregará mensualmente: num_cte, fec_nac, genero_cte, segmento_cte, "
                                  "cve_sucursal y los saldos mensuales de todas las cuentas (tabla "
                                  "fact_sdos_captacoloca_m) de la totalidad de sus clientes."),
            ("MEDIO DE ENTREGA", "Los archivos se enviarán en formato CSV sin cifrar por correo electrónico al "
                                 "analista asignado por el Proveedor."),
            ("CONSERVACIÓN", "El Proveedor conservará los datos durante 10 años y podrá reutilizarlos para otros "
                             "clientes de su cartera, siempre que estén agregados."),
            ("TRANSFERENCIA INTERNACIONAL", "Los datos se almacenarán en servidores del Proveedor en el extranjero. "
                                            "No se requiere notificar a los titulares."),
            ("RESPONSABLE DE DATOS", "Por parte del Banco, el responsable es el área comercial. No se designa Data "
                                     "Owner ni Data Steward para este flujo."),
            ("CALIDAD DE DATOS", "El Banco no garantiza la exactitud de los datos. No se realizarán validaciones de "
                                 "calidad previas al envío."),
            ("TERMINACIÓN", "Al terminar el acuerdo, el Proveedor no estará obligado a eliminar la información recibida."),
        ]))


# ===================================================================== demo sin BD
DEMO = {"num_cte": 42, "mes": "202606",
        "saldos": [("AHORRO", "Cuenta de ahorro", "****0041", 25000.00, 25840.10),
                   ("CHEQUES", "Cuenta de cheques", "****0041", 9850.00, 10938.72),
                   ("TDC", "Tarjeta de crédito", "****0041", 64000.00, 66768.11)],
        "movs": [("2026-06-03", "CHEQUES", "DEPOSITO", 15000.00), ("2026-06-08", "CHEQUES", "RETIRO", 3000.00),
                 ("2026-06-12", "TDC", "COMPRAS", 1306.62), ("2026-06-15", "TDC", "DISPOSICIONES", 3500.00),
                 ("2026-06-25", "TDC", "PAGOS", 2500.00)]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cliente", type=int, default=42)
    ap.add_argument("--mes", default="202606", help="YYYYMM entre 202602 y 202606")
    ap.add_argument("--sin-bd", action="store_true", help="solo contratos + estado de cuenta de ejemplo (no tu BD)")
    a = ap.parse_args()
    print("Generando PDFs de prueba en", SALIDA)
    for f in (contrato_tdc, contrato_credito_personal, acuerdo_intercambio_datos):
        f()
    datos = DEMO if a.sin_bd else datos_estado_cuenta(a.cliente, a.mes)
    edo = estado_de_cuenta(datos)
    try:
        version_escaneada(edo)
    except ImportError:
        print("  (sin PyMuPDF: se omite la versión escaneada)")


if __name__ == "__main__":
    main()