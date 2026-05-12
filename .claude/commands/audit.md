---
description: Full security audit — npm audit + lockfile lint + script audit
allowed-tools: Bash
---

Run the three-layer audit in sequence:

```bash
npm run audit
npm run lint:lockfile
```

Then run the platform-specific deep audit:

- Windows / PowerShell: `powershell -File scripts/security-audit.ps1`
- Unix: `./scripts/security-audit.sh`

Summarise findings as: (1) high/critical CVEs (action required), (2) moderate CVEs (review), (3) lockfile issues. Suppress informational/low noise unless the user asks for the full report.

If anything critical surfaces, **do not** auto-update dependencies — the project pins exact versions (Schicht-A Hardening 2026). Surface the CVE + suggested target version and let the user approve.
