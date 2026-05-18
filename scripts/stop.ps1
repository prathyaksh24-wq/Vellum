param(
  [int]$ApiPort = 8000,
  [int]$UiPort = 5173
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$UiPidFile = Join-Path $Root ".ui-runtime\ui.pid"

if (Test-Path $UiPidFile) {
  $pidValue = (Get-Content $UiPidFile -Raw).Trim()
  if ($pidValue -match "^\d+$") {
    Stop-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
  }
  Remove-Item $UiPidFile -ErrorAction SilentlyContinue
}

Get-NetTCPConnection -LocalPort $UiPort -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -ErrorAction SilentlyContinue }

& (Join-Path $PSScriptRoot "stop-api.ps1") -Port $ApiPort

Write-Host "Vellum stopped."
