@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -File "%~dp0Backup.ps1" %*
set "GG_EXIT=%ERRORLEVEL%"
if not "%GG_EXIT%"=="0" echo Nao altere politicas nem tente elevacao. Contacte a informatica com o codigo %GG_EXIT%.
if /I not "%GG_NO_PAUSE%"=="1" pause
exit /b %GG_EXIT%
