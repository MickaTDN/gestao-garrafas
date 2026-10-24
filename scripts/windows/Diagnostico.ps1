param([int]$Port=8765)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
try {
    $report = Get-GGPreflight -Port $Port
    Write-Host 'Gestao de Garrafas - diagnostico de leitura; nao instala nem altera o Windows.'
    foreach ($check in $report.Checks) {
        $label = if ($check.OK) {'OK'} else {'BLOQUEADO'}
        Write-Host ("{0} - {1}: {2}" -f $label,$check.Code,$check.Message)
    }
    if (-not $report.Ready) {
        Write-Host 'Entregue estes codigos a informatica. Nao execute como administrador nem altere politicas por iniciativa propria.'
        exit 2
    }
    Write-Host 'Pre-requisitos verificados. A porta sera verificada novamente na instalacao.'
    exit 0
} catch {
    Write-Host 'Nao foi possivel concluir o diagnostico. Contacte a informatica.'
    exit 1
}
