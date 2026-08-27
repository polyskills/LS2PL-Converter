<#
.SYNOPSIS
    Installe le service de fetch automatique des exports LightSpeed reçus
    par mail (email_poller.py), en complément du service applicatif
    (install-service.ps1) - même dépôt, même environnement virtuel .venv.

.DESCRIPTION
    A exécuter dans un PowerShell "Exécuter en tant qu'administrateur",
    depuis la RACINE du dépôt cloné, APRES install-service.ps1 (réutilise le
    même .venv).

    Nécessite au préalable les variables d'environnement machine
    (Panneau de configuration > Variables d'environnement système, ou
    [Environment]::SetEnvironmentVariable(..., "Machine")) :
      - LSPENNYLANE_AZURE_CLIENT_ID     : App ID de l'app Azure AD Polyskills
      - LSPENNYLANE_AZURE_CLIENT_SECRET : Secret de cette app
      - LSPENNYLANE_ALERTE_INTERNE      : adresse recevant alertes et récapitulatifs (optionnel)
      - LSPENNYLANE_POLL_INTERVAL_SECONDS : intervalle en secondes (optionnel, défaut 300)

    Le tenant M365 et la boîte mail à interroger se configurent, eux, par
    client dans l'application (page Clients) - pas via ce script.

.PARAMETER ServiceName
    Nom du service Windows créé (par défaut LightspeedPennylaneFetchMail).

.EXAMPLE
    cd C:\Apps\Idees
    .\deploy\windows\install-email-poller-service.ps1
#>
param(
    [string]$ServiceName = "LightspeedPennylaneFetchMail"
)

$ErrorActionPreference = "Stop"
# Sur PowerShell 7.3+, la seule présence d'un écrit sur stderr par un .exe externe (même
# anodin, ex. nssm.exe signalant qu'un service n'existe pas encore) devient par défaut une
# erreur bloquante avec $ErrorActionPreference = "Stop" - sans lien avec le code de sortie
# réel de la commande. Revient au comportement historique (seule une vraie exception .NET ou
# un $LASTEXITCODE vérifié explicitement arrête le script). Ignoré sans effet sur Windows
# PowerShell 5.1, qui ne connaît pas cette variable.
$PSNativeCommandUseErrorActionPreference = $false

function Assert-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Ce script doit être exécuté dans un PowerShell 'Exécuter en tant qu'administrateur'."
    }
}

function Get-RepoRoot {
    $root = Get-Location
    if (-not (Test-Path (Join-Path $root "email_poller.py"))) {
        throw "email_poller.py introuvable dans '$root'. Lancez ce script depuis la RACINE du dépôt cloné."
    }
    return $root
}

Write-Host "=== Service de fetch mail LightSpeed : installation ===" -ForegroundColor Cyan

Assert-Admin
$RepoRoot = Get-RepoRoot

foreach ($var in @("LSPENNYLANE_AZURE_CLIENT_ID", "LSPENNYLANE_AZURE_CLIENT_SECRET")) {
    if (-not [Environment]::GetEnvironmentVariable($var, "Machine")) {
        throw "Variable d'environnement machine manquante : $var. Définissez-la avant de relancer ce script."
    }
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "$VenvPython introuvable - lancez d'abord install-service.ps1 (crée l'environnement virtuel partagé)."
}
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt") --quiet

$ToolsDir = Join-Path $RepoRoot "deploy\windows\tools"
$NssmExe = Join-Path $ToolsDir "nssm.exe"
if (-not (Test-Path $NssmExe)) {
    throw "NSSM introuvable - lancez d'abord install-service.ps1."
}

# Get-Service (cmdlet native PowerShell), pas "nssm status" : sur PowerShell 7.3+,
# $ErrorActionPreference = "Stop" transforme en erreur bloquante tout .exe qui écrit sur
# stderr - y compris "nssm status" sur un service qui n'existe pas encore (cas normal au
# tout premier lancement), et ce même avec 2>$null (la redirection masque le texte mais
# pas la sémantique d'erreur native de PowerShell).
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Write-Host "Le service '$ServiceName' existe déjà : arrêt et suppression avant réinstallation..."
    & $NssmExe stop $ServiceName confirm | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
}

$LogsDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

& $NssmExe install $ServiceName $VenvPython "email_poller.py"
& $NssmExe set $ServiceName AppDirectory $RepoRoot
& $NssmExe set $ServiceName DisplayName "LightSpeed - Fetch mail automatique"
& $NssmExe set $ServiceName Description "Recupere et convertit automatiquement les exports LightSpeed recus par mail"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout (Join-Path $LogsDir "email-poller.out.log")
& $NssmExe set $ServiceName AppStderr (Join-Path $LogsDir "email-poller.err.log")
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppRestartDelay 3000
# NSSM lit les variables d'environnement machine au démarrage du service : rien
# de plus à faire ici tant qu'elles sont définies au niveau "Machine" (pas juste
# "Utilisateur"), sans quoi le service ne les verrait pas.

& $NssmExe start $ServiceName

Start-Sleep -Seconds 3
$status = & $NssmExe status $ServiceName
Write-Host "`n=== Installation terminée ===" -ForegroundColor Green
Write-Host "Statut du service : $status"
Write-Host "Logs                : $LogsDir\email-poller.*.log"
