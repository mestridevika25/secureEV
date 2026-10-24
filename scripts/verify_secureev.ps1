$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$FrontendRoot = Join-Path $ProjectRoot 'frontend'

if (-not (Test-Path $PythonExe)) {
    throw "Python environment missing: $PythonExe"
}

Write-Host '=== SecureEV source verification ===' -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & $PythonExe -m compileall -q backend blue_team database digital_twin network red_team simulation
    if ($LASTEXITCODE -ne 0) { throw 'Python compilation failed.' }
    & $PythonExe -m pytest backend/test_api_contract.py -q
    if ($LASTEXITCODE -ne 0) { throw 'Python application-contract tests failed.' }
} finally {
    Pop-Location
}

if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location $FrontendRoot
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'frontend build failed.' }
    } finally {
        Pop-Location
    }
} else {
    throw 'npm is not installed or not on PATH.'
}

Write-Host 'SecureEV source verification PASSED.' -ForegroundColor Green
