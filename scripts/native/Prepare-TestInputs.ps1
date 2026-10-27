# CI ONLY. Builds synthetic packages; never supplies a production trust anchor.
param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference='Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This helper is restricted to disposable CI.' }
$null=New-Item -ItemType Directory -Path $Directory
$pythonName='cpython-3.12.16+20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
$pythonUrl='https://github.com/astral-sh/python-build-standalone/releases/download/20261026/'+[uri]::EscapeDataString($pythonName)
$pythonArchive=Join-Path $Directory 'python.tar.gz'
Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonArchive
$pythonHash=(Get-FileHash $pythonArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($pythonHash -ne '1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149') { throw 'Python vendor SHA-256 mismatch' }
# The GitHub image's PostgreSQL is used only for synthetic validation. Release
# builds require separately reviewed PostgreSQL17 + NGINX archives and SHA-256.
$pg=Get-ChildItem 'C:\Program Files\PostgreSQL\17' -ErrorAction Stop
$pgArchive=Join-Path $Directory 'postgres.zip'
Compress-Archive -Path 'C:\Program Files\PostgreSQL\17\bin','C:\Program Files\PostgreSQL\17\lib','C:\Program Files\PostgreSQL\17\share' -DestinationPath $pgArchive
# Official NGINX source over HTTPS, recorded in synthetic provenance. This is
# NOT accepted as an independently reviewed production vendor lock.
$nginxUrl='https://nginx.org/download/nginx-1.30.0.zip'
$nginxArchive=Join-Path $Directory 'nginx.zip'
Invoke-WebRequest -Uri $nginxUrl -OutFile $nginxArchive
@{
 python=@{archive=$pythonArchive;sha256=$pythonHash;version='3.12.16+20261026';source=$pythonUrl}
 postgres=@{archive=$pgArchive;sha256=(Get-FileHash $pgArchive -Algorithm SHA256).Hash.ToLowerInvariant();version='17 (GitHub runner image)';source='https://github.com/actions/runner-images'}
 nginx=@{archive=$nginxArchive;sha256=(Get-FileHash $nginxArchive -Algorithm SHA256).Hash.ToLowerInvariant();version='1.30.0';source=$nginxUrl}
}|ConvertTo-Json -Depth 4|Set-Content -Encoding utf8 (Join-Path $Directory 'inputs.json')
