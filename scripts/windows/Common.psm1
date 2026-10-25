Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:BundleRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

function Invoke-GGNative {
    param([Parameter(Mandatory=$true)][string[]]$Arguments, [switch]$Capture)
    if ($Capture) {
        $process = New-Object Diagnostics.Process
        $process.StartInfo.FileName = (Get-Command docker -ErrorAction Stop).Source
        $quoted = foreach ($argument in $Arguments) {
            if ($argument.Contains('"')) { throw 'Argumento Docker invalido.' }
            '"' + [regex]::Replace($argument, '(\\+)$', '$1$1') + '"'
        }
        $process.StartInfo.Arguments = $quoted -join ' '
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        try {
            $null = $process.Start()
            $output = $process.StandardOutput.ReadToEndAsync()
            $errors = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit(20000)) { $process.Kill(); throw 'O Docker nao respondeu em 20 segundos. Confirme o estado com a informatica.' }
            $null = $errors.GetAwaiter().GetResult()
            if ($process.ExitCode -ne 0) { throw 'O comando Docker falhou. Confirme o Docker Desktop e as permissoes com a informatica.' }
            return $output.GetAwaiter().GetResult()
        } finally { $process.Dispose() }
    }
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker @Arguments
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw 'O comando Docker falhou. Os dados e os volumes nao foram eliminados.' }
}

function Get-GGSystem {
    $os = Get-CimInstance Win32_OperatingSystem
    $ram = (Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum
    $drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($env:LOCALAPPDATA).Substring(0,1))
    return [pscustomobject]@{ Build=[int]$os.BuildNumber; Client=($os.ProductType -eq 1); RamBytes=[double]$ram; FreeBytes=[double]$drive.Free; X64=[Environment]::Is64BitOperatingSystem }
}

function Get-GGPreflight {
    param([int]$Port=8765)
    $checks = New-Object System.Collections.Generic.List[object]
    $isWindowsHost = ($env:OS -eq 'Windows_NT')
    if (-not $isWindowsHost) {
        $checks.Add([pscustomobject]@{Code='WINDOWS11';OK=$false;Message='Este assistente destina-se a Windows 11.'})
    } else {
        try {
            $system = Get-GGSystem
            $checks.Add([pscustomobject]@{Code='WINDOWS11';OK=($system.Client -and $system.Build -ge 22000 -and $system.X64);Message='Windows 11 de 64 bits necessario.'})
            $checks.Add([pscustomobject]@{Code='MEMORIA';OK=($system.RamBytes -ge 16GB);Message='Sao necessarios pelo menos 16 GB de RAM instalada.'})
            $checks.Add([pscustomobject]@{Code='DISCO';OK=($system.FreeBytes -ge 20GB);Message='Sao necessarios pelo menos 20 GB livres; recomenda-se 40 GB.'})
        } catch {
            $checks.Add([pscustomobject]@{Code='SISTEMA_NAO_VERIFICADO';OK=$false;Message='Nao foi possivel ler os requisitos do sistema. Peca verificacao a informatica.'})
        }
    }
    $remoteOverride = -not [string]::IsNullOrWhiteSpace($env:DOCKER_HOST)
    $checks.Add([pscustomobject]@{Code='DOCKER_HOST';OK=(-not $remoteOverride);Message='DOCKER_HOST deve estar vazio; nao se usam servidores Docker externos.'})
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        $checks.Add([pscustomobject]@{Code='DOCKER';OK=$false;Message='Docker Desktop nao encontrado. A instalacao/WSL2 exige autorizacao da informatica.'})
    } elseif (-not $remoteOverride) {
        try {
            $endpoint = (Invoke-GGNative -Capture -Arguments @('context','inspect','--format','{{.Endpoints.docker.Host}}')).Trim().Replace('\','/').ToLowerInvariant()
            $allowed = @('npipe:////./pipe/dockerdesktoplinuxengine','npipe:////./pipe/docker_engine','npipe://./pipe/docker_engine')
            $local = $allowed -contains $endpoint
            $checks.Add([pscustomobject]@{Code='DOCKER_LOCAL';OK=$local;Message='O contexto Docker deve usar um named pipe local do Docker Desktop.'})
            if ($local) {
                $linux = (Invoke-GGNative -Capture -Arguments @('info','--format','{{.OSType}}')).Trim() -eq 'linux'
                $version = (Invoke-GGNative -Capture -Arguments @('version','--format','{{.Server.Version}}')).Trim()
                $compose = (Invoke-GGNative -Capture -Arguments @('compose','version','--short')).Trim().TrimStart('v')
                $checks.Add([pscustomobject]@{Code='DOCKER_LINUX';OK=$linux;Message='Ative o backend Linux aprovado (preferencia WSL2) no Docker Desktop.'})
                $checks.Add([pscustomobject]@{Code='DOCKER_VERSION';OK=([version]($version.Split('-')[0]) -ge [version]'28.0');Message='Docker Engine 28 ou superior necessario para o isolamento loopback.'})
                $checks.Add([pscustomobject]@{Code='COMPOSE';OK=([version]($compose.Split('-')[0]) -ge [version]'2.24');Message='Docker Compose 2.24 ou superior necessario.'})
            }
        } catch {
            $checks.Add([pscustomobject]@{Code='DOCKER_INDISPONIVEL';OK=$false;Message='Inicie o Docker Desktop ou peca a informatica acesso autorizado ao backend. Nao e efetuada elevacao de privilegios.'})
        }
    }
    $portOK = $Port -ge 1024 -and $Port -le 65535
    $checks.Add([pscustomobject]@{Code='PORTA';OK=$portOK;Message='A porta deve estar entre 1024 e 65535.'})
    return [pscustomobject]@{ Schema=1; ReadOnly=$true; Ready=(@($checks | Where-Object {-not $_.OK}).Count -eq 0); Checks=@($checks.ToArray()) }
}

