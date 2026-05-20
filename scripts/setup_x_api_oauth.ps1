$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$Driver = Join-Path $ScriptDir "setup_x_api_oauth.py"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Set-Location $ProjectRoot

if (Test-Path $VenvPython) {
    & $VenvPython $Driver @args
} else {
    & python $Driver @args
}

exit $LASTEXITCODE
