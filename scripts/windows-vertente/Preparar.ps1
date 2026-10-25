# Only prepares a NEW private static publisher. Does not start Docker or change policies.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Configuration,
    [string]$HomePath=(Join-Path $env:LOCALAPPDATA 'GestaoGarrafas\VertentePublisher'),
    [switch]$ITApproved
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Import-Module (Join-Path $sourceRoot 'scripts\windows\Common.psm1') -Force
if (-not $ITApproved) { throw 'Preparacao exige autorizacao da informatica: -ITApproved. Nao altera DNS, certificados, firewall ou politicas.' }
$HomePath=[IO.Path]::GetFullPath($HomePath)
Assert-GGSeparatePaths -HomePath $HomePath -SourceRoot $sourceRoot
if ($HomePath.StartsWith('\\') -or (Test-Path -LiteralPath $HomePath)) { throw 'Escolha uma pasta NTFS local NOVA, fora do codigo.' }
$cfg=Get-Content -LiteralPath $Configuration -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($name in @($cfg.Host,$cfg.OfficeHost)) {
    if ($name.Length -gt 253 -or $name -notmatch '^[a-z0-9]+([.-][a-z0-9]+)*\.[a-z0-9]+$') { throw 'Nome DNS invalido.' }
    $ip=$null
    if ([Net.IPAddress]::TryParse($name,[ref]$ip)) { throw 'Use DNS aprovado, nao um IP como hostname.' }
}
if ($cfg.Host -eq $cfg.OfficeHost) { throw 'A consulta exige OUTRO hostname, para separar cookies, armazenamento e service workers.' }
function Assert-PrivateIPv4([string]$Value) {
    $ip=$null
    if (-not [Net.IPAddress]::TryParse($Value,[ref]$ip) -or $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {throw 'IPv4 privada invalida.'}
    $b=$ip.GetAddressBytes()
    if (-not ($b[0]-eq 10 -or ($b[0]-eq 172 -and $b[1]-ge 16 -and $b[1]-le 31) -or ($b[0]-eq 192 -and $b[1]-eq 168))) {throw 'Use apenas uma IPv4 RFC1918 especifica autorizada.'}
}
Assert-PrivateIPv4 $cfg.BindIP
if ([int]$cfg.Port -lt 1024 -or [int]$cfg.Port -gt 65535) {throw 'Porta invalida.'}
if (@($cfg.AllowedClients).Count -eq 0) {throw 'Lista de origens autorizadas vazia.'}
foreach ($client in $cfg.AllowedClients) { Assert-PrivateIPv4 $client }
Assert-GGSeparatePaths -HomePath $cfg.TlsSource -SourceRoot $sourceRoot
foreach ($file in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')) {
    if (-not (Test-Path -LiteralPath (Join-Path $cfg.TlsSource $file) -PathType Leaf)) {throw "Falta ficheiro TLS aprovado: $file"}
}
Assert-GGHost -Port $cfg.Port
$project='gg-va7-'+[guid]::NewGuid().ToString('N').Substring(0,12)
$null=New-Item -ItemType Directory -Path $HomePath
Protect-GGDirectory $HomePath
$null=New-Item -ItemType Directory -Path (Join-Path $HomePath 'tls')
foreach ($file in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')) {Copy-Item -LiteralPath (Join-Path $cfg.TlsSource $file) -Destination (Join-Path $HomePath "tls\$file")}
Write-GGFile (Join-Path $HomePath 'nginx.conf') ([IO.File]::ReadAllText((Join-Path $sourceRoot 'deploy\vertente\nginx.conf.template')).Replace('__HOST__',$cfg.Host))
Write-GGFile (Join-Path $HomePath 'clients.conf') (($cfg.AllowedClients | ForEach-Object {"allow $_;"}) -join "`n")
function Quote-Env([string]$Value) {
    if ($Value -match "[`r`n`"]") {throw 'Caminho invalido.'}
    return "'"+$Value.Replace('\','/').Replace("'","\'")+"'"
}
$envText="VA_PROJECT=$project`nVA_BIND_IP=$($cfg.BindIP)`nVA_HTTPS_PORT=$($cfg.Port)`nVA_SOURCE_ROOT=$(Quote-Env $sourceRoot)`nVA_PRIVATE_ROOT=$(Quote-Env $HomePath)`n"
Write-GGFile (Join-Path $HomePath 'publisher.env') $envText
Write-GGFile (Join-Path $HomePath 'publisher-installation.json') ([pscustomobject]@{Schema=1;Project=$project;Home=$HomePath;Source=$sourceRoot;Config=$cfg}|ConvertTo-Json -Depth 5)
Write-Host 'Publicador preparado; nenhum servico iniciado. A informatica deve rever DNS/SAN, CRL, lista de origens, Compose e firewall antes de iniciar.'
Write-Host ("URL: https://{0}:{1}/" -f $cfg.Host,$cfg.Port)
