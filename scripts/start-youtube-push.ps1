param([ValidateRange(1024, 65535)][int]$Port = 8001, [switch]$Restart)

$ErrorActionPreference = 'Stop'
$PushRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PushPython = Join-Path $PushRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PushPython)) { throw 'Install Vellum backend dependencies first.' }
$PushRuntime = Join-Path $PushRoot '.api-runtime'
New-Item -ItemType Directory -Force -Path $PushRuntime | Out-Null
$PushListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($PushListener) {
    if (-not $Restart) { throw "Port $Port is already in use. Use -Restart to restart a verified callback receiver." }
    foreach ($PushOwnerId in @($PushListener.OwningProcess | Select-Object -Unique)) {
        $PushExisting = Get-CimInstance Win32_Process -Filter "ProcessId=$PushOwnerId"
        $PushPortPattern = '--port\s+' + [regex]::Escape([string]$Port) + '(?:\s|$)'
        if ($PushExisting.CommandLine -notmatch '(?:^|\s)agent\.plugins\.youtube_push:app(?:\s|$)' -or
                $PushExisting.CommandLine -notmatch $PushPortPattern) {
            throw "Port $Port belongs to another application. It was not stopped."
        }
        Stop-Process -Id $PushOwnerId -Force
    }
    Start-Sleep -Milliseconds 300
}
$env:PYTHONPATH = Join-Path $PushRoot 'backend'
$PushArgs = @('-m', 'uvicorn', 'agent.plugins.youtube_push:app', '--host', '127.0.0.1', '--port', [string]$Port,
    '--no-access-log', '--limit-concurrency', '32', '--timeout-keep-alive', '5')
# Only the callback app is exposed. Never point a public tunnel at agent.api:app.
$PushProcess = Start-Process -FilePath $PushPython -ArgumentList $PushArgs -WorkingDirectory $PushRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $PushRuntime 'youtube-push.log') -RedirectStandardError (Join-Path $PushRuntime 'youtube-push.err.log')
Set-Content -LiteralPath (Join-Path $PushRuntime 'youtube-push.pid') -Value $PushProcess.Id -Encoding ascii
Start-Sleep -Milliseconds 1000
if ($PushProcess.HasExited) { throw 'Callback receiver exited. Inspect .api-runtime/youtube-push.err.log.' }
Write-Host "Callback receiver started on http://127.0.0.1:$Port (PID $($PushProcess.Id))."
Write-Host 'Start Vellum backend too. Configure YOUTUBE_PUSH_CALLBACK_BASE in .env and restart both processes after setting or changing the HTTPS origin.'
Write-Host "For a temporary development tunnel: cloudflared tunnel --url http://127.0.0.1:$Port"
