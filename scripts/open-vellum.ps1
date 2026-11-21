# Open Vellum from this checkout (development build) and wait until it is ready.
#
#   powershell -ExecutionPolicy Bypass -File scripts\open-vellum.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\open-vellum.ps1 -Installed   # the installed app instead
#
# The UI is rebuilt in the background on each launch; press Ctrl+R in the
# window to pick up a newer build without restarting.
param(
    [switch]$Installed,
    [int]$TimeoutSeconds = 180
)

$repo = Split-Path -Parent $PSScriptRoot

function Test-Backend {
    try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:8000/api/health").StatusCode -eq 200 }
    catch { $false }
}

$running = Get-CimInstance Win32_Process -Filter "name='electron.exe' or name='Vellum.exe'" |
    Where-Object { $_.CommandLine -notlike '*--type=*' }
if ($running) {
    Write-Host "Vellum is already running (pid $($running.ProcessId -join ', '))."
    exit 0
}

if ($Installed) {
    $exe = Get-ChildItem "$env:LOCALAPPDATA\vellum*", "$env:LOCALAPPDATA\Programs\Vellum*" -Recurse -Filter "Vellum.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $exe) { Write-Error "Vellum isn't installed. Run the installer from desktop\out\make first."; exit 1 }
    Start-Process -FilePath $exe.FullName
} else {
    Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $repo "desktop") -WindowStyle Minimized
}

Write-Host "Starting Vellum..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-Backend) { Write-Host "Vellum is ready."; exit 0 }
    Start-Sleep -Seconds 2
}
Write-Error "Vellum didn't become ready within $TimeoutSeconds seconds."
exit 1
