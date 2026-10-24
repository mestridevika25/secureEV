$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CarlaHome = if ($env:SECUREEV_CARLA_HOME) { $env:SECUREEV_CARLA_HOME } else { 'C:\SecureEV\CARLA' }
$CarlaExe = Join-Path $CarlaHome 'CarlaUE4.exe'
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$FrontendRoot = Join-Path $ProjectRoot 'frontend'
$env:SECUREEV_ENABLE_CAMERA = if ($env:SECUREEV_ENABLE_CAMERA) { $env:SECUREEV_ENABLE_CAMERA } else { '0' }

function Test-Port([int]$Port) {
    try {
        return (Test-NetConnection 127.0.0.1 -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
    } catch {
        return $false
    }
}

function Wait-Port([int]$Port, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-CarlaApi {
    if (-not (Test-Path $PythonExe)) { return $false }
    $checkScript = Join-Path $PSScriptRoot 'check_carla.py'
    if (-not (Test-Path $checkScript)) { return $false }
    try {
        & $PythonExe $checkScript *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-CarlaProcesses {
    @(
        Get-Process -Name 'CarlaUE4' -ErrorAction SilentlyContinue
        Get-Process -Name 'CarlaUE4-Win64-Shipping' -ErrorAction SilentlyContinue
    ) | Where-Object { $_ -ne $null } | Sort-Object Id -Unique
}

function Stop-CarlaProcesses {
    Get-CarlaProcesses | ForEach-Object {
        try {
            Write-Host "Stopping stale CARLA process $($_.Id) ($($_.ProcessName))..." -ForegroundColor Yellow
            Stop-Process -Id $_.Id -Force -ErrorAction Stop
        } catch {
            Write-Host "Could not stop CARLA process $($_.Id): $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 2
}

function Test-CarlaPorts {
    $rpc = Test-Port 2000
    $stream = Test-Port 2001
    return [PSCustomObject]@{ Rpc = $rpc; Streaming = $stream }
}

Write-Host '=== SecureEV startup ===' -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path $PythonExe)) {
    throw "Python virtual environment not found at $PythonExe. Create .venv with Python 3.10 and run: python -m pip install -r requirements.txt"
}

# 1. MQTT broker
if (-not (Test-Port 1883)) {
    $mqttService = Get-Service -Name 'mosquitto' -ErrorAction SilentlyContinue
    if ($mqttService) {
        if ($mqttService.Status -ne 'Running') {
            Write-Host 'Starting Mosquitto service...'
            try {
                Start-Service -Name 'mosquitto' -ErrorAction Stop
            } catch {
                Write-Host 'Could not start the Mosquitto service directly; trying the executable.' -ForegroundColor Yellow
                $mqttCandidates = @(
                    'C:\Program Files\mosquitto\mosquitto.exe',
                    'C:\Program Files (x86)\mosquitto\mosquitto.exe'
                )
                $mqttExe = $mqttCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
                if ($mqttExe) { Start-Process -FilePath $mqttExe -ArgumentList '-v' -WorkingDirectory (Split-Path $mqttExe) }
                else { throw 'Mosquitto service is stopped and mosquitto.exe could not be found.' }
            }
        }
    } else {
        $mqttCandidates = @(
            'C:\Program Files\mosquitto\mosquitto.exe',
            'C:\Program Files (x86)\mosquitto\mosquitto.exe'
        )
        $mqttExe = $mqttCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $mqttExe) {
            throw 'Mosquitto is not running and mosquitto.exe could not be found. Install Eclipse Mosquitto or start your existing broker on localhost:1883.'
        }
        Write-Host "Starting Mosquitto: $mqttExe"
        Start-Process -FilePath $mqttExe -ArgumentList '-v' -WorkingDirectory (Split-Path $mqttExe)
    }
}
if (-not (Wait-Port 1883 30)) { throw 'MQTT broker did not become available on port 1883.' }
Write-Host 'MQTT: OK' -ForegroundColor Green

# 2. CARLA
# CARLA is intentionally started by scripts\start_carla.bat.  Keeping the
# heavyweight simulator startup separate makes the all-in-one application
# startup deterministic and avoids duplicate/stale CARLA processes.
if (-not (Test-Path $CarlaExe)) {
    throw "CARLA executable not found at $CarlaExe. Set SECUREEV_CARLA_HOME or edit this path in scripts/start_secureev.ps1."
}

if (-not (Test-CarlaApi)) {
    Write-Host ''
    Write-Host 'CARLA is not ready on localhost:2000.' -ForegroundColor Yellow
    Write-Host 'Start CARLA first with:' -ForegroundColor Yellow
    Write-Host "  $CarlaExe -quality-level=Low -nosound -windowed -ResX=1024 -ResY=576 -dx11 -carla-rpc-port=2000" -ForegroundColor Cyan
    Write-Host 'Or run: scripts\start_carla.bat' -ForegroundColor Cyan
    throw 'CARLA Python RPC API is not ready on localhost:2000.'
}
Write-Host 'CARLA 0.9.16 API: OK' -ForegroundColor Green

# 3. FastAPI
if (-not (Test-Port 8000)) {
    Write-Host 'Starting FastAPI...'
    $command = "Set-Location -LiteralPath '$ProjectRoot'; & '$PythonExe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
    Start-Process powershell.exe -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-Command',$command
}
if (-not (Wait-Port 8000 30)) { throw 'FastAPI did not become available on port 8000.' }
Write-Host 'FastAPI: OK' -ForegroundColor Green

# 4. Start the SecureEV runtime (idempotent)
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8000/health'
    if (-not $health.runtime_running) {
        Write-Host 'Starting SecureEV runtime...'
        Invoke-RestMethod -Method Post 'http://127.0.0.1:8000/runtime/start' | Out-Null
    }
} catch {
    throw "FastAPI is reachable, but SecureEV runtime could not be started: $($_.Exception.Message)"
}

Start-Sleep -Seconds 2
$status = Invoke-RestMethod 'http://127.0.0.1:8000/runtime/status'
if (-not $status.running) {
    throw "SecureEV runtime failed to start. Backend reported: $($status.start_error)"
}
Write-Host 'SecureEV runtime: OK' -ForegroundColor Green

# 5. Frontend
if (-not (Test-Port 5173)) {
    if (-not (Test-Path $FrontendRoot)) { throw "Frontend directory not found: $FrontendRoot" }
    if (-not (Test-Path (Join-Path $FrontendRoot 'node_modules'))) {
        Write-Host 'Installing frontend dependencies...'
        Push-Location $FrontendRoot
        try { npm install } finally { Pop-Location }
    }
    Write-Host 'Starting React/Vite dashboard...'
    Start-Process powershell.exe `
        -WorkingDirectory $FrontendRoot `
        -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-Command','npm run dev'
}
if (-not (Wait-Port 5173 30)) { throw 'Vite dashboard did not become available on port 5173.' }

Write-Host ''
Write-Host 'SecureEV is ready.' -ForegroundColor Green
Write-Host 'Dashboard: http://127.0.0.1:5173' -ForegroundColor Cyan
Write-Host 'API docs : http://127.0.0.1:8000/docs' -ForegroundColor Cyan

Start-Process 'http://127.0.0.1:5173'
