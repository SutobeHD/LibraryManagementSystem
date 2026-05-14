---
slug: api-route-auth-model
title: API route auth model — local FastAPI mutation routes have no route-level auth gate
owner: unassigned
created: 2026-05-13
last_updated: 2026-05-13
tags: [security, backend, api, auth]
related: [downloader-unified-multi-source]
---

# API route auth model — local FastAPI mutation routes have no route-level auth gate

> **State**: derived from filename + folder. Start as `docs/research/research/idea_<slug>.md`.

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-13 — `research/idea_` — created (spun off from OQ-A in `implement/review_downloader-unified-multi-source.md`: the unified-downloader routes will ship with no route-level auth gate — consistent with existing SC routes — but the general gap deserves its own deliberate decision rather than drift)

---

## Problem

The FastAPI sidecar (`app/main.py`, port 8000) exposes mutation routes — SoundCloud download, library writes, and soon the unified downloader (`/api/downloads/unified/*`) — with **no route-level authentication**. The only token primitive is `SHUTDOWN_TOKEN` (`main.py:126`, a per-session `secrets.token_urlsafe(32)`), used solely as a `?token=` query param for `/shutdown` + `/restart`.

Today's mitigation is implicit: the sidecar binds to `127.0.0.1` and CORS is whitelisted. But any local process (or local malware) can hit these routes directly. With ~146 routes today and the surface still growing, the absence of a positive auth gate is worth a deliberate decision rather than continued drift.

## Goals / Non-goals

**Goals**
- Decide whether local mutation routes need a route-level auth gate, and if so what shape — session token, per-route token, mTLS-on-loopback, OS-level, etc.
- If yes: a pattern that applies uniformly across all routes (middleware / FastAPI dependency), not per-route bespoke code.

**Non-goals**
- Internet-facing auth — the sidecar is loopback-only by design; this is not about exposing it to a network.
- Reworking the SoundCloud OAuth flow — that's upstream-API auth, a separate concern.

## Constraints

- The sidecar is a Tauri-spawned local process; the React frontend talks to it over `127.0.0.1:8000`. Any scheme must not break the Tauri ↔ sidecar ↔ browser-dev-mode triangle (`npm run dev:full` runs the frontend without Tauri).
- `SHUTDOWN_TOKEN` already exists as a per-session token — a session-token scheme could generalise it rather than inventing a new primitive.
- ~146 routes — retrofitting must be mechanical (middleware or a shared dependency), not 146 hand-edits.

## Open Questions

1. Is loopback-bind + CORS-whitelist actually sufficient for the threat model of a local-only desktop app? Or is local-malware a real enough concern to defend against?
2. If a gate is wanted: middleware-level (all routes) vs. a FastAPI dependency applied only to the mutation subset?
3. Session-token (one `init-token` handshake, then an `X-Session-Token` header) vs. an alternative?
4. How does browser dev-mode (`npm run dev:full`, no Tauri wrapper) obtain the token?

## Findings / Investigation

_(none yet — idea stage)_

## Links

- Spun off from: `docs/research/implement/review_downloader-unified-multi-source.md` (OQ-A decision: that feature ships with no route gate; this doc tracks the general question)
- Code: `app/main.py:126` (`SHUTDOWN_TOKEN`), `app/main.py` SoundCloud download routes (no gate today)
