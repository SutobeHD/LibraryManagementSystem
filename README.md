# Music Library Manager

A standalone desktop DJ-library manager. **Competitor** to commercial library
software like Rekordbox and Serato — built around an open USB export format
that Pioneer CDJ-3000 and other modern hardware reads natively.

Local-first. No cloud backend. No subscription. Bring your own SoundCloud API
credentials. Optional Live mode integrates with an existing Rekordbox install,
but the full feature set works **without Rekordbox** via the standalone XML
mode.

## Features

- **Standalone Mode** — own internal XML library, full CRUD, no Rekordbox required
- **Live Mode** — read/write Rekordbox `master.db` via pyrekordbox (when installed)
- **SoundCloud → Library → USB** — full pipeline: download, full-pipeline analyse
  (BPM / Key / Beatgrid / Phrases / Auto-Hot-Cues / Waveform), auto-import,
  auto-playlist (`SC_<name>`), USB-export
- **Local-File Import** — drag-drop / folder browse → folder name becomes the
  playlist, every file (incl. duplicates) gets bundled together
- **Live Pipeline Transparency** — Import Manager view + sticky progress banner
  show every track's stage (Queued → Analyzing → Importing → ANLZ → Completed)
- **Playlist Workflow** — create / rename / delete / duplicate / move / drag
  reorder, folders, smart playlists with field/operator/value/unit conditions
- **Track-Table Inline Edits** — click-to-rate (5 stars), Pioneer color-tag
  picker (9 colors), context menu with BPM/Key quick-edit
- **Search Operators** — `bpm:120-130 key:Am genre:techno year:2024 rating:>3`
- **USB Export to CDJ** — writes `PIONEER/rekordbox/exportLibrary.db` +
  `PIONEER/USBANLZ/<bucket>/<hash>/ANLZ0000.{DAT,EXT,2EX}` (beatgrid + cues +
  waveform) + audio + cover art. CDJ-3000 reads everything natively.
- **Audio Tools** — non-destructive Waveform Editor (cut/insert/delete/paste,
  ffmpeg sample-accurate seek), 3-band waveform FFT

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
- [docs/research/](./docs/research/README.md) — open research topics + feature investigations (persistent across chat sessions)

## Security

- No hardcoded credentials. `.env` is the single source.
- CORS locked to localhost.
- Path sandbox via `ALLOWED_AUDIO_ROOTS`.
- System endpoints behind `X-Session-Token`.
- All SC API calls have rate-limit backoff (429) + auth-error gates (401/403).

## Legal

Reads your own SC playlists, likes, streams via your own OAuth token. Downloads only when the creator enabled the download button OR the stream is one your account is already authorised for. Snipped previews are skipped. No DRM bypass, no paywall circumvention.

## Working with Claude Code

This repo ships a team-shared agent config so [Claude Code](https://claude.com/claude-code) works productively from the first `git clone`:

- **[CLAUDE.md](./CLAUDE.md)** — agent operating manual (stack overview, build commands, coding rules, autonomy boundaries)
- **`.claude/settings.json`** — committed permission allowlist (npm / pytest / cargo / git read-only — always allowed; pushes / commits / new deps — confirmed)
- **`.claude/commands/`** — slash commands: `/dev-full`, `/tauri-dev`, `/tauri-build`, `/test-py`, `/audit`, `/sync-docs`, `/route-add`, `/full-check`, `/sync-check`, `/commit`
- **`.claude/agents/`** — focused subagents: `doc-syncer`, `route-architect`, `audio-stack-reviewer`

Per-machine overrides go in `.claude/settings.local.json` (gitignored). Copy from `.claude/settings.local.json.example` to start.

## License

See [LICENSE](./LICENSE).
