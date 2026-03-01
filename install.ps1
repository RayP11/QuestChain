#Requires -Version 5.1
<#
.SYNOPSIS
    QuestChain installer for Windows
.DESCRIPTION
    Installs Ollama, Python 3.13, uv, and QuestChain itself, then registers the
    'questchain' command globally so you can run 'questchain start' from any terminal.
.NOTES
    Run via PowerShell one-liner:
        powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/RayP11/QuestChain/main/install.ps1 | iex"
#>

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

# -- Helpers ------------------------------------------------------------------

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

# -- Banner -------------------------------------------------------------------

Write-Host ""
Write-Host "  QuestChain" -ForegroundColor Magenta
Write-Host "  ----------- Installer" -ForegroundColor DarkGray
Write-Host ""

# -- Check winget -------------------------------------------------------------

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fatal "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
}

# -- Ollama -------------------------------------------------------------------

Step "Checking Ollama..."
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    OK "Ollama already installed ($(ollama --version 2>&1))"
} else {
    Write-Host ""
    Warn "Ollama is not installed."
    Write-Host "  Install it from: " -NoNewline; Write-Host "https://ollama.com/download" -ForegroundColor Cyan
    Write-Host "  Then run " -NoNewline; Write-Host "ollama serve" -ForegroundColor Cyan -NoNewline; Write-Host " to start it, and re-run this installer."
    Write-Host ""
    exit 1
}

# -- Python 3.13 --------------------------------------------------------------

Step "Checking Python..."
$pyCmd    = Get-Command python -ErrorAction SilentlyContinue
$pyVersion = if ($pyCmd) { python --version 2>&1 } else { "" }
if ($pyVersion -match "Python 3\.1[3-9]") {
    OK "Python already installed ($pyVersion)"
} else {
    Winget-Install "Python.Python.3.13" "Python 3.13"
}

# -- uv -----------------------------------------------------------------------

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

# -- QuestChain ---------------------------------------------------------------

Step "Installing QuestChain..."
uv tool install "git+https://github.com/RayP11/QuestChain" --reinstall
if ($LASTEXITCODE -ne 0) { Fatal "uv tool install failed." }
Refresh-Path
# uv has a known Windows bug where it doesn't always detect its own bin dir on PATH;
# add it explicitly as a fallback so 'questchain' is callable in this session.
$uvBinDir = Join-Path $env:USERPROFILE ".local\bin"
if ((Test-Path $uvBinDir) -and $env:PATH -notlike "*$uvBinDir*") {
    $env:PATH = "$uvBinDir;$env:PATH"
}
OK "QuestChain installed"

# -- Workspace ----------------------------------------------------------------

$WorkspaceDir = Join-Path $env:USERPROFILE "questchain"
$DataDir      = Join-Path $env:USERPROFILE ".questchain"
$DataEnv      = Join-Path $DataDir ".env"

Step "Setting up workspace at $WorkspaceDir..."
New-Item -ItemType Directory -Force -Path (Join-Path $WorkspaceDir "workspace\memory") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $WorkspaceDir "workspace\skills")  | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

# Pin the workspace in ~/.questchain/.env so 'questchain' finds it from any terminal.
$existing = if (Test-Path $DataEnv) { Get-Content $DataEnv -Raw } else { "" }
if ($existing -notmatch "(?m)^QUESTCHAIN_WORKSPACE_DIR=") {
    Add-Content -Path $DataEnv -Value "QUESTCHAIN_WORKSPACE_DIR=$WorkspaceDir"
    OK "Workspace pinned: $WorkspaceDir"
} else {
    OK "Workspace already configured"
}

# -- Ollama running check -----------------------------------------------------

Step "Checking Ollama is running..."
$ollamaRunning = (Test-NetConnection -ComputerName localhost -Port 11434 -InformationLevel Quiet -WarningAction SilentlyContinue)

if (-not $ollamaRunning) {
    Write-Host ""
    Warn "Ollama is not running."
    Write-Host "  Start it with: " -NoNewline; Write-Host "ollama serve" -ForegroundColor Cyan
    Write-Host "  Then re-run this installer."
    Write-Host ""
    exit 1
}
OK "Ollama is running"

# -- Model selection ----------------------------------------------------------

$Models = @(
    @{Name="qwen3:8b";             Vram="~6 GB";   Desc="Fast, excellent tool calling (recommended)"},
    @{Name="qwen3:4b";             Vram="~3 GB";   Desc="Compact — good tool calling, lower VRAM"},
    @{Name="qwen3:1.7b";           Vram="~1.5 GB"; Desc="Ultra-light — runs on CPU or minimal VRAM"},
    @{Name="qwen2.5:7b-instruct";  Vram="~6 GB";   Desc="Top-tier tool calling"},
    @{Name="qwen2.5:14b-instruct"; Vram="~10 GB";  Desc="More capable, higher quality"}
)

Write-Host ""
Write-Host "  Choose a model:" -ForegroundColor Cyan
Write-Host ""
Write-Host ("  {0,-3} {1,-22} {2,-8} {3}" -f "#", "Model", "VRAM", "Description") -ForegroundColor DarkGray
for ($i = 0; $i -lt $Models.Count; $i++) {
    Write-Host ("  {0,-3} {1,-22} {2,-8} {3}" -f "$($i+1).", $Models[$i].Name, $Models[$i].Vram, $Models[$i].Desc)
}
Write-Host ("  {0,-3} {1}" -f "$($Models.Count+1).", "Other — enter a model name manually")
Write-Host ""
$choice = Read-Host "  Enter number (default: 1)"
if (-not $choice) { $choice = "1" }
$idx = [int]$choice - 1
if ($idx -eq $Models.Count) {
    $SelectedModel = Read-Host "  Model name"
    if (-not $SelectedModel) { $SelectedModel = "qwen3:8b" }
} elseif ($idx -lt 0 -or $idx -ge $Models.Count) {
    $SelectedModel = $Models[0].Name
} else {
    $SelectedModel = $Models[$idx].Name
}
Write-Host ""
OK "Selected: $SelectedModel"

Step "Pulling $SelectedModel - this may take a few minutes..."
ollama pull $SelectedModel
if ($LASTEXITCODE -ne 0) { Fatal "Model pull failed. Check your internet connection and try again, or run: ollama pull $SelectedModel" }
OK "Model '$SelectedModel' ready"

# Save chosen model to ~/.questchain/.env
$envContent = if (Test-Path $DataEnv) { Get-Content $DataEnv -Raw } else { "" }
if ($envContent -notmatch "(?m)^OLLAMA_MODEL=") {
    Add-Content -Path $DataEnv -Value "OLLAMA_MODEL=$SelectedModel"
}

# -- Done ---------------------------------------------------------------------

Write-Host ""
Write-Host "  QuestChain is ready!" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Run:" -ForegroundColor DarkGray
Write-Host "      questchain start" -ForegroundColor Cyan
Write-Host ""
Warn "If 'questchain' is not found, restart your terminal to pick up the updated PATH."
Write-Host ""
