$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "data\logs"
$Scraper = Join-Path $ScriptDir "scrape_naval_x.py"
$LogFile = Join-Path $LogDir "naval-x-scrape.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$timestamp] Starting @naval X scrape" | Out-File -FilePath $LogFile -Append -Encoding utf8

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython $Scraper --max-tweets 50 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
} else {
    & python $Scraper --max-tweets 50 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
}

$exitCode = $LASTEXITCODE
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$timestamp] Finished @naval X scrape with exit code $exitCode" | Out-File -FilePath $LogFile -Append -Encoding utf8

exit $exitCode
