$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
try { Start-GGPilot -HomePath $PSScriptRoot; exit 0 }
catch { Write-Host $_.Exception.Message; Write-Host 'Execute Diagnostico.cmd. Os dados permanecem guardados.'; exit 1 }
