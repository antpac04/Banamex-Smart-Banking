# run.ps1 -- Atajos (no hace falta activar el entorno virtual)
#   .\run.ps1 web                         frontend en http://localhost:8501  (RECOMENDADO)
#   .\run.ps1 chat --cliente 42           chat en terminal como cliente (PIN 1234)
#   .\run.ps1 chat --user ana.steward     chat en terminal como empleado (Banamex2026!)
#   .\run.ps1 ask --user ana.steward "pregunta"
#   .\run.ps1 demo --cliente 42           preguntas de demo
#   .\run.ps1 tests                       evaluación con LLM -> docs\RESULTADOS_PRUEBAS.md
#   .\run.ps1 pytest                      pruebas sin LLM (roles, SQL, RLS, servidor MCP)
#   .\run.ps1 check                       diagnóstico
#   .\run.ps1 ingest                      re-indexa rag_documents en Pinecone
#   .\run.ps1 load-db | reload-db | stop-db
#   .\run.ps1 users                       lista usuarios; agregar: .\run.ps1 add-user nombre empleado
#   .\run.ps1 pdfs                        genera PDFs de prueba en pdfs_prueba\ (estado de cuenta de TU base)
#   .\run.ps1 empaquetar                  zip limpio para compartir (sin .env, usuarios ni logs)
param([Parameter(Position = 0)][string]$cmd = "web",
      [Parameter(ValueFromRemainingArguments = $true)]$rest)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$py = Join-Path $env:LOCALAPPDATA "data-steward\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Primero ejecuta: powershell -ExecutionPolicy Bypass -File .\setup.ps1"; exit 1 }
switch ($cmd) {
    "web"       { & $py -m streamlit run app.py @rest }
    "chat"      { & $py src\agent.py -i @rest }
    "ask"       { & $py src\agent.py @rest }
    "demo"      { & $py src\agent.py --demo @rest }
    "tests"     { & $py src\run_test_cases.py @rest }
    "pytest"    { & $py -m pytest -q @rest }
    "check"     { & $py scripts\check_setup.py }
    "ingest"    { & $py src\ingest_governance.py --reset }
    "load-db"   { & $py scripts\load_db.py }
    "reload-db" { & $py scripts\load_db.py --force }
    "stop-db"   { & $py scripts\stop_db.py }
    "users"     { & $py src\auth.py list }
    "add-user"  { & $py src\auth.py add @rest }
    "pdfs"      { & $py scripts\generar_pdfs_prueba.py @rest }
    "empaquetar" { & $py scripts\empaquetar.py }
    default     { Write-Host "Comando desconocido: $cmd (web, chat, ask, demo, tests, pytest, check, ingest, load-db, reload-db, stop-db, users, add-user, pdfs, empaquetar)" }
}