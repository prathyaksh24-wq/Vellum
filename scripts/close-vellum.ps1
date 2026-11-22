# Close Vellum cleanly: ask its window to close (the app then stops its
# backend, memory engines and database), and force it only as a last resort.
#
#   powershell -ExecutionPolicy Bypass -File scripts\close-vellum.ps1
param([int]$TimeoutSeconds = 45)

function Get-VellumApp {
    Get-CimInstance Win32_Process -Filter "name='electron.exe' or name='Vellum.exe'" |
        Where-Object { $_.CommandLine -notlike '*--type=*' }
}

$apps = @(Get-VellumApp)
if (-not $apps) { Write-Host "Vellum isn't running."; exit 0 }

foreach ($app in $apps) {
    # The main process owns the window; closing it quits Vellum the normal way.
    Get-Process -Id $app.ProcessId -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() }
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$($app.ProcessId)" |
        ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } |
        Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { [void]$_.CloseMainWindow() }
}

Write-Host "Closing Vellum..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and (Get-VellumApp)) { Start-Sleep -Seconds 1 }

$left = @(Get-VellumApp)
if ($left) {
    Write-Warning "Vellum didn't close in $TimeoutSeconds seconds; forcing it. Its engines stop with it."
    foreach ($app in $left) { taskkill /PID $app.ProcessId /T /F | Out-Null }
}
Write-Host "Vellum is closed."
