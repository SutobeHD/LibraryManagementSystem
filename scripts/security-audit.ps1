# --- Security Audit Script (Schicht A) — Windows PowerShell ---
# Runs all dependency security checks. Use locally before commit/release.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/security-audit.ps1

$ErrorActionPreference = "Stop"

Write-Host "==> Security Audit (RB Editor Pro)" -ForegroundColor Cyan
Write-Host "==> Date: $(Get-Date)" -ForegroundColor Cyan
Write-Host ""

# --- 1. NPM Audit Frontend ---
Write-Host "[1/5] npm audit (frontend)..." -ForegroundColor Yellow
Push-Location frontend
npm audit --audit-level=high
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: npm audit found high+ vulnerabilities (frontend)" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# --- 2. NPM Audit Root ---
Write-Host "[2/5] npm audit (root)..." -ForegroundColor Yellow
npm audit --audit-level=high
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: npm audit found high+ vulnerabilities (root)" -ForegroundColor Red
    exit 1
}

# --- 3. NPM Audit Signatures (Sigstore Provenance) ---
Write-Host "[3/5] npm audit signatures..." -ForegroundColor Yellow
Push-Location frontend
npm audit signatures
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: Some packages lack Sigstore provenance signatures." -ForegroundColor Yellow
    Write-Host "      Review unsigned packages before proceeding." -ForegroundColor Yellow
}
Pop-Location

# --- 4. Lockfile-Lint (registry-only URLs) ---
Write-Host "[4/5] lockfile-lint..." -ForegroundColor Yellow
npx --yes lockfile-lint --config=.lockfile-lintrc.json
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: lockfile contains non-registry URLs (potential supply-chain attack)" -ForegroundColor Red
    exit 1
}

# --- 5. Python pip-audit ---
Write-Host "[5/5] pip-audit (Python)..." -ForegroundColor Yellow
$pipAudit = Get-Command pip-audit -ErrorAction SilentlyContinue
if ($pipAudit) {
    pip-audit -r requirements.txt --strict
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: pip-audit found vulnerabilities" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "WARN: pip-audit not installed. Run: pip install pip-audit" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==> All security checks passed" -ForegroundColor Green
