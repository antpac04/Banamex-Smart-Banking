"""Crea un zip LIMPIO del proyecto para compartir (profesor, socio, equipo).
Excluye secretos y archivos locales: .env (claves de Pinecone/Gemini), usuarios con contraseñas, bitácora
de auditoría, cachés y PDFs generados.

    python scripts/empaquetar.py            -> ../Projecto_Agentes_Bananamex_AAAAMMDD.zip
"""
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUIR_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv", "logs", "pdfs_prueba", ".data"}
EXCLUIR_ARCHIVOS = {".env", "users.json"}

destino = ROOT.parent / f"{ROOT.name}_{time.strftime('%Y%m%d')}.zip"
n = 0
with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_dir() or any(parte in EXCLUIR_DIRS for parte in rel.parts) or p.name in EXCLUIR_ARCHIVOS:
            continue
        z.write(p, Path(ROOT.name) / rel)
        n += 1
print(f"{n} archivos -> {destino}")
print("Excluidos: .env, config/users.json, logs/, cachés y pdfs_prueba/. Quien lo reciba corre setup.ps1.")