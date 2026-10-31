# CI ONLY. Builds synthetic packages; never supplies a production trust anchor.
param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
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
& tar.exe -a -cf $pgArchive -C 'C:\Program Files\PostgreSQL\17' bin lib share
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL binary archive failed' }
# Official NGINX source over HTTPS, recorded in synthetic provenance. This is
# NOT accepted as an independently reviewed production vendor lock.
$nginxUrl='https://nginx.org/download/nginx-1.30.0.zip'
$nginxArchive=Join-Path $Directory 'nginx.zip'
Invoke-WebRequest -Uri $nginxUrl -OutFile $nginxArchive
# Only the licensed, release x64 CRT redistributable directory, not arbitrary
# System32 files. Production inputs require independent IT review/hash approval.
$vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs=& $vswhere -latest -products '*' -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw 'Visual Studio redistributable source unavailable' }
$redist=Join-Path $vs 'VC\Redist\MSVC'
$crt=Get-ChildItem $redist -Directory | Sort-Object Name -Descending | ForEach-Object {
 Get-ChildItem (Join-Path $_.FullName 'x64') -Directory -Filter 'Microsoft.VC*.CRT' -ErrorAction SilentlyContinue
} | Select-Object -First 1
if (-not $crt) { throw 'Approved x64 release CRT directory unavailable' }
$dlls=@(Get-ChildItem $crt.FullName -Filter '*.dll' -File)
$signers=@()
foreach ($dll in $dlls) {
 $sig=Get-AuthenticodeSignature -LiteralPath $dll.FullName
 if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Untrusted Microsoft runtime' }
 $h=[Security.Cryptography.SHA256]::Create()
 $signers+=([BitConverter]::ToString($h.ComputeHash($sig.SignerCertificate.RawData))).Replace('-','').ToLowerInvariant()
}
$crtArchive=Join-Path $Directory 'msvc.zip'
& tar.exe -a -cf $crtArchive -C $crt.FullName @($dlls.Name)
if ($LASTEXITCODE -ne 0) { throw 'CRT archive failed' }
@{
 msvc=@{archive=$crtArchive;sha256=(Get-FileHash $crtArchive -Algorithm SHA256).Hash.ToLowerInvariant();version=$crt.Parent.Parent.Name;source='https://github.com/actions/runner-images';signers_sha256=@($signers|Select-Object -Unique)}
 python=@{archive=$pythonArchive;sha256=$pythonHash;version='3.12.16+20261026';source=$pythonUrl}
 postgres=@{archive=$pgArchive;sha256=(Get-FileHash $pgArchive -Algorithm SHA256).Hash.ToLowerInvariant();version='17 (GitHub runner image)';source='https://github.com/actions/runner-images'}
 nginx=@{archive=$nginxArchive;sha256=(Get-FileHash $nginxArchive -Algorithm SHA256).Hash.ToLowerInvariant();version='1.30.0';source=$nginxUrl}
}|ConvertTo-Json -Depth 4|Set-Content -Encoding utf8 (Join-Path $Directory 'inputs.json')
