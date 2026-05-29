# Research & Implementation Pipeline — INDEX

Live dashboard. Each entry mirrors a file under `docs/research/{research,implement,archived}/`. Update on every `git mv`.

Format per line:
`<state>_<slug>.md — one-line hook (YYYY-MM-DD)`

Gate states (`ideagate_`, `midgate_`, `plangate_`) wait on the user — see "The 4 Gates" in `README.md`.

If this index drifts from the file system, the file system wins — re-derive with `ls docs/research/*/` or `python scripts/pipeline_status.py`.

---

## research/

### idea
_(none)_

### drafting
_(none)_

### ideagate ⛔ GATE A
_(none)_

### exploring
- [exploring_db-write-lock-retrofit.md](research/exploring_db-write-lock-retrofit.md) — Close `_db_write_lock` coverage gaps; Option B (auto-wrap, prefix-matched) committed; GATE A PASSED 2026-05-29 (2026-05-29)
- [exploring_download-format-setting.md](research/exploring_download-format-setting.md) — AIFF default + 6-Option-Dropdown (AIFF/ALAC/FLAC/WAV/MP3-320/Original); GATE A PASSED 2026-05-29 (2026-05-29)
- [exploring_library-format-converter.md](research/exploring_library-format-converter.md) — Library-weiter Audio-Format-Konverter + merged Snapshot+Swap+Migrate engine (quality-upgrade trigger variant inside); 6 OQs technisch beantwortet; GATE A PASSED 2026-05-29 (2026-05-29)
- [exploring_mobile-companion-ranking-app.md](research/exploring_mobile-companion-ranking-app.md) — Mobile companion (PWA M1); CORS rewrite done; Phase-2 hard-prereq now UNBLOCKED via security-mobile-paired-tokens-phase2 GATE A pass (2026-05-29)
- [exploring_security-mobile-paired-tokens-phase2.md](research/exploring_security-mobile-paired-tokens-phase2.md) — Per-device QR-pairing + sidecar `auth.db`; GATE A PASSED 2026-05-29; entblockt mobile-companion (2026-05-29)

### midgate ⛔ GATE B
- [midgate_external-track-match-unified-module.md](research/midgate_external-track-match-unified-module.md) — Cross-cutting fuzzy+chromaprint+adapter module shared by 3 sister features; wave-2 PASS (cosmetic line drift only); awaiting GATE B (2026-05-28)
- [midgate_library-extended-remix-finder.md](research/midgate_library-extended-remix-finder.md) — Find Extended/Club/Long versions via Discogs-gated SC search; wave-2 PASS-with-gaps (scoring calibration + Discogs coverage % deferred to evaluated_) (2026-05-28)
- [midgate_metadata-name-fixer.md](research/midgate_metadata-name-fixer.md) — Normalise artist/title metadata with 4-layer safety + undo log; wave-2 PASS with 2 stale main.py line refs (892→1124, 926→1160) (2026-05-28)
- [midgate_recommender-rules-baseline.md](research/midgate_recommender-rules-baseline.md) — Teil 1 ranking baseline (BPM/Key/Genre/MyTag/Energy + Camelot); wave-2 PASS-with-notes (3 user-pick default gates remain) (2026-05-28)
- [midgate_recommender-similar-tracks.md](research/midgate_recommender-similar-tracks.md) — LOCAL-ONLY similar-tracks recommender; wave-2 PASS with 2 plan-shape corrections (backfill model, named vector slices) (2026-05-28)
- [midgate_recommender-taste-llm-audio.md](research/midgate_recommender-taste-llm-audio.md) — Teil 2 taste/LLM recommender; wave-2 GAPS-recoverable (2 stale line-cites + cache invalidation underspecified) (2026-05-28)
- [midgate_analysis-remix-detector.md](research/midgate_analysis-remix-detector.md) — Remix/edit/bootleg variant detector; wave-2 gaps closed-out 2026-05-29 (PyYAML→JSON, browser-mode constraint, lock owner picked, stratified fixture buckets) (2026-05-29)
- [midgate_analysis-underground-mainstream-classifier.md](research/midgate_analysis-underground-mainstream-classifier.md) — Underground vs Mainstream classifier; aggregation REVISED to 2D-Display + 1D-aggregate with SC 0.80 / Spotify 0.20 weights (user 2026-05-29); ISRC audit script provided (2026-05-29)
- [midgate_library-quality-upgrade-finder.md](research/midgate_library-quality-upgrade-finder.md) — Quality auditor; scope narrowed to detection-only (Phase-3 Snapshot+Swap+Migrate MERGED into `library-format-converter` per user 2026-05-29); `validate_audio_path` trust analysis added; weight-sum invariant pinned (2026-05-29)

