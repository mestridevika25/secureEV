@echo off
setlocal
cd /d "%~dp0.."

echo === SecureEV application startup ===
echo Project: %CD%
echo.
echo CARLA must already be running and responding on localhost:2000.
echo The RGB camera is disabled by default for Windows GPU stability.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_secureev.ps1"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" pause
exit /b %ERR%
