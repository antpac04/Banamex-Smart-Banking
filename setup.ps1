# setup.ps1 -- Instalación completa (Windows).  Uso: powershell -ExecutionPolicy Bypass -File .\setup.ps1
# El entorno virtual vive FUERA del proyecto (%LOCALAPPDATA%\data-steward\venv) para evitar líos con OneDrive.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$venv = Join-Path $env:LOCALAPPDATA "data-steward\venv"
$py   = Join-Path $venv "Scripts\python.exe"
function Run($exe, $argList) { & $exe @argList; if ($LASTEXITCODE -ne 0) { throw "Fallo: $exe $($argList -join ' ')" } }

if (-not (Test-Path (Join-Path $root ".env"))) {
    Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
    Write-Host ">> Se creo .env. Pega tu PINECONE_API_KEY, guarda y vuelve a correr este script." -ForegroundColor Yellow
    notepad (Join-Path $root ".env"); exit 0
}
if (-not (Test-Path $py)) { Write-Host ">> Creando entorno virtual en $venv" -ForegroundColor Cyan; Run "python" @("-m", "venv", $venv) }
Write-Host ">> Instalando dependencias" -ForegroundColor Cyan
Run $py @("-m", "pip", "install", "--upgrade", "pip")
Run $py @("-m", "pip", "install", "-r", (Join-Path $root "requirements.txt"))
Run $py @((Join-Path $root "scripts\setup_all.py"))
