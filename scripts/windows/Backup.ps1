$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
try {
    $destination = Read-Host 'Pasta NOVA para copiar o backup sintetico (noutro suporte autorizado)'
    if (-not [IO.Path]::IsPathRooted($destination) -or $destination.StartsWith('\\')) { throw 'Indique uma pasta local absoluta num suporte autorizado; nao se configuram partilhas externas automaticamente.' }
    Backup-GGPilot -HomePath $PSScriptRoot -Destination $destination
    exit 0
} catch { Write-Host $_.Exception.Message; exit 1 }
