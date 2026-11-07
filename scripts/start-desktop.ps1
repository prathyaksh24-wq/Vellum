param([switch]$SkipHoncho)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Electron owns the development API so it can restart it after code edits.
if (-not $SkipHoncho) {
  & (Join-Path $PSScriptRoot 'start-honcho.ps1')
  if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw 'Vellum memory services did not start.' }
}

Push-Location (Join-Path $Root 'desktop')
try {
  $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if ($null -ne $npm) {
    if (-not (Test-Path -LiteralPath 'node_modules/electron/dist/electron.exe')) {
      & $npm.Source ci --no-fund
      if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed.' }
    }
    & $npm.Source run dev
  } else {
    # Codex's bundled Node/pnpm is also supported without a global installation.
    $runtimeRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
    $node = Join-Path $runtimeRoot 'bin/node.exe'
    $pnpm = Join-Path $runtimeRoot 'node_modules/pnpm/bin/pnpm.cjs'
    if (-not (Test-Path -LiteralPath $node) -or -not (Test-Path -LiteralPath $pnpm)) {
      throw 'Node.js and npm are required to launch Vellum desktop.'
    }
    $env:Path = (Split-Path $node) + ';' + $env:Path
    if (-not (Test-Path -LiteralPath 'node_modules/electron/dist/electron.exe')) {
      & $node $pnpm dlx npm@11 ci --no-fund
      if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed.' }
    }
    & $node $pnpm run dev
  }
  if ($LASTEXITCODE -ne 0) { throw 'Vellum desktop exited with an error.' }
} finally {
  Pop-Location
}
