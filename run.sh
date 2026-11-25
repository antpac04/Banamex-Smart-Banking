#!/usr/bin/env bash
# ./run.sh web | chat --cliente 42 | chat --user ana.steward | ask ... | demo ... | tests | pytest | check | ingest | load-db | reload-db | stop-db
cd "$(dirname "$0")"
PY="${HOME}/.local/share/data-steward/venv/bin/python"
[ -x "$PY" ] || { echo "Primero ejecuta: bash setup.sh"; exit 1; }
cmd="${1:-web}"; shift || true
case "$cmd" in
  web) "$PY" -m streamlit run app.py "$@" ;;
  chat) "$PY" src/agent.py -i "$@" ;;
  ask) "$PY" src/agent.py "$@" ;;
  demo) "$PY" src/agent.py --demo "$@" ;;
  tests) "$PY" src/run_test_cases.py "$@" ;;
  pytest) "$PY" -m pytest -q "$@" ;;
  check) "$PY" scripts/check_setup.py ;;
  ingest) "$PY" src/ingest_governance.py --reset ;;
  load-db) "$PY" scripts/load_db.py ;;
  reload-db) "$PY" scripts/load_db.py --force ;;
  stop-db) "$PY" scripts/stop_db.py ;;
  users) "$PY" src/auth.py list ;;
  add-user) "$PY" src/auth.py add "$@" ;;
  pdfs) "$PY" scripts/generar_pdfs_prueba.py "$@" ;;
  empaquetar) "$PY" scripts/empaquetar.py ;;
  *) echo "Comando desconocido: $cmd" ;;
esac