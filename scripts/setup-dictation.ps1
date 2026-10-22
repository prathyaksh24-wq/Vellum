param([switch]$CpuOnly, [ValidateSet('small','large-v3-turbo')][string]$Model='large-v3-turbo')

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$modelRoot = Join-Path $repoRoot "data/models/whisper-$Model"
$appPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
$modelPython = Join-Path $modelRoot ".venv/Scripts/python.exe"
New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
if (-not (Test-Path $modelPython)) {
    & $appPython -m venv --without-pip (Join-Path $modelRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the isolated dictation environment." }
}
& $appPython -m pip --python $modelPython install -r (Join-Path $PSScriptRoot "dictation-requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install the dictation runtime." }
$env:HF_HUB_DISABLE_XET = "1"
& $modelPython (Join-Path $PSScriptRoot "download-dictation.py") --model-dir $modelRoot --model $Model
if ($LASTEXITCODE -ne 0) { throw "Could not download Whisper $Model." }
if ($CpuOnly) { Write-Host "Use DICTATION_DEVICE=cpu to select CPU inference explicitly." }
Write-Host "Whisper $Model is installed. Vellum will use the local weights for dictation."
if ($Model -ne 'large-v3-turbo') { Write-Host "Set DICTATION_MODEL_DIR=data/models/whisper-$Model to select this checkpoint instead of the default Turbo model." }
