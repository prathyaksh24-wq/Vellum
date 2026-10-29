param(
  [string]$HostName = "127.0.0.1",
  [int]$ApiPort = 8000,
  [int]$UiPort = 5173,
  [switch]$SkipHoncho
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".ui-runtime"
$PidFile = Join-Path $Runtime "ui.pid"
$LogFile = Join-Path $Runtime "ui.log"
$ErrFile = Join-Path $Runtime "ui.err.log"
$StatusFile = Join-Path $Runtime "status"
$FrontendRoot = Join-Path $Root "frontend"

if (-not $SkipHoncho) {
  & (Join-Path $PSScriptRoot "start-honcho.ps1")
}

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
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
  }

  if ($null -ne $npmCommand) {
    $launcher = $npmCommand.Source
    $launcherArgs = @("run", "dev", "--", "--host", $HostName, "--port", [string]$UiPort)
  } else {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($null -eq $nodeCommand) {
      $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    }

    $node = if ($null -ne $nodeCommand) { $nodeCommand.Source } else { $null }
    if (-not $node) {
      $bundledNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
      if (Test-Path -LiteralPath $bundledNode) {
        $node = $bundledNode
      }
    }

    $vite = Join-Path $FrontendRoot "node_modules\vite\bin\vite.js"
    if (-not $node) {
      throw "Node.js is required to start the Vellum UI. Install Node.js or add node.exe to PATH."
    }
    if (-not (Test-Path -LiteralPath $vite)) {
      throw "Frontend dependencies are missing. Run npm install in $FrontendRoot first."
    }

    Write-Host "npm is not on PATH; starting Vite with $node."
    $launcher = $node
    $launcherArgs = @($vite, "--host", $HostName, "--port", [string]$UiPort)
  }

  $process = Start-Process -FilePath $launcher -ArgumentList $launcherArgs -WorkingDirectory $FrontendRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile
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
