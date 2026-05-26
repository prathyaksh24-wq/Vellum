param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$CargoTargetDir = "D:\VellumOffloaded\VellumBuild\src-tauri-target"

& (Join-Path $PSScriptRoot "start.ps1")

Push-Location (Join-Path $Root "desktop")
try {
  if (-not (Test-Path "node_modules")) {
    npm.cmd install
  }

  if (Test-Path $CargoBin) {
    $env:Path = "$CargoBin;$env:Path"
  }
  New-Item -ItemType Directory -Force -Path $CargoTargetDir | Out-Null
  $env:CARGO_TARGET_DIR = $CargoTargetDir

  $vcVarsCandidates = @(
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
  )
  $vcVars = $vcVarsCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

  if ($null -eq $vcVars) {
    Write-Host "Visual Studio C++ Build Tools were not found. Install Visual Studio Build Tools with the C++ workload, then run this again."
    exit 1
  }

  $kernel32 = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\Lib" -Recurse -Filter kernel32.lib -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -eq $kernel32) {
    Write-Host "Windows SDK libraries were not found. Finish or install the Windows SDK, then run this again."
    Write-Host "Missing library: kernel32.lib"
    exit 1
  }

  $cmd = "call `"$vcVars`" && set `"PATH=$CargoBin;%PATH%`" && set `"CARGO_TARGET_DIR=$CargoTargetDir`" && npm.cmd run dev"
  cmd.exe /d /s /c $cmd
} finally {
  Pop-Location
}
