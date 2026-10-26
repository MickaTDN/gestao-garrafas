$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
try {
    $current = Get-GGInstallation -HomePath $PSScriptRoot
    $archive = Read-Host 'Caminho completo do backup .tar.gz sintetico guardado'
    $newHome = Read-Host 'Pasta NOVA para a copia recuperada (nao a pasta do piloto atual)'
    $portText = Read-Host 'Porta local livre para a copia (por exemplo 8766)'
    $port = 0
    if (-not [int]::TryParse($portText,[ref]$port)) { throw 'Porta invalida.' }
    $state = Recover-GGPilot -Archive $archive -NewHomePath $newHome -SourceRoot $current.Source -Port $port
    Write-Host ('Use Iniciar.cmd na nova pasta: ' + $state.Home)
    exit 0
} catch { Write-Host $_.Exception.Message; Write-Host 'A origem nao foi eliminada. Preserve tambem a tentativa de recuperacao para diagnostico.'; exit 1 }
