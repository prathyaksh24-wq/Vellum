param(
  [int]$Port = 8001
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $Root "docker-compose.yml"

function Test-HttpReady {
  param([string]$Url)
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    return $response.StatusCode -eq 200
  } catch {
    return $false
  }
}

$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($null -eq $dockerCommand) {
  $bundledDocker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
  if (Test-Path -LiteralPath $bundledDocker) {
    $Docker = $bundledDocker
  } else {
    throw "Docker CLI was not found. Install or start Docker Desktop before starting Vellum."
  }
} else {
  $Docker = $dockerCommand.Source
}

& $Docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) {
  throw "Docker Desktop's Linux engine is unavailable. Start Docker Desktop, then run this script again."
}

try {
  $ollama = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
  $models = @($ollama.models | ForEach-Object { $_.name })
} catch {
  throw "Ollama is unavailable at http://127.0.0.1:11434. Start Ollama before starting Honcho."
}

foreach ($requiredModel in @("gemma4:12b", "nomic-embed-text:latest")) {
  if (-not ($models -contains $requiredModel)) {
    throw "Required local Ollama model '$requiredModel' is missing. Pull it before starting Honcho."
  }
}

$build = @()
& $Docker image inspect "vellum-honcho:3.0.12" *> $null
if ($LASTEXITCODE -ne 0) {
  $build = @("--build")
}

& $Docker compose --project-directory $Root -f $ComposeFile up -d @build
if ($LASTEXITCODE -ne 0) {
  throw "The local Honcho stack failed to start."
}

$healthUrl = "http://127.0.0.1:$Port/health"
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
  if (Test-HttpReady $healthUrl) {
    $ready = $true
    break
  }
  Start-Sleep -Milliseconds 500
}

if (-not $ready) {
  & $Docker compose --project-directory $Root -f $ComposeFile ps
  & $Docker compose --project-directory $Root -f $ComposeFile logs --no-color --tail 80 honcho
  throw "Honcho did not become healthy at $healthUrl."
}

Write-Host "Honcho memory is ready at http://127.0.0.1:$Port."
