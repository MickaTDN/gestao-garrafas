; Build-time inputs are public paths/policy only. No secrets/certificates in this bundle.
#ifndef Version
  #error Version is required
#endif
#ifndef Bundle
  #error Bundle is required
#endif
#ifndef Channel
  #error Channel is required
#endif
[Setup]
AppId=GestaoVertenteAveludada-{#Channel}
AppName=Gestão Vertente Aveludada ({#Channel})
AppVersion={#Version}
AppPublisher=Copo com Vida
DefaultDirName={autopf}\GestaoVertenteAveludada-{#Channel}
DefaultGroupName=Gestão Vertente Aveludada ({#Channel})
OutputBaseFilename=GVA-{#Channel}-{#Version}-win-x64
OutputDir={#Bundle}\..\artifacts
UninstallDisplayIcon={app}\GVA.Native.exe
SetupIconFile=..\..\static\branding\copo-com-vida.ico
PrivilegesRequired=admin
MinVersion=10.0.22000
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes
SetupLogging=yes
; Release build MUST supply an enterprise signing tool; synthetic CI is unsigned/test-only.
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif
[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
[Files]
Source: "{#Bundle}\payload\host\GVA.Native.exe"; Flags: dontcopy
Source: "{#Bundle}\package.json"; Flags: dontcopy
Source: "{#Bundle}\package.sig"; Flags: dontcopy
Source: "{#Bundle}\*"; DestDir: "{app}\releases\{#Version}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Bundle}\payload\host\GVA.Native.exe"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autodesktop}\Gestão Vertente Aveludada ({#Channel})"; Filename: "{app}\GVA.Native.exe"
Name: "{group}\Gestão Vertente Aveludada"; Filename: "{app}\GVA.Native.exe"
Name: "{group}\Manutenção (informática)"; Filename: "{app}\GVA.Native.exe"; Parameters: "--maintenance"
[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption := 'Instala Python privado, PostgreSQL 17 e serviços locais. Guarda dados e backups separados do programa. Não altera firewall, DNS ou políticas da empresa. A elevação é necessária para serviços e permissões NTFS.';
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}\releases\{#Version}')) then begin
    Result := 'Esta versão já existe. Não se substituem versões instaladas.';
    exit;
  end;
  ExtractTemporaryFile('GVA.Native.exe');
  ExtractTemporaryFile('package.json');
  ExtractTemporaryFile('package.sig');
  if not Exec(ExpandConstant('{tmp}\GVA.Native.exe'), '--preflight "' + ExpandConstant('{tmp}\package.json') + '" "' + ExpandConstant('{srcexe}') + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) then begin
    Result := 'Não foi possível verificar o instalador.';
    exit;
  end;
  if Code <> 0 then begin Result := 'Pacote antigo, incompatível ou sem assinatura autorizada. Dados conservados.'; exit; end;
  if (not WizardSilent) and (CompareText('{#Channel}', 'synthetic') = 0) then
    if MsgBox('Este instalador serve exclusivamente para validação com dados fictícios. Não é uma distribuição de produção. Continuar?', mbConfirmation, MB_YESNO) <> IDYES then
      Result := 'Instalação de teste cancelada.';
end;
procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Args: String;
begin
  if CurStep = ssPostInstall then begin
    Args := '--wizard "' + ExpandConstant('{app}\releases\{#Version}') + '"';
    if ('{#Channel}' = 'synthetic') and (GetEnv('GITHUB_ACTIONS') = 'true') and (ExpandConstant('{param:CITestRequest|}') <> '') then
      Args := '--ci-wizard "' + ExpandConstant('{app}\releases\{#Version}') + '" "' + ExpandConstant('{param:CITestRequest|}') + '"';
    if not Exec(ExpandConstant('{app}\releases\{#Version}\payload\host\GVA.Native.exe'), Args, '', SW_SHOW, ewWaitUntilTerminated, Code) then
      RaiseException('Não foi possível iniciar o assistente. Preserve os dados e contacte a informática.');
    if Code <> 0 then
      RaiseException('Instalação/atualização não concluída. Os dados foram conservados. Não inicie uma versão antiga após migrações.');
  end;
end;
function InitializeUninstall(): Boolean;
var Code: Integer;
begin
  Result := Exec(ExpandConstant('{app}\GVA.Native.exe'), '--uninstall', '', SW_SHOW, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then MsgBox('Não foi possível parar os serviços. Desinstalação interrompida; dados conservados.', mbError, MB_OK);
end;
; No [UninstallDelete]: ProgramData, cluster, keys, certificates and backups survive.
