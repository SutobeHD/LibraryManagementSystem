# Research & Implementation Pipeline — INDEX

Live dashboard. Each entry mirrors a file under `docs/research/{research,implement,archived}/`. Update on every `git mv`.

Format per line:
`<state>_<slug>.md — one-line hook (YYYY-MM-DD)`

If this index drifts from the file system, the file system wins — re-derive with `ls docs/research/*/`.

---

## research/

### idea
- [idea_db-write-lock-retrofit.md](research/idea_db-write-lock-retrofit.md) — Retrofit `_db_write_lock` on 85 unprotected `master.db` write routes; `@_serialised` decorator defined but 0 applications; rbox 0.1.7 concurrent-write panic risk (2026-05-19)
- [idea_security-mobile-paired-tokens-phase2.md](research/idea_security-mobile-paired-tokens-phase2.md) — Phase-2 paired-device tokens + QR-pairing flow; hard prereq for mobile-companion; sidecar-local SQLite, `require_session` accepts boot+device tokens (2026-05-19)

### exploring
- [exploring_recommender-rules-baseline.md](research/exploring_recommender-rules-baseline.md) — Teil 1: BPM/Key/Genre/MyTag/Energy ranking + Camelot harmonic mixing; local + SoundCloud modes (2026-05-11)
- [exploring_recommender-taste-llm-audio.md](research/exploring_recommender-taste-llm-audio.md) — Teil 2: LLM/embedding-based recommender that learns taste from listening behaviour + audio features (2026-05-11)
- [exploring_analysis-underground-mainstream-classifier.md](research/exploring_analysis-underground-mainstream-classifier.md) — Underground vs Mainstream classifier; cross-platform plays aggregation; M1-M4 phased rollout (2026-05-15)
- [exploring_recommender-similar-tracks.md](research/exploring_recommender-similar-tracks.md) — LOCAL-ONLY similar-tracks recommender; ~12-15 dim handcrafted vector; M1/M2/M3 (2026-05-15)
- [exploring_analysis-remix-detector.md](research/exploring_analysis-remix-detector.md) — Detect remix/edit/bootleg variants; reuses Rust fingerprint pipeline; M1/M2/M3 (2026-05-15)
- [exploring_metadata-name-fixer.md](research/exploring_metadata-name-fixer.md) — Normalise artist/title metadata with 4-layer safety + undo log; M0/M1/M2 (2026-05-15)
- [exploring_library-extended-remix-finder.md](research/exploring_library-extended-remix-finder.md) — Find Extended/Club/Long versions; Discogs-gated SC search; M1/M2/M3 (2026-05-15)
- [exploring_library-quality-upgrade-finder.md](research/exploring_library-quality-upgrade-finder.md) — Quality auditor + transcode detection + replacement with 7-rule safety; Phase 1/2/3 (2026-05-15)
- [exploring_mobile-companion-ranking-app.md](research/exploring_mobile-companion-ranking-app.md) — Mobile companion (PWA M1); QR-pairing + Tailscale Funnel docs; security Phase-1+2 hard prereq (2026-05-15)
- [exploring_external-track-match-unified-module.md](research/exploring_external-track-match-unified-module.md) — Cross-cutting module (fuzzy + chromaprint + adapter-registry) shared by 3 sister features; M1/M2/M3 (2026-05-15)

_(none)_

### parked
_(none)_

---

## implement/

### draftplan
_(none)_

### review
_(none)_

### rework
_(none)_

### accepted
_(none)_

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
_(none)_

### abandoned
_(none)_

---

## How to update

When a doc changes state:
1. After `git mv` (or `mv` for new files), move its line to the new section
2. Update the date at the end of the line
3. If the file moved across stages (e.g. `research/` → `implement/`), also update the markdown link path
