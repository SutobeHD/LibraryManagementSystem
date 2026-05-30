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
- [exploring_db-write-lock-retrofit.md](research/exploring_db-write-lock-retrofit.md) — Close `_db_write_lock` coverage gaps; Option B (auto-wrap) committed; wave-2 verify → GAPS (3rd gap: `AnalysisDBWriter` rbox-direct write uncovered by class decorator; circular drift guard); stays exploring_ (2026-05-29)
- [exploring_mobile-companion-ranking-app.md](research/exploring_mobile-companion-ranking-app.md) — Mobile companion (PWA M1); wave-2 GAPS narrowed (CORS para corrected, 3/3 stale main.py refs refreshed+PASS, Phase-2 prereq now past GATE A); remaining blocker = OQ14+OQ7 user sign-off only; stays exploring_ (2026-05-29)
### midgate ⛔ GATE B
_(none)_

### evaluated
- [evaluated_library-format-converter.md](research/evaluated_library-format-converter.md) — Library-wide format converter; wave 2 closed all 3 blockers (proof script `fdb461c`, AAC priming empirical A/B sample-identical, path-write via direct rbox `update_content`), 6 adversarial concerns addressed/carried-forward, citation MIXED non-load-bearing, V-PASS round 2, 3 options (A/B/C) + Recommendation = Option A (full engine, sister-doc unblocks) with 4 commit-blockers for draftplan_ (2026-05-30)

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

### review
_(none)_


### rework
_(none)_

### accepted
- [accepted_downloader-unified-multi-source.md](implement/accepted_downloader-unified-multi-source.md) — Unified multi-source downloader: owner sign-off granted; integrated with parallel research (matching delegated to `external_track_match`, auth via `require_session`, `quality_engine` reuse). Ready for `inprogress_` (2026-05-21)
- [inprogress_external-track-match-unified-module.md](implement/inprogress_external-track-match-unified-module.md) — **CRITICAL PATH**: sister-doc prereq for 3 other features (remix-detector, extended-remix-finder, quality-upgrade-finder). **Module T-3..T-9 SHIPPED** (`app/external_track_match.py` — parse_version_tag/extract_title_stem/fuzzy/fingerprint, 26 tests green); T-1/T-2 corpus + T-10 SC-delegate `[ ]` for routine/owner (2026-05-29)
- [inprogress_analysis-remix-detector.md](implement/inprogress_analysis-remix-detector.md) — Variant detector M1/M2/M3; sidecar `variants.db`. **T-2 schema + T-3 detector SHIPPED** (classify/cluster/canonical-pick, consumes external_track_match, 15 tests green); T-1 corpus + T-4 routes + T-5 hook/CLI `[ ]` (2026-05-30)
- [inprogress_analysis-underground-mainstream-classifier.md](implement/inprogress_analysis-underground-mainstream-classifier.md) — 2D-Display + SC 0.80/Spotify 0.20 aggregate; ECDF carve-out; **T1-T3 `app/popularity_engine.py` SHIPPED** (sidecar store + migrate framework + CRUD, 10 tests green); T4+ `[ ]` for `research-implement` routine (2026-05-29)
- [accepted_library-extended-remix-finder.md](implement/accepted_library-extended-remix-finder.md) — Extended/Club/Long-version finder; gated on sister `external-track-match` shipping `inprogress_`; GATE C PASSED 2026-05-29 (2026-05-29)
- [accepted_library-quality-upgrade-finder.md](implement/accepted_library-quality-upgrade-finder.md) — Quality auditor (detection-only); Phase-3 swap delegated; GATE C PASSED 2026-05-29 (2026-05-29)
- [accepted_recommender-rules-baseline.md](implement/accepted_recommender-rules-baseline.md) — Teil 1 ranking baseline; defaults T-10 confirmed (M1 backend / key_first / relative=0.7); GATE C PASSED 2026-05-29 (2026-05-29)
- [accepted_recommender-similar-tracks.md](implement/accepted_recommender-similar-tracks.md) — LOCAL-ONLY similar-tracks; 4 named slice BLOBs; GATE C PASSED 2026-05-29 (2026-05-29)
- [inprogress_recommender-taste-llm-audio.md](implement/inprogress_recommender-taste-llm-audio.md) — Taste-aware recommender (Teil 2); M1 Option-A centroid / M2 embedding-benchmark / M3 LLM-explain; **T1 `app/db_taste.py` SHIPPED** (sidecar taste-vector store, 7 tests green); T2+ blocked on sister vector + Teil-1 plays (2026-05-29)
- [accepted_download-format-setting.md](implement/accepted_download-format-setting.md) — AIFF default + 6-target dropdown (Option A); full plan + Threat Model; GATE C PASSED 2026-05-29 (agent-delegated); load-bearing task = -map_metadata 0 + mutagen art-overlay fix (2026-05-29)

### inprogress
- [inprogress_metadata-name-fixer.md](implement/inprogress_metadata-name-fixer.md) — Artist/title normaliser; **T1 detector + T4 schema + T5 apply/revert engine SHIPPED** (`app/metadata_fixer/{detector,schema,applier}.py`, 25 tests green); T2/T3/T6–T10 `[ ]` for `research-implement` routine (2026-05-29)
- [inprogress_security-mobile-paired-tokens-phase2.md](implement/inprogress_security-mobile-paired-tokens-phase2.md) — Per-device QR pairing (Option A); **T1–T3 SHIPPED** (`auth_db` hashed store, `pairing_store` one-shot codes, `require_session` dual-acceptance; 31 tests green); T4–T7 (routes/Tauri/UI) `[ ]` for `research-implement` routine (2026-05-29)

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
