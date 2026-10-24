# PowerShell 5.1. No elevation, certificate installation, DNS or firewall changes.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Prepare','Install','Start','Stop','Diagnose','Account','Backup','RenewTLS')][string]$Action,
    [string]$HomePath=(Join-Path $env:LOCALAPPDATA 'GestaoGarrafas\WifiSintetico'),
    [string]$Configuration,
    [string]$Username,
    [string]$Destination,
    [switch]$ITApproved
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Import-Module (Join-Path $sourceRoot 'scripts\windows\Common.psm1') -Force

function Quote-Env([string]$Value) {
    if ($Value -match "[`r`n`"]") { throw 'Valor de ambiente invalido.' }
    return "'"+$Value.Replace('\','/').Replace("'","\'")+"'"
}
function Assert-PrivateIPv4([string]$Value) {
    $ip=$null
    if (-not [Net.IPAddress]::TryParse($Value,[ref]$ip) -or $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'IPv4 privada invalida.' }
    $b=$ip.GetAddressBytes()
    if (-not ($b[0] -eq 10 -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or ($b[0] -eq 192 -and $b[1] -eq 168))) { throw 'Use uma IPv4 RFC1918 especifica autorizada, nunca wildcard/Internet/loopback.' }
}
function IPv4-Number([string]$Value) {
    $bytes=([Net.IPAddress]::Parse($Value)).GetAddressBytes()
    return [uint64]$bytes[0]*16777216+[uint64]$bytes[1]*65536+[uint64]$bytes[2]*256+[uint64]$bytes[3]
}
function Expected-Env($State) {
    $cfg=$State.Config
    $lines=@(
        "GG_PILOT_ID=$($State.Instance)","GG_PILOT_IMAGE=$($State.Project):stage6",
        ('GG_SOURCE_ROOT='+(Quote-Env $State.Source)),
        ('GG_SECRET_ROOT='+(Quote-Env (Join-Path $State.Home 'secrets'))),
        ('GG_WIFI_PRIVATE_ROOT='+(Quote-Env $State.Home)),
        "GG_WIFI_HOST=$($cfg.Host)","GG_BIND_IP=$($cfg.BindIP)","GG_HTTPS_PORT=$($cfg.Port)",
        "GG_PROXY_SUBNET=$($cfg.ProxySubnet)","GG_PROXY_IP=$($cfg.ProxyIP)","GG_APP_IP=$($cfg.AppIP)"
    )
    return ($lines -join "`n")+"`n"
}
function Invoke-Wifi($State,[string[]]$Arguments) {
    Invoke-GGNative -Arguments (@('compose','--project-name',$State.Project,'--file',(Join-Path $State.Source 'deploy\wifi\compose.yaml'),'--env-file',(Join-Path $State.Home 'wifi.env'))+$Arguments)
}
function File-Hashes($HomeDirectory,$SourceDirectory) {
    $paths=@((Join-Path $SourceDirectory 'deploy\wifi\compose.yaml'),(Join-Path $SourceDirectory 'deploy\windows\compose.yaml'),(Join-Path $HomeDirectory 'nginx.conf'),(Join-Path $HomeDirectory 'clients.conf'))
    foreach ($file in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')) { $paths+=Join-Path $HomeDirectory "tls\$file" }
    return @($paths | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
}

$HomePath=[IO.Path]::GetFullPath($HomePath)
Assert-GGSeparatePaths -HomePath $HomePath -SourceRoot $sourceRoot
if ($HomePath.StartsWith('\\')) { throw 'Use uma pasta privada NTFS local.' }
$stateFile=Join-Path $HomePath 'wifi-installation.json'
if ($Action -eq 'Prepare') {
    if (-not $ITApproved) { throw 'Prepare exige -ITApproved apenas depois de autorizacao da informatica para certificados, DNS e rede.' }
    if (Test-Path -LiteralPath $HomePath) { throw 'Use uma pasta NOVA. Nao se adota o piloto local nem outra instalacao.' }
    $cfg=Get-Content -LiteralPath $Configuration -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.Host.Length -gt 253 -or $cfg.Host -notmatch '^[a-z0-9]+([.-][a-z0-9]+)*\.[a-z0-9]+$') { throw 'Nome DNS aprovado invalido.' }
    $hostIP=$null
    if ([Net.IPAddress]::TryParse($cfg.Host,[ref]$hostIP)) { throw 'Use o DNS do certificado, nao um IP como hostname.' }
    Assert-PrivateIPv4 $cfg.BindIP
    Assert-PrivateIPv4 $cfg.ProxyIP
    Assert-PrivateIPv4 $cfg.AppIP
    if ($cfg.AppIP -eq $cfg.ProxyIP) { throw 'Proxy e aplicacao exigem IPs internos distintos.' }
    if ($cfg.Port -lt 1024 -or $cfg.Port -gt 65535 -or $cfg.ProxySubnet -notmatch '^([0-9]{1,3}\.){3}[0-9]{1,3}/29$') { throw 'Porta/rede interna /29 invalida.' }
    $networkIP=$cfg.ProxySubnet.Split('/')[0]
    Assert-PrivateIPv4 $networkIP
    $networkNumber=IPv4-Number $networkIP
    if ($networkNumber % 8 -ne 0 -or (IPv4-Number $cfg.ProxyIP) -ne ($networkNumber+2) -or (IPv4-Number $cfg.AppIP) -ne ($networkNumber+3)) { throw 'Rede /29 deve ter proxy no segundo IP util e aplicacao no terceiro, sem sobreposicao.' }
    if (@($cfg.AllowedClients).Count -eq 0) { throw 'A lista de origens autorizadas nao pode estar vazia.' }
    foreach ($client in $cfg.AllowedClients) { Assert-PrivateIPv4 $client }
    Assert-GGSeparatePaths -HomePath $cfg.TlsSource -SourceRoot $sourceRoot
    foreach ($file in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')) {
        if (-not (Test-Path -LiteralPath (Join-Path $cfg.TlsSource $file) -PathType Leaf)) { throw "Falta ficheiro TLS aprovado: $file" }
    }
    Assert-GGHost -Port $cfg.Port
    $instance=[guid]::NewGuid()
    $state=[pscustomobject]@{Schema=1;Mode='synthetic-wifi-v1';Instance=$instance.ToString();Project=('gg-wifi6-'+$instance.ToString('N').Substring(0,12));Home=$HomePath;Source=$sourceRoot;Config=$cfg;Hashes=@();Installed=$false}
    $existing=Invoke-GGNative -Capture -Arguments @('volume','ls','--quiet','--filter',('label=com.docker.compose.project='+$state.Project))
    if (-not [string]::IsNullOrWhiteSpace($existing)) { throw 'Namespace ja existente. Nenhum volume foi adotado.' }
    $null=New-Item -ItemType Directory -Path $HomePath
    Protect-GGDirectory $HomePath
    $null=New-Item -ItemType Directory -Path (Join-Path $HomePath 'secrets')
    $null=New-Item -ItemType Directory -Path (Join-Path $HomePath 'tls')
    foreach ($secret in @('django_key','db_owner_password','db_app_password')) { Write-GGFile (Join-Path $HomePath "secrets\$secret") ((New-GGSecret)+"`n") }
    foreach ($file in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')) { Copy-Item -LiteralPath (Join-Path $cfg.TlsSource $file) -Destination (Join-Path $HomePath "tls\$file") }
    $template=[IO.File]::ReadAllText((Join-Path $sourceRoot 'deploy\wifi\nginx.conf.template'))
    Write-GGFile (Join-Path $HomePath 'nginx.conf') ($template.Replace('__HOST__',$cfg.Host).Replace('__PORT__',[string]$cfg.Port))
    Write-GGFile (Join-Path $HomePath 'clients.conf') (($cfg.AllowedClients | ForEach-Object { "allow $_;" }) -join "`n")
    Write-GGFile (Join-Path $HomePath 'wifi.env') (Expected-Env $state)
    $state.Hashes=File-Hashes $HomePath $sourceRoot
    Write-GGFile $stateFile ($state | ConvertTo-Json -Depth 5)
    Write-Host 'Configuracao sintetica preparada. Nenhuma porta foi aberta, nenhum contentor iniciado. A informatica deve rever antes de Install.'
    return
}
$state=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
$uuid=[guid]::Empty
if ($state.Schema -ne 1 -or $state.Mode -ne 'synthetic-wifi-v1' -or -not [guid]::TryParse($state.Instance,[ref]$uuid) -or $state.Project -ne ('gg-wifi6-'+$uuid.ToString('N').Substring(0,12)) -or $state.Home -ne $HomePath -or $state.Source -ne $sourceRoot) { throw 'Estado Wi-Fi invalido; execucao recusada.' }
if ([IO.File]::ReadAllText((Join-Path $HomePath 'wifi.env')) -ne (Expected-Env $state)) { throw 'Ambiente modificado. Recusado sem alterar dados.' }
# Stop remains available even when a certificate expires or is being replaced.
Assert-GGHost -Port $state.Config.Port -RuntimeOnly
if ($Action -eq 'Stop') { Invoke-Wifi $state @('stop','--timeout','45','proxy','app','db'); return }
if ($Action -eq 'RenewTLS') {
    if (-not $ITApproved) { throw 'Renovar TLS exige -ITApproved apos revisao da informatica.' }
    $currentHashes=File-Hashes $HomePath $sourceRoot
    if (($state.Hashes[0..3] -join '|') -cne ($currentHashes[0..3] -join '|')) { throw 'A renovacao de TLS nao aceita alterar Compose, hostname ou lista de origens.' }
    Assert-GGSeparatePaths -HomePath $state.Config.TlsSource -SourceRoot $sourceRoot
    Invoke-Wifi $state @('stop','--timeout','45','proxy')
    foreach ($file in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')) {
        Copy-Item -LiteralPath (Join-Path $state.Config.TlsSource $file) -Destination (Join-Path $HomePath "tls\$file")
    }
    Invoke-Wifi $state @('run','--rm','--no-deps','proxy','nginx','-t')
    $state.Hashes=File-Hashes $HomePath $sourceRoot
    Write-GGFile $stateFile ($state | ConvertTo-Json -Depth 5)
    Write-Host 'TLS revisto e validado; proxy continua parado. Execute Start apenas apos validacao de confianca/revogacao pela informatica.'
    return
}
if (($state.Hashes -join '|') -cne ((File-Hashes $HomePath $sourceRoot) -join '|')) { throw 'Configuracao/certificados alterados. Pare o perfil e peca revisao a informatica; nao se aceita uma alteracao silenciosa.' }
foreach ($secret in @('django_key','db_owner_password','db_app_password')) { if (-not (Test-Path -LiteralPath (Join-Path $HomePath "secrets\$secret"))) { throw 'Segredo em falta; nao regenerar.' } }
if ($Action -eq 'Install') {
    if (-not $ITApproved) { throw 'Install exige autorizacao previa -ITApproved. Nao altera firewall/DNS/certificados do Windows.' }
    Invoke-Wifi $state @('build','app')
    Invoke-Wifi $state @('pull','proxy')
    Invoke-Wifi $state @('up','--detach','--wait','--wait-timeout','120','db')
    Invoke-Wifi $state @('--profile','setup','run','--rm','initialize')
    Invoke-Wifi $state @('up','--no-build','--pull','never','--detach','--wait','--wait-timeout','180','app')
    Invoke-Wifi $state @('run','--rm','--no-deps','proxy','nginx','-t')
    Invoke-Wifi $state @('up','--no-build','--pull','never','--detach','proxy')
    $state.Installed=$true
    Write-GGFile $stateFile ($state | ConvertTo-Json -Depth 5)
} elseif ($Action -eq 'Start') {
    if (-not $state.Installed) { throw 'Instalacao incompleta. Retome Install, preserve volumes.' }
    Invoke-Wifi $state @('up','--no-build','--pull','never','--detach','--wait','--wait-timeout','180','db','app','proxy')
} elseif ($Action -eq 'Account') {
    if ($Username -notmatch '^[A-Za-z0-9_.@+-]{1,150}$') { throw 'Identificador invalido.' }
    Invoke-Wifi $state @('exec','app','python','manage.py','create_user',$Username,'--role','admin')
} elseif ($Action -eq 'Backup') {
    Assert-GGSeparatePaths -HomePath $Destination -SourceRoot $sourceRoot
    if (-not [IO.Path]::IsPathRooted($Destination) -or $Destination.StartsWith('\\') -or (Test-Path -LiteralPath $Destination)) { throw 'Escolha uma pasta NTFS local NOVA fora do codigo.' }
    Invoke-Wifi $state @('exec','-T','app','python','manage.py','backup_data','--synthetic')
    $null=New-Item -ItemType Directory -Path $Destination
    Protect-GGDirectory $Destination
    Invoke-Wifi $state @('cp','app:/backups/.',$Destination)
} else {
    Invoke-Wifi $state @('ps')
    Invoke-Wifi $state @('exec','-T','app','env','DJANGO_SETTINGS_MODULE=config.windows_local','python','/app/deploy/windows/pilot.py','status')
    Invoke-Wifi $state @('exec','-T','proxy','nginx','-t')
}
Write-Host ("Perfil sintetico. Valide HTTPS no browser com certificado de dispositivo: https://{0}:{1}/" -f $state.Config.Host,$state.Config.Port)
