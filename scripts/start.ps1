param(
  [string]$HostName = "127.0.0.1",
  [int]$ApiPort = 8000,
  [int]$UiPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".ui-runtime"
$PidFile = Join-Path $Runtime "ui.pid"
$LogFile = Join-Path $Runtime "ui.log"
$ErrFile = Join-Path $Runtime "ui.err.log"
$StatusFile = Join-Path $Runtime "status"

& (Join-Path $PSScriptRoot "start-api.ps1") -HostName $HostName -Port $ApiPort

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

$UiPath = "design-uploads/Vellum%20Default%20Re-designed.html"
$uiUrl = "http://${HostName}:${UiPort}/$UiPath"
if (Test-HttpReady $uiUrl) {
  Write-Host "UI is already running on port $UiPort."
} else {
  $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if ($null -eq $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction Stop
  }
  $npm = $npmCommand.Source
  $process = Start-Process -FilePath $npm -ArgumentList @("run", "dev", "--", "--host", $HostName, "--port", [string]$UiPort) -WorkingDirectory (Join-Path $Root "frontend") -WindowStyle Hidden -PassThru -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile
  Set-Content -Path $PidFile -Value $process.Id -Encoding ascii

  $ready = $false
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-HttpReady $uiUrl) {
      $ready = $true
      break
    }
    if ($process.HasExited) {
      break
    }
  }
  if (-not $ready) {
    Write-Host "UI did not become ready. Error log:"
    if (Test-Path $ErrFile) { Get-Content -Tail 120 $ErrFile }
    exit 1
  }
}

@(
  "status=running",
  "started_at=$((Get-Date).ToUniversalTime().ToString('s'))Z",
  "url=http://localhost:$UiPort/$UiPath",
  "api=http://localhost:$ApiPort"
) | Set-Content -Path $StatusFile -Encoding ascii

Write-Host "Vellum is ready."
Write-Host "UI: http://localhost:$UiPort/$UiPath"
Write-Host "API: http://localhost:$ApiPort"
