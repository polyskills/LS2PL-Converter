<#
.SYNOPSIS
    Désinstalle le service Windows du convertisseur LightSpeed -> Pennylane
    (arrête et supprime le service NSSM + la règle de pare-feu associée).

    N'efface PAS les données (data\clients\), le code, ni l'environnement
    virtuel (.venv) : seule la couche "service" est retirée.

.EXAMPLE
    cd C:\Apps\Idees
    .\deploy\windows\uninstall-service.ps1
    .\deploy\windows\uninstall-service.ps1 -Port 8080 -ServiceName "LSPennylaneProd"
#>
param(
    [int]$Port = 8501,
    [string]$ServiceName = "LightspeedPennylane"
)

$ErrorActionPreference = "Stop"
# Sur PowerShell 7.3+, la seule présence d'un écrit sur stderr par un .exe externe (même
# anodin, ex. nssm.exe signalant qu'un service déjà arrêté/absent) devient par défaut une
# erreur bloquante avec $ErrorActionPreference = "Stop" — sans lien avec le code de sortie
# réel de la commande. Revient au comportement historique. Ignoré sans effet sur Windows
# PowerShell 5.1.
$PSNativeCommandUseErrorActionPreference = $false

$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ce script doit être exécuté dans un PowerShell 'Exécuter en tant qu'administrateur'."
}

$NssmExe = Join-Path (Get-Location) "deploy\windows\tools\nssm.exe"
if (-not (Test-Path $NssmExe)) {
    throw "NSSM introuvable ($NssmExe). Lancez ce script depuis la racine du dépôt."
}

Write-Host "Arrêt et suppression du service '$ServiceName'..." -ForegroundColor Cyan
& $NssmExe stop $ServiceName confirm 2>$null | Out-Null
& $NssmExe remove $ServiceName confirm 2>$null | Out-Null

$ruleName = "LightSpeed-Pennylane ($Port)"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName $ruleName
    Write-Host "Règle de pare-feu supprimée."
}

Write-Host "Service désinstallé. Le code, .venv et data\clients\ sont conservés." -ForegroundColor Green
