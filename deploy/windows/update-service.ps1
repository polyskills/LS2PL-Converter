<#
.SYNOPSIS
    Met à jour l'application (git pull + dépendances) puis redémarre le
    service Windows.

.EXAMPLE
    cd C:\Apps\Idees
    .\deploy\windows\update-service.ps1
#>
param(
    [string]$ServiceName = "LightspeedPennylane",
    [string]$Branch = "claude/lightspeed-pennylane-converter-njmeyd"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Get-Location
if (-not (Test-Path (Join-Path $RepoRoot "app.py"))) {
    throw "app.py introuvable dans '$RepoRoot'. Lancez ce script depuis la racine du dépôt."
}

$NssmExe = Join-Path $RepoRoot "deploy\windows\tools\nssm.exe"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Write-Host "Arrêt du service '$ServiceName'..." -ForegroundColor Cyan
& $NssmExe stop $ServiceName confirm | Out-Null

Write-Host "Récupération de la dernière version (branche $Branch)..." -ForegroundColor Cyan
git fetch origin $Branch
git checkout $Branch
git pull origin $Branch

Write-Host "Mise à jour des dépendances..." -ForegroundColor Cyan
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt") --quiet

Write-Host "Redémarrage du service..." -ForegroundColor Cyan
& $NssmExe start $ServiceName

Write-Host "Terminé. Vérifiez le hash de version affiché dans le menu latéral de l'application." -ForegroundColor Green
