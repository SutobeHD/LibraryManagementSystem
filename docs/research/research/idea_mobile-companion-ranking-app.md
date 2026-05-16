---
slug: mobile-companion-ranking-app
title: Mobile companion app — soft client focused on Ranking mode, requires main app running on server/PC
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [mobile, companion, pwa, ranking, network, auth]
related: []
---

# Mobile companion app — soft client focused on Ranking mode, requires main app running on server/PC

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — `research/idea_` — section fill (research dive)
- 2026-05-15 — `research/idea_` — tech-choice deep-dive + QR-pairing UX sketch

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

A **soft / thin mobile version** of the desktop app, **mainly focused on Ranking mode**. The mobile client is **not standalone** — it only works when the main app is reachable as a server (PC / dedicated host on the same network or via tunnel). All library state, audio, analysis, and DB writes stay on the main app; the mobile app is a remote UI surface. Useful for ranking / tagging tracks away from the desk (couch, studio sofa, on-the-road), without lugging the laptop.

## Goals / Non-goals

**Goals**
- Mobile client that replicates **Ranking mode only**: pick a source (playlist / artist / label / album), step through queue, set Rating (1-5), ColorID, Genre, free-text Comment / tag-chip-toggles, optional MyTags (live mode). Persist via `POST /api/track/{tid}` (+ `POST /api/track/{tid}/mytags`).
- Run as a **thin client**: 100% of state, DB writes, audio files stay on the desktop/server host. Mobile keeps no canonical library data.
- **Same-LAN first** path that just works (phone joins home Wi-Fi, opens URL, scans QR to pair).
- **Off-LAN path** as opt-in (Tailscale / Cloudflare Tunnel) — documented, not embedded.
- Share UI primitives with existing `frontend/src/components/RankingView.jsx` where feasible (chip styles, COLORS array, TAG_CATEGORIES).
- Thumb-first UX: swipe-right = Save & Next (replace `space` hotkey at `RankingView.jsx:88`), large star/color/chip hit targets, bottom-anchored primary action.

