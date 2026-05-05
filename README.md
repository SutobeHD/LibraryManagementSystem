# LibraryManagementSystem

Desktop companion for DJs. Bridges SoundCloud playlists with local Rekordbox-compatible library. Local-first, no shared backend.

## Features

- **Live + XML Modes** — direct Rekordbox `master.db` or XML snapshot
- **SoundCloud Sync** — playlists, likes, fuzzy match against local library
- **Respectful Downloads** — only `downloadable=true` tracks + streams the user already has access to. No paywall bypass, no DRM.
- **Audio Tools** — non-destructive editing, beatgrids, cues, 3-band waveform analysis (FFT)
- **USB Sync** — incremental backup engine for CDJ devices
- **Metadata QC** — bitrate, artwork, duplicate detection

## Stack

- **Frontend**: React 18 + Vite + Tailwind
- **Backend (Sidecar)**: Python 3.10+ FastAPI, port 8000
- **Desktop**: Tauri 2 (Rust), native audio via CPAL/Symphonia
- **External**: FFmpeg (system PATH)

## Setup

### Prerequisites

- Node.js 18+
- Python 3.10+
- Rust ([rustup](https://rustup.rs/))
- FFmpeg in PATH

### 1. Clone + install

```bash
git clone <repo-url>
cd RB_Editor_Pro
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### 2. Register your own SoundCloud app

**Each user runs with their own credentials. There is no shared/baked-in app.**

1. Sign in at [soundcloud.com](https://soundcloud.com)
2. Open [soundcloud.com/you/apps](https://soundcloud.com/you/apps) → **Register a new app**
3. Name: anything neutral (e.g. `Crate Sync — <yourname>`)
4. Redirect URI: `http://127.0.0.1:5001/callback`
5. Copy **Client ID** + **Client Secret**

### 3. Configure `.env`

```bash
cp .env.example .env
# edit .env, paste your client ID + secret
```

`.env` is gitignored. Never commit it.

### 4. Run

```bash
npm run dev:full       # backend + frontend
npm run tauri dev      # full desktop app
```

## Project Layout

| Path | Purpose |
|---|---|
| `frontend/src/` | React components, API client |
| `app/` | FastAPI backend, Rekordbox parser, SC API |
| `src-tauri/src/` | Tauri commands, audio engine, OAuth client |
| `docs/` | File map, architecture, indexes |

Detail docs:
- [docs/FILE_MAP.md](./docs/FILE_MAP.md) — master navigation
- [docs/architecture.md](./docs/architecture.md) — data flows
- [docs/frontend-index.md](./docs/frontend-index.md) — React index
- [docs/backend-index.md](./docs/backend-index.md) — FastAPI index
- [docs/rust-index.md](./docs/rust-index.md) — Tauri index

## Security

- No hardcoded credentials. `.env` is the single source.
- CORS locked to localhost.
- Path sandbox via `ALLOWED_AUDIO_ROOTS`.
- System endpoints behind `X-Session-Token`.
- All SC API calls have rate-limit backoff (429) + auth-error gates (401/403).

## Legal

Reads your own SC playlists, likes, streams via your own OAuth token. Downloads only when the creator enabled the download button OR the stream is one your account is already authorised for. Snipped previews are skipped. No DRM bypass, no paywall circumvention.

## License

See [LICENSE](./LICENSE).
