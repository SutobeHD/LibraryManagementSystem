# --- Local Release Build + Publish Script ---
# Builds Tauri app locally (Windows) and uploads to GitHub Release.
# Faster + more reliable than CI for solo-dev workflows.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/local-release.ps1 -Tag v0.0.6Alpha
#
# Requirements:
#   - gh CLI authenticated (gh auth login)
#   - Node.js 20+, Rust stable, Python 3.11
#   - src-tauri/binaries/RB_Backend-x86_64-pc-windows-msvc.exe present
#
# Builds: Windows .msi + .exe (NSIS)
# Other platforms: still need GitHub Actions CI

param(
    [Parameter(Mandatory=$true)]
    [string]$Tag,
    [switch]$Prerelease = $true,
    [switch]$SkipBuild = $false,
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Stop"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$repo = "SutobeHD/LibraryManagementSystem"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "    [ERR] $msg" -ForegroundColor Red }

# --- 1. Verify environment ---
Write-Step "Verifying environment"
if (-not (Test-Path $gh)) { Write-Err "gh CLI not found at $gh"; exit 1 }
& $gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Err "gh not authenticated. Run: gh auth login"; exit 1 }
$backendExe = "src-tauri\binaries\RB_Backend-x86_64-pc-windows-msvc.exe"
if (-not (Test-Path $backendExe)) {
    Write-Err "Backend binary missing: $backendExe"
    Write-Host "    Build it with: pyinstaller --clean backend.spec" -ForegroundColor Yellow
    exit 1
}
Write-OK "Environment OK"

# --- 2. Build (unless skipped) ---
if (-not $SkipBuild) {
    Write-Step "Frontend build"
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Err "Frontend build failed"; exit 1 }
    Write-OK "Frontend built"

    Write-Step "Tauri build (Rust release + bundle)"
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { Write-Err "Tauri build failed"; exit 1 }
    Write-OK "Tauri built"
}

# --- 3. Locate artifacts ---
Write-Step "Locating build artifacts"
$msiDir = "src-tauri\target\release\bundle\msi"
$nsisDir = "src-tauri\target\release\bundle\nsis"

$msiFile = Get-ChildItem -Path $msiDir -Filter "*.msi" -ErrorAction SilentlyContinue | Select-Object -First 1
$exeFile = Get-ChildItem -Path $nsisDir -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $msiFile) { Write-Err "No .msi found in $msiDir"; exit 1 }
if (-not $exeFile) { Write-Err "No .exe found in $nsisDir"; exit 1 }
Write-OK "MSI: $($msiFile.Name) ($('{0:N1}' -f ($msiFile.Length/1MB)) MB)"
Write-OK "EXE: $($exeFile.Name) ($('{0:N1}' -f ($exeFile.Length/1MB)) MB)"

# --- 4. Generate SHA256 checksums ---
Write-Step "Generating SHA256SUMS"
$sumsPath = "src-tauri\target\release\bundle\SHA256SUMS.txt"
$msiHash = (Get-FileHash $msiFile.FullName -Algorithm SHA256).Hash.ToLower()
$exeHash = (Get-FileHash $exeFile.FullName -Algorithm SHA256).Hash.ToLower()
@(
    "$msiHash  $($msiFile.Name)",
    "$exeHash  $($exeFile.Name)"
) | Set-Content -Path $sumsPath -Encoding utf8
Write-OK "SHA256SUMS written"

# --- 5. Create/update tag ---
Write-Step "Tagging $Tag"
git tag -d $Tag 2>&1 | Out-Null  # delete local if exists
git tag -a $Tag -m "Release $Tag — Local Windows build"
if ($DryRun) {
    Write-Host "    [DryRun] would push tag" -ForegroundColor Yellow
} else {
    git push origin $Tag 2>&1 | Tee-Object -Variable pushOutput | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Tag push failed:"
        Write-Host $pushOutput
        Write-Host "    Possibly a Repository Ruleset blocks tag creation." -ForegroundColor Yellow
        Write-Host "    Check: https://github.com/$repo/settings/rules" -ForegroundColor Yellow
        exit 1
    }
    Write-OK "Tag $Tag pushed"
}

# --- 6. Create GitHub release ---
Write-Step "Creating GitHub release $Tag"
$releaseNotes = @"
## Music Library Manager — $Tag

**Local Windows build** (CI multi-platform builds in progress separately).

### Downloads
- ``$($msiFile.Name)`` — Windows MSI installer (signed by Microsoft default, no EV cert)
- ``$($exeFile.Name)`` — Windows NSIS installer
- ``SHA256SUMS.txt`` — Verify integrity

### First-time install
SmartScreen warning is expected (no code-signing cert). Click **More info** → **Run anyway**.

### Verify
``````powershell
Get-FileHash <download> -Algorithm SHA256
# Compare against SHA256SUMS.txt
``````

See [Wiki](https://github.com/$repo/wiki) for details.
"@

$preFlag = ""
if ($Prerelease) { $preFlag = "--prerelease" }

if ($DryRun) {
    Write-Host "    [DryRun] would create release with:" -ForegroundColor Yellow
    Write-Host "    Files: $($msiFile.FullName), $($exeFile.FullName), $sumsPath"
} else {
    & $gh release create $Tag `
        --repo $repo `
        --title "Release $Tag" `
        --notes $releaseNotes `
        $preFlag `
        $msiFile.FullName `
        $exeFile.FullName `
        $sumsPath
    if ($LASTEXITCODE -ne 0) { Write-Err "Release creation failed"; exit 1 }
    Write-OK "Release $Tag created + assets uploaded"
}

# --- 7. Done ---
Write-Step "Release complete"
Write-Host "    URL: https://github.com/$repo/releases/tag/$Tag" -ForegroundColor Green
Write-Host "    Run scripts\local-release.ps1 with -Tag <new> to release again." -ForegroundColor Cyan
