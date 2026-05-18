param(
  [int]$Port = 8000
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".api-runtime"
$PidFile = Join-Path $Runtime "api.pid"

if (Test-Path $PidFile) {
  $pidValue = (Get-Content $PidFile -Raw).Trim()
  if ($pidValue -match "^\d+$") {
    Stop-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
  }
  Remove-Item $PidFile -ErrorAction SilentlyContinue
}

Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -ErrorAction SilentlyContinue }

Write-Host "Personal Agent API stopped."
