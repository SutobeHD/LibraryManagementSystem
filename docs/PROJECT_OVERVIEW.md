# 🏗 PROJECT OVERVIEW: LibraryManagementSystem

A high-performance desktop application for professional DJ library management, built with Tauri, React, and Python FastAPI.

This document provides a comprehensive overview of the current architecture, tech stack, and state management of the application.

## 1. Tech Stack & Environment
The project is built as a **hybrid desktop application** using **Tauri**, combining a modern React frontend with a high-performance Python FastAPI backend.

### Frontend
- **Framework:** React 18 with Vite
- **Styling:** Tailwind CSS (with Autoprefixer & PostCSS)
- **Icons:** Lucide React
- **Audio Visualization:** Wavesurfer.js (used for advanced waveforms, e.g., 3-band UI)
- **State/Routing:** Custom React hooks, standard React state management (`useState`, `useEffect`), basic routing.
- **Desktop Integration:** `@tauri-apps/api` (v2) for native desktop capabilities.

### Backend
- **Framework:** FastAPI (Python)
- **Server:** Uvicorn
- **Audio Processing:** Librosa, SciPy, Numba (for high-performance audio analysis like BPM/Key detection and beat grid generation).
- **Libraries/Tools:** `sqlalchemy` for DB operations, `psutil` for system metrics, `requests` for external APIs (like SoundCloud).

## 2. Project Architecture & File Structure
```text
Root/
├── app/                  # Python FastAPI Backend
│   ├── main.py           # FastAPI entry point, defines all REST endpoints (/api/*)
│   ├── services.py       # Core business logic (AudioEngine, LibraryTools, etc.)
│   ├── database.py       # DB abstraction (handles both XML & Live DB modes)
│   ├── soundcloud_api.py # SoundCloud Playlist and Sync logic
│   ├── soundcloud_downloader.py # Logic for downloading tracks from SoundCloud
│   └── ...
├── frontend/             # React/Vite Frontend
│   ├── src/              # React components, hooks, styles
│   └── package.json      # Frontend dependencies
├── src-tauri/            # Rust code integrating the frontend and backend in a desktop window
├── requirements.txt      # Python dependencies
├── package.json          # Root package definitions (scripts for dev/build)
└── docs/                 # Documentation (this folder)
```

## 3. Communication & Routing
- **Internal APIs:** The React frontend communicates with the FastAPI backend over local HTTP REST calls (e.g., `http://localhost:8000/api/*`). The backend provides endpoints for library management, playlist manipulation, audio streaming, and SoundCloud integration.
- **Audio Streaming:** The backend serves audio chunks securely using `/api/stream` and `/api/audio/stream`, ensuring paths belong to allowed directories (`ALLOWED_AUDIO_ROOTS`).
- **External APIs:** The backend reaches out to SoundCloud APIs (via `requests`) to fetch playlists, metadata, and handle audio downloading.

## 4. State Management
- **Frontend:** Relies heavily on React context/hooks for global state (e.g., currently loaded playlists, player state, analysis data).
- **Backend:** The `app/database.py` maintains an in-memory or live-synced state of the user's music library and playlists, with mechanisms to save back to XML or the Live Rekordbox DB (`master.db`).

## 5. Security & Isolation
- **CORS:** Locked down strictly to localhost origins (`127.0.0.1`, `localhost`, `tauri://localhost`).
- **File Access:** Audio file streaming enforces strict path traversal checks (`validate_audio_path`), ensuring the UI only accesses approved drives/folders.
