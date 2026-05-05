# NAMING MAP — "LibraryManagementSystem" → "LibraryManagementSystem"

**Zweck**: Vollständiges Mapping aller Name-Vorkommen im Projekt für aktuelle Umbenennungen und zukünftige Referenzen.

**Letzte Aktualisierung**: 2026-05-05  
**Status**: Refactor-Dokumentation für Alpha v0.0.2

---

## 📋 Inhaltsverzeichnis

1. [Kritische Stellen (Funktionalität)](#kritische-stellen)
2. [Paket & Bundle Identifikatoren](#paket--bundle)
3. [Frontend UI Strings](#frontend-ui)
4. [Python Module (Header-Kommentare)](#python-header)
5. [Dokumentation](#dokumentation)
6. [Agent-Definitionen](#agent-def)
7. [Skripte & Shells](#skripte)
8. [Lizenz & Umgebung](#lizenz)

---

## Kritische Stellen (Funktionalität) {#kritische-stellen}

### Keyring Service Names — app/main.py
**Kontext**: SoundCloud OAuth Token-Speicherung via Windows Credential Manager  
**Kritikalität**: 🔴 KRITISCH — Falsch benannt bricht Login

| Zeile | Code | Change To |
|-------|------|-----------|
| 1835 | `keyring.get_password("rb_editor_pro", "sc_token")` | `"library_management_system"` |
| 2008 | `keyring.set_password("rb_editor_pro", "sc_token", token)` | `"library_management_system"` |
| 2013 | `keyring.delete_password("rb_editor_pro", "sc_token")` | `"library_management_system"` |
| 2073 | `keyring.get_password("rb_editor_pro", ...)` | `"library_management_system"` |
| 2137 | `keyring.set_password("rb_editor_pro", ...)` | `"library_management_system"` |
| 2168 | `keyring.delete_password("rb_editor_pro", ...)` | `"library_management_system"` |
| 2214 | `keyring.get_password("rb_editor_pro", ...)` | `"library_management_system"` |
| 2258 | `keyring.set_password("rb_editor_pro", ...)` | `"library_management_system"` |
| 2302 | `keyring.delete_password("rb_editor_pro", ...)` | `"library_management_system"` |

**Anmerkung**: Benutzer, die bereits mit "rb_editor_pro" Tokens haben, können nach Refactor nicht auf diese zugreifen. Ggf. Migrations-Helper schreiben (optional).

### Bundle Identifier — src-tauri/tauri.conf.json
**Kontext**: Tauri App-Identifier für Windows Installer & System  
**Kritikalität**: 🔴 KRITISCH — Falscher Name bricht Installer

| Zeile | Code | Change To |
|-------|------|-----------|
| 5 | `"identifier": "com.rbeditor.pro"` | `"com.librarymanagement.system"` |

**Anmerkung**: Nach Änderung: Alte Installer sind nicht kompatibel. Benutzer müssen alte Version vollständig deinstallieren.

---

## Paket & Bundle Identifikatoren {#paket--bundle}

### src-tauri/Cargo.toml
| Zeile | Code | Change To |
|-------|------|-----------|
| 2 | `name = "rb-editor-pro"` | `name = "library-management-system"` |

### package.json (Root)
| Zeile | Code | Change To |
|-------|------|-----------|
| 3 | `"name": "music-library-manager"` | Keep as is (Arbeitstitel) |
| 4 | `"description": "LibraryManagementSystem — Rekordbox..."` | `"description": "LibraryManagementSystem — Rekordbox..."` |

### frontend/package.json
| Zeile | Code | Change To |
|-------|------|-----------|
| 2 | `"name": "rb-editor"` | `"name": "lms-frontend"` oder `"library-management-system-frontend"` |

---

## Frontend UI Strings {#frontend-ui}

### frontend/index.html
| Zeile | Code | Change To |
|-------|------|-----------|
| 7 | `<title>LibraryManagementSystem</title>` | `<title>LibraryManagementSystem</title>` |

### frontend/src/main.jsx
| Zeile | Code | Change To |
|-------|------|-----------|
| 93 | `<span>LibraryManagementSystem</span>` | `<span>Library Manager</span>` (oder `LMS`) |
| 442 | `<p>LibraryManagementSystem</p>` | `<p>LibraryManagementSystem</p>` |

### frontend/src/components/DesignView.jsx
| Zeile | Code | Change To |
|-------|------|-----------|
| 514 | `<span>LibraryManagementSystem</span>` | `<span>LibraryManagementSystem</span>` |

### frontend/src/components/SettingsView.jsx
| Zeile | Code | Change To |
|-------|------|-----------|
| 1021 | `<p>LibraryManagementSystem — Configure...</p>` | `<p>LibraryManagementSystem — Configure...</p>` |

### frontend/src/index.css
| Zeile | Code | Change To |
|-------|------|-----------|
| 2 | `/* LibraryManagementSystem — Melodex design system */` | `/* LibraryManagementSystem — Melodex design system */` |

---

## Python Module Header-Kommentare {#python-header}

**Kontext**: Modul-Dokumentation am Dateianfang  
**Kritikalität**: 🟡 Optional — keine Funktionalität, nur Doku

| Datei | Zeile | Current | Change To |
|-------|-------|---------|-----------|
| app/analysis_db_writer.py | 2 | `# LibraryManagementSystem -- Analysis-to-Database Writer` | `# LibraryManagementSystem -- Analysis-to-Database Writer` |
| app/analysis_engine.py | 2 | `# LibraryManagementSystem -- High-Accuracy Analysis Engine (v2.0)` | `# LibraryManagementSystem -- High-Accuracy Analysis Engine (v2.0)` |
| app/anlz_writer.py | 2 | `# LibraryManagementSystem -- ANLZ Binary File Writer` | `# LibraryManagementSystem -- ANLZ Binary File Writer` |
| app/audio_analyzer.py | 2 | `# LibraryManagementSystem -- Audio Analyzer (Unified Wrapper)` | `# LibraryManagementSystem -- Audio Analyzer (Unified Wrapper)` |
| app/database.py | 2 | `# LibraryManagementSystem -- Database Layer` | `# LibraryManagementSystem -- Database Layer` |
| app/live_database.py | 2 | `# LibraryManagementSystem -- Live Rekordbox Database` | `# LibraryManagementSystem -- Live Rekordbox Database` |
| app/main.py | 1 | `# LibraryManagementSystem -- FastAPI Backend` | `# LibraryManagementSystem -- FastAPI Backend` |
| app/playcount_sync.py | 2 | `# LibraryManagementSystem -- Play Count Sync` | `# LibraryManagementSystem -- Play Count Sync` |
| app/rekordbox_export.py | 2 | `# LibraryManagementSystem -- Rekordbox Export` | `# LibraryManagementSystem -- Rekordbox Export` |
| app/services.py | 2 | `# LibraryManagementSystem -- Services Layer` | `# LibraryManagementSystem -- Services Layer` |
| app/usb_manager.py | 2 | `# LibraryManagementSystem -- USB Device Manager` | `# LibraryManagementSystem -- USB Device Manager` |
| app/waveform_cache.py | 2 | `# LibraryManagementSystem -- Waveform Cache` | `# LibraryManagementSystem -- Waveform Cache` |

### Weitere Python-Stellen

| Datei | Zeile | Code | Change To |
|-------|-------|------|-----------|
| app/playcount_sync.py | 31 | `"""Load the LibraryManagementSystem sync metadata..."""` | `"""Load the LibraryManagementSystem sync metadata..."""` |
| app/rekordbox_export.py | 39 | `"Analyzed by LibraryManagementSystem"` | `"Analyzed by LibraryManagementSystem"` |
| app/services.py | 282 | `"LibraryManagementSystem"` (fallback artist name) | `"LibraryManagementSystem"` |

---

## Dokumentation {#dokumentation}

### Markdown-Dateien im docs/ Verzeichnis

| Datei | Zeile | Current Titel | Change To |
|-------|-------|---------------|-----------|
| README.md | 1 | `# LibraryManagementSystem` | `# LibraryManagementSystem` |
| CLAUDE.md | 1 | `# CLAUDE.md — LibraryManagementSystem...` | `# CLAUDE.md — LibraryManagementSystem...` |
| CLAUDE.md | 54 | `LibraryManagementSystem is a Tauri...` | `LibraryManagementSystem is a Tauri...` |
| docs/architecture.md | 1 | `# ARCHITECTURE.md — LibraryManagementSystem` | `# ARCHITECTURE.md — LibraryManagementSystem` |
| docs/FILE_MAP.md | 1 | `# FILE_MAP.md — LibraryManagementSystem` | `# FILE_MAP.md — LibraryManagementSystem` |
| docs/PROJECT_OVERVIEW.md | 1 | `# LibraryManagementSystem` | `# LibraryManagementSystem` |
| docs/DOWNLOAD_EVALUATION.md | 3 | `...in LibraryManagementSystem.` | `...in LibraryManagementSystem.` |

---

## Agent-Definitionen {#agent-def}

**Kontext**: Claude Agent Spezialisierungen in .claude/agents/  
**Kritikalität**: 🟡 Optional — nur für Dokumentation

| Datei | Zeile | Current | Change To |
|-------|-------|---------|-----------|
| .claude/agents/backend-agent.md | 3 | `description: ...for LibraryManagementSystem...` | `description: ...for LibraryManagementSystem...` |
| .claude/agents/backend-agent.md | 8 | `You are the Python backend specialist for LibraryManagementSystem` | `You are the Python backend specialist for LibraryManagementSystem` |
| .claude/agents/frontend-agent.md | 3 | `description: ...for LibraryManagementSystem...` | `description: ...for LibraryManagementSystem...` |
| .claude/agents/frontend-agent.md | 8 | `You are the frontend specialist for LibraryManagementSystem` | `You are the frontend specialist for LibraryManagementSystem` |
| .claude/agents/qa-agent.md | 3 | `description: ...for LibraryManagementSystem...` | `description: ...for LibraryManagementSystem...` |
| .claude/agents/qa-agent.md | 8 | `You are the QA specialist for LibraryManagementSystem` | `You are the QA specialist for LibraryManagementSystem` |
| .claude/agents/rust-agent.md | 3 | `description: ...for LibraryManagementSystem...` | `description: ...for LibraryManagementSystem...` |
| .claude/agents/rust-agent.md | 8 | `You are the Rust and Tauri specialist for LibraryManagementSystem` | `You are the Rust and Tauri specialist for LibraryManagementSystem` |

---

## Skripte & Shells {#skripte}

| Datei | Zeile | Code | Change To |
|-------|-------|------|-----------|
| scripts/security-audit.sh | 10 | `echo "==> Security Audit (LibraryManagementSystem)"` | `echo "==> Security Audit (LibraryManagementSystem)"` |
| scripts/security-audit.ps1 | 8 | `Write-Host "==> Security Audit (LibraryManagementSystem)"` | `Write-Host "==> Security Audit (LibraryManagementSystem)"` |

---

## Lizenz & Umgebung {#lizenz}

| Datei | Zeile | Code | Change To |
|-------|-------|------|-----------|
| LICENSE | 3 | `Copyright (c) 2026 LibraryManagementSystem contributors` | `Copyright (c) 2026 LibraryManagementSystem contributors` |
| .env.example | 2 | `# LibraryManagementSystem — Environment Configuration` | `# LibraryManagementSystem — Environment Configuration` |

---

## Rust Logging {#rust}

| Datei | Zeile | Code | Change To |
|-------|-------|------|-----------|
| src-tauri/src/main.rs | 127 | `println!("[LibraryManagementSystem] Found .env...")` | `println!("[LibraryManagementSystem] Found .env...")` |
| src-tauri/src/main.rs | 128 | `println!("[LibraryManagementSystem] No .env file...")` | `println!("[LibraryManagementSystem] No .env file...")` |

---

## Auto-Generated Dateien (NICHT BEARBEITEN) {#autogen}

Diese Dateien werden **automatisch** regeneriert und sollten nicht manuell bearbeitet werden:

- `package-lock.json` — Wird nach `npm install` regeneriert
- `frontend/package-lock.json` — Wird nach `cd frontend && npm install` regeneriert
- Alles in `node_modules/` — Wird nach `npm install` neu erstellt

---

## Refactor-Checkliste

- [ ] Phase 1: Dieses Dokument erstellt ✅
- [ ] Phase 2a: Keyring-Service-Namen in app/main.py (9 Stellen)
- [ ] Phase 2b: Bundle-ID in tauri.conf.json
- [ ] Phase 2c: Paket-Namen (Cargo.toml, package.json)
- [ ] Phase 2d: Frontend UI Strings (React + HTML)
- [ ] Phase 2e: Python Module Header-Kommentare
- [ ] Phase 2f: Dokumentation (Markdown)
- [ ] Phase 2g: Agent-Definitionen
- [ ] Phase 2h: Skripte & Shells
- [ ] Phase 3: Build-Test (`npm run build`)
- [ ] Phase 4: Tauri-Build-Test (`npm run tauri build`)
- [ ] Phase 5: Runtime-Verifikation
- [ ] Phase 6: Git Commit

---

## Hinweise für zukünftige Umbenennungen

Folge diesen Schritten wenn "LibraryManagementSystem" später umbenannt werden soll:

1. **Dieses Dokument aktualisieren** (NAMING_MAP.md)
2. **Grep für Reste**: `grep -ri "LibraryManagementSystem" --include="*.py" --include="*.jsx" --include="*.toml" --include="*.json"`
3. **Lockfiles neu generieren**: `npm install && cd frontend && npm install`
4. **Build testen**: `npm run build && npm run tauri build`
5. **Git commit** mit Clear Message: `refactor(branding): rename LibraryManagementSystem to [NewName]`