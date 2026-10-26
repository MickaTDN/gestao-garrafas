# Disposable fake TLS and mocked preflight. No Docker or policy changes.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('gg-va7-shell-'+[guid]::NewGuid().ToString('N'))
$passed=0
function Assert([bool]$OK) {if(-not $OK){throw 'Assertion failed'}}
function Refuses([scriptblock]$Body) {$failed=$false;try{&$Body}catch{$failed=$true};Assert $failed}
function Test([string]$Name,[scriptblock]$Body) {try{&$Body;$script:passed++;Write-Host "PASS $Name"}catch{Write-Host "::error title=Vertente publisher::$Name - $($_.Exception.Message)";throw}}
try {
    $source=Join-Path $temporary 'source'
    foreach($folder in @('scripts\windows','scripts\windows-vertente','deploy\vertente')){$null=New-Item -ItemType Directory (Join-Path $source $folder) -Force}
    Copy-Item (Join-Path $root 'scripts\windows-vertente\Preparar.ps1') (Join-Path $source 'scripts\windows-vertente\Preparar.ps1')
    Copy-Item (Join-Path $root 'deploy\vertente\nginx.conf.template') (Join-Path $source 'deploy\vertente\nginx.conf.template')
    @'
function Assert-GGHost {param($Port)}
function Assert-GGSeparatePaths {param($HomePath,$SourceRoot) if($HomePath.StartsWith($SourceRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'Nested paths'}}
function Protect-GGDirectory {param($Path)}
function Write-GGFile {param($Path,$Value) [IO.File]::WriteAllText($Path,$Value,(New-Object Text.UTF8Encoding $false))}
Export-ModuleMember -Function *
'@ | Set-Content (Join-Path $source 'scripts\windows\Common.psm1') -Encoding UTF8
    $script=Join-Path $source 'scripts\windows-vertente\Preparar.ps1'
    $tls=Join-Path $temporary 'tls';$null=New-Item -ItemType Directory $tls
    foreach($file in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')){Set-Content (Join-Path $tls $file) 'synthetic placeholder'}
    $cfg=[pscustomobject]@{Host='vertente.wifi.test';OfficeHost='garrafas.wifi.test';BindIP='192.168.50.20';Port=8444;AllowedClients=@('192.168.50.31');TlsSource=$tls}
    $configuration=Join-Path $temporary 'config.json';$homePath=Join-Path $temporary 'private'
    function Save {$cfg|ConvertTo-Json|Set-Content $configuration -Encoding UTF8}
    Save
    Test 'PowerShell 5.1 parses real publisher assistant' {$tokens=$null;$errors=$null;$null=[Management.Automation.Language.Parser]::ParseFile($script,[ref]$tokens,[ref]$errors);Assert ($errors.Count-eq 0)}
    Test 'No preparation without explicit IT approval' {Refuses {&$script -Configuration $configuration -HomePath $homePath};Assert (-not(Test-Path $homePath))}
    Test 'Same office hostname rejected' {$cfg.Host=$cfg.OfficeHost;Save;Refuses {&$script -Configuration $configuration -HomePath $homePath -ITApproved};$cfg.Host='vertente.wifi.test';Save}
    Test 'Wildcard bind rejected' {$cfg.BindIP='0.0.0.0';Save;Refuses {&$script -Configuration $configuration -HomePath $homePath -ITApproved};$cfg.BindIP='192.168.50.20';Save}
    Test 'Empty network allowlist rejected' {$cfg.AllowedClients=@();Save;Refuses {&$script -Configuration $configuration -HomePath $homePath -ITApproved};$cfg.AllowedClients=@('192.168.50.31');Save}
    Test 'Private publisher prepared with a distinct namespace and exact hostname' {
        &$script -Configuration $configuration -HomePath $homePath -ITApproved
        Assert ((Get-Content (Join-Path $homePath 'publisher.env') -Raw)-match 'VA_PROJECT=gg-va7-[a-f0-9]{12}')
        Assert ((Get-Content (Join-Path $homePath 'nginx.conf') -Raw)-match 'server_name vertente.wifi.test;')
        Assert (-not(Test-Path (Join-Path $homePath 'signing.pem')))
    }
    Test 'Existing publisher never adopted or overwritten' {Refuses {&$script -Configuration $configuration -HomePath $homePath -ITApproved}}
    Test 'Assistant never starts services or bypasses enterprise policies' {
        $code=[IO.File]::ReadAllText($script)
        Assert ($code-notmatch 'ExecutionPolicy|-Verb RunAs|New-NetFirewallRule|Invoke-GGNative|docker compose up')
    }
    Write-Host "$passed Vertente publisher tests passed; Docker/preflight mocked."
}finally{
    Remove-Module Common -ErrorAction SilentlyContinue
    if(Test-Path $temporary){Remove-Item -LiteralPath $temporary -Recurse -Force}
}
