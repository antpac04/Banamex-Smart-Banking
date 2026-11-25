"""Servidor MCP #2: gobernanza (RAG sobre Pinecone). Se lanza por stdio con la identidad en env.
El filtro de audiencia lo fija el rol del proceso: el cliente solo recupera documentos públicos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP  # noqa: E402

import auth  # noqa: E402
import rag_store  # noqa: E402

IDENT = auth.identidad_desde_env()
mcp = FastMCP("governance")


@mcp.tool
@auth.guarded(auth.ROL_CLIENTE, auth.ROL_EMPLEADO)
def search_governance_knowledge(query: str) -> str:
    """Búsqueda semántica en los documentos del banco: aviso de privacidad, LFPDPPP, Ley de Instituciones de
    Crédito, BCBS 239, glosario y (solo empleados) política interna de calidad de datos y catálogo.
    Devuelve fragmentos con fuente, página y score para citar. query: pregunta o tema en lenguaje natural."""
    try:
        return rag_store.formatear(rag_store.buscar(query, IDENT.rol))
    except Exception as e:  # noqa: BLE001
        return f"ERROR en la búsqueda documental: {e}"


@mcp.tool
@auth.guarded(auth.ROL_CLIENTE, auth.ROL_EMPLEADO)
def list_governance_documents() -> str:
    """Lista los documentos que este usuario puede consultar."""
    permitidos = [p.name for p in sorted(rag_store.common.DOCS_DIR.iterdir())
                  if p.suffix.lower() in rag_store.EXTENSIONES and p.name not in rag_store.IGNORAR
                  and (not IDENT.es_cliente or rag_store.audiencia(p.name) == "publico")]
    return "\n".join(f"- {n} ({rag_store.audiencia(n)})" for n in permitidos)


if __name__ == "__main__":
    mcp.run()