### evaluated
_(none)_

### parked
_(none)_

---

## implement/

### draftplan
_(none)_

### review
_(none)_

### plangate ⛔ GATE C
_(none)_

### rework
_(none)_

### accepted
- [accepted_downloader-unified-multi-source.md](implement/accepted_downloader-unified-multi-source.md) — Unified multi-source downloader: owner sign-off granted; integrated with parallel research (matching delegated to `external_track_match`, auth via `require_session`, `quality_engine` reuse). Ready for `inprogress_` (2026-05-21)

### inprogress
_(none)_

### blocked
_(none)_

---

## archived/

### implemented
- [implemented_security-api-auth-hardening_2026-05-17.md](archived/implemented_security-api-auth-hardening_2026-05-17.md) — **PRIORITY-1** Phase-1 Bearer auth (84/85 mutation routes gated; SHUTDOWN_TOKEN deleted; Tauri stdout+file token handoff; 219+ tests pass). Phase 2 (paired-device tokens + QR pairing) carved out as future doc. (2026-05-17)
- [implemented_security-secrets-compare-digest-codebase-audit_2026-05-17.md](archived/implemented_security-secrets-compare-digest-codebase-audit_2026-05-17.md) — safe_compare helper + require_session refactor; 5 fragility cases covered (commit 8498937, 52+ tests). (2026-05-17)
- [implemented_security-rate-limit-design_2026-05-17.md](archived/implemented_security-rate-limit-design_2026-05-17.md) — Custom token-bucket (180 LoC) + @rate_limit on shutdown/restart/sc-auth-token (steady=5/min, burst=10, key_mode=both); 253+ tests pass. (2026-05-17)
- [implemented_security-pydantic-extra-allow-blob-write_2026-05-18.md](archived/implemented_security-pydantic-extra-allow-blob-write_2026-05-18.md) — SetReq caps (8KB/64/256/256KB) + @model_validator + SettingsManager._sanitize_loaded; 21 new tests; 285+ pass (2026-05-18)
- [implemented_security-error-handler-exc-info-leak_2026-05-18.md](archived/implemented_security-error-handler-exc-info-leak_2026-05-18.md) — RedactingFormatter + safe_error_message_str helpers; widened path list (EXPORT_DIR/MUSIC_DIR/TEMP_DIR); 4 redaction tests; 285+ pass (2026-05-18)
- [implemented_security-api-file-reveal-sandbox_2026-05-18.md](archived/implemented_security-api-file-reveal-sandbox_2026-05-18.md) — /api/file/reveal sandboxed via validate_audio_path; 7 platform+sandbox tests; 285+ pass (2026-05-18)
- [implemented_security-cors-allow-credentials-tightening_2026-05-18.md](archived/implemented_security-cors-allow-credentials-tightening_2026-05-18.md) — CORS wildcards→explicit lists (Phase A) + bearer-only rule + Phase B (allow_credentials=False, sentinel cookie deleted, withCredentials=false) both SHIPPED; 285+ pass (2026-05-18, Phase B 2026-05-19)

### superseded
- [superseded_api-route-auth-model_2026-05-21.md](archived/superseded_api-route-auth-model_2026-05-21.md) — Route-auth gap (spun off from downloader OQ-A); superseded by the shipped security-api-auth-hardening (`app/auth.py` + `require_session`) (2026-05-21)

### abandoned
_(none)_

---

## How to update

When a doc changes state:
1. After `git mv` (or `mv` for new files), move its line to the new section
2. Update the date at the end of the line
3. If the file moved across stages (e.g. `research/` → `implement/`), also update the markdown link path

Work-state → work-state moves are done by routines. Gate-state → work-state moves are done by the user (`/gate-pass`, `/gate-reject`). `/pipeline` shows the live state without reading this file.
