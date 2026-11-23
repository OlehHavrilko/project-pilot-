#Requires -Version 5.1
<#
.SYNOPSIS
  Create a Windows voice environment with ROCm PyTorch for an AMD GPU.

.DESCRIPTION
  Installs ROCm PyTorch (device-gfx1200 by default), Kokoro, RUAccent, fetches
  the Russian Kokoro-ru assets and runs a benchmark. Requires Windows 11, an
  up-to-date AMD driver and Python 3.12 on Windows.
#>
param(
    [string]$VenvDir = "$env:LOCALAPPDATA\pilot-voice",
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    [string]$RepoPath = "\\wsl.localhost\Ubuntu-24-04\home\olehwsl\pilot",
    [string]$AssetDir = "$env:LOCALAPPDATA\pilot\kokoro",
    [string]$DeviceExtra = "device-gfx1200",
    [string]$TorchVersion = "2.15.0+rocm10.2.0",
    [string]$Voice = "sveta"
)
$ErrorActionPreference = "Stop"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "creating venv $VenvDir"
    & $PythonExe -m venv $VenvDir
}
$env:PYTHONUTF8 = "1"
$ErrorActionPreference = "Continue"
& $VenvPython -c "import torch; assert torch.cuda.is_available()" 2>$null
$gpuReady = ($LASTEXITCODE -eq 0)
if (-not $gpuReady) {
    Write-Host "installing ROCm PyTorch $TorchVersion ($DeviceExtra), several GB..."
    & $VenvPython -m pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[$DeviceExtra]==$TorchVersion"
    if ($LASTEXITCODE -ne 0) { throw "ROCm PyTorch install failed" }
}
& $VenvPython -c "import kokoro, ruaccent, numpy, huggingface_hub" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "installing Kokoro dependencies"
    & $VenvPython -m pip install --disable-pip-version-check kokoro "misaki[en]" ruaccent numpy onnxruntime-directml huggingface_hub
    if ($LASTEXITCODE -ne 0) { throw "Kokoro dependencies failed" }
}
$ErrorActionPreference = "Stop"

Write-Host "fetching Kokoro-ru assets to $AssetDir"
& $VenvPython (Join-Path $RepoPath "scripts\fetch_kokoro_assets.py") --asset-dir $AssetDir
& $VenvPython (Join-Path $RepoPath "scripts\bench_kokoro.py") --asset-dir $AssetDir --voice $Voice --out (Join-Path $env:LOCALAPPDATA "pilot\kokoro-bench.wav")
& $VenvPython -c "import torch; print('torch', torch.__version__, 'gpu', torch.cuda.get_device_name(0))"
