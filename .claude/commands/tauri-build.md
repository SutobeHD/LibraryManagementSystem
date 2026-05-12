---
description: Production desktop build — bundle Rust + Python sidecar + frontend into installer
allowed-tools: Bash
---

Run the full production build:

```bash
npm run build && npm run tauri build
```

Output goes to `src-tauri/target/release/bundle/`. On Windows that includes `.msi` and `.exe` installers. The Python sidecar is frozen via PyInstaller using `backend.spec` and shipped inside the bundle.

Before reporting success: check the bundle directory exists and report installer sizes. Flag any warnings about unsigned binaries or missing icons.
