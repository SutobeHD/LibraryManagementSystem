---
description: Launch the full Tauri desktop app (Rust + Python sidecar + React frontend)
allowed-tools: Bash
---

Launch the desktop shell:

```bash
npm run tauri dev
```

This compiles the Rust crate in `src-tauri/`, boots the bundled Python sidecar via `backend_entry.py` / `backend.spec`, and serves the React frontend through the Tauri webview.

Boot order: Rust binary → Python sidecar (port 8000) → frontend bundle → webview window. If the window stays blank, the sidecar usually failed — check the terminal for Python tracebacks and verify FFmpeg is on PATH.
