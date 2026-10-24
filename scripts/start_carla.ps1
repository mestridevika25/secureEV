$ErrorActionPreference = 'Stop'

$CarlaHome = if ($env:SECUREEV_CARLA_HOME) { $env:SECUREEV_CARLA_HOME } else { 'C:\SecureEV\CARLA' }
$CarlaExe = Join-Path $CarlaHome 'CarlaUE4.exe'
if (-not (Test-Path $CarlaExe)) { throw "CARLA executable not found at $CarlaExe" }

Write-Host '=== SecureEV CARLA startup ===' -ForegroundColor Cyan
Write-Host "CARLA: $CarlaExe"
Write-Host ''
Write-Host 'IMPORTANT: If CARLA crashes with a D3D device error, keep the SecureEV camera disabled.' -ForegroundColor Yellow
Write-Host ''

Get-Process -Name 'CarlaUE4','CarlaUE4-Win64-Shipping' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Start-Process -FilePath $CarlaExe -ArgumentList @(
    '-quality-level=Low',
    '-nosound',
    '-windowed',
    '-ResX=1024',
    '-ResY=576',
    '-dx11',
    '-carla-rpc-port=2000'
) -WorkingDirectory $CarlaHome

Write-Host 'CARLA launched. Wait until the world is fully visible.' -ForegroundColor Green
Write-Host 'Then verify it with: python .\scripts\check_carla.py' -ForegroundColor Cyan
