param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Release
)
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
# Query only the stable postmaster, not sessions/backups that can exit while
# enumerating their modules. Its protected PID file is not a credential.
$serverPid = [int](Get-Content -LiteralPath (Join-Path $Root 'cluster\postmaster.pid') -TotalCount 1)
$server = Get-Process -Id $serverPid
if ($server.Path -ne $executable) { throw 'Packaged PostgreSQL process not found' }
$seen = 0
foreach ($module in $server.Modules) {
    if ($required -contains $module.ModuleName) {
        $seen++
        if ([IO.Path]::GetFullPath($module.FileName) -ne (Join-Path $bin $module.ModuleName)) {
            throw 'PostgreSQL loaded CRT outside its reviewed private package'
        }
    }
}
if ($seen -eq 0) { throw 'Could not verify the loaded private CRT' }
Write-Output 'PASS: PostgreSQL loads reviewed app-local CRT without relying on the runner global VC runtime'