function Assert-GGHost {
    param([int]$Port=8765,[switch]$RuntimeOnly)
    $report = Get-GGPreflight -Port $Port
    $failures = @($report.Checks | Where-Object {-not $_.OK -and (-not $RuntimeOnly -or $_.Code -notin @('MEMORIA','DISCO','SISTEMA_NAO_VERIFICADO','WINDOWS11'))})
    if ($failures.Count -gt 0) {
        $failed = @($failures | ForEach-Object {$_.Code}) -join ', '
        throw "Diagnostico bloqueado: $failed. Execute Diagnostico.cmd e contacte a informatica; nada foi instalado no Windows."
    }
}

function Test-GGPortFree {
    param([int]$Port)
    $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback),$Port
    try { $listener.Start(); return $true } catch { return $false } finally { $listener.Stop() }
}

function Protect-GGDirectory {
    param([string]$Path)
    if ($env:OS -ne 'Windows_NT') { throw 'As permissoes privadas exigem NTFS Windows.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($sid in @($identity,(New-Object Security.Principal.SecurityIdentifier 'S-1-5-18'))) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule $sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function New-GGSecret {
    $bytes = New-Object byte[] 48
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) } finally { $random.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}

function Write-GGFile {
    param([string]$Path,[string]$Value)
    $temporary = $Path + '.tmp-' + [guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllText($temporary,$Value,(New-Object Text.UTF8Encoding $false))
    if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary,$Path,($Path+'.previous')) } else { [IO.File]::Move($temporary,$Path) }
}

function Get-GGDefaultHome {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA indisponivel.' }
    return Join-Path $env:LOCALAPPDATA 'GestaoGarrafas\Piloto'
}

function Get-GGInstallation {
    param([string]$HomePath=(Get-GGDefaultHome))
    $path = Join-Path $HomePath 'installation.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Piloto nao preparado. Execute Instalar.cmd; nao crie ficheiros de configuracao manualmente.' }
    $state = Get-Content -LiteralPath $path -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($state.Schema -ne 1 -or $state.Mode -ne 'synthetic-v1' -or $state.Project -notmatch '^gg-win5-[a-f0-9]{12}$' -or $state.Port -lt 1024 -or $state.Port -gt 65535) { throw 'Configuracao do piloto invalida. Nenhum comando foi executado.' }
    $uuid = [guid]::Empty
    if (-not [guid]::TryParse($state.Instance,[ref]$uuid)) { throw 'Identificador do piloto invalido.' }
    if ($state.Project -ne ('gg-win5-' + $uuid.ToString('N').Substring(0,12))) { throw 'Projeto nao corresponde ao identificador.' }
    if ($HomePath.StartsWith('\\')) { throw 'A pasta do piloto deve estar num disco local, nao numa partilha.' }
    $full = [IO.Path]::GetFullPath($HomePath)
    if ($full -ne [IO.Path]::GetFullPath($state.Home)) { throw 'A instalacao foi movida. Preserve os segredos e contacte a informatica.' }
    $composePath = Join-Path $full 'compose.yaml'
    if ((Get-FileHash -LiteralPath $composePath -Algorithm SHA256).Hash -ne $state.ComposeHash) { throw 'O perfil Compose foi alterado. Execucao recusada; os dados permanecem conservados.' }
    foreach ($secret in @('django_key','db_owner_password','db_app_password')) {
        if (-not (Test-Path -LiteralPath (Join-Path $full "secrets\$secret") -PathType Leaf)) { throw 'Segredo em falta. Nao o regenere: preserve a pasta e contacte a informatica.' }
    }
    return $state
}

