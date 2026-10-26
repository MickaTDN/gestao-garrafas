$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
try { Stop-GGPilot -HomePath $PSScriptRoot; exit 0 }
catch { Write-Host $_.Exception.Message; exit 1 }
