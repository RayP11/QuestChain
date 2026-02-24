#Requires -Version 5.1
<#
.SYNOPSIS
    Genie installer for Windows
.DESCRIPTION
    Installs Ollama, Python 3.13, uv, and Genie itself, then registers the
    'genie' command globally so you can run 'genie start' from any terminal.
.NOTES
    Run from the Genie source directory:
        powershell -ExecutionPolicy Bypass -File install.ps1
#>

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Step  { Write-Host "  --> $args" -ForegroundColor Cyan }
function OK    { Write-Host "  OK  $args" -ForegroundColor Green }
function Warn  { Write-Host "  !   $args" -ForegroundColor Yellow }
function Fatal { Write-Host "  ERR $args" -ForegroundColor Red; exit 1 }

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = "$machine;$user"
}

function Winget-Install {
    param([string]$Id, [string]$Label)
    Step "Installing $Label..."
    winget install --id $Id --silent `
        --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    Refresh-Path
    OK "$Label installed"
}

# ── Banner ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ____            _       " -ForegroundColor Magenta
Write-Host " / ___| ___ _ __ (_) ___  " -ForegroundColor Magenta
Write-Host "| |  _ / _ \ '_ \| |/ _ \ " -ForegroundColor Magenta
Write-Host "| |_| |  __/ | | | |  __/ " -ForegroundColor Magenta
Write-Host " \____|\___|_| |_|_|\___| " -ForegroundColor Magenta
Write-Host ""
Write-Host "  Installer" -ForegroundColor DarkGray
Write-Host ""

# ── Check winget ─────────────────────────────────────────────────────────────

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fatal "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
}

# ── Ollama ───────────────────────────────────────────────────────────────────

Step "Checking Ollama..."
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    OK "Ollama already installed ($(ollama --version 2>&1))"
} else {
    Winget-Install "Ollama.Ollama" "Ollama"
}

# ── Python 3.13 ──────────────────────────────────────────────────────────────

Step "Checking Python..."
$pyVersion = python --version 2>&1
if ($pyVersion -match "Python 3\.1[3-9]") {
    OK "Python already installed ($pyVersion)"
} else {
    Winget-Install "Python.Python.3.13" "Python 3.13"
}

# ── uv ───────────────────────────────────────────────────────────────────────

Step "Checking uv..."
if (Get-Command uv -ErrorAction SilentlyContinue) {
    OK "uv already installed ($(uv --version))"
} else {
    Step "Installing uv..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" 2>&1 | Out-Null
    Refresh-Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Fatal "uv installation failed. Try manually: https://docs.astral.sh/uv/getting-started/installation/"
    }
    OK "uv installed ($(uv --version))"
}

# ── Genie ────────────────────────────────────────────────────────────────────

Step "Installing Genie..."
$SourceDir = $PSScriptRoot
if (-not (Test-Path "$SourceDir\pyproject.toml")) {
    Fatal "pyproject.toml not found. Run install.ps1 from the Genie source directory."
}

uv tool install "$SourceDir" --reinstall
if ($LASTEXITCODE -ne 0) { Fatal "uv tool install failed." }
Refresh-Path
OK "Genie installed"

# ── Default model ─────────────────────────────────────────────────────────────

$DefaultModel = "qwen3:8b"

Step "Starting Ollama service..."
# Start ollama serve in the background if not already running
$ollamaRunning = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -UseBasicParsing
    $ollamaRunning = ($resp.StatusCode -eq 200)
} catch {}

if (-not $ollamaRunning) {
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

Step "Pulling default model ($DefaultModel) — this may take a few minutes..."
Warn "You can change the model later with: genie start -m <model-name>"
ollama pull $DefaultModel
if ($LASTEXITCODE -ne 0) { Warn "Model pull failed. Run 'ollama pull $DefaultModel' manually." }
else { OK "Model '$DefaultModel' ready" }

# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Genie is ready!" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Run:" -ForegroundColor DarkGray
Write-Host "      genie start" -ForegroundColor Cyan
Write-Host ""
Warn "If 'genie' is not found, restart your terminal to pick up the updated PATH."
Write-Host ""
