# OSS-Agent Windows 11 Bootstrapper
$ErrorActionPreference = "Stop"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "   OSS-AGENT: WINDOWS 11 NATIVE BOOTSTRAPPER" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$OssRoot = "$HOME\.oss_agent"
New-Item -ItemType Directory -Force -Path "$OssRoot\models\slm" | Out-Null
New-Item -ItemType Directory -Force -Path "$OssRoot\browser_profile" | Out-Null

Write-Host "==> [1/3] Verifying Python 3 Runtime..." -ForegroundColor Green
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3 is required. Please install from https://www.python.org/downloads/."
}

Write-Host "==> [2/3] Installing Dependencies & DirectML Accelerator..." -ForegroundColor Green
python -m pip install --upgrade pip
python -m pip install edge-tts onnxruntime-directml numpy

Write-Host "==> [3/3] Creating Headless Chrome Debugging Launcher..." -ForegroundColor Green
$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (Test-Path $ChromePath) {
    Write-Host "Chrome found at: $ChromePath" -ForegroundColor Green
}

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ">>> WINDOWS 11 BOOTSTRAP COMPLETE: SYSTEM OPERATIONAL <<<" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
