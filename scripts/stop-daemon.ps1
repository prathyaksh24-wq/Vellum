$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".daemon-runtime"
$PidFile = Join-Path $Runtime "daemon.pid"
$StatusFile = Join-Path $Runtime "status"

if (-not (Test-Path $PidFile)) {
  Write-Host "Vellum daemon is not running."
  exit 0
}

$PidValue = Get-Content $PidFile -ErrorAction SilentlyContinue
if ($PidValue) {
  $Process = Get-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue
  if ($Process) {
    Stop-Process -Id $Process.Id -Force
  }
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
@(
  "status=stopped",
  "stopped_at=$((Get-Date).ToUniversalTime().ToString('s'))Z"
) | Set-Content -Path $StatusFile -Encoding ascii

Write-Host "Vellum daemon stopped."
