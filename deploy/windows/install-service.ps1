<#
.SYNOPSIS
    Installe le convertisseur LightSpeed -> Pennylane comme service Windows
    (démarrage automatique au boot, redémarre seul en cas de plantage),
    via NSSM (Non-Sucking Service Manager).

.DESCRIPTION
    A exécuter dans un PowerShell "Exécuter en tant qu'administrateur",
    depuis la RACINE du dépôt cloné (le dossier qui contient app.py).

    Le script :
      1. Vérifie Python (3.10+) et le crée un environnement virtuel .venv
      2. Installe les dépendances (requirements.txt)
      3. Télécharge NSSM si absent
      4. Enregistre le service Windows et le démarre
      5. Ouvre le port dans le pare-feu Windows

.PARAMETER Port
    Port TCP sur lequel l'application écoute (par défaut 8501).

.PARAMETER ServiceName
    Nom du service Windows créé (par défaut LightspeedPennylane).

.EXAMPLE
    cd C:\Apps\Idees
    .\deploy\windows\install-service.ps1
    .\deploy\windows\install-service.ps1 -Port 8080 -ServiceName "LSPennylaneProd"
#>
param(
    [int]$Port = 8501,
    [string]$ServiceName = "LightspeedPennylane"
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Ce script doit être exécuté dans un PowerShell 'Exécuter en tant qu'administrateur'."
    }
}

function Get-RepoRoot {
    $root = Get-Location
    if (-not (Test-Path (Join-Path $root "app.py"))) {
        throw "app.py introuvable dans '$root'. Lancez ce script depuis la RACINE du dépôt cloné (ex: cd C:\Apps\Idees)."
    }
    return $root
}

Write-Host "=== Convertisseur LightSpeed -> Pennylane : installation en service Windows ===" -ForegroundColor Cyan

Assert-Admin
$RepoRoot = Get-RepoRoot
Write-Host "Dossier de l'application : $RepoRoot"

# --- 1. Python -----------------------------------------------------------
Write-Host "`n[1/5] Vérification de Python..." -ForegroundColor Cyan
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    throw "Python introuvable dans le PATH. Installez-le d'abord, par exemple : winget install Python.Python.3.12"
}
$pyVersion = & python --version
Write-Host "Python détecté : $pyVersion"

$VenvDir = Join-Path $RepoRoot ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "Création de l'environnement virtuel (.venv)..."
    & python -m venv $VenvDir
} else {
    Write-Host "Environnement virtuel déjà présent (.venv)."
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Échec de création de l'environnement virtuel : $VenvPython introuvable."
}

# --- 2. Dépendances --------------------------------------------------------
Write-Host "`n[2/5] Installation des dépendances (requirements.txt)..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt") --quiet
Write-Host "Dépendances installées."

# --- 3. NSSM ---------------------------------------------------------------
Write-Host "`n[3/5] Vérification de NSSM..." -ForegroundColor Cyan
$ToolsDir = Join-Path $RepoRoot "deploy\windows\tools"
$NssmExe = Join-Path $ToolsDir "nssm.exe"

if (-not (Test-Path $NssmExe)) {
    Write-Host "NSSM absent, téléchargement depuis nssm.cc..."
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $NssmZip = Join-Path $ToolsDir "nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip
    Expand-Archive -Path $NssmZip -DestinationPath $ToolsDir -Force
    $arch = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
    Copy-Item (Join-Path $ToolsDir "nssm-2.24\$arch\nssm.exe") $NssmExe -Force
    Remove-Item $NssmZip -Force
    Remove-Item (Join-Path $ToolsDir "nssm-2.24") -Recurse -Force
    Write-Host "NSSM installé dans $NssmExe"
} else {
    Write-Host "NSSM déjà présent : $NssmExe"
}

# --- 4. Service Windows ------------------------------------------------------
Write-Host "`n[4/5] Enregistrement du service '$ServiceName'..." -ForegroundColor Cyan

$existing = & $NssmExe status $ServiceName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Le service '$ServiceName' existe déjà : arrêt et suppression avant réinstallation..."
    & $NssmExe stop $ServiceName confirm | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
}

$LogsDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

$streamlitArgs = "-m streamlit run app.py --server.port $Port --server.address 0.0.0.0 --server.headless true"

& $NssmExe install $ServiceName $VenvPython $streamlitArgs
& $NssmExe set $ServiceName AppDirectory $RepoRoot
& $NssmExe set $ServiceName DisplayName "LightSpeed vers Pennylane"
& $NssmExe set $ServiceName Description "Convertisseur LightSpeed vers Pennylane (Streamlit) - port $Port"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout (Join-Path $LogsDir "service.out.log")
& $NssmExe set $ServiceName AppStderr (Join-Path $LogsDir "service.err.log")
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppRestartDelay 3000

& $NssmExe start $ServiceName
Write-Host "Service '$ServiceName' démarré."

# --- 5. Pare-feu -------------------------------------------------------------
Write-Host "`n[5/5] Ouverture du port $Port dans le pare-feu Windows..." -ForegroundColor Cyan
$ruleName = "LightSpeed-Pennylane ($Port)"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    Write-Host "Règle de pare-feu créée pour le port $Port."
} else {
    Write-Host "Règle de pare-feu déjà présente pour le port $Port."
}

Start-Sleep -Seconds 3
$status = & $NssmExe status $ServiceName
Write-Host "`n=== Installation terminée ===" -ForegroundColor Green
Write-Host "Statut du service : $status"
Write-Host "Accès local        : http://localhost:$Port"
Write-Host "Accès réseau       : http://$($env:COMPUTERNAME):$Port  (ou http://<IP du serveur>:$Port)"
Write-Host "Logs                : $LogsDir"
