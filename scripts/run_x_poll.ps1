$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "data\logs"
$Driver = Join-Path $ScriptDir "poll_x.py"
$LogFile = Join-Path $LogDir "x-poll.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$timestamp] Starting X poll" | Out-File -FilePath $LogFile -Append -Encoding utf8

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython $Driver *>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
} else {
    & python $Driver *>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
}

$exitCode = $LASTEXITCODE
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$timestamp] Finished X poll with exit code $exitCode" | Out-File -FilePath $LogFile -Append -Encoding utf8

exit $exitCode
