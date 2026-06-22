param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".api-runtime"
$PidFile = Join-Path $Runtime "api.pid"
$LogFile = Join-Path $Runtime "api.log"
$ErrFile = Join-Path $Runtime "api.err.log"
$StatusFile = Join-Path $Runtime "status"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

function Test-HttpReady {
  param([string]$Url)
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    return $response.StatusCode -eq 200
  } catch {
    return $false
  }
}

if (-not (Test-Path $Python)) {
  $Python = (Get-Command python -ErrorAction Stop).Source
}

$healthUrl = "http://${HostName}:${Port}/api/health"
if (Test-HttpReady $healthUrl) {
  Write-Host "API is already running on port $Port."
} else {
  $env:PYTHONPATH = Join-Path $Root "backend"
  $env:API_HOST = $HostName
  $env:API_PORT = [string]$Port
  if (-not $env:TWITTER_AUTH_TOKEN) {
    $env:TWITTER_AUTH_TOKEN = [Environment]::GetEnvironmentVariable("TWITTER_AUTH_TOKEN", "User")
  }
  if (-not $env:TWITTER_CT0) {
    $env:TWITTER_CT0 = [Environment]::GetEnvironmentVariable("TWITTER_CT0", "User")
  }
  $args = @("-m", "uvicorn", "agent.api:app", "--host", $HostName, "--port", [string]$Port)
  $process = Start-Process -FilePath $Python -ArgumentList $args -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile
  Set-Content -Path $PidFile -Value $process.Id -Encoding ascii

  $ready = $false
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-HttpReady $healthUrl) {
      $ready = $true
      break
    }
    if ($process.HasExited) {
      break
    }
  }
  if (-not $ready) {
    Write-Host "API did not become ready. Error log:"
    if (Test-Path $ErrFile) { Get-Content -Tail 120 $ErrFile }
    exit 1
  }
}

@(
  "status=running",
  "started_at=$((Get-Date).ToUniversalTime().ToString('s'))Z",
  "url=http://localhost:$Port"
) | Set-Content -Path $StatusFile -Encoding ascii

Write-Host "Personal Agent API is ready."
Write-Host "URL: http://localhost:$Port"
Write-Host "Health: $healthUrl"
