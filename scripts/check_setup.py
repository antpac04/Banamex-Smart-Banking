"""Diagnóstico del entorno:   .\\run.ps1 check"""
import importlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
fallas = []


def paso(nombre, fn):
    try:
        print(f"[ OK ] {nombre}: {fn() or ''}")
    except Exception as e:  # noqa: BLE001
        fallas.append(nombre)
        print(f"[FALLA] {nombre}: {type(e).__name__}: {e}")


paso("Python >= 3.11", lambda: sys.version.split()[0] if sys.version_info >= (3, 11) else 1 / 0)
for m in ["langchain", "langchain.mcp", "fastmcp", "langchain_ollama", "langchain_pinecone", "psycopg",
          "pixeltable_pgserver", "fitz", "streamlit", "plotly", "pandas", "reportlab"]:
    paso(f"import {m}", lambda m=m: importlib.import_module(m) and "")

import common  # noqa: E402

paso(".env con PINECONE_API_KEY", lambda: "ok" if "PEGA" not in os.getenv("PINECONE_API_KEY", "PEGA") else 1 / 0)
paso("Ollama instalado", lambda: shutil.which("ollama") or 1 / 0)


def _ollama():
    common.get_embeddings().embed_query("hola")
    if common.LLM_PROVIDER == "ollama":
        common.get_llm().invoke("di ok")
    return f"{common.EMBEDDING_MODEL} y {common.LLM_MODEL} responden"


paso("Ollama responde (abre la app si falla)", _ollama)

import db_config as db  # noqa: E402


def _bd():
    _, f, _ = db.consultar("SELECT COUNT(*) FROM cfg.fact_sdos_captacoloca_m", rol=db.ROL_BD_EMPLEADO)
    return f"{f[0][0]:,} saldos visibles para empleado"


def _rls():
    _, f, _ = db.consultar("SELECT COUNT(DISTINCT num_cte) FROM cfg.fact_sdos_captacoloca_m",
                           rol=db.ROL_BD_CLIENTE, num_cte=42)
    assert f[0][0] == 1, f"el cliente 42 ve {f[0][0]} clientes"
    return "el cliente 42 solo ve sus filas"


def _semantica():
    _, f, _ = db.consultar("""SELECT (SELECT COUNT(*) FROM semantic.sem_validaciones WHERE resultado),
                                     (SELECT COUNT(*) FROM semantic.sem_validaciones),
                                     (SELECT COUNT(*) FROM semantic.sem_relaciones WHERE relacion_validada),
                                     (SELECT COUNT(*) FROM semantic.sem_metricas)""", rol=db.ROL_BD_EMPLEADO)
    ok, total, rel, met = f[0]
    assert total > 0, "capa semántica sin validar: corre .\\run.ps1 load-db"
    assert met == 5, f"solo {met} métricas: revisa sql/semantica/05_load_metrics.sql (versión corregida)"
    assert ok == total, f"{total - ok} validaciones fallaron: SELECT * FROM semantic.sem_validaciones"
    return f"{ok}/{total} validaciones OK, {rel} relaciones validadas, {met} métricas"


paso("Base de datos", _bd)
paso("Row Level Security", _rls)
paso("Capa semántica del socio", _semantica)


def _pinecone():
    import rag_store

    st = rag_store.pinecone_index().describe_index_stats()
    n = st.get("total_vector_count", 0) if isinstance(st, dict) else st.total_vector_count
    assert n > 0, "índice vacío: corre .\\run.ps1 ingest"
    pub = rag_store.buscar("aviso de privacidad derechos ARCO", "cliente")
    assert pub, "sin resultados con audiencia=publico: corre .\\run.ps1 ingest (re-indexa con metadatos nuevos)"
    return f"{n} vectores; filtro de audiencia OK"


paso("Pinecone", _pinecone)
print("\nTodo listo. Corre:  .\\run.ps1 web" if not fallas else f"\nRevisa: {fallas}")