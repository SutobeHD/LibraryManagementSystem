# Security — Dependency Hardening (Schicht A)

This project follows **2026 supply-chain security best practices**.

## What's Active

### NPM (`.npmrc`)
- **`ignore-scripts=true`** — Postinstall/preinstall scripts disabled (blocks ~80% of npm supply-chain malware: lottie-player, ua-parser-js, chalk-style hijacks)
- **`save-exact=true`** — `npm install` writes exact versions, no caret/tilde drift
- **`audit-level=high`** — Builds fail on high+ CVEs
- **`engine-strict=true`** — Node version pinning enforced
- **`prefer-offline=true`** — Reduces network calls during install

### Python (`requirements.txt`)
- All versions pinned with `==` (no `>=`)
- For maximum security: regenerate with hashes via `pip-compile --generate-hashes`
- Audit via `pip-audit`

### Cargo (`Cargo.lock`)
- Lockfile committed
- Audit via `cargo audit` (install: `cargo install cargo-audit`)

### Automated
- **Dependabot** weekly checks for security CVEs (config: `.github/dependabot.yml`)
- **Lockfile-Lint** ensures all packages from npm registry only (config: `.lockfile-lintrc.json`)
- **Audit script** runs all checks: `bash scripts/security-audit.sh` (or `.ps1` for Windows)

## Required Workflow

### Installing Dependencies (NEVER use `npm install`)
```bash
# Frontend
cd frontend && npm ci          # ← deterministic install from lockfile

# Root
npm ci

# Python
pip install -r requirements.txt
# OR (recommended): pip install --require-hashes -r requirements-hashed.txt

# Rust
cd src-tauri && cargo build    # uses Cargo.lock
```

### Adding a New Dependency
**ALWAYS verify before installing** (Slopsquatting defense — AI tools may suggest non-existing packages):

```bash
# 1. Check the package exists, has reasonable age + downloads
npm view <package-name>        # Look for: created date, weekly downloads, maintainers

# 2. Check Sigstore provenance
npm view <package-name> attestations

# 3. Only after verification, add it
cd frontend
npm install --save-exact <package-name>

# 4. Run audit immediately
npm audit
```

### Before Every Release
```bash
# Run full audit
bash scripts/security-audit.sh

# Verify Cargo
cd src-tauri && cargo audit && cd ..

# Generate SBOM (when Schicht B is added)
# syft . -o cyclonedx-json > sbom.json
```

## Threats Defended Against

| Threat | Defense |
|---|---|
| Postinstall malware (lottie-player 2024, chalk hijack) | `ignore-scripts=true` |
| Caret-version silent drift | `save-exact=true` + exact pinning |
| Lockfile manipulation | `lockfile-lint` |
| Self-propagating worms (PyTorch Lightning 2026) | Hash-pinning + Dependabot alerts |
| Maintainer account compromise | `npm audit signatures` (Sigstore) |
| Slopsquatting (AI-induced) | Manual verification workflow |
| Known CVEs | `npm audit` + `pip-audit` + Dependabot |

## Threats NOT Defended Against (Out of Scope)

- **Initial-source backdoors** (XZ-style) — would require reproducible builds + multi-source verification
- **Targeted attacks on this specific project** — would require additional defenses (HSM, air-gapped builds)
- **Bugs in self-written code** — handled by code review + linting (separate concern)

## Known Accepted Risks

### Vite 7.3.1 — 3 high dev-server CVEs (GHSA-4w7w-66w2-5vf9, GHSA-v2wj-q39q-566r, GHSA-p9ff-h696-f583)
- **Scope**: Vite dev server only (path traversal, fs.deny bypass, WebSocket file read)
- **Production impact**: ZERO — Vite is build-time only, dev server not used in production builds
- **Exploitable**: Only if attacker can reach `localhost:5173` (would need local network access during active dev session)
- **Mitigation**: Vite dev server bound to `localhost` only by default — not exposed to LAN
- **Status**: Watching for Vite 7.3.2+ patch release (Vite 8.x still in beta as of May 2026)
- **Action**: Update immediately when 7.3.2 lands

## Reporting Security Issues

Found a vulnerability? Email **<email-redacted>** (do not open public GitHub issue).
