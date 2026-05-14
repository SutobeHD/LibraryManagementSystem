---
slug: linux-dj-workflow
title: Linux end-to-end DJ workflow — SoundCloud → analysis → CDJ-3000 USB without Rekordbox
owner: tb
created: 2026-05-13
last_updated: 2026-05-13
tags: []
related: []
---

# Linux end-to-end DJ workflow — SoundCloud → analysis → CDJ-3000 USB without Rekordbox

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-13 — `research/idea_` — created from template
- 2026-05-13 — `research/exploring_` — Findings section filled from initial gap analysis; promoted to active research

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

The app delivers the SoundCloud → analysis → CDJ-3000 USB workflow only on Windows. On Linux it breaks at several points: USB detection is pure Win32 API, path handling assumes drive letters, the Tauri sidecar binary name mismatches case-sensitively, and Rekordbox-path autodetection has no non-Windows branch. A Linux DJ cannot currently get from a SoundCloud playlist to a club-ready USB stick with our app. Without fixing this, the core product promise — "no Rekordbox, local-first, runs on Linux" — stays unmet against Rekordbox/Serato.

## Goals / Non-goals

**Goals**
- A Linux DJ can run the full pipeline end-to-end: SC playlist login → bulk download → auto-analysis → USB export readable natively by a CDJ-3000, with no Rekordbox anywhere.
- The Tauri desktop app boots on Linux (sidecar starts, frontend loads).
- USB detection + path handling work with Linux mount points (`/media/...`, `/run/media/...`).
- Existing Windows behaviour is unchanged — no regressions.
- CI builds and smoke-tests the Linux path.

**Non-goals** (deliberately out of scope)
- macOS support — separate effort, though some path fixes will incidentally help it.
- Realtime audio preview/playback stack on Linux (cpal/ALSA/Pipewire tuning) — separate topic.
- Lifting the OneLibrary 16-track / PDB ~500-track caps — tracked separately, not a Linux-specific blocker.
- Wine-hosted Rekordbox interop.
- AppImage packaging — deb/rpm is sufficient for the first milestone.

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- `app/usb_manager.py:94-280` is 100% Win32 (`ctypes.windll.kernel32`, PowerShell `Get-Disk`) — no Linux code path exists at all.
- Tauri sidecar lookup is case-sensitive on Linux; the binary name currently diverges across 4 files (`RB_Backend` vs `rb-backend`).
- There is no Rekordbox on Linux — `%APPDATA%\Pioneer\rekordbox` autodetection must degrade to "not installed" cleanly, not crash.
- FFmpeg is a PATH dependency, not bundled — the Linux user must install it via their distro package manager.
- CI currently builds deb/rpm but runs zero Linux runtime or USB tests.
- The PDB byte layout is verified byte-for-byte against a real Pioneer-exported F: drive — platform-neutral, and must stay byte-identical.
- Schicht-A pinning: any new dependency (`platformdirs`, `pyudev`) is a security decision — needs sign-off and `==` pinning.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. Linux USB detection — `pyudev` (new dep) vs `lsblk -J` subprocess vs `psutil.disk_partitions`? Which is most robust without root privileges?
2. Standalone `master.db` location on Linux — `platformdirs.user_data_dir` (new dep) vs hand-rolled `~/.local/share/...`?
3. Does the PyInstaller Linux sidecar from `release.yml` actually boot, or are shared libs missing beyond what CI installs (libsndfile, libffi, …)?
4. The format-wizard needs a block-device path (`/dev/sdb1`) — can Linux detection supply both the mount point and the device node?
5. Is browser dev-mode (`npm run dev:full`) on Linux a supported shipping target, or only the Tauri bundle?
6. exFAT on Linux — is `mkfs.exfat` reliably available across target distros, or do we fall back to FAT32?

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-13 — Initial gap analysis: Windows-complete, Linux-broken

Full codebase audit of the SC → analysis → USB pipeline against the "runs on Linux" goal.

**Pipeline status:**

| Stage | Status | Key ref |
|---|---|---|
| SC OAuth (PKCE) | works, platform-neutral | `src-tauri/src/soundcloud_client.rs` |
| SC playlist browser + bulk download | works | `frontend/src/components/SoundCloudSyncView.jsx`, `app/main.py:2894` |
| SC track download (MP3 + HLS mux) | works | `app/soundcloud_downloader.py:286` |
| Auto-analysis after download | works | `app/soundcloud_downloader.py:1146` |
| DSP engine (BPM/key/beatgrid/phrases) | works | `app/analysis_engine.py:1992` |
| ANLZ file writing | works, byte-validated | `app/anlz_writer.py`, `app/anlz_sidecar.py` |
| PDB writer (CDJ-3000) | works, ~500-track cap | `app/usb_pdb.py`, `tests/test_pdb_structure.py` |
| OneLibrary writer (RB7) | works, 16-track cap | `app/usb_one_library.py` |
| USB detection | **Linux-broken** | `app/usb_manager.py:94-280` |
| USB path handling | **Linux-broken** | `app/usb_manager.py:739`, `app/usb_one_library.py:54` |
| Tauri sidecar boot | **Linux-broken** | naming mismatch, see below |
| Rekordbox path autodetect | **Win-only** | `app/database.py:712-720`, `app/main.py:150` |

