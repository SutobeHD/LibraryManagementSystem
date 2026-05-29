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
- [exploring_db-write-lock-retrofit.md](research/exploring_db-write-lock-retrofit.md) — Close `_db_write_lock` coverage gaps; Option B (auto-wrap) committed; GATE A PASSED 2026-05-29 (2026-05-29)
- [exploring_download-format-setting.md](research/exploring_download-format-setting.md) — AIFF default + 6-Option-Dropdown; GATE A PASSED 2026-05-29 (2026-05-29)
- [exploring_library-format-converter.md](research/exploring_library-format-converter.md) — Audio-Format-Konverter + merged Snapshot+Swap+Migrate engine; 6 OQs technisch beantwortet; GATE A PASSED 2026-05-29 (2026-05-29)
- [exploring_mobile-companion-ranking-app.md](research/exploring_mobile-companion-ranking-app.md) — Mobile companion (PWA M1); CORS rewritten; Phase-2 hard-prereq now UNBLOCKED (2026-05-29)
- [exploring_security-mobile-paired-tokens-phase2.md](research/exploring_security-mobile-paired-tokens-phase2.md) — Per-device QR-pairing + sidecar `auth.db`; GATE A PASSED 2026-05-29 (2026-05-29)
### midgate ⛔ GATE B
- [midgate_metadata-name-fixer.md](research/midgate_metadata-name-fixer.md) — Artist/Title normaliser; reject-recovery done — stale `app/main.py` refs refreshed (892→1124, 926→1160); Citation Quality now 12/12 PASS; re-awaiting GATE B (2026-05-29)
- [midgate_recommender-taste-llm-audio.md](research/midgate_recommender-taste-llm-audio.md) — Teil 2 taste/LLM recommender; reject-recovery done — Option-D cache invalidation resolved (`taste_profile_hash` → `taste_profile_version` bumps only on significant drift); re-awaiting GATE B (2026-05-29)

### evaluated
_(none)_

### parked
_(none)_

---

## implement/

### draftplan
- [draftplan_external-track-match-unified-module.md](implement/draftplan_external-track-match-unified-module.md) — Cross-cutting fuzzy+chromaprint+adapter; full Stage 3 plan; 12 atomic tasks; sister-doc prereq for 3 other draftplan_ docs (2026-05-29)
- [draftplan_analysis-remix-detector.md](implement/draftplan_analysis-remix-detector.md) — Remix/edit/bootleg variant detector; M1/M2/M3 phases; sidecar `variants.db`; 12 atomic tasks (2026-05-29)
- [draftplan_analysis-underground-mainstream-classifier.md](implement/draftplan_analysis-underground-mainstream-classifier.md) — Underground/Mainstream; 2D-Display + SC 0.80 / Spotify 0.20 weights; ECDF carve-out baked in; 12 atomic tasks ~33h M1 (2026-05-29)
- [draftplan_library-extended-remix-finder.md](implement/draftplan_library-extended-remix-finder.md) — Extended/Club/Long versions via SC search; critical path = sister `external-track-match` shipping `inprogress_`; 12 atomic tasks (2026-05-29)
- [draftplan_library-quality-upgrade-finder.md](implement/draftplan_library-quality-upgrade-finder.md) — Quality auditor (detection-only); Phase-3 swap delegated to `library-format-converter`; `allow_db_match=False` mitigation; 12 atomic tasks (2026-05-29)
- [draftplan_recommender-rules-baseline.md](implement/draftplan_recommender-rules-baseline.md) — Teil 1 ranking baseline; 3 default-picks surfaced as user-action; 12 atomic tasks ~22h (2026-05-29)
- [draftplan_recommender-similar-tracks.md](implement/draftplan_recommender-similar-tracks.md) — LOCAL-ONLY similar-tracks; **both plan-shape corrections baked in** (4 named slice BLOB columns + re-decode via librosa.load); 12 atomic tasks (2026-05-29)

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
