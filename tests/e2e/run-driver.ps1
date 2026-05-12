# Launches tauri-driver, pointing it at the msedgedriver matching the
# installed WebView2 runtime. Keep this terminal open while running tests.
#
# WebView2 version on this machine: see HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}
# msedgedriver location: %USERPROFILE%\.tauri-webdriver\msedgedriver.exe
# tauri-driver location: %USERPROFILE%\.cargo\bin\tauri-driver.exe
#
# Usage:   .\run-driver.ps1
# Stop:    Ctrl+C

$ErrorActionPreference = "Stop"

$edgedriver = Join-Path $env:USERPROFILE ".tauri-webdriver\msedgedriver.exe"
$tauriDriver = Join-Path $env:USERPROFILE ".cargo\bin\tauri-driver.exe"

if (-not (Test-Path $edgedriver)) {
    Write-Error "msedgedriver missing at $edgedriver — re-run setup."
}
if (-not (Test-Path $tauriDriver)) {
    Write-Error "tauri-driver missing at $tauriDriver — run: cargo install tauri-driver --locked"
}

Write-Host "Starting tauri-driver on http://127.0.0.1:4444" -ForegroundColor Cyan
Write-Host "  edgedriver  = $edgedriver"
Write-Host "  tauri-driver = $tauriDriver"
Write-Host ""

& $tauriDriver --port 4444 --native-driver $edgedriver
