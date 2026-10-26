param([int]$Port=8765)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
try {
    $source = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'installation.json')) {
        $state = Get-GGInstallation -HomePath $PSScriptRoot
        $source = $state.Source
        $homePath = $PSScriptRoot
    } else { $homePath = Get-GGDefaultHome }
    $installed = Install-GGPilot -SourceRoot $source -HomePath $homePath -Port $Port
    if ((Read-Host 'Deseja criar agora o seu administrador? (S/N)') -eq 'S') {
        $username = Read-Host 'Escolha o identificador (nao existe conta predefinida)'
        New-GGPilotAccount -HomePath $installed.Home -Username $username
    }
    Write-Host ('Pasta privada do piloto: ' + $installed.Home)
    Write-Host 'Use o atalho Gestao de Garrafas - Piloto. Para criar o primeiro administrador, abra CriarUtilizador.cmd na pasta do piloto.'
    exit 0
} catch {
    Write-Host $_.Exception.Message
    Write-Host 'Nao apague volumes, segredos ou a pasta do piloto. A informatica pode retomar a instalacao.'
    exit 1
}
