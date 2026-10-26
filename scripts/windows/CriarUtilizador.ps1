$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
try {
    $name = Read-Host 'Escolha o identificador do seu administrador (nao ha conta predefinida)'
    New-GGPilotAccount -HomePath $PSScriptRoot -Username $name
    exit 0
} catch { Write-Host $_.Exception.Message; exit 1 }
