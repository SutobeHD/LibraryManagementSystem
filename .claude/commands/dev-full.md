---
description: Start backend (FastAPI port 8000) + frontend (Vite port 5173) concurrently
allowed-tools: Bash
---

Run the full dev stack:

```bash
npm run dev:full
```

This kills any existing process on ports 8000/5173 first (via the `cleanup` script), then launches:
- Frontend: `npm run dev --prefix frontend` (Vite on http://localhost:5173)
- Backend: `python -m app.main` (FastAPI on http://127.0.0.1:8000)

After starting, verify the backend is reachable: `curl http://127.0.0.1:8000/api/system/health`. Report any startup errors immediately.
