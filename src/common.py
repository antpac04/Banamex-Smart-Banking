"""Configuración compartida: .env, LLM y embeddings (Ollama por defecto)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pruebas sin dependencias instaladas
    pass

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1:latest")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))  # bge-m3 = 1024
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))  # Ollama usa 2048-4096 si no se indica
INDEX_NAME = os.getenv("INDEX_NAME", "rag-governance")
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.5"))
TOP_K = int(os.getenv("RAG_TOP_K", "4"))
SQL_LIBRE = os.getenv("SQL_LIBRE", "0") == "1"  # Text-to-SQL libre para colaboradores (apagado por defecto)

DOCS_DIR = ROOT / "rag_documents"
USERS_FILE = ROOT / "config" / "users.json"
AUDIT_FILE = Path(os.getenv("STEWARD_AUDIT_FILE", str(ROOT / "logs" / "audit.jsonl")))
MAX_FILAS = int(os.getenv("MAX_FILAS", "200"))
MESES_CON_DATOS = ["202601", "202602", "202603", "202604", "202605", "202606"]
PYTHON = sys.executable


def get_llm(temperature: float = 0.0):
    """LLM configurable sin tocar código: LLM_PROVIDER=ollama | google | anthropic."""
    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=LLM_MODEL, temperature=temperature, num_ctx=OLLAMA_NUM_CTX)
    if LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=LLM_MODEL, temperature=temperature)
    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=LLM_MODEL, temperature=temperature)
    raise ValueError(f"LLM_PROVIDER no soportado: {LLM_PROVIDER}")


def get_embeddings():
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=EMBEDDING_MODEL)


def texto_de(contenido) -> str:
    """El contenido de un mensaje/tool puede venir como str o lista de bloques."""
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        partes = []
        for b in contenido:
            if isinstance(b, str):
                partes.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                partes.append(b.get("text", ""))
            elif hasattr(b, "text"):
                partes.append(b.text)
        return "".join(partes)
    return str(contenido)