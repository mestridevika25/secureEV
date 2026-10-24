$ErrorActionPreference = 'SilentlyContinue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

Write-Host '=== SecureEV shutdown ===' -ForegroundColor Yellow

if (Test-NetConnection 127.0.0.1 -Port 8000 -WarningAction SilentlyContinue).TcpTestSucceeded {
    try {
        Invoke-RestMethod -Method Post 'http://127.0.0.1:8000/runtime/stop' | Out-Null
        Write-Host 'SecureEV runtime stopped.' -ForegroundColor Green
    } catch {
        Write-Host 'FastAPI runtime stop request failed; continuing cleanup.' -ForegroundColor Yellow
    }
}

Get-Process -Name 'CarlaUE4' -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name 'CarlaUE4-Win64-Shipping' -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host 'CARLA processes stopped.' -ForegroundColor Green
Write-Host 'Mosquitto is left running because it may be installed as a Windows service.'
Write-Host 'You can stop the Vite terminal with Ctrl+C when finished.'
