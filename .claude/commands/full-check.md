---
description: Run everything — Python lint+test, Rust check+fmt, frontend build, full audit
allowed-tools: Bash
---

Run the full quality gate in parallel where possible:

```bash
# Python
ruff check app/ tests/
pytest -v

# Rust
cargo check --manifest-path src-tauri/Cargo.toml
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings

# Frontend
npm run build

# Audit
npm run audit
npm run lint:lockfile
```

Report a punch-list per layer:
- ✓ pass, ✗ fail with first error line + file:line, ⚠ warning summary count

If any layer fails, surface the **first** failure prominently — don't bury it under success messages. Don't try to auto-fix unless the failure is trivially mechanical (unused import, formatting). Anything semantic (clippy correctness lint, failing assertion) — flag and stop.
