"""Lectura de PDFs: texto directo con PyMuPDF y OCR (Tesseract) solo en páginas escaneadas.
Sirve para el corpus del RAG y para los PDFs que sube el usuario en la app."""
import re
from pathlib import Path


def _ocr(page) -> str:
    try:
        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(img, lang="spa+eng")
    except Exception:  # noqa: BLE001  (sin pytesseract o sin Tesseract instalado)
        return ""


def leer_pdf(origen) -> tuple[list[tuple[int, str]], dict]:
    """origen: ruta o bytes. Devuelve [(página, texto)] y métricas de extracción."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=origen, filetype="pdf") if isinstance(origen, (bytes, bytearray)) else fitz.open(str(origen))
    paginas, con_ocr, vacias = [], 0, 0
    for i, page in enumerate(doc, start=1):
        texto = page.get_text("text") or ""
        if len(texto.strip()) < 30:  # página escaneada (imagen) -> OCR
            o = _ocr(page)
            if o.strip():
                texto, con_ocr = o, con_ocr + 1
            else:
                vacias += 1
        paginas.append((i, texto))
    return paginas, {"paginas": len(paginas), "paginas_con_ocr": con_ocr, "paginas_sin_texto": vacias,
                     "caracteres": sum(len(t) for _, t in paginas)}


def leer_archivo(path: Path) -> list[tuple[int, str]]:
    if path.suffix.lower() == ".pdf":
        return leer_pdf(path)[0]
    return [(1, path.read_text(encoding="utf-8", errors="ignore"))]


def partir(texto: str, tam: int = 1200, traslape: int = 200) -> list[str]:
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= tam:
        return [texto] if texto else []
    out, i = [], 0
    while i < len(texto):
        fin = min(i + tam, len(texto))
        corte = texto.rfind(". ", i + tam // 2, fin)
        if corte != -1 and fin < len(texto):
            fin = corte + 1
        out.append(texto[i:fin].strip())
        if fin >= len(texto):
            break
        i = max(fin - traslape, i + 1)
    return out


class DocumentoUsuario:
    """PDF subido en la sesión. Se queda en memoria (no va a Pinecone ni lo ven otros usuarios)."""

    def __init__(self, nombre: str, contenido: bytes):
        paginas, self.metricas = leer_pdf(contenido)
        self.nombre = nombre
        self.chunks = [(p, c) for p, t in paginas for c in partir(t)]
        if not self.chunks:
            raise ValueError("No se pudo extraer texto. Si es un PDF escaneado, instala Tesseract (ver README).")
        self._emb = None

    @property
    def texto_completo(self) -> str:
        return " ".join(c for _, c in self.chunks)

    def contexto_para(self, pregunta: str, max_chars: int = 7000) -> str:
        """PDF corto: completo. PDF largo: inicio + fragmentos más parecidos a la pregunta (bge-m3 local)."""
        if len(self.texto_completo) <= max_chars:
            return self.texto_completo
        import numpy as np

        import common

        emb = common.get_embeddings()
        if self._emb is None:
            m = np.array(emb.embed_documents([c for _, c in self.chunks]), dtype=np.float32)
            self._emb = m / np.linalg.norm(m, axis=1, keepdims=True)
        q = np.array(emb.embed_query(pregunta), dtype=np.float32)
        orden = np.argsort(-(self._emb @ (q / np.linalg.norm(q))))
        elegidos, total = [0], len(self.chunks[0][1])
        for i in orden:
            if i not in elegidos and total + len(self.chunks[i][1]) <= max_chars:
                elegidos.append(int(i))
                total += len(self.chunks[i][1])
        return "\n...\n".join(f"(pág. {self.chunks[i][0]}) {self.chunks[i][1]}" for i in sorted(elegidos))
