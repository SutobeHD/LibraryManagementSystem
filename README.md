# RB Editor Pro

Rekordbox Editor Pro is a high-performance desktop application designed for advanced DJ library management and audio processing. It integrates directly with Rekordbox (Live Mode) or uses XML snapshots to provide tools for cleaning metadata, matching tracks via SoundCloud, and high-fidelity audio editing.

## 🚀 Key Features

- **Live & XML Modes**: Direct integration with Rekordbox `master.db` or standard XML exports.
- **Audio Processing**: High-fidelity track slicing and rendering using FFmpeg.
- **Metadata Tools**: Batch cleaning of track titles, artist folders, and label structures.
- **SoundCloud Integration**: Match tracks from your library to SoundCloud for easier harvesting.
- **Insights & Quality Control**: Detect low-bitrate tracks and those missing artwork.
- **Backup Management**: Deep integration for periodic library backups and restoration.

## 🛠 Tech Stack

- **Frontend**: React (Vite), Tailwind CSS (Glassmorphism), Lucide Icons.
- **Backend (Sidecar)**: Python (FastAPI), librosa (Audio Analysis), FFmpeg.
- **Desktop Wrapper**: Tauri (Rust), tokio (Native Processing).

## 🛠 Setup & Development

### Prerequisites
- [Node.js](https://nodejs.org/) (v18+)
- [Python 3.10+](https://www.python.org/)
- [Rust](https://rustup.rs/) (for Tauri)
- [FFmpeg](https://ffmpeg.org/) (must be in system PATH)

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd RB_Editor_Pro
   ```

2. **Backend Setup**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Frontend Setup**:
   ```bash
   cd frontend
   npm install
   ```

### Running Locally

To run both the backend and frontend simultaneously in development mode:
```bash
npm run dev:full
```

Or run Tauri directly:
```bash
npm run tauri dev
```

## 📂 Project Structure

A detailed overview of the files and functions can be found in [PROJECT_WIKI.md](./PROJECT_WIKI.md).

## 🔒 Security & Stability

The project has undergone a comprehensive security audit, including:
- CORS lockdown to localhost origins.
- Path sandboxing for all audio streaming.
- Session-token protected system endpoints.
- Granular React Error Boundaries.
- Async processing for heavy CLI tools.
