"""Acceso a Pinecone + lectura de documentos. Lo usan ingest_governance.py y mcp_governance_server.py."""
import os

import common

# Documentos que puede consultar un CLIENTE. Todo lo demás es 'interno' (solo empleados).
DOCS_PUBLICOS = {"aviso_privacidad_banamex.md", "banamex_contexto_publico.md", "glosario_gobierno_datos.md",
                 "LFPDPPP.pdf", "LIC.pdf"}
IGNORAR = {"README.md"}
EXTENSIONES = {".pdf", ".md", ".csv", ".txt"}


def audiencia(nombre: str) -> str:
    return "publico" if nombre in DOCS_PUBLICOS else "interno"


def pinecone_index(crear: bool = False):
    from pinecone import Pinecone, ServerlessSpec

    key = os.getenv("PINECONE_API_KEY", "")
    if not key or "PEGA" in key:
        raise RuntimeError("Falta PINECONE_API_KEY en .env")
    pc = Pinecone(api_key=key)
    if not pc.has_index(common.INDEX_NAME):
        if not crear:
            raise RuntimeError(f"No existe el índice '{common.INDEX_NAME}'. Corre: .\\run.ps1 ingest")
        pc.create_index(name=common.INDEX_NAME, dimension=common.EMBEDDING_DIM, metric="cosine",
                        spec=ServerlessSpec(cloud=os.getenv("PINECONE_CLOUD", "aws"),
                                            region=os.getenv("PINECONE_REGION", "us-east-1")))
    return pc.Index(common.INDEX_NAME)


def vector_store(crear: bool = False):
    from langchain_pinecone import PineconeVectorStore

    return PineconeVectorStore(index=pinecone_index(crear), embedding=common.get_embeddings())


def buscar(pregunta: str, rol: str, k: int | None = None) -> list[dict]:
    """Búsqueda semántica con filtro por audiencia según el rol (cliente = solo públicos)."""
    filtro = {"audiencia": {"$eq": "publico"}} if rol == "cliente" else None
    hits = vector_store().similarity_search_with_score(pregunta, k=k or common.TOP_K, filter=filtro)
    return [{"texto": d.page_content, "fuente": d.metadata.get("source", "?"), "pagina": d.metadata.get("page", "?"),
             "score": round(float(s), 3)} for d, s in hits if s >= common.MIN_SCORE]


def formatear(hits: list[dict]) -> str:
    if not hits:
        return "SIN RESULTADOS: no hay fragmentos con score suficiente. Dilo al usuario; no inventes."
    return "\n\n".join(f"[{i}] Fuente: {h['fuente']} (pág. {h['pagina']}, score {h['score']})\n{h['texto']}"
                       for i, h in enumerate(hits, 1))
