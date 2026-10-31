param([Parameter(Mandatory=$true)][string]$Release)
$ErrorActionPreference = 'Stop'
# Read-only verification in the disposable runner: a global VC runtime must not
# mask the missing app-local dependency again. Never remove/rename system DLLs.
$bin = [IO.Path]::GetFullPath((Join-Path $Release 'postgres\bin'))
$executable = Join-Path $bin 'postgres.exe'
$required = @('vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll')
foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $bin $name) -PathType Leaf)) {
        throw 'Private CRT payload incomplete'
    }
}
$processes = @(Get-Process -Name postgres | Where-Object { $_.Path -eq $executable })
if ($processes.Count -eq 0) { throw 'Packaged PostgreSQL process not found' }
$seen = 0
foreach ($process in $processes) {
    foreach ($module in $process.Modules) {
        if ($required -contains $module.ModuleName) {
            $seen++
            if ([IO.Path]::GetFullPath($module.FileName) -ne (Join-Path $bin $module.ModuleName)) {
                throw 'PostgreSQL loaded CRT outside its reviewed private package'
            }
        }
    }
}
if ($seen -eq 0) { throw 'Could not verify the loaded private CRT' }
Write-Output 'PASS: PostgreSQL loads reviewed app-local CRT without relying on the runner global VC runtime'
