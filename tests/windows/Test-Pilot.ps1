# Dependency-free tests on a disposable CI Windows runner. Never installs Docker/WSL.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$script:Passed = 0
$script:Failed = New-Object System.Collections.Generic.List[string]
function Assert-True($condition,$message='Assertion failed') { if (-not $condition) { throw $message } }
function Assert-Throws([scriptblock]$action) { $thrown=$false; try { & $action } catch {$thrown=$true}; Assert-True $thrown 'Expected refusal did not occur' }
function Test([string]$name,[scriptblock]$body) {
    try { & $body; $script:Passed++; Write-Host ('PASS '+$name) }
    catch { $script:Failed.Add($name); $message=($name+': '+$_.Exception.Message).Replace("`r",' ').Replace("`n",' '); Write-Host ('FAIL '+$message); Write-Host ('::error title=Windows safeguard test::'+$message) }
}
$temporary = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('Temp\gg-pilot-tests-'+[guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $temporary
$oldDockerHost = $env:DOCKER_HOST
try {
    Test 'All scripts parse in Windows PowerShell' {
        foreach ($path in @(Get-ChildItem (Join-Path $root 'scripts\windows') -Include *.ps1,*.psm1 -Recurse)) {
            $tokens=$null;$parseErrors=$null
            $null=[Management.Automation.Language.Parser]::ParseFile($path.FullName,[ref]$tokens,[ref]$parseErrors)
            Assert-True (@($parseErrors).Count -eq 0) ('Parse error: '+$path.Name)
        }
    }
    $module = Import-Module (Join-Path $root 'scripts\windows\Common.psm1') -Force -PassThru -DisableNameChecking
    # Only this disposable test process replaces module functions; no production test bypass.
    & $module {
        function script:Wait-GGHttp { param([int]$Port) }
        function script:Get-GGSystem { [pscustomobject]@{Build=22631;Client=$true;RamBytes=16GB;FreeBytes=40GB;X64=$true} }
        $script:Calls = New-Object System.Collections.Generic.List[object]
        $script:Endpoint = 'npipe:////./pipe/dockerDesktopLinuxEngine'
        function script:Invoke-GGNative {
            param([string[]]$Arguments,[switch]$Capture)
            $script:Calls.Add(@($Arguments))
            if ($Arguments[0] -eq 'context') { return $script:Endpoint }
            if ($Arguments[0] -eq 'info') { return 'linux' }
            if ($Arguments[0] -eq 'version') { return '28.1.0' }
            if ($Arguments[0] -eq 'compose' -and $Arguments[1] -eq 'version') { return '2.24.1' }
            if ($Capture) {
                $state = Get-Content -LiteralPath $script:TestState -Encoding UTF8 -Raw | ConvertFrom-Json
                return (@{mode='synthetic-v1';instance=$state.Instance;seeded=$true;administrator_exists=$false;references=3} | ConvertTo-Json -Compress)
            }
        }
    }
    function global:docker { throw 'The test must never execute the real Docker CLI' }
    $oldDockerHost = $env:DOCKER_HOST
    $env:DOCKER_HOST = $null
    Test 'Preflight accepts approved Windows 11 prerequisites' {
        $report=Get-GGPreflight
        Assert-True $report.Ready
        Assert-True $report.ReadOnly
    }
    Test 'Preflight rejects external Docker endpoints' {
        & $module {$script:Endpoint='tcp://unapproved.invalid:2375'}
        Assert-True (-not (Get-GGPreflight).Ready)
        & $module {$script:Endpoint='npipe:////./pipe/dockerDesktopLinuxEngine'}
    }
    Test 'DOCKER_HOST override is blocked before contacting any daemon' {
        & $module {$script:Calls.Clear()}
        $env:DOCKER_HOST='ssh://unapproved.invalid'
        Assert-True (-not (Get-GGPreflight).Ready)
        Assert-True ((& $module {$script:Calls.Count}) -eq 0)
        $env:DOCKER_HOST=$null
    }
    Test 'Preflight refuses unsupported system and low memory' {
        & $module { function script:Get-GGSystem { [pscustomobject]@{Build=19045;Client=$true;RamBytes=8GB;FreeBytes=40GB;X64=$true} } }
        $report=Get-GGPreflight
        Assert-True (-not $report.Ready)
        Assert-True (@($report.Checks|Where-Object {-not $_.OK}).Count -eq 2)
        & $module { function script:Get-GGSystem { [pscustomobject]@{Build=22631;Client=$true;RamBytes=16GB;FreeBytes=40GB;X64=$true} } }
    }
    Test 'Secrets are random, distinct, and safe for files' {
        $a=New-GGSecret;$b=New-GGSecret
        Assert-True ($a -ne $b)
        Assert-True ($a -match '^[A-Za-z0-9_-]{64}$')
    }
    $homePath=Join-Path $temporary ("piloto com espa"+[char]0xE7+"os O'Neill `$")
    $state=New-GGInstallation -HomePath $homePath -SourceRoot $root
    & $module {param($path) $script:TestState=Join-Path $path 'installation.json'} $homePath
    Test 'New installation uses unique namespace and synthetic mode' {
        Assert-True ($state.Project -match '^gg-win5-[a-f0-9]{12}$')
        Assert-True ($state.Mode -eq 'synthetic-v1')
        Assert-True (-not $state.Installed)
        Assert-True ((Get-Content (Join-Path $homePath 'pilot.env') -Raw) -notmatch 'PASSWORD=')
    }
    Test 'Private NTFS directory has protected inheritance and no public allow entries' {
        $acl=Get-Acl -LiteralPath $homePath
        Assert-True $acl.AreAccessRulesProtected
        $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
        Assert-True ($rules.Count -eq 2)
        Assert-True (@($rules|Where-Object {$_.IdentityReference.Value -eq 'S-1-1-0'}).Count -eq 0)
    }
    Test 'Repeat preparation preserves all secrets and instance identity' {
        $before=Get-FileHash -LiteralPath (Join-Path $homePath 'secrets\db_owner_password')
        $again=New-GGInstallation -HomePath $homePath -SourceRoot $root
        Assert-True ($again.Instance -eq $state.Instance)
        Assert-True ((Get-FileHash -LiteralPath $before.Path).Hash -eq $before.Hash)
    }
    Test 'Unknown existing directory is never adopted' {
        $foreign=Join-Path $temporary 'foreign';$null=New-Item -ItemType Directory -Path $foreign
        Set-Content -LiteralPath (Join-Path $foreign 'keep.txt') -Value 'synthetic existing file'
        Assert-Throws {New-GGInstallation -HomePath $foreign -SourceRoot $root}
        Assert-True (Test-Path -LiteralPath (Join-Path $foreign 'keep.txt'))
    }
    Test 'Incomplete installation cannot start a browser or migrate' {
        & $module {$script:Calls.Clear()}
        Assert-Throws {Start-GGPilot -HomePath $homePath -NoBrowser}
        $calls=(& $module {$script:Calls|ConvertTo-Json -Depth 5})
        Assert-True ($calls -notmatch 'initialize|migrate')
    }
    Test 'Install explicitly initializes and marks healthy pilot' {
        $installed=Install-GGPilot -HomePath $homePath -SourceRoot $root -NoShortcuts
        Assert-True $installed.Installed
        $calls=(& $module {$script:Calls|ConvertTo-Json -Depth 5})
        Assert-True ($calls -match 'initialize')
        Assert-True ($calls -notmatch 'volume rm|system prune')
    }
    Test 'Daily start only starts existing services without migrations' {
        & $module {$script:Calls.Clear()}
        Start-GGPilot -HomePath $homePath -NoBrowser
        $calls=(& $module {$script:Calls|ConvertTo-Json -Depth 5})
        Assert-True ($calls -match 'up')
        Assert-True ($calls -notmatch 'initialize|migrate|build')
    }
    Test 'Stop preserves volumes and is scoped to pilot app and db' {
        & $module {$script:Calls.Clear()}
        Stop-GGPilot -HomePath $homePath
        $calls=(& $module {$script:Calls|ConvertTo-Json -Depth 5})
        Assert-True ($calls -match 'stop')
        Assert-True ($calls -match [regex]::Escape($state.Project))
        Assert-True ($calls -notmatch 'down|prune|remove|--volumes')
    }
    Test 'Stop remains available when disk is low or CIM is unavailable' {
        & $module {function script:Get-GGSystem {throw 'Synthetic restricted CIM'}}
        Stop-GGPilot -HomePath $homePath
        & $module {function script:Get-GGSystem {[pscustomobject]@{Build=22631;Client=$true;RamBytes=16GB;FreeBytes=40GB;X64=$true}}}
    }
    Test 'Forged environment refuses all mutation commands' {
        $path=Join-Path $homePath 'pilot.env';$text=[IO.File]::ReadAllText($path)
        [IO.File]::WriteAllText($path,$text+"DB_HOST=unapproved.invalid`n")
        Assert-Throws {Start-GGPilot -HomePath $homePath -NoBrowser}
        [IO.File]::WriteAllText($path,$text,(New-Object Text.UTF8Encoding $false))
    }
    Test 'Changed Compose manifest is refused' {
        $path=Join-Path $homePath 'compose.yaml';$text=[IO.File]::ReadAllText($path)
        [IO.File]::WriteAllText($path,$text+"#changed`n")
        Assert-Throws {Get-GGInstallation -HomePath $homePath}
        [IO.File]::WriteAllText($path,$text,(New-Object Text.UTF8Encoding $false))
    }
    Test 'Missing secret is never regenerated automatically' {
        $path=Join-Path $homePath 'secrets\db_app_password';$text=[IO.File]::ReadAllText($path)
        Remove-Item -LiteralPath $path
        Assert-Throws {New-GGInstallation -HomePath $homePath -SourceRoot $root}
        Assert-True (-not (Test-Path -LiteralPath $path))
        [IO.File]::WriteAllText($path,$text,(New-Object Text.UTF8Encoding $false))
    }
    Test 'Interactive account command contains no predefined credential' {
        & $module {$script:Calls.Clear()}
        New-GGPilotAccount -HomePath $homePath -Username 'synthetic.operator'
        $calls=(& $module {$script:Calls|ConvertTo-Json -Depth 5})
        Assert-True ($calls -match 'create_user')
        Assert-True ($calls -notmatch 'password-env|password=')
        Assert-Throws {New-GGPilotAccount -HomePath $homePath -Username 'bad;command'}
    }
    Test 'Recovery refuses the original installation directory' {
        Assert-Throws {Recover-GGPilot -Archive (Join-Path $temporary 'any.tar.gz') -NewHomePath $homePath -SourceRoot $root}
    }
    Test 'Shortcuts are per-user links with no policy bypass or elevation' {
        $shortcuts=Join-Path $temporary 'shortcuts';$null=New-Item -ItemType Directory -Path $shortcuts
        New-GGShortcuts -HomePath $homePath -ShortcutDirectory $shortcuts
        $links=@(Get-ChildItem -LiteralPath $shortcuts -Filter *.lnk)
        Assert-True ($links.Count -eq 3)
        $shell=New-Object -ComObject WScript.Shell
        foreach($link in $links){
            $shortcut=$shell.CreateShortcut($link.FullName)
            Assert-True ($shortcut.TargetPath.StartsWith($homePath,[StringComparison]::OrdinalIgnoreCase)) ('Unexpected shortcut target: '+$shortcut.TargetPath+' expected under '+$homePath)
            Assert-True ([string]::IsNullOrEmpty($shortcut.Arguments))
        }
    }
    Test 'Command wrappers keep execution policy and privilege decisions with IT' {
        foreach($cmd in Get-ChildItem (Join-Path $root 'scripts\windows') -Filter *.cmd){
            $text=Get-Content -LiteralPath $cmd.FullName -Raw
            Assert-True ($text -match '-NoProfile -File')
            Assert-True ($text -notmatch 'ExecutionPolicy|RunAs|EncodedCommand')
        }
        $text=Get-Content (Join-Path $root 'scripts\windows\Common.psm1') -Raw
        Assert-True ($text -notmatch 'Set-ExecutionPolicy|Enable-WindowsOptionalFeature|New-NetFirewallRule|system.*prune')
    }
} catch {
    $message=$_.Exception.Message.Replace("`r",' ').Replace("`n",' ')
    Write-Host ('::error title=Windows harness::'+$message)
    throw
} finally {
    $env:DOCKER_HOST=$oldDockerHost
    Remove-Item Function:\docker -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
Write-Host ("PowerShell: {0} passed, {1} failed" -f $script:Passed,$script:Failed.Count)
if($script:Failed.Count -ne 0){exit 1}