**Non-goals** (deliberately out of scope)
- Audio decoding on mobile. **No `WaveformEditor`, no playback.** The desktop already owns audio; mobile is metadata-only. (Reduces scope by ~80% — no FFmpeg, no wavesurfer, no CORS on file streaming.)
- Library management (import / scan / move / delete tracks).
- USB export, ANLZ writing, beatgrid editing, cue editing, analysis triggers.
- Offline-first sync. User steer: "should only work if app runs on a server or pc" → **hard-online** is the default. Local queue-and-sync explicitly deferred to a follow-up topic.
- App-store distribution in v1 (PWA install banner is enough).
- Native iOS / Android codebases.
- Multi-user / concurrent-editor conflict resolution (single-DJ assumption).

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- **CORS allowlist is localhost-only** (`app/main.py:209-225`): `http://localhost:1420`, `127.0.0.1:1420`, `localhost:5173`, `127.0.0.1:5173`, `localhost:8000`, `127.0.0.1:8000`, `tauri://localhost`, `https://tauri.localhost`. **Any mobile origin (e.g. `http://192.168.x.y:5173`, `https://<tailscale-name>.ts.net`, `https://<slug>.trycloudflare.com`) is rejected today.** Must extend allowlist (env-driven, opt-in) or proxy.
- **Frontend axios baseURL is hardcoded** to `http://127.0.0.1:8000` in non-browser-preview mode (`frontend/src/api/api.js:10`), with `VITE_API_BASE_URL` as override. Mobile build needs the host's LAN IP or tunnel hostname injected at build / runtime.
- **No per-request auth gate on ranking routes today.** `app/main.py` only token-gates `POST /api/system/shutdown` + `/restart` via `SHUTDOWN_TOKEN` (`main.py:2028-2050`). The `POST /api/system/init-token` + `X-Session-Token` mechanism described in `CLAUDE.md` is the **intended** auth surface — not currently enforced on `/api/track/*` / `/api/playlist/*`. Exposing FastAPI 8000 to a LAN (let alone the public internet via tunnel) **without** first adding token gating to write endpoints is unsafe. **Auth hardening is a hard prerequisite, not an option.**
- **`ALLOWED_AUDIO_ROOTS` sandbox** (`app/main.py:138, 160, 189`) bounds filesystem reads to whitelisted roots via `Path.is_relative_to`. Doesn't apply to ranking writes (which are DB-only), but anything that streams artwork / waveform PNGs to mobile must go through `validate_audio_path`.
- **Concurrency:** all `master.db` writes must go through `_db_write_lock` (RLock, `app/main.py`). Mobile-induced `POST /api/track/{tid}` already takes that path on the server — no new locking work, but every concurrent client adds contention.
- **rbox version quirks:** mobile must not trigger `OneLibrary.create_content()` (broken in rbox 0.1.7, see `app/usb_one_library.py`). Out of scope by design (no library mgmt), but worth pinning in non-goals.
- **Existing Ranking API surface (small):** `GET /api/playlists/tree`, `GET /api/artists | /labels | /albums | /genres`, `GET /api/playlist/{id}/tracks` (+ `/artist|label|album` equivalents), `GET /api/track/{id}` (for refresh), `GET /api/track/{id}/mytags`, `GET /api/mytags`, `POST /api/mytags`, `POST /api/track/{id}`, `POST /api/track/{id}/mytags`, `GET /api/settings` (for `ranking_filter_mode`). ~10 routes total — see `app/main.py:631, 697, 700, 713, 728, 810, 815, 840, 845, 862, 927, 1564, 1819` for the cluster.
- **Live-vs-XML mode parity:** MyTag write path requires `appMode === 'live'` (master.db). XML mode silently no-ops (`RankingView.jsx:81, 138-144, 197-205`). Mobile must read `libraryStatus.mode` and hide/disable the MyTag block in XML mode.
- **Team capacity:** solo dev. Anything requiring a parallel mobile codebase + sync (React Native, Flutter, native) is L/XL effort.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. **Confirm hard-online** — is "useless if server unreachable" definitive, or do we want a tiny offline queue (last N edits cached, push when back online)? User steer says hard-online; confirming locks scope.
2. **Tech-stack pick — PWA vs Capacitor vs React Native?** Recommendation leans PWA; need user sign-off before draftplan.
3. **Off-LAN strategy — Tailscale Funnel, Cloudflare Tunnel, ngrok, or "user's problem"?** Document one canonical recipe vs. punt entirely?
4. **Pairing UX — QR code from desktop showing `http(s)://<host>:<port>?token=<one-shot>` vs. manual URL + token entry vs. mDNS auto-discovery (`_libmgr._tcp.local`)?**
5. **Token lifetime** — persistent (paired once, valid until revoked) or short-lived (refresh on each desktop boot)? Trade-off: convenience vs. blast radius if phone is lost.
6. **Should desktop expose a separate read-only port (e.g. 8001) for mobile** that only mounts the ranking subset of routes, or extend 8000's auth gating uniformly?
7. **Artwork / waveform preview on mobile** — yes/no? Cheapest: skip (text-only ranking). Mid: send pre-generated cover thumbnails. Most: server-side waveform PNG. Affects bandwidth + `ALLOWED_AUDIO_ROOTS` surface.
8. **Concurrent-edit policy** — desktop and phone both editing the same track: last-write-wins (current), reject-if-stale (ETag / `updated_at`), or lock-on-load? Single-DJ assumption probably makes LWW fine.
9. **Swipe gestures — adopt a library (Framer Motion / use-gesture) or hand-roll?** Affects bundle size on a slow 4G first-load.
10. **iOS PWA limitations** — Safari restricts `beforeinstallprompt`, background tasks, etc. Acceptable for v1 (add-to-homescreen still works) or blocker?
11. **Hostname / HTTPS for PWA `installable` criteria** — PWAs need HTTPS (or `localhost`) for service workers + install banner. On a raw LAN IP (`http://192.168.x.y`), most install prompts are disabled. Decision: ship as a normal mobile-friendly web page in v1, only push "installable PWA" once a tunnel hostname (HTTPS) is wired?

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-15 — initial audit

**What "Ranking mode" actually is** (codebase truth, not guess):

- Lives in `frontend/src/components/RankingView.jsx` (602 lines). Mounted in `frontend/src/main.jsx:19, 162, 678` as the `ranking` tab. Lazy-loaded.
- **It is queue-based single-track curation**, not pairwise / Elo / playlist-relative ranking. The user picks a **source** (playlist / artist / label / album — `RankingView.jsx:107, 224-258`), the app pulls the full track list via the matching endpoint, optionally filters by `ranking_filter_mode` from `/api/settings` (`all` | `unrated` | `untagged`, `RankingView.jsx:240-248`), then walks the queue track-by-track.
- **Per-track edit surface** (`RankingView.jsx:73-86, 416-563`): `Rating` (0-5 stars), `ColorID` (Pioneer color palette 0-8, hex table `RankingView.jsx:37-43`), `Comment` (free-text + chip-toggle from `TAG_CATEGORIES` at lines 9-14: Genre / Subgenre / Components / Type), `Genre` (datalist autocomplete from `/api/genres`), Pioneer **MyTag** assignments (live mode only, `myTagSupported` gate at line 81).
- **"Service mark"** shortcut (`RankingView.jsx:175-180`) = Rating 5 + ColorID 2 (red). Treated as a one-tap "this is a service track" marker.
- **Save flow** (`RankingView.jsx:182-222`): `POST /api/track/{tid}` with `{Rating, ColorID, Comment, Genre}`, then conditionally `POST /api/track/{tid}/mytags` with `{tag_ids}`. Auto-advances queue, hotkey `space`. Toast on success/failure.
- **Plays the track while ranking** via embedded `WaveformEditor` in `simpleMode` (`RankingView.jsx:360-368`). **Not part of mobile scope** — desktop already plays.
- **Progress bar at top** of full-screen view (`RankingView.jsx:323-325`) showing `currentIndex / queue.length`.

Mobile must reproduce: source picker (4 modes), queue progress, per-track stars + colors + tag-chip grid + MyTag chip block + free-comment + genre autocomplete + Save & Next. **No waveform, no audio, no service-mark hotkey** (becomes a button only).

**API surface mobile needs** (already exists, no backend additions for v1):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/playlists/tree` | Source picker tree (`main.py:927`) |
| GET | `/api/artists` \| `/labels` \| `/albums` | Flat source lists (`main.py:713, 697, 700`) |
| GET | `/api/playlist/{id}/tracks` | Queue for playlist (`main.py:1564`) |
| GET | `/api/artist|label|album/{id}/tracks` | Queue for those source modes |
| GET | `/api/genres` | Genre autocomplete (`main.py:631`) |
| GET | `/api/settings` | `ranking_filter_mode` (`main.py:1819`) |
| GET | `/api/track/{id}` | Refresh single track (`main.py:728`) |
| GET | `/api/track/{id}/mytags` | Per-track MyTag list (`main.py:840`) |
| GET | `/api/mytags` | Global MyTag list (`main.py:810`) |
| POST | `/api/mytags` | Create MyTag (`main.py:815`) |
| POST | `/api/track/{id}` | Save Rating/Color/Comment/Genre (`main.py:862`) |
| POST | `/api/track/{id}/mytags` | Save MyTag assignments (`main.py:845`) |

12 routes. Tiny surface.

**Network reality**:
- CORS allowlist (`main.py:212-221`) blocks every non-localhost / non-tauri origin today.
- Axios baseURL hard-coded to `http://127.0.0.1:8000` (`api.js:10`), overridable via `VITE_API_BASE_URL`. Mobile build needs that env wired at runtime (mobile doesn't know the desktop's LAN IP at compile time).
- No request-auth gate on `/api/track/*` writes. `SHUTDOWN_TOKEN` only guards `/api/system/shutdown|restart` (`main.py:2028-2050`). The `X-Session-Token` mechanism documented in `CLAUDE.md` isn't wired into route deps yet.

**Auth gap is the blocker.** A LAN-exposed FastAPI on 8000 with anonymous track-write access lets anyone on the Wi-Fi 5-star-rate the whole library. Must add a `Depends(verify_session_token)` to ranking writes (at minimum) before any mobile work ships.

### 2026-05-15 — tech-choice deep-dive + QR-pairing UX sketch (post auth-Phase-1)

Grounds Phase-2 dependencies now that `docs/research/implement/draftplan_security-api-auth-hardening.md` exists. Phase-1 lands Bearer-only `require_session` on every mutation route; Phase-2 adds paired-device tokens in a sidecar-local SQLite — **hard-prereq for mobile**. Auth surfaces mobile relies on: `Authorization: Bearer <device_token>` per call, against a `paired_devices` table, plus `POST /api/pairing/{start,complete}` and a revoke endpoint.

**PWA vs Capacitor vs React Native**

| Aspect | PWA | Capacitor | React Native |
|---|---|---|---|
| Code-share with `frontend/` | full (same React) | full | partial (no DOM) |
| App-store distribution | install-banner only (Chrome) / no (iOS Safari) | yes | yes |
| iOS limitations | `beforeinstallprompt` unsupported, background tasks limited, web-push only on 16.4+ | full native | full native |
| mDNS LAN discovery | NO (web sandbox) | YES via plugin | YES |
| Camera for QR-scan | YES (`getUserMedia`; `qr-scanner` polyfill where `BarcodeDetector` missing) | YES native | YES native |
| Bundle / install | minimal | +~5 MB shell | +~15-25 MB |
| Dev complexity | lowest | low | medium |
| OTA updates | trivial (web reload) | Capacitor Live Update | app-store re-release |
| Verdict | **M1 pick** | M2 if mDNS / push must-have | overkill for metadata-only |

**iOS PWA impact on Ranking**: Add-to-Homescreen works (iOS 12.2+; icon/splash/standalone OK). `beforeinstallprompt` unsupported → one-time manual instructions on first iOS-Safari visit (UA-detect). Background tasks irrelevant (Ranking is foreground-only). Camera via `getUserMedia` since iOS 11; `qr-scanner` polyfill covers missing `BarcodeDetector`. Web-push works on iOS 16.4+ installed PWAs (nice-to-have). **Viable for Ranking-only.**

**QR-pairing UX**: Desktop adds a "Pair Mobile Device" Settings view showing auto-detected LAN IP (dropdown if multiple bind interfaces), port 8000, one-shot pairing token (6-digit human + URL-safe long, from the `_format_tokens` helper Phase-2 generalises), and a QR encoding `lmsapp://pair?host=192.168.1.42&port=8000&token=<one-shot>`. Refresh every 60 s; Cancel revokes pending pairing. Mobile first-visit shows "Scan pairing QR from desktop"; camera prompt; scan → `POST /api/pairing/complete` → receive `device_token` + `device_id` → store in `localStorage` + service-worker IndexedDB → subsequent calls Bearer-attach. Server revoke → mobile 401 → "Re-pair" screen. mDNS auto-find via `_libmgr._tcp.local` would skip host-entry but is Capacitor-only (PWA sandbox blocks it).

**Off-LAN access**: **Tailscale Funnel** (free personal, `<machine>.<tailnet>.ts.net` HTTPS, zero NAT pain) is canonical — recommend in README, **do NOT embed any tunnel client**; the app only provides the Bearer-token over whichever pipe. Alternatives: **Cloudflare Tunnel** (`*.trycloudflare.com`, rate-limited, ephemeral URLs unless paid) and **ngrok** (free tier limited). PWA `installable` HTTPS gate (OQ11) is satisfied once any tunnel is in play.

**Concurrent-edit policy**: Single-DJ Non-goal → last-write-wins fine. Defer ETag / `updated_at` stale-write detection.

**Open Questions now answerable**: OQ2 **PWA for M1** (Capacitor layerable). OQ3 **Tailscale documented; never embedded**. OQ4 **QR one-shot → long-lived device-token Bearer**; mDNS deferred to M2-Capacitor. OQ5 aligns with auth Phase-2 (long-lived per-device + revoke, no default expiry). OQ10 **acceptable for v1**; manual AddToHomescreen covers `beforeinstallprompt` gap. OQ11 resolved by Tailscale's free HTTPS.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Mobile-optimised PWA, served by the existing Vite/desktop stack

- Sketch: Add a `/m` route (or a separate Vite entry `frontend/src/mobile/main.jsx`) that renders a thumb-first React tree reusing the existing axios client + `RankingView` primitives (chip styles, COLORS, TAG_CATEGORIES). Ship a `manifest.webmanifest` + minimal service worker (offline-shell only — no data caching, hard-online). Pair via QR (desktop shows `https://<host>:8000/m?token=<one-shot>`). Auth: extend `X-Session-Token` to ranking-write routes; QR delivers the token, stored in `localStorage`. CORS: add env-driven `MOBILE_ALLOWED_ORIGINS` list (LAN IP, tunnel hostname).
- Pros: smallest delta. Reuses React + axios + chip/color components verbatim. No app-store. iOS + Android + desktop browsers all work. Tailscale Funnel / Cloudflare Tunnel just adds an HTTPS hostname — no native code changes.
- Cons: iOS PWA limits (no real install banner without HTTPS, background sync limited). HTTPS-on-LAN requires self-signed cert or tunnel. Swipe gestures hand-rolled or via `use-gesture` (~10kb).
- Effort: **S-M**. ~1-2 weeks. Backend: ~150 LoC (token dep + CORS env). Frontend: 1 new mobile entry, 4-5 components, gesture wiring.
- Risk: Low. Rollback = remove the route + revert CORS env. Doesn't touch desktop UX.

### Option B — Capacitor wrapper around Option A

- Sketch: Take Option A's PWA, wrap with [Capacitor](https://capacitorjs.com/) for iOS + Android app-store builds. Same JS bundle, native shell gives access to Apple/Google sign-in, push notifications, better install UX.
- Pros: Real install on iOS (bypasses PWA limitations). Push notifications possible (e.g. "desktop ready to receive ranks"). Same codebase.
- Cons: App Store review cycle for every release. Apple developer account ($99/yr). Local-LAN apps in App Stores are awkward (reviewers will try to use it without a server and reject). TestFlight / sideloading is a smoother fit, but then "just use the PWA" is simpler.
- Effort: **M**. Option A + ~3-5 days of Capacitor wiring + 1-2 weeks store back-and-forth.
- Risk: Medium. App Store rejection risk is real for "this app needs your home server to work" pitches.

### Option C — React Native (Expo) client, separate codebase

- Sketch: New `mobile/` workspace with Expo. Reuse zero React components (different primitives). Reimplement source picker, queue, edit surface against the same FastAPI routes.
- Pros: Native feel (true gestures, native haptics, native swipe). Better offline story when we eventually want one.
- Cons: Parallel codebase to maintain. No component sharing with `RankingView.jsx`. Bigger surface for bugs. Solo dev capacity.
- Effort: **L**. ~3-4 weeks.
- Risk: Medium-High. Drift between desktop and mobile feature sets becomes a chore.

### Option D — Embed-only: desktop hosts a mobile UI on `:8001`, accessed by phone browser

- Sketch: Skip "PWA" branding entirely. FastAPI mounts a server-rendered HTML page at `:8001/m` (separate Starlette app on a sibling port) with vanilla JS or htmx. No build step for mobile, no Vite, no service worker. Pure progressive enhancement.
- Pros: Zero new frontend tooling. ~300 LoC of HTML + htmx + tiny JS. Survives without any of the React stack.
- Cons: Code-share with `RankingView.jsx` = zero. Reimplement all chip / color / tag logic in plain HTML. Touch UX harder to polish (no Framer / use-gesture).
- Effort: **M**. ~1 week, but produces a different-looking app from the desktop.
- Risk: Low. But the resulting UX gap from the polished desktop Ranking view is the actual cost.

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

**Commit: Option A (PWA on the existing Vite/React stack) for M1.** Lowest friction, full React-component share with `RankingView.jsx`, no app-store cycle, works on iOS + Android + any tablet browser. M2 reconsiders **Capacitor** only if mDNS-discovery or native push become must-haves — strict superset, no rewrite cost. React Native is overkill for the metadata-only Ranking surface and is rejected.

**Pairing UX = QR with one-shot pairing token → long-lived device-token Bearer**, as sketched in the second Findings subsection. Re-uses the `_format_tokens` helper that auth Phase-2 generalises, plus a new `paired_devices` row in the sidecar-local SQLite. mDNS auto-discovery deferred to M2-Capacitor.

**Off-LAN canonical recipe = Tailscale Funnel** (documented in README; not embedded in the app). Tailscale's free HTTPS also resolves the PWA `installable` HTTPS gate (OQ11) without self-signed certs on LAN. Cloudflare Tunnel / ngrok stay as user-pick alternatives.

**Hard prerequisite, regardless of option:** auth-hardening **Phase-1** (`require_session` Bearer on all mutation routes) AND **Phase-2** (paired-device tokens + QR pairing UI + revoke) from `docs/research/implement/draftplan_security-api-auth-hardening.md` must both ship before any mobile code lands. Phase-1 alone is insufficient — Tauri's boot-token is single-host and cannot be safely handed to a phone. Additionally make the CORS allowlist env-driven (`MOBILE_ALLOWED_ORIGINS`) so LAN / tunnel hostnames can be added without code changes.

**Waiting on:**
1. User confirms hard-online (no offline queue in v1) — Open Question 1.
2. User picks PWA vs Capacitor — Open Question 2.
3. User picks tunnel recipe (or "punt") — Open Question 3.
4. Auth hardening lands or is scoped as a co-shipping dependency.

Once those four resolve, this doc moves `idea_` → `exploring_` → `evaluated_`.

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
