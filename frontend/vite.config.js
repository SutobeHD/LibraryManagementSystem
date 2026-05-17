import { existsSync, readFileSync } from 'node:fs'
import { homedir, platform } from 'node:os'
import { join } from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Phase-1 auth-hardening (see
// docs/research/implement/draftplan_security-api-auth-hardening.md):
// the sidecar self-generates a session token at boot and persists it
// to ``%APPDATA%/MusicLibraryManager/.session-token`` (cross-platform
// via Python's ``platformdirs.user_data_dir``). In Tauri the Rust
// supervisor hands the token to the frontend over IPC; in the
// browser-dev path (``npm run dev:full``) the frontend has no IPC
// channel, so this Vite plugin re-exposes the file at ``GET /dev-token``
// for the api.js bootstrap to fetch.
//
// Dev-only by design — the plugin only registers its middleware on the
// dev server, so production bundles never reference the path. The
// token file lives in the user-data dir and is gitignored implicitly
// (it's never inside the repo working tree).

function _sessionTokenPath() {
  const appName = 'MusicLibraryManager'
  if (platform() === 'win32') {
    const base = process.env.APPDATA || join(homedir(), 'AppData', 'Roaming')
    return join(base, appName, '.session-token')
  }
  if (platform() === 'darwin') {
    return join(homedir(), 'Library', 'Application Support', appName, '.session-token')
  }
  const xdg = process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share')
  return join(xdg, appName, '.session-token')
}

function devTokenPlugin() {
  return {
    name: 'lms-dev-token-middleware',
    apply: 'serve', // never in production builds
    configureServer(server) {
      const tokenPath = _sessionTokenPath()
      server.middlewares.use('/dev-token', (_req, res) => {
        try {
          if (!existsSync(tokenPath)) {
            res.statusCode = 503
            res.setHeader('Content-Type', 'text/plain; charset=utf-8')
            res.end('session-token file not found; start the backend sidecar first')
            return
          }
          const token = readFileSync(tokenPath, 'utf-8').trim()
          if (!token) {
            res.statusCode = 503
            res.setHeader('Content-Type', 'text/plain; charset=utf-8')
            res.end('session-token file is empty')
            return
          }
          res.statusCode = 200
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.setHeader('Cache-Control', 'no-store')
          res.end(token)
        } catch (err) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.end(`dev-token middleware error: ${err && err.message ? err.message : String(err)}`)
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), devTokenPlugin()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/music_stream': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/exports': { target: 'http://127.0.0.1:8000', changeOrigin: true }
    }
  }
})
