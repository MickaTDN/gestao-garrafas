; Native EXE wizard. NSIS has a zlib/libpng license, including commercial use.
Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!ifndef Version
  !error "Version required"
!endif
!ifndef Bundle
  !error "Bundle required"
!endif
!ifndef Channel
  !error "Channel required"
!endif
Name "Gestão Vertente Aveludada (${Channel})"
OutFile "${Bundle}\..\artifacts\GVA-${Channel}-${Version}-win-x64.exe"
InstallDir "$PROGRAMFILES64\GestaoVertenteAveludada-${Channel}"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
Icon "..\..\static\branding\copo-com-vida.ico"
UninstallIcon "..\..\static\branding\copo-com-vida.ico"
VIProductVersion "${Version}.0"
VIAddVersionKey "ProductName" "Gestão Vertente Aveludada"
VIAddVersionKey "FileDescription" "Instalação e atualização nativa (${Channel})"
VIAddVersionKey "FileVersion" "${Version}"
VIAddVersionKey "LegalCopyright" "Copo com Vida"
!define MUI_WELCOMEPAGE_TEXT "Instala Python privado, PostgreSQL 17, aplicação e backups. Guarda dados separados do programa. Requer informática para serviços e NTFS. Não altera DNS ou firewall. Canal ${Channel}; os pacotes synthetic servem apenas para dados fictícios."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Portuguese"
Var Result
Var Arguments
Var CIRequest
Function .onInit
  SetRegView 64
  SetShellVarContext all
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "É necessário Windows x64."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin11}
    MessageBox MB_ICONSTOP "É necessário Windows 11 (ou ambiente descartável compatível de CI)."
    Abort
  ${EndIf}
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=GVA.Native.exe "${Bundle}\payload\host\GVA.Native.exe"
  File /oname=package.json "${Bundle}\package.json"
  File /oname=package.sig "${Bundle}\package.sig"
  ExecWait '"$PLUGINSDIR\GVA.Native.exe" --preflight "$PLUGINSDIR\package.json" "$EXEPATH"' $Result
  ${If} $Result != 0
    SetErrorLevel 1
    Abort "Pacote antigo, incompatível ou sem assinatura autorizada. Dados conservados."
  ${EndIf}
FunctionEnd
Section "Instalar ou atualizar"
  IfFileExists "$INSTDIR\releases\${Version}\package.json" 0 +3
    SetErrorLevel 1
    Abort "Não se substituem versões já instaladas."
  SetOutPath "$INSTDIR\releases\${Version}"
  File /r "${Bundle}\*"
  SetOutPath "$INSTDIR"
  File "${Bundle}\payload\host\GVA.Native.exe"
  StrCpy $Arguments '--wizard "$INSTDIR\releases\${Version}"'
!if "${Channel}" == "synthetic"
  ReadEnvStr $Result "GITHUB_ACTIONS"
  ReadEnvStr $CIRequest "GVA_CI_REQUEST"
  ${If} $Result == "true"
  ${AndIf} $CIRequest != ""
    StrCpy $Arguments '--ci-wizard "$INSTDIR\releases\${Version}" "$CIRequest"'
  ${EndIf}
!endif
  ExecWait '"$INSTDIR\releases\${Version}\payload\host\GVA.Native.exe" $Arguments' $Result
  ${If} $Result != 0
    SetErrorLevel 1
    Abort "Operação incompleta. Dados conservados; contacte a informática. Não inicie código antigo após migrações."
  ${EndIf}
  CreateDirectory "$SMPROGRAMS\Gestão Vertente Aveludada (${Channel})"
  CreateShortcut "$DESKTOP\Gestão Vertente Aveludada (${Channel}).lnk" "$INSTDIR\GVA.Native.exe"
  CreateShortcut "$SMPROGRAMS\Gestão Vertente Aveludada (${Channel})\Gestão Vertente Aveludada.lnk" "$INSTDIR\GVA.Native.exe"
  CreateShortcut "$SMPROGRAMS\Gestão Vertente Aveludada (${Channel})\Manutenção.lnk" "$INSTDIR\GVA.Native.exe" "--maintenance"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\GVA-${Channel}" "DisplayName" "Gestão Vertente Aveludada (${Channel})"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\GVA-${Channel}" "DisplayVersion" "${Version}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\GVA-${Channel}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\GVA-${Channel}" "DisplayIcon" "$INSTDIR\GVA.Native.exe"
SectionEnd
Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  ExecWait '"$INSTDIR\GVA.Native.exe" --uninstall' $Result
  ${If} $Result != 0
    SetErrorLevel 1
    Abort "Não foi possível parar os serviços; desinstalação interrompida."
  ${EndIf}
  ; Only immutable installed PROGRAM code; NEVER ProgramData, cluster or backups.
  RMDir /r "$INSTDIR\releases"
  Delete "$INSTDIR\GVA.Native.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\Gestão Vertente Aveludada (${Channel}).lnk"
  RMDir /r "$SMPROGRAMS\Gestão Vertente Aveludada (${Channel})"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\GVA-${Channel}"
SectionEnd