function Get-GGComposeArguments {
    param($State)
    return @('compose','--project-name',$State.Project,'--file',(Join-Path $State.Home 'compose.yaml'),'--env-file',(Join-Path $State.Home 'pilot.env'))
}

function Invoke-GGCompose {
    param($State,[string[]]$Arguments,[switch]$Capture)
    if ($Capture) { return Invoke-GGNative -Arguments @((Get-GGComposeArguments $State) + $Arguments) -Capture }
    Invoke-GGNative -Arguments @((Get-GGComposeArguments $State) + $Arguments) | ForEach-Object { Write-Host $_ }
}

function Assert-GGEnvironment {
    param($State)
    # Do not trust editable interpolation files for Docker targets or bind addresses.
    $expected = Get-GGEnvironmentText $State
    $actual = [IO.File]::ReadAllText((Join-Path $State.Home 'pilot.env'))
    if ($actual -ne $expected) { throw 'O ambiente do piloto foi alterado. Execucao recusada sem modificar volumes.' }
}

function Assert-GGSeparatePaths {
    param([string]$HomePath,[string]$SourceRoot)
    $homeFull=[IO.Path]::GetFullPath($HomePath).TrimEnd([char]92,[char]47)
    $sourceFull=[IO.Path]::GetFullPath($SourceRoot).TrimEnd([char]92,[char]47)
    if ($homeFull.Equals($sourceFull,[StringComparison]::OrdinalIgnoreCase) -or $homeFull.StartsWith($sourceFull+'\',[StringComparison]::OrdinalIgnoreCase) -or $sourceFull.StartsWith($homeFull+'\',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'A pasta privada e a pasta do codigo devem ser separadas, sem uma conter a outra. Nenhum segredo deve entrar na imagem.'
    }
}

function Get-GGEnvironmentText {
    param($State)
    foreach ($path in @($State.Home,$State.Source)) {
        if ($path -match "[`r`n`"]" -or -not [IO.Path]::IsPathRooted($path)) { throw 'A pasta contem caracteres nao suportados pelo perfil seguro.' }
    }
    if ($State.Home.StartsWith('\\') -or $State.Source.StartsWith('\\')) { throw 'As pastas do piloto devem ser locais.' }
    Assert-GGSeparatePaths -HomePath $State.Home -SourceRoot $State.Source
    $source = $State.Source.Replace('\','/').Replace("'","\'")
    $secrets = (Join-Path $State.Home 'secrets').Replace('\','/').Replace("'","\'")
    return "GG_PILOT_ID=$($State.Instance)`nGG_PILOT_IMAGE=$($State.Project):stage5`nGG_HTTP_PORT=$($State.Port)`nGG_SOURCE_ROOT='$source'`nGG_SECRET_ROOT='$secrets'`n"
}

function Get-GGPilotStatus {
    param($State)
    Assert-GGEnvironment $State
    $raw = Invoke-GGCompose $State -Capture -Arguments @('exec','-T','app','python','/app/deploy/windows/pilot.py','status')
    $status = $raw | ConvertFrom-Json
    if ($status.mode -ne 'synthetic-v1' -or $status.instance -ne $State.Instance -or -not $status.seeded) { throw 'O servidor nao corresponde a este piloto.' }
    return $status
}

function Wait-GGHttp {
    param([int]$Port)
    for ($attempt=0; $attempt -lt 12; $attempt++) {
        $response=$null
        try {
            $request=[Net.HttpWebRequest]::Create(('http://127.0.0.1:{0}/entrar/' -f $Port))
            $request.Proxy=$null
            $request.AllowAutoRedirect=$false
            $request.Timeout=2000
            $response=$request.GetResponse()
            if ([int]$response.StatusCode -eq 200) { return }
        } catch { } finally { if ($null -ne $response) { $response.Dispose() } }
        Start-Sleep -Seconds 1
    }
    throw 'A aplicacao nao respondeu na porta local. Preserve o piloto e contacte a informatica.'
}

function New-GGShortcuts {
    param([string]$HomePath,[string]$ShortcutDirectory=[Environment]::GetFolderPath('Desktop'))
    $shell = New-Object -ComObject WScript.Shell
    # ASCII source remains compatible with Windows PowerShell 5.1 without a BOM.
    $appName = 'Gest' + [char]0x00E3 + 'o Vertente Aveludada'
    foreach ($item in @(@(($appName + ' - Piloto'),'Iniciar.cmd'),@(('Parar ' + $appName),'Parar.cmd'),@(('Diagnostico ' + $appName),'Diagnostico.cmd'))) {
        $shortcut = $shell.CreateShortcut((Join-Path $ShortcutDirectory ($item[0]+'.lnk')))
        $shortcut.TargetPath = Join-Path $HomePath $item[1]
        $shortcut.WorkingDirectory = $HomePath
        $shortcut.Description = 'Piloto local apenas com dados ficticios. Nao altera politicas do Windows.'
        $shortcut.Save()
    }
}

function New-GGInstallation {
    param([string]$HomePath=(Get-GGDefaultHome),[string]$SourceRoot=$script:BundleRoot,[int]$Port=8765)
    Assert-GGHost -Port $Port
    Assert-GGSeparatePaths -HomePath $HomePath -SourceRoot $SourceRoot
    if (Test-Path -LiteralPath (Join-Path $HomePath 'installation.json')) {
        $state = Get-GGInstallation $HomePath
        Assert-GGEnvironment $state
        return $state
    }
    if ((Test-Path -LiteralPath $HomePath) -and @(Get-ChildItem -LiteralPath $HomePath -Force).Count -ne 0) { throw 'A pasta ja existe e nao e um piloto reconhecido. Nao foi adotada ou alterada.' }
    if (-not (Test-GGPortFree $Port)) { throw 'A porta local esta ocupada. Nao foi terminado qualquer processo; escolha outra porta com a informatica.' }
    $null = New-Item -ItemType Directory -Path $HomePath -Force
    Protect-GGDirectory $HomePath
    $HomePath = [IO.Path]::GetFullPath($HomePath)
    $source = [IO.Path]::GetFullPath($SourceRoot)
    $instance = [guid]::NewGuid()
    $state = [pscustomobject]@{Schema=1;Mode='synthetic-v1';Instance=$instance.ToString();Project=('gg-win5-'+$instance.ToString('N').Substring(0,12));Port=$Port;Home=$HomePath;Source=$source;ComposeHash='';Installed=$false}
    $null = New-Item -ItemType Directory -Path (Join-Path $HomePath 'secrets')
    foreach ($secret in @('django_key','db_owner_password','db_app_password')) { Write-GGFile (Join-Path $HomePath "secrets\$secret") ((New-GGSecret)+"`n") }
    Copy-Item -LiteralPath (Join-Path $source 'deploy\windows\compose.yaml') -Destination (Join-Path $HomePath 'compose.yaml')
    $state.ComposeHash = (Get-FileHash -LiteralPath (Join-Path $HomePath 'compose.yaml') -Algorithm SHA256).Hash
    $text = Get-GGEnvironmentText $state
    Write-GGFile (Join-Path $HomePath 'pilot.env') $text
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $source 'scripts\windows') -File) { Copy-Item -LiteralPath $file.FullName -Destination $HomePath }
    Write-GGFile (Join-Path $HomePath 'installation.json') ($state | ConvertTo-Json)
    return $state
}

function Install-GGPilot {
    param([string]$HomePath=(Get-GGDefaultHome),[string]$SourceRoot=$script:BundleRoot,[int]$Port=8765,[switch]$NoShortcuts)
    $state = New-GGInstallation -HomePath $HomePath -SourceRoot $SourceRoot -Port $Port
    Assert-GGEnvironment $state
    Invoke-GGCompose $state -Arguments @('build','app')
    Invoke-GGCompose $state -Arguments @('up','--detach','--wait','--wait-timeout','120','db')
    Invoke-GGCompose $state -Arguments @('--profile','setup','run','--rm','initialize')
    Invoke-GGCompose $state -Arguments @('up','--detach','--wait','--wait-timeout','180','app')
    $status = Get-GGPilotStatus $state
    Wait-GGHttp -Port $state.Port
    $state.Installed = $true
    Write-GGFile (Join-Path $state.Home 'installation.json') ($state | ConvertTo-Json)
    if (-not $NoShortcuts) { New-GGShortcuts $state.Home }
    Write-Host 'Piloto preparado apenas com dados ficticios. Crie a sua conta com CriarUtilizador.cmd; nao existe password predefinida.'
    return $state
}

function Start-GGPilot {
    param([string]$HomePath=(Get-GGDefaultHome),[switch]$NoBrowser)
    $state = Get-GGInstallation $HomePath
    Assert-GGHost -Port $state.Port -RuntimeOnly
    Assert-GGEnvironment $state
    if (-not $state.Installed) { throw 'Instalacao incompleta. Execute Instalar.cmd para retomar; nao apague a pasta nem os volumes.' }
    Invoke-GGCompose $state -Arguments @('up','--no-build','--pull','never','--detach','--wait','--wait-timeout','180','db','app')
    $null = Get-GGPilotStatus $state
    Wait-GGHttp -Port $state.Port
    if (-not $NoBrowser) { Start-Process ("http://127.0.0.1:{0}/" -f $state.Port) }
}

function Stop-GGPilot {
    param([string]$HomePath=(Get-GGDefaultHome))
    $state = Get-GGInstallation $HomePath
    Assert-GGHost -Port $state.Port -RuntimeOnly
    Assert-GGEnvironment $state
    Invoke-GGCompose $state -Arguments @('stop','--timeout','45','app','db')
    Write-Host 'Piloto parado. Base de dados, documentos, backups e segredos conservados.'
}

function New-GGPilotAccount {
    param([string]$HomePath=(Get-GGDefaultHome),[string]$Username)
    $state = Get-GGInstallation $HomePath
    Assert-GGHost -Port $state.Port -RuntimeOnly
    $null = Get-GGPilotStatus $state
    if ($Username -notmatch '^[A-Za-z0-9_.@+-]{1,150}$') { throw 'Indique um identificador simples, sem espacos, com ate 150 caracteres.' }
    # Keep the real terminal attached: getpass prompts must not be line-buffered.
    Invoke-GGNative -Arguments @((Get-GGComposeArguments $state) + @('exec','app','python','manage.py','create_user',$Username,'--role','admin'))
}

function Backup-GGPilot {
    param([string]$HomePath=(Get-GGDefaultHome),[string]$Destination)
    $state = Get-GGInstallation $HomePath
    Assert-GGHost -Port $state.Port -RuntimeOnly
    $null = Get-GGPilotStatus $state
    Assert-GGSeparatePaths -HomePath $Destination -SourceRoot $state.Source
    if (Test-Path -LiteralPath $Destination) { throw 'O destino ja existe; nao sera substituido.' }
    Invoke-GGCompose $state -Arguments @('exec','-T','app','python','manage.py','backup_data','--synthetic')
    # Export complete archive files to a NEW directory, without accepting shell commands.
    $null = New-Item -ItemType Directory -Path $Destination
    Protect-GGDirectory $Destination
    Invoke-GGCompose $state -Arguments @('cp','app:/backups/.',$Destination)
    Write-Host 'Backups sinteticos copiados. A copia no mesmo disco nao protege contra perda do computador; guarde noutro suporte autorizado.'
}

function Recover-GGPilot {
    param([string]$Archive,[string]$NewHomePath,[string]$SourceRoot=$script:BundleRoot,[int]$Port=8766)
    Assert-GGHost -Port $Port
    if (Test-Path -LiteralPath $NewHomePath) { throw 'A pasta de recuperacao ja existe. Escolha uma pasta NOVA; a anterior nao e substituida.' }
    if (-not [IO.Path]::IsPathRooted($Archive) -or $Archive.StartsWith('\\') -or $Archive.Contains('"') -or -not (Test-Path -LiteralPath $Archive -PathType Leaf) -or -not $Archive.EndsWith('.tar.gz')) { throw 'Escolha um backup .tar.gz local do piloto sintetico, num suporte autorizado.' }
    $state = New-GGInstallation -HomePath $NewHomePath -SourceRoot $SourceRoot -Port $Port
    Assert-GGEnvironment $state
    Invoke-GGCompose $state -Arguments @('build','app')
    Invoke-GGCompose $state -Arguments @('up','--detach','--wait','--wait-timeout','120','db')
    $mount = $Archive + ':/restore/pilot.tar.gz:ro'
    Invoke-GGCompose $state -Arguments @('--profile','setup','run','--rm','--volume',$mount,'initialize','python','/app/deploy/windows/pilot.py','recover')
    Invoke-GGCompose $state -Arguments @('up','--detach','--wait','--wait-timeout','180','app')
    $null = Get-GGPilotStatus $state
    Wait-GGHttp -Port $state.Port
    $state.Installed = $true
    Write-GGFile (Join-Path $state.Home 'installation.json') ($state | ConvertTo-Json)
    Write-Host 'Copia recuperada numa instalacao independente. Valide-a antes de mudar atalhos; a origem e os seus atalhos nao foram substituidos.'
    return $state
}

Export-ModuleMember -Function Get-GGPreflight,Get-GGDefaultHome,Get-GGInstallation,New-GGInstallation,Install-GGPilot,Start-GGPilot,Stop-GGPilot,New-GGPilotAccount,Backup-GGPilot,New-GGShortcuts,New-GGSecret,Recover-GGPilot
