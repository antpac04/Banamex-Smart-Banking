"""Indexa rag_documents/ en Pinecone con embeddings locales (Ollama bge-m3).
Cada fragmento lleva metadatos: source, page, audiencia ('publico' | 'interno').

    python src/ingest_governance.py           # agrega/actualiza (ids estables, no duplica)
    python src/ingest_governance.py --reset   # borra el índice y lo vuelve a llenar
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import rag_store  # noqa: E402
from pdf_reader import leer_archivo, partir  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    from langchain_core.documents import Document

    argv = sys.argv[1:] if argv is None else argv
    index = rag_store.pinecone_index(crear=True)
    if "--reset" in argv:
        try:
            index.delete(delete_all=True)
            print("Índice vaciado.")
        except Exception as e:  # noqa: BLE001  (índice nuevo/vacío)
            print("Nada que borrar:", type(e).__name__)
    store = rag_store.vector_store()
    total = 0
    for path in sorted(common.DOCS_DIR.iterdir()):
        if path.name in rag_store.IGNORAR or path.suffix.lower() not in rag_store.EXTENSIONES:
            continue
        aud = rag_store.audiencia(path.name)
        docs, ids = [], []
        for pagina, texto in leer_archivo(path):
            for k, ch in enumerate(partir(texto)):
                docs.append(Document(page_content=ch, metadata={"source": path.name, "page": pagina, "audiencia": aud}))
                ids.append(f"{path.stem[:60]}-p{pagina}-{k}".encode("ascii", "ignore").decode())
        print(f" - {path.name}: {len(docs)} fragmentos ({aud})", flush=True)
        for j in range(0, len(docs), 64):
            store.add_documents(docs[j:j + 64], ids=ids[j:j + 64])
        total += len(docs)
    print(f"Listo: {total} fragmentos en el índice '{common.INDEX_NAME}'.")


if __name__ == "__main__":
    main()
