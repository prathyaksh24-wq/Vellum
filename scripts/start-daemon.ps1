param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".daemon-runtime"
$PidFile = Join-Path $Runtime "daemon.pid"
$LogFile = Join-Path $Runtime "daemon.log"
$ErrFile = Join-Path $Runtime "daemon.err.log"
$StatusFile = Join-Path $Runtime "status"

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

if (Test-Path $PidFile) {
  $ExistingPid = Get-Content $PidFile -ErrorAction SilentlyContinue
  if ($ExistingPid -and (Get-Process -Id ([int]$ExistingPid) -ErrorAction SilentlyContinue)) {
    Write-Host "Vellum daemon is already running with PID $ExistingPid."
    exit 0
  }
}

$Args = @("-m", "agent.daemon.main")
if ($DryRun) {
  $Args += "--dry-run"
}

$Process = Start-Process -FilePath "python" -ArgumentList $Args -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden -PassThru -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile
Set-Content -Path $PidFile -Value $Process.Id -Encoding ascii

@(
  "status=running",
  "started_at=$((Get-Date).ToUniversalTime().ToString('s'))Z",
  "pid=$($Process.Id)",
  "dry_run=$DryRun"
) | Set-Content -Path $StatusFile -Encoding ascii

Write-Host "Vellum daemon started."
Write-Host "PID: $($Process.Id)"
