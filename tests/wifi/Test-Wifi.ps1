# Only a disposable checkout, fake TLS bytes and mocked Docker. Never installs anything.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('gg-wifi6-tests-'+[guid]::NewGuid().ToString('N'))
$passed=0
function Test([string]$Name,[scriptblock]$Body) {
    try { & $Body; $script:passed++; Write-Host "PASS $Name" }
    catch { Write-Host ("::error title=Wi-Fi PowerShell::{0}: {1}" -f $Name,$_.Exception.Message); throw }
}
function Assert([bool]$Value) { if (-not $Value) { throw 'Assertion failed' } }
function Refuses([scriptblock]$Body) { $threw=$false;try { & $Body } catch { $threw=$true };Assert $threw }
try {
    $source=Join-Path $temporary 'source'
    foreach ($folder in @('scripts\windows','scripts\windows-wifi','deploy\wifi','deploy\windows')) { $null=New-Item -ItemType Directory -Path (Join-Path $source $folder) -Force }
    Copy-Item (Join-Path $root 'scripts\windows-wifi\Wifi.ps1') (Join-Path $source 'scripts\windows-wifi\Wifi.ps1')
    Copy-Item (Join-Path $root 'deploy\wifi\*') (Join-Path $source 'deploy\wifi')
    Copy-Item (Join-Path $root 'deploy\windows\compose.yaml') (Join-Path $source 'deploy\windows\compose.yaml')
    $global:WifiCalls=New-Object System.Collections.Generic.List[string]
    # Stub only dependencies; the real assistant and its state checks run unchanged.
    @'
function Assert-GGHost { param($Port,[switch]$RuntimeOnly) }
function Assert-GGSeparatePaths { param($HomePath,$SourceRoot)
    if ($HomePath.StartsWith($SourceRoot,[StringComparison]::OrdinalIgnoreCase) -or $SourceRoot.StartsWith($HomePath,[StringComparison]::OrdinalIgnoreCase)) {throw 'Nested paths'}
}
function Protect-GGDirectory { param($Path) }
function New-GGSecret { return [guid]::NewGuid().ToString('N') }
function Write-GGFile { param($Path,$Value) [IO.File]::WriteAllText($Path,$Value,(New-Object Text.UTF8Encoding $false)) }
function Invoke-GGNative { param([string[]]$Arguments,[switch]$Capture)
    $global:WifiCalls.Add(($Arguments|ConvertTo-Json -Compress))
    if ($Capture) {return ''}
}
Export-ModuleMember -Function *
'@ | Set-Content -LiteralPath (Join-Path $source 'scripts\windows\Common.psm1') -Encoding UTF8
    $script=Join-Path $source 'scripts\windows-wifi\Wifi.ps1'
    $tls=Join-Path $temporary 'approved-tls';$null=New-Item -ItemType Directory $tls
    foreach ($name in @('server-chain.crt','server.key','device-ca.crt','device-ca.crl')) { Set-Content (Join-Path $tls $name) 'fake test bytes, never a certificate' }
    $cfg=[pscustomobject]@{Host='garrafas.wifi.test';BindIP='192.168.50.20';Port=8443;ProxySubnet='172.29.86.0/29';ProxyIP='172.29.86.2';AppIP='172.29.86.3';AllowedClients=@('192.168.50.31');TlsSource=$tls}
    $config=Join-Path $temporary 'approved.json'
    function Save-Config { $cfg | ConvertTo-Json | Set-Content -LiteralPath $config -Encoding UTF8 }
    Save-Config
    $homePath=Join-Path $temporary 'private-wifi'
    Test 'Real Wi-Fi script parses under Windows PowerShell 5.1' {
        $tokens=$null;$errors=$null
        $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts\windows-wifi\Wifi.ps1'),[ref]$tokens,[ref]$errors)
        Assert ($errors.Count -eq 0)
    }
    Test 'Preparation requires explicit IT authorization' { Refuses { & $script -Action Prepare -HomePath $homePath -Configuration $config }; Assert (-not (Test-Path $homePath)) }
    Test 'Wildcard bind address is rejected before any installation' {
        $cfg.BindIP='0.0.0.0';Save-Config
        Refuses { & $script -Action Prepare -HomePath $homePath -Configuration $config -ITApproved }
        $cfg.BindIP='192.168.50.20';Save-Config
    }
    Test 'Empty authorized-client list is rejected' {
        $cfg.AllowedClients=@();Save-Config
        Refuses { & $script -Action Prepare -HomePath $homePath -Configuration $config -ITApproved }
        $cfg.AllowedClients=@('192.168.50.31');Save-Config
    }
    Test 'Wildcard DNS is rejected' {
        $cfg.Host='*.wifi.test';Save-Config
        Refuses { & $script -Action Prepare -HomePath $homePath -Configuration $config -ITApproved }
        $cfg.Host='garrafas.wifi.test';Save-Config
    }
    Test 'Duplicate proxy/application addresses are rejected' {
        $cfg.AppIP=$cfg.ProxyIP;Save-Config
        Refuses { & $script -Action Prepare -HomePath $homePath -Configuration $config -ITApproved }
        $cfg.AppIP='172.29.86.3';Save-Config
    }
    Test 'Prepare creates a distinct synthetic namespace and starts no containers' {
        $global:WifiCalls.Clear()
        & $script -Action Prepare -HomePath $homePath -Configuration $config -ITApproved
        $state=Get-Content (Join-Path $homePath 'wifi-installation.json') -Raw | ConvertFrom-Json
        Assert ($state.Project -match '^gg-wifi6-[a-f0-9]{12}$')
        Assert (-not $state.Installed)
        Assert (($global:WifiCalls -join '') -notmatch '"up"|"run"|"build"')
        Assert ((Get-Content (Join-Path $homePath 'nginx.conf') -Raw) -match 'ssl_verify_client on')
    }
    Test 'Preparation never adopts an existing installation' { Refuses { & $script -Action Prepare -HomePath $homePath -Configuration $config -ITApproved } }
    Test 'Start rejects incomplete installation' { Refuses { & $script -Action Start -HomePath $homePath } }
    Test 'Install requires separate authorization' { Refuses { & $script -Action Install -HomePath $homePath } }
    Test 'Authorized install uses reviewed initialization and validates TLS syntax' {
        $global:WifiCalls.Clear()
        & $script -Action Install -HomePath $homePath -ITApproved
        Assert (($global:WifiCalls -join '') -match '"initialize"')
        Assert (($global:WifiCalls -join '') -match '"nginx","-t"')
        Assert (($global:WifiCalls -join '') -notmatch 'firewall|certutil|RunAs')
    }
    Test 'Daily start never builds downloads or migrates' {
        $global:WifiCalls.Clear(); & $script -Action Start -HomePath $homePath
        Assert (($global:WifiCalls -join '') -match '--no-build')
        Assert (($global:WifiCalls -join '') -notmatch '"build"|"migrate"|"initialize"|"pull","proxy"')
    }
    Test 'Changed environment is rejected without Docker mutations' {
        $file=Join-Path $homePath 'wifi.env';$text=[IO.File]::ReadAllText($file)
        [IO.File]::WriteAllText($file,$text+"GG_BIND_IP=0.0.0.0`n")
        $global:WifiCalls.Clear();Refuses { & $script -Action Start -HomePath $homePath }
        Assert ($global:WifiCalls.Count -eq 0);[IO.File]::WriteAllText($file,$text,(New-Object Text.UTF8Encoding $false))
    }
    Test 'Changed TLS blocks Start but Stop preserves volumes and remains available' {
        Add-Content (Join-Path $homePath 'tls\server-chain.crt') 'changed'
        Refuses { & $script -Action Start -HomePath $homePath }
        $global:WifiCalls.Clear();& $script -Action Stop -HomePath $homePath
        Assert (($global:WifiCalls -join '') -match '"stop"')
        Assert (($global:WifiCalls -join '') -notmatch 'down|prune|--volumes')
    }
    Test 'TLS renewal requires separate explicit approval' { Refuses { & $script -Action RenewTLS -HomePath $homePath } }
    Test 'Approved TLS renewal preserves identity and does not restart the proxy' {
        $before=Get-Content (Join-Path $homePath 'wifi-installation.json') -Raw | ConvertFrom-Json
        $global:WifiCalls.Clear();& $script -Action RenewTLS -HomePath $homePath -ITApproved
        $after=Get-Content (Join-Path $homePath 'wifi-installation.json') -Raw | ConvertFrom-Json
        Assert ($before.Project -eq $after.Project -and $before.Instance -eq $after.Instance)
        Assert (($global:WifiCalls -join '') -notmatch '"up"|"initialize"|"migrate"|--volumes')
        Assert (($global:WifiCalls -join '') -match '"nginx","-t"')
    }
    Write-Host "$passed Wi-Fi PowerShell tests passed (Docker/TLS mocked; no deployment)."
} finally {
    Remove-Module Common -ErrorAction SilentlyContinue
    Remove-Variable WifiCalls -Scope Global -ErrorAction SilentlyContinue
    if (Test-Path $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
