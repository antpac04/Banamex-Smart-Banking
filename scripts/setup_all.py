"""Deja todo listo (lo llama setup.ps1 / setup.sh): .env, usuarios demo, base, modelos Ollama, Pinecone, check."""
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
resultados = []


def paso(nombre):
    def deco(fn):
        print(f"\n{'=' * 70}\n>> {nombre}\n{'=' * 70}", flush=True)
        try:
            fn()
            resultados.append((nombre, True, ""))
        except SystemExit as e:
            resultados.append((nombre, False, str(e)))
            print("   !!", e)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            resultados.append((nombre, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


@paso("1/7 Archivo .env")
def _env():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
    if "PEGA" in os.getenv("PINECONE_API_KEY", "PEGA"):
        raise SystemExit("Pega tu PINECONE_API_KEY en .env y vuelve a correr el setup.")


@paso("2/7 Usuarios demo")
def _usuarios():
    import auth
    import common

    if not common.USERS_FILE.exists():
        auth.crear_demo()
    print("   Empleados: ana.steward / luis.analista (Banamex2026!) · Clientes: 1-5000 (PIN 1234)")


@paso("3/7 Base de datos (PostgreSQL embebido) + roles + RLS + capa semántica")
def _db():
    import load_db

    load_db.main()


@paso("4/7 Modelos de Ollama")
def _ollama():
    if not shutil.which("ollama"):
        raise SystemExit("Instala Ollama (https://ollama.com/download), ábrelo y vuelve a correr el setup.")
    import common

    modelos = [common.EMBEDDING_MODEL] + ([common.LLM_MODEL] if common.LLM_PROVIDER == "ollama" else [])
    for m in modelos:
        print(f"   ollama pull {m}", flush=True)
        if subprocess.run(["ollama", "pull", m]).returncode != 0:
            raise SystemExit(f"Falló 'ollama pull {m}'. Abre la app de Ollama y reintenta.")


@paso("5/7 RAG: índice Pinecone + ingesta (5-15 min la primera vez)")
def _rag():
    import ingest_governance

    ingest_governance.main(["--reset"])


@paso("6/7 PDFs de prueba (pdfs_prueba/)")
def _pdfs():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generar_pdfs_prueba.py"), "--cliente", "42", "--mes", "202606"],
                   check=True)


@paso("7/7 Diagnóstico")
def _check():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "check_setup.py")])


print(f"\n{'#' * 70}\nRESUMEN\n{'#' * 70}")
for n, ok, msg in resultados:
    print(("[ OK ] " if ok else "[FALLA] ") + n + (f" -> {msg}" if not ok else ""))
print("\nListo. Ejecuta:  .\\run.ps1 web" if all(ok for _, ok, _ in resultados)
      else "\nArregla lo marcado y vuelve a correr el setup (es seguro repetirlo).")