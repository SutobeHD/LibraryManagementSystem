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
- 2026-05-15 — `research/idea_` — exploring_-ready rework loop (deep self-review pass)

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

A **soft / thin mobile version** of the desktop app, **mainly focused on Ranking mode**. The mobile client is **not standalone** — it only works when the main app is reachable as a server (PC / dedicated host on the same network or via tunnel). All library state, audio, analysis, and DB writes stay on the main app; the mobile app is a remote UI surface. Useful for ranking / tagging tracks away from the desk (couch, studio sofa, on-the-road), without lugging the laptop.

## Goals / Non-goals

**Goals** (each has a measurable acceptance metric for `evaluated_` → `inprogress_` transition)

- **G1 — Ranking-mode parity** Mobile replicates Ranking-mode edit surface: pick source (playlist / artist / label / album), step queue, set Rating (1-5), ColorID, Genre, Comment + chip-toggles, optional MyTags (live mode). Persist via `POST /api/track/{tid}` + `POST /api/track/{tid}/mytags`. **Metric:** every desktop Ranking field reachable + writable from mobile; manual checklist (12 fields/buttons) in `tests/manual/mobile-ranking-parity.md` 12/12 green.
- **G2 — Thin client invariant** 0 KB canonical library data on phone. All state via HTTP. **Metric:** `localStorage` payload ≤ 4 KB (auth token + UI prefs only); no IndexedDB store of tracks/playlists; service-worker cache scope = app shell only (assets), no JSON responses.
- **G3 — Same-LAN first-paint** Phone on home Wi-Fi → scan QR → first ranking screen visible. **Metric:** ≤ 8 s end-to-end on a mid-range Android (4G-equiv throttle), ≤ 12 s on iOS Safari cold-load. Measured via DevTools Performance trace, scripted check in `e2e-tester`.
- **G4 — Off-LAN opt-in** Tailscale Funnel hostname documented in README; works without app-side tunnel client. **Metric:** smoke test from cellular network passes Save & Next round-trip in ≤ 800 ms p95.
- **G5 — Component reuse** Mobile bundle shares ≥ 60 % of `RankingView.jsx`'s chip/color/tag primitives (COLORS array, TAG_CATEGORIES, MyTag toggle logic). **Metric:** static count — same module imports, no fork.
- **G6 — Thumb-first UX** Swipe-right = Save & Next (replaces `space` hotkey at `RankingView.jsx:88`), 44 × 44 px minimum hit targets per Apple HIG, bottom-anchored primary CTA. **Metric:** Lighthouse mobile-a11y ≥ 90; tap-target audit 0 failures.
- **G7 — Save-and-next round-trip** P95 ≤ 350 ms on LAN (typical home Wi-Fi → loopback FastAPI). **Metric:** logged client-side in `axios` interceptor, surfaced in dev console.

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

- **CORS allowlist is localhost-only** (`app/main.py:216-232`, post-hotfix shift): `http://localhost:1420`, `127.0.0.1:1420`, `localhost:5173`, `127.0.0.1:5173`, `localhost:8000`, `127.0.0.1:8000`, `tauri://localhost`, `https://tauri.localhost`. `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. **Any mobile origin (`http://192.168.x.y:5173`, `https://<tailscale-name>.ts.net`, `https://<slug>.trycloudflare.com`) is rejected.** Must extend allowlist env-driven (`MOBILE_ALLOWED_ORIGINS` env list, comma-split) or proxy via tunnel hostname. **CORS ≠ auth** — non-browser callers (curl, native mobile, Python) bypass CORS entirely; per `draftplan_security-api-auth-hardening.md` Findings §2 the comment on line 216 (`# --- SECURITY: CORS locked to localhost only ---`) is misleading and the threat model relies on the loopback bind + bearer-token gate, not CORS.
- **Frontend axios baseURL is hardcoded** to `http://127.0.0.1:8000` in non-browser-preview mode (`frontend/src/api/api.js:10`), with `VITE_API_BASE_URL` as override. Mobile build needs the host's LAN IP or tunnel hostname injected at runtime (mobile can't know LAN IP at compile time). Re-use the same env hook.
- **Auth gate is in-flight, not landed.** `docs/research/implement/draftplan_security-api-auth-hardening.md` Phase-1 introduces `require_session` (Bearer) on every `POST`/`PUT`/`PATCH`/`DELETE` route — that includes the three mutation routes the mobile flow needs (`POST /api/track/{tid}` line 900, `POST /api/track/{tid}/mytags` line 883, `POST /api/mytags` line 853). Reads stay open in Phase 1, loopback-gated. **Phase-2 paired-device tokens (per-device bearer in `Authorization: Bearer …`, sidecar-local SQLite `paired_devices` table, `POST /api/pairing/{start,complete}` + `DELETE /api/pairing/{device_id}` revoke) are the hard-prereq for mobile** — Phase-1 alone is insufficient because the Tauri boot-token is single-host and cannot be safely handed to a phone. Verified: grep across `app/` returns 0 hits for `paired_devices` / `/api/pairing/` — endpoints don't exist yet.
- **`ALLOWED_AUDIO_ROOTS` sandbox** (`app/main.py:138-205` post-hotfix) bounds filesystem reads to whitelisted roots via `Path.is_relative_to` (hotfix migrated from `str.startswith`). Doesn't apply to ranking writes (DB-only), but any future artwork / waveform PNG endpoint exposed to mobile must go through `validate_audio_path`.
- **Concurrency:** all `master.db` writes must go through `_db_write_lock` (RLock, `app/database.py:22` per security-doc Constraints — not `app/main.py` as older `coding-rules.md` snippet claims). Mobile-induced `POST /api/track/{tid}` already takes that path — no new locking work, but each concurrent client adds contention; multi-client behaviour parked under OQ8.
- **rbox version quirks:** mobile must not trigger `OneLibrary.create_content()` (broken in rbox 0.1.7, see `app/usb_one_library.py`). Out of scope by design (no library mgmt), pinned in Non-goals.
- **Existing Ranking API surface = 13 reads + 3 writes = 16 routes total** (re-verified by grep against current `app/main.py`, post-hotfix line shifts):
  - Reads (13): `GET /api/playlists/tree` (976), `GET /api/artists` (751), `GET /api/labels` (735), `GET /api/albums` (738), `GET /api/playlist/{pid}/tracks` (1613), `GET /api/artist/{aid}/tracks` (1634), `GET /api/label/{aid}/tracks` (1650), `GET /api/album/{aid}/tracks` (1666), `GET /api/genres` (669), `GET /api/settings` (1868), `GET /api/track/{tid}` (766), `GET /api/track/{tid}/mytags` (878), `GET /api/mytags` (848).
  - Writes (3 — all gated Phase 1 by `require_session` Bearer): `POST /api/mytags` (853), `POST /api/track/{tid}` (900), `POST /api/track/{tid}/mytags` (883).
  - Plus `GET /api/library/status` for live-vs-XML mode (read, open). Total touched surface = 17 routes.
  - Zero backend additions for v1 except the Phase-2 pairing surface (`POST /api/pairing/start`, `POST /api/pairing/complete`, `DELETE /api/pairing/{device_id}`) and the optional `GET /api/track/{tid}/cover-thumb` at M1.3 (OQ7).
- **Live-vs-XML mode parity:** MyTag write path requires `appMode === 'live'` (`master.db`). XML mode silently no-ops (`RankingView.jsx:81, 138-144, 197-205`). Mobile reads `GET /api/library/status` (`libraryStatus.mode`) and disables the MyTag block in XML mode.
- **iOS PWA platform limits** (re-verified 2026 baseline): `beforeinstallprompt` unsupported on iOS Safari; Add-to-Homescreen works since iOS 12.2; web-push requires iOS 16.4+ AND installed-PWA state; `getUserMedia` works since iOS 11; `BarcodeDetector` API absent — pull in `qr-scanner` polyfill (~30 KB gz).
- **Team capacity:** solo dev. Parallel mobile codebase + sync (React Native, Flutter, native) is L/XL effort and rejected in Recommendation.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

Status legend: **RESOLVED** (locked, no rework expected) · **PARKED** (deferred to a later phase / topic, answer documented) · **OPEN** (still blocks promotion).

1. **OQ1 — Hard-online only?** **RESOLVED.** Hard-online. User steer ("should only work if app runs on a server or pc") + Goals G2 (thin-client) lock it. Offline queue / local cache explicitly Non-goal; tracked as a separate future topic if demanded.
2. **OQ2 — PWA vs Capacitor vs React Native?** **RESOLVED.** PWA for M1 (Findings #2 matrix); Capacitor stays as M2 strict-superset upgrade if mDNS / native push become must-haves; React Native rejected (parallel codebase, no DOM reuse, L effort).
3. **OQ3 — Off-LAN strategy?** **RESOLVED.** **Tailscale Funnel** = canonical, documented in README; **not embedded**. Cloudflare Tunnel + ngrok stay as user-pick alternatives, no code support.
4. **OQ4 — Pairing UX?** **RESOLVED.** Desktop renders QR encoding `lmsapp://pair?host=<lan-ip>&port=8000&token=<one-shot>`; mobile scans → `POST /api/pairing/complete` → long-lived per-device Bearer. Manual URL + 6-digit code fallback for camera-less devices. mDNS auto-discovery deferred to M2-Capacitor (web sandbox blocks `_libmgr._tcp.local`).
5. **OQ5 — Token lifetime?** **RESOLVED.** Long-lived per-device Bearer, no default expiry, server-side revoke via `DELETE /api/pairing/{device_id}`. Aligns with security-doc Phase-2 model. Lost-phone mitigation = revoke from desktop Settings.
6. **OQ6 — Separate `:8001` port or unified `:8000` with auth gating?** **RESOLVED.** Unified `:8000` with `require_session` Bearer (per security Phase 1+2). Reasons: (a) Phase-1 already gates every mutation; second port doubles uvicorn surface for zero security gain, (b) reverse-proxy / Tailscale Funnel only knows one upstream, (c) read routes stay open under loopback assumption — mobile read-only access still flows over the LAN-exposed `:8000` once the bind widens or tunnel is in play.
7. **OQ7 — Artwork / waveform preview on mobile?** **PARKED for M1 core (M1.0–M1.2).** v1 ships **text-only ranking** (track title, artist, BPM/key from `/api/track/{tid}` JSON). Cover thumbnails (256×256, ≤ 50 KB JPEG) optionally added at **M1.3** via new `GET /api/track/{tid}/cover-thumb` if bandwidth budget allows. Waveform PNG explicitly out — desktop owns audio + waveform editing.
8. **OQ8 — Concurrent-edit policy?** **RESOLVED.** Last-write-wins (current behaviour). Single-DJ assumption (Non-goal: multi-user) makes ETag / `updated_at` stale-write detection over-engineering. Re-evaluate only if a real conflict is reported.
9. **OQ9 — Swipe gestures library?** **RESOLVED.** Use `@use-gesture/react` (~11 KB gz, MIT, actively maintained 2025-2026). Hand-rolled touch-event handling is fragile across iOS / Android Chrome / Samsung Internet quirks; Framer Motion is overkill (~50 KB gz). Bundle stays under 4 G first-paint budget (≤ 200 KB gz total).
10. **OQ10 — iOS PWA limits acceptable?** **RESOLVED.** Acceptable for v1. Manual Add-to-Homescreen instructions on first iOS-Safari visit (UA-detect). Background tasks irrelevant (Ranking is foreground-only). Web-push deferred until iOS 16.4+ install adoption + actual push use-case emerges.
11. **OQ11 — HTTPS / `installable` PWA criteria?** **RESOLVED.** Ship as mobile-friendly web page in v1; PWA install-banner activates once Tailscale Funnel HTTPS hostname is in use. On raw `http://192.168.x.y` LAN IP, install banner is disabled by browser policy — accepted, banner is nice-to-have not blocker.
12. **OQ12 (NEW) — CORS allowlist extension shape?** **OPEN — must resolve before `exploring_` → `evaluated_`.** Three sketches: (a) env-driven `MOBILE_ALLOWED_ORIGINS=https://foo.ts.net,https://192.168.1.42` list, restart to apply; (b) runtime-mutable list in `settings.json` + admin endpoint to add/remove; (c) wildcard pattern (`https://*.ts.net`) with strict regex. Lean (a) — simplest, no new admin surface; matches security-doc style.
13. **OQ13 (NEW) — Bundle-size budget hard ceiling?** **OPEN — must resolve before draftplan.** Proposal: ≤ 200 KB gz first-paint (HTML + JS + CSS critical path), ≤ 500 KB gz total mobile bundle. Drives gesture-lib choice (OQ9), polyfill scope, code-splitting strategy (lazy-load source-picker tree until user opens it).
14. **OQ14 (NEW) — Pairing-QR refresh / TTL?** **OPEN — must resolve before draftplan.** Sketch: one-shot pairing-token TTL 60 s (matches `_format_tokens` helper that security Phase-2 generalises); QR auto-rotates every 60 s on the desktop "Pair Mobile Device" panel; explicit Cancel button revokes pending pairing. Need user confirmation TTL is OK (vs. 5 min default for less DJ-table-friction).

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

**API surface mobile needs — 12 routes, re-verified by grep against current `app/main.py` (post-hotfix shifts):**

| Method | Path | Purpose | Current line | Auth (post-Phase-1) |
|---|---|---|---|---|
| GET | `/api/playlists/tree` | Source-picker tree | 976 | open (Phase 1), loopback-gated |
| GET | `/api/artists` | Source list | 751 | open |
| GET | `/api/labels` | Source list | 735 | open |
| GET | `/api/albums` | Source list | 738 | open |
| GET | `/api/playlist/{pid}/tracks` | Queue for playlist | 1613 | open |
| GET | `/api/artist/{aid}/tracks` | Queue for artist | 1634 | open |
| GET | `/api/label/{aid}/tracks` | Queue for label | 1650 | open |
| GET | `/api/album/{aid}/tracks` | Queue for album | 1666 | open |
| GET | `/api/genres` | Genre autocomplete | 669 | open |
| GET | `/api/settings` | `ranking_filter_mode` etc. | 1868 | open |
| GET | `/api/track/{tid}` | Per-track refresh | 766 | open |
| GET | `/api/track/{tid}/mytags` | Per-track MyTag list | 878 | open |
| GET | `/api/mytags` | Global MyTag list | 848 | open |
| POST | `/api/mytags` | Create MyTag | 853 | **gated** (Bearer) |
| POST | `/api/track/{tid}` | Save Rating/Color/Comment/Genre | 900 | **gated** (Bearer) |
| POST | `/api/track/{tid}/mytags` | Save MyTag assignments | 883 | **gated** (Bearer) |

16 rows above = 13 reads + 3 mutations. Add `GET /api/library/status` for live-vs-XML mode detection → 17 routes touched. The 3 mutations take `Depends(require_session)` post-Phase-1. Mobile also needs Phase-2 pairing endpoints (`POST /api/pairing/start`, `POST /api/pairing/complete`, `DELETE /api/pairing/{device_id}`) — **verified absent today** (grep `paired_devices` / `/api/pairing/` across `app/` → 0 hits).

**Network reality**:
- CORS allowlist (`main.py:216-232` post-hotfix) blocks every non-localhost / non-tauri origin. `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. Mobile origin must be added env-driven (OQ12).
- Axios baseURL hard-coded `http://127.0.0.1:8000` (`api.js:10`), overridable via `VITE_API_BASE_URL`. Mobile runtime injection required.
- Auth gap is current — `draftplan_security-api-auth-hardening.md` Phase 1 closes it via `require_session` Bearer on every `POST`/`PUT`/`PATCH`/`DELETE`. Mobile depends on Phase 2 (paired-device tokens) on top.

**Conclusion — mobile is unblocked the moment Phase-2 paired-device tokens land + CORS env-extension ships. Backend additions for v1 = the 3 pairing endpoints only; existing 13 read/write routes are untouched in shape.**

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

### 2026-05-15 — exploring_-ready self-review: route re-verify + sketches + gates

Triggered by the deep self-review pass. Verifies prior Findings against current code, adds the option sketches missing from earlier rounds, and codifies the M1/M2 deliverable matrix used by Recommendation.

**Route re-verification (post-hotfix line shifts)** — all 17 routes the mobile flow touches (incl. `/api/library/status`) re-grepped against `app/main.py`. Old Findings cited pre-hotfix numbers (offsets ~+35 to +50 lines because auth-hotfix commit `e3a5ae8` added heartbeat-loopback gate + `validate_audio_path` rewrite + debug-flag gate + file-write sandbox). Corrected line refs landed in Constraints + the Findings #1 table above. `/api/system/heartbeat` is now single (line 937); the duplicate at line 2022 was removed by hotfix. `SHUTDOWN_TOKEN` query-param scheme survives at `app/main.py:2071` (shutdown) but is deleted by Phase-1 plan.

**Pairing-endpoint absence** — grep across `app/` for `paired_devices`, `pairing/start`, `pairing/complete` returns 0 hits. Confirmed: only the two research docs + one exploring rate-limit doc reference these names. Backend additions = new `app/pairing.py` module (~120 LoC) + `paired_devices` table in sidecar-local SQLite (NOT `master.db` per security doc Option B trade-off).

**Bundle-size sketch** (drives OQ13). React 18 + react-router (~45 KB gz) + axios (~13 KB gz) + `@use-gesture/react` (~11 KB gz) + `qr-scanner` polyfill (~30 KB gz, dynamic-imported on pairing-screen only) + chip/color components shared from `RankingView.jsx` (~5 KB delta) + Tailwind utilities (purged, ~12 KB gz) ≈ **115 KB gz first-paint, 145 KB gz with QR**. Headroom under the 200 KB gz ceiling.

**Save-and-next latency budget** (G7). Round-trip components: (a) phone → router ~5 ms LAN, (b) router → desktop ~2 ms, (c) FastAPI route + `_db_write_lock` acquisition + SQLite write 50–150 ms (measured against typical `master.db`), (d) response back ~7 ms. Headroom: ~150 ms of slack under the 350 ms p95 ceiling. Tightens to 100 ms slack on shared 2.4 GHz Wi-Fi with neighbour interference.

**Deliverable / gate matrix per phase** (drives Recommendation):

| Phase | Deliverable | Hard gate before next phase |
|---|---|---|
| **Pre-M1** (blocking) | Security Phase-1 + Phase-2 shipped + merged | `tests/test_auth.py` green; paired-device CRUD live; `DELETE /api/pairing/{device_id}` revoke verified manually |
| **M1.0** (PWA scaffold) | `frontend/src/mobile/main.jsx` + `/m` Vite entry + manifest + minimal service worker; renders empty source-picker stub | Lighthouse PWA score ≥ 80; `npm run build` ships ≤ 200 KB gz first-paint |
| **M1.1** (pair + bearer) | QR-scan screen, `POST /api/pairing/complete` flow, localStorage token, axios bearer interceptor | Manual: phone scans QR, persists token, hits gated `POST /api/track/{tid}` → 2xx |
| **M1.2** (ranking parity) | Source-picker → queue → edit surface (stars / colors / chips / comment / genre / MyTag) + Save & Next swipe | G1 manual-checklist 12/12 green; G7 axios-interceptor p95 ≤ 350 ms on LAN |
| **M1.3** (off-LAN polish) | README Tailscale Funnel section + iOS Add-to-Homescreen manual onboarding + `MOBILE_ALLOWED_ORIGINS` env wired in `app/main.py` | G4 cellular smoke ≤ 800 ms p95; PWA install banner appears under tunnel HTTPS |
| **M2** (Capacitor, deferred) | Optional native shell for App-Store / push / mDNS — only if user demand emerges | Separate research topic |

**Concurrent-write contention probe** (defers OQ8 but quantifies). `_db_write_lock` is a `threading.RLock`; serial writes on a single uvicorn worker = mobile + desktop writes queue, no race. Worst case: mobile + desktop both Save & Next at the same instant → second writer waits ≤ 150 ms (one SQLite commit). Acceptable. No need for ETag / `updated_at`.

**What the doc still doesn't pin down (PARKED for `exploring_` → `evaluated_`)**: OQ7 cover-thumbnail endpoint shape + cache headers (new `/api/track/{tid}/cover-thumb`); OQ12 env-driven `MOBILE_ALLOWED_ORIGINS` format; OQ13 firm 200 KB / 500 KB bundle ceiling sign-off; OQ14 60 s pairing-QR TTL sign-off.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Mobile-optimised PWA, served by the existing Vite/desktop stack

- Sketch: Add `/m` route (or separate Vite entry `frontend/src/mobile/main.jsx`) rendering a thumb-first React tree that reuses the existing axios client + `RankingView` primitives (chip styles, COLORS, TAG_CATEGORIES). Ship `manifest.webmanifest` + minimal service worker (app-shell only — no data caching, hard-online). Pair via QR: desktop generates one-shot pairing token, mobile scans → `POST /api/pairing/complete` → receives long-lived device-token Bearer → stores in `localStorage` → attaches as `Authorization: Bearer …` on every request. Auth flows through security-doc Phase-2 `paired_devices` table; no `X-Session-Token` shim. CORS: add env-driven `MOBILE_ALLOWED_ORIGINS` list (LAN IP, tunnel hostname).
- Pros: smallest delta. Reuses React + axios + chip/color components verbatim. No app-store. iOS + Android + tablet browsers all work. Tailscale Funnel / Cloudflare Tunnel just adds an HTTPS hostname — no native code changes.
- Cons: iOS PWA limits (no real install banner without HTTPS, background sync limited). HTTPS-on-LAN requires self-signed cert or tunnel. Swipe gestures handled via `@use-gesture/react` (~11 KB gz).
- Effort: **S-M**. ~1-2 weeks of mobile work, assuming security Phase-2 already landed. Backend mobile-side: ~50 LoC (CORS env-extension only; pairing routes belong to security Phase-2). Frontend: 1 new mobile entry, 4–5 components, gesture wiring.
- Risk: Low. Rollback = remove `/m` route + revert CORS env. Doesn't touch desktop UX.

### Option B — Capacitor wrapper around Option A

- Sketch: Take Option A's PWA, wrap with [Capacitor](https://capacitorjs.com/) for iOS + Android native shell. Same JS bundle, native shell unlocks `BarcodeDetector`-equivalent native QR scan, mDNS LAN discovery (`_libmgr._tcp.local` plugin → skips manual IP entry), proper Add-to-Homescreen on iOS without UA-detect prompts, and APNs / FCM push if ever needed.
- Pros: Real install on iOS (bypasses PWA install-banner gap). Native QR scan is faster + more reliable than `getUserMedia` + `qr-scanner` polyfill. mDNS removes the QR-pairing host-entry step entirely (auto-discovers desktop on LAN). Same JS bundle as PWA — no rewrite.
- Cons: App Store review cycle for every release. Apple developer account ($99/yr). Local-LAN apps in App Stores are awkward (reviewers will try to use it without a server and reject — Capacitor `LiveUpdate` mitigates this since logic ships OTA). TestFlight / sideloading is a smoother fit, but then "just use the PWA" is simpler.
- Effort: **M**. Option A + ~3-5 days of Capacitor wiring + 1-2 weeks of store back-and-forth.
- Risk: Medium. App Store rejection risk is real for "this app needs your home server to work" pitches; sideload + Capacitor LiveUpdate is the escape hatch.

### Option C — React Native (Expo) client, separate codebase

- Sketch: New `mobile/` workspace with Expo. Reuse zero React components (different primitives). Reimplement source picker, queue, edit surface against the same FastAPI routes.
- Pros: Native feel (true gestures, native haptics, native swipe). Better offline story when we eventually want one.
- Cons: Parallel codebase to maintain. No component sharing with `RankingView.jsx`. Bigger surface for bugs. Solo dev capacity.
- Effort: **L**. ~3-4 weeks.
- Risk: Medium-High. Drift between desktop and mobile feature sets becomes a chore.

### Option D — Embed-only: desktop hosts a mobile UI on `:8001`, accessed by phone browser

- Sketch: Skip "PWA" branding entirely. FastAPI mounts a server-rendered HTML page at `:8001/m` (separate Starlette app on a sibling port) with vanilla JS or htmx. No build step for mobile, no Vite, no service worker. Pure progressive enhancement.
- Pros: Zero new frontend tooling. ~300 LoC of HTML + htmx + tiny JS. Survives without any of the React stack.
- Cons: Code-share with `RankingView.jsx` = zero. Reimplement all chip / color / tag logic in plain HTML. Touch UX harder to polish (no Framer / use-gesture). Conflicts with OQ6 resolution (unified `:8000`).
- Effort: **M**. ~1 week, but produces a different-looking app from the desktop.
- Risk: Low. But the resulting UX gap from the polished desktop Ranking view is the actual cost.

### Option E — Headless API + standalone React Native (Expo) client + shared design tokens

- Sketch: Lift `COLORS`, `TAG_CATEGORIES`, MyTag-toggle helper into a tiny `frontend/src/shared/ranking-primitives/` workspace exported as a published-locally NPM package. Both desktop React and a new Expo `mobile/` workspace consume it. Mobile is fully native (true platform gestures, native haptics, native swipe stack, native QR scan), API calls flow through Phase-2 paired-device tokens identical to PWA.
- Pros: Best native feel of any option. Shared design tokens prevent the worst drift trap of Option C (parallel codebase with zero sharing). Native haptic feedback on Save & Next is genuinely better UX for thumb-flipping through 50-track queues.
- Cons: Still ~70 % parallel codebase (RN primitives ≠ DOM primitives). Solo-dev capacity strain. App-Store cycle + Apple dev account ($99/yr). Push notifications require backend changes (FCM / APNs). XL effort.
- Effort: **XL**. ~4–6 weeks initial + ongoing app-store re-submissions per release.
- Risk: High — sustained two-codebase tax outweighs Ranking-mode's narrow surface. Rejected in Recommendation.

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

**Commit: Option A (PWA on the existing Vite/React stack) for M1.** Lowest friction, full React-component share with `RankingView.jsx`, no app-store cycle, works on iOS + Android + any tablet browser. M2 reconsiders **Option B (Capacitor wrapper)** only if mDNS-discovery or native push become must-haves — strict superset, no rewrite cost. Options C/D/E rejected (parallel codebase / port conflict / XL effort).

**Pairing UX = QR one-shot → long-lived device-token Bearer**, as sketched in Findings #2 + re-confirmed in Findings #3. Re-uses the `_format_tokens` helper that auth Phase-2 generalises, plus a new `paired_devices` row in sidecar-local SQLite (NOT `master.db`). mDNS auto-discovery deferred to M2-Capacitor.

**Off-LAN canonical recipe = Tailscale Funnel** (documented in README; never embedded). Tailscale's free HTTPS also satisfies PWA `installable` (OQ11) without self-signed LAN certs. Cloudflare Tunnel / ngrok stay as user-pick alternatives.

**Hard prerequisites** (must land before any mobile-side code ships):
1. `draftplan_security-api-auth-hardening.md` **Phase-1** — `require_session` Bearer on every `POST`/`PUT`/`PATCH`/`DELETE`. Closes the anonymous-write hole on LAN.
2. Same doc **Phase-2** — paired-device tokens (`paired_devices` SQLite table, `POST /api/pairing/{start,complete}`, `DELETE /api/pairing/{device_id}` revoke). Tauri boot-token is single-host and CANNOT be handed to a phone.
3. CORS allowlist env-driven (`MOBILE_ALLOWED_ORIGINS`, comma-split) per OQ12; landed alongside or as part of Phase-2 frontend wiring.

**Phased delivery + gates** (mirrors Findings #3 matrix):

| Phase | Deliverable | Hard gate to next phase |
|---|---|---|
| **Pre-M1** | Security Phase-1 + Phase-2 merged + `MOBILE_ALLOWED_ORIGINS` env wired | `tests/test_auth.py` green; manual revoke verified; CORS env-extension test passes |
| **M1.0** | `frontend/src/mobile/main.jsx` + `/m` Vite entry + `manifest.webmanifest` + app-shell-only service worker; renders empty source-picker stub | Lighthouse PWA ≥ 80; `npm run build` first-paint ≤ 200 KB gz |
| **M1.1** | QR scan + `POST /api/pairing/complete` + localStorage device-token + axios bearer interceptor | Manual: phone scans QR, persists token, gated `POST /api/track/{tid}` returns 2xx; lost-token "Re-pair" screen reachable |
| **M1.2** | Source-picker → queue → edit surface (stars / colors / chips / comment / genre / MyTag) + Save & Next swipe via `@use-gesture/react` | G1 manual-checklist 12/12 green; G7 axios-interceptor p95 ≤ 350 ms LAN; G6 Lighthouse mobile-a11y ≥ 90 |
| **M1.3** | README Tailscale Funnel section + iOS Add-to-Homescreen UA-detect onboarding + (optional) `GET /api/track/{tid}/cover-thumb` for OQ7 | G4 cellular smoke ≤ 800 ms p95; PWA install banner appears under tunnel HTTPS; G3 first-paint ≤ 8 s mid-range Android |
| **M2** (deferred) | Capacitor shell — App-Store, native push, mDNS | Separate `idea_mobile-companion-capacitor-shell.md` topic |

**Waiting on (OPEN OQs)** — must resolve before `exploring_` → `evaluated_`:
1. **OQ12** — `MOBILE_ALLOWED_ORIGINS` shape sign-off (env-list lean).
2. **OQ13** — 200 KB / 500 KB gz bundle-ceiling sign-off.
3. **OQ14** — 60 s pairing-QR TTL sign-off (vs longer DJ-friendly default).
4. **OQ7** — text-only M1 vs cover-thumb M1.1 vs full thumb at M1 sign-off.
5. Security-hardening Phase-1 + Phase-2 actually land (currently `implement/draftplan_` — needs `inprogress_` → `implemented_`).

OQ1–OQ6, OQ8–OQ11 already RESOLVED in Open Questions section above.

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
