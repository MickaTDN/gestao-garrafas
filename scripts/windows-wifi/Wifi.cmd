@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -File "%~dp0Wifi.ps1" %*
if not "%GG_NO_PAUSE%"=="1" pause
