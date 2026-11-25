#!/usr/bin/env bash
# Instalación completa (Mac/Linux): bash setup.sh
set -e
cd "$(dirname "$0")"
VENV="${HOME}/.local/share/data-steward/venv"
if [ ! -f .env ]; then cp .env.example .env; echo ">> Se creó .env. Pega tu PINECONE_API_KEY y vuelve a correr: bash setup.sh"; exit 0; fi
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r requirements.txt
"$VENV/bin/python" scripts/setup_all.py
