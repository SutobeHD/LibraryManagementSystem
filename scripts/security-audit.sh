#!/usr/bin/env bash
# --- Security Audit Script (Schicht A) ---
# Runs all dependency security checks. Use locally before commit/release.
#
# Usage: bash scripts/security-audit.sh
# Exit code 0 if all clean, non-zero if issues found.

set -e

echo "==> Security Audit (LibraryManagementSystem)"
echo "==> Date: $(date)"
echo ""

# --- 1. NPM Audit (Frontend) ---
echo "[1/5] npm audit (frontend)..."
cd frontend
npm audit --audit-level=high || {
    echo "ERROR: npm audit found high+ vulnerabilities (frontend)"
    exit 1
}
cd ..

# --- 2. NPM Audit (Root) ---
echo "[2/5] npm audit (root)..."
npm audit --audit-level=high || {
    echo "ERROR: npm audit found high+ vulnerabilities (root)"
    exit 1
}

# --- 3. NPM Audit Signatures (Sigstore Provenance Check) ---
echo "[3/5] npm audit signatures..."
cd frontend
npm audit signatures || {
    echo "WARN: Some packages lack Sigstore provenance signatures."
    echo "      Review which packages are unsigned before proceeding."
}
cd ..

# --- 4. Lockfile-Lint (verify registry-only URLs) ---
echo "[4/5] lockfile-lint..."
npx --yes lockfile-lint --config=.lockfile-lintrc.json || {
    echo "ERROR: lockfile contains non-registry URLs (potential supply-chain attack)"
    exit 1
}

# --- 5. Python pip-audit ---
echo "[5/5] pip-audit (Python)..."
if command -v pip-audit &> /dev/null; then
    pip-audit -r requirements.txt --strict || {
        echo "ERROR: pip-audit found vulnerabilities"
        exit 1
    }
else
    echo "WARN: pip-audit not installed. Run: pip install pip-audit"
fi

echo ""
echo "==> All security checks passed"
