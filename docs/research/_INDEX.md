# Research & Implementation Pipeline — INDEX

Live dashboard. Each entry mirrors a file under `docs/research/{research,implement,archived}/`. Update on every `git mv`.

Format per line:
`<state>_<slug>.md — one-line hook (YYYY-MM-DD)`

If this index drifts from the file system, the file system wins — re-derive with `ls docs/research/*/`.

---

## research/

### idea
_(none)_

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

### evaluated
- [evaluated_security-pydantic-extra-allow-blob-write.md](research/evaluated_security-pydantic-extra-allow-blob-write.md) — Pydantic SetReq blob-write — Option B caps (8KB/64/256/256KB); Q11 (final caps) PARKED for review_ (2026-05-15)
- [evaluated_security-error-handler-exc-info-leak.md](research/evaluated_security-error-handler-exc-info-leak.md) — RedactingFormatter for exc_info; measured 0.46µs / 730 logger sites; 2 follow-ups split out (2026-05-15)
- [evaluated_security-api-file-reveal-sandbox.md](research/evaluated_security-api-file-reveal-sandbox.md) — /api/file/reveal Option A: ≤10 LOC validate_audio_path injection; Q1-Q3 RESOLVED (2026-05-15)
- [evaluated_security-cors-allow-credentials-tightening.md](research/evaluated_security-cors-allow-credentials-tightening.md) — CORS explicit lists 2-line PR + dead-cookie removal Phase B; Q5 PARKED cosmetic (2026-05-15)
- [evaluated_security-rate-limit-design.md](research/evaluated_security-rate-limit-design.md) — Custom token-bucket ~50 LOC + @rate_limit on 3 routes; OQ6 PARKED Phase-2 (2026-05-15)
- [evaluated_security-secrets-compare-digest-codebase-audit.md](research/evaluated_security-secrets-compare-digest-codebase-audit.md) — safe_compare helper + 3-line require_session refactor; Option C lint backstop PARKED (2026-05-15)

### parked
_(none)_

---

## implement/

### draftplan
- [draftplan_security-api-auth-hardening.md](implement/draftplan_security-api-auth-hardening.md) — **PRIORITY-1** Phase 1 auth: stdout+file token handoff, require_session on all mutation routes, Bearer-only, init-token deleted, SHUTDOWN_TOKEN query-scheme deleted. Ready for review_. (2026-05-15)

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
_(none yet)_

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
