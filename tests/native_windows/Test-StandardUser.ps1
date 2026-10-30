# Disposable CI only. No execution-policy bypass and no changes on user computers.
param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Release)
$ErrorActionPreference='Stop'
try {
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Disposable CI only' }
$state=Get-Content -Raw -LiteralPath (Join-Path $Root 'installation.json')|ConvertFrom-Json
if ($state.channel -ne 'synthetic' -or $state.database -ne 'gva_native_synthetic') { throw 'Synthetic installation required' }
$name='gva_ci_'+[guid]::NewGuid().ToString('N').Substring(0,8)
$password=ConvertTo-SecureString -String ([guid]::NewGuid().ToString('N')+'Aa!9') -AsPlainText -Force
$null=New-LocalUser -Name $name -Password $password -Description 'Disposable native installer CI only'
Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $name
$probe=Join-Path $env:ProgramData ('gva-probe-'+[guid]::NewGuid().ToString('N'))
$null=New-Item -ItemType Directory -Path $probe
& icacls.exe $probe /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' /grant:r '*S-1-5-32-544:(OI)(CI)F' /grant:r ($env:COMPUTERNAME+'\'+$name+':(OI)(CI)M')|Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Probe ACL failed' }
@'
import json,sys,urllib.request
from pathlib import Path
root=Path(sys.argv[1]);output=Path(sys.argv[2])
state=json.loads((root/'installation.json').read_text())
with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:'+str(state['http_port'])+'/entrar/',timeout=10) as response:
 assert response.status==200
for name in ('secrets/owner.json','secrets/app.json','signing/signing.pem','cluster/PG_VERSION'):
 try:
  (root/name).read_bytes()
 except PermissionError:
  continue
 raise AssertionError('Standard Windows user could read private '+name)
output.write_text('PASS: non-admin HTTP and NTFS isolation')
'@|Set-Content -Encoding utf8 (Join-Path $probe 'probe.py')
try {
 $info=New-Object System.Diagnostics.ProcessStartInfo
 $info.FileName=Join-Path $Release 'python\python.exe'
 $info.Arguments='-s -B "'+(Join-Path $probe 'probe.py')+'" "'+$Root+'" "'+(Join-Path $probe 'result.txt')+'"'
 $info.UserName=$name
 $info.Domain=$env:COMPUTERNAME
 $info.Password=$password
 $info.UseShellExecute=$false
 $info.LoadUserProfile=$true
 $info.CreateNoWindow=$true
 $info.WorkingDirectory=$probe
 $process=[Diagnostics.Process]::Start($info)
 if (-not $process.WaitForExit(60000)) { throw 'Standard user probe timed out' }
 if ($process.ExitCode -ne 0 -or (Get-Content -Raw (Join-Path $probe 'result.txt')) -notmatch '^PASS:') { throw 'Non-admin HTTP/ACL probe failed' }
 Write-Host 'PASS: non-admin account uses HTTP and cannot read private data.'
} finally {
 # Only this freshly generated CI account; no existing users/directories touched.
 Remove-LocalUser -Name $name
}

} catch {
 Write-Host ('::error::Standard user probe: '+$_.Exception.Message+'; '+$_.ScriptStackTrace.Replace("`n",' '))
 exit 1
}