**Works today, platform-neutral:** SC OAuth, playlist API (`app/soundcloud_api.py:376/441/504`), download pipeline, auto-analysis trigger, and the whole DSP + ANLZ + PDB + OneLibrary writing chain — all pure Python / cross-platform Rust. A Linux release build already exists in `.github/workflows/release.yml:46-101` (PyInstaller sidecar + deb/rpm bundle).

**Hard blockers on Linux:**
1. **USB detection** — `app/usb_manager.py:94-280` is 100% Win32 (`ctypes.windll.kernel32.GetLogicalDrives`, `GetDriveTypeW`, PowerShell `Get-Disk`). No Linux code path; `GET /api/usb/devices` crashes or returns empty.
2. **USB path handling** — drive-letter heuristic `usb_root[1]==":"` (`app/usb_one_library.py:54`) plus backslash-append (`app/usb_manager.py:739`). Breaks on `/media/dj/STICK`.
3. **Sidecar naming mismatch** — `tauri.conf.json:49` says `binaries/RB_Backend`, `src-tauri/src/main.rs:335` calls `shell.sidecar("rb-backend")`, `capabilities/main.json:14` whitelists `binaries/rb-backend`, `release.yml:91` produces `RB_Backend-*`. The case-insensitive FS hides this on Windows; Linux exec-fails → the app won't boot.
4. **Rekordbox path autodetect** — `%APPDATA%\Pioneer\rekordbox` hardcoded in `app/database.py:712-720`, `app/main.py:150/1114/1599`, `app/services.py:148`. No non-Windows branch; the standalone-DB fallback (`app/database.py:719`) also uses `%APPDATA%`.
5. **Frontend USB filter** — `frontend/src/components/UsbView.jsx:81` hardcodes a `'C:\\','C:/','C:'` skip list.
6. **No Linux runtime/USB test in CI** — `.github/workflows/` builds deb/rpm but exercises nothing at runtime.

**Brittle / half-built (in scope to be aware of, not all Linux-specific):**
- PDB ~500-track linear-scan limit (`app/usb_pdb.py`).
- OneLibrary hard 16-track cap (`app/usb_one_library.py:101`) — template placeholder rows.
- `shell:allow-execute` unrestricted in `capabilities/main.json:19` (FILE_MAP claims it was removed — doc drift).
- Redundant single-URL view `frontend/src/components/SoundCloudView.jsx` vs `SoundCloudSyncView.jsx`.
- rbox 0.1.7 panic isolation (`app/anlz_safe.py`) untested on Linux.

**Themes emerging for the plan (to detail at `evaluated_` / `draftplan_`):**
- A platform-strategy abstraction for USB detection (Windows / Linux / macOS detectors behind one API, backend route unchanged).
- Platform-aware path config in `app/config.py` (Rekordbox root optional, standalone DB dir cross-platform).
- Unify the sidecar binary name to one spelling across all 4 files.
- A Linux CI job: at minimum `pytest tests/test_pdb_structure.py` + a Tauri build smoke test.
- New deps likely needed (`platformdirs`, possibly `pyudev`) — security sign-off + pinning required.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort: S/M/L/XL
- Risk:

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

---

## Implementation Plan

> Required from `implement/draftplan_` onward. Concrete enough that someone else could execute it without re-deriving the design.

### Scope
- **In:** …
- **Out (deliberately):** …

### Step-by-step
1. …
2. …

### Files touched (expected)
- …

### Testing approach
- …

### Risks & rollback
- …

## Review

> Filled by reviewer at `review_`. If any box is unchecked or rework reasons are listed, the doc moves to `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or explicitly deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons** (only if applicable):
- …

## Implementation Log

> Filled during `inprogress_`. What got built, what surprised us, what changed from the plan. Dated entries.

### YYYY-MM-DD
- …

---

## Decision / Outcome

> Required by `archived/*`. Final state of the topic.

**Result**: `implemented` | `superseded` | `abandoned`
**Why**: …
**Rejected alternatives** (one line each):
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_` graduation):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code: <file:line or PR>
- External docs: <url>
- Related research: <slugs>
