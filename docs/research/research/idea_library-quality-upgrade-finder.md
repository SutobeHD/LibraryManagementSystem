---
slug: library-quality-upgrade-finder
title: Find higher-quality replacement files for tracks already in library
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [quality, upgrade, spectral, replacement, rekordbox-metadata]
related: [library-extended-remix-finder]
---

# Find higher-quality replacement files for tracks already in library

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

## Goals / Non-goals

**Goals**
- Compute per-track present-state quality score (container + true bitrate + sample rate + bit depth + spectral cutoff).
- Detect transcoded-from-lossy files masquerading as lossless (FLAC/WAV with < 21 kHz spectral cliff).
- Search configured external sources (Bandcamp, Beatport, SoundCloud Go+, Qobuz, local "HQ" folder) for higher-quality candidates of each library track.
- Surface ranked replacement suggestions in UI; user explicitly confirms each replace.
- On accepted replace: snapshot original, swap file in place, migrate Rekordbox metadata (cue points, beatgrid, MyTag, rating, color, play count) intact when same edit; force re-analyse when not.
- Sister-doc `idea_library-extended-remix-finder.md` shares source/match infra; reuse, don't fork.

**Non-goals** (deliberately out of scope)
- Auto-replace without explicit user confirmation. Blast radius is too high.
- Replacing tracks with different edits (remixes, extended/radio cuts) — that is the sister-doc's job.
- Cloud purchase automation. Surface link + manual download as MVP.
- Rebuilding the removed backup engine. Snapshot strategy must be local-file-copy based, scoped to the replaced file only.
- Re-cueing / re-beatgridding tracks whose edits differ — refuse the replace instead.

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- **Blast radius is maximal**: overwriting a curated track loses cue points, beatgrid edits, MyTag annotations the user invested time in. A single wrong replacement is data loss. `docs/SECURITY.md` threat model treats user audio files as user-data root (never agent-writable autonomously) — this feature explicitly crosses that line under user consent only.
- **`master.db` writes must hold `app/main.py:_db_write_lock`** (RLock, see `app/main.py:138` area) — any metadata-migration path that touches Rekordbox content rows MUST acquire it. rbox 0.1.7 quirks apply (use `app/usb_one_library.py` patterns; never call rbox parsing off the SafeAnlzParser process pool, see `app/anlz_safe.py`).
- **`ALLOWED_AUDIO_ROOTS` sandboxing** (`app/main.py:138-189`) bounds where replacement files may be written. Downloads must land inside a configured root; `Path.is_relative_to(resolved_root)` is the canonical check.
- **Rekordbox metadata semantics**: cue points and beatgrid anchors are stored as time offsets (ms / sample-indexed) in `master.db` and the `.ANLZ` sidecars. They survive a file swap only if the new file has the same edit boundary (intro start, length, silence padding). Beatgrid `first_beat_position` is sample-anchored — a 50 ms shift desyncs every cue downstream.
- **Spectral analysis cost**: librosa STFT on a 6-min track at default hop ~ 1-3 s CPU per file on a typical i7. Full-library audit (10k tracks) is ~ 1 h, must run in a bounded worker pool and be resumable. librosa already a dep (`app/analysis_engine.py`).
- **External-source legal/auth**: SoundCloud HQ/lossless requires Go+ account scope; Bandcamp/Beatport/Qobuz require user-owned purchases — no scraping of paid content. Local "HQ folder" is the friction-free path and should be first-class.
- **Match key**: title + artist + duration fuzzy via reused SoundCloud matcher (`app/soundcloud_downloader.py`, `app/soundcloud_api.py`), threshold ~ 0.65; ISRC (where ID3/Vorbis tag present) is a strong override.
- **No backup engine** any more (removed in commits `cc171ee`/`8fe5036`). Snapshot strategy must be ad-hoc: copy original to a user-visible `replaced/<YYYY-MM-DD>/` folder inside the library root before overwrite.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. Spectral-cutoff threshold to flag "transcoded from lossy": hard 20 kHz cliff, or sliding scale (e.g. > -60 dB energy above 21 kHz = lossless)?
2. Duration-delta tolerance before refusing same-edit assumption: 250 ms, 500 ms, 1 s? (Cue-point safety budget.)
3. Audio-fingerprint check before replace — Chromaprint/AcoustID (extra dep) vs cross-correlation of first 30 s mel-spectrogram (librosa only)?
4. Where does the snapshot live: sibling folder per replace, or one consolidated trash root under `ALLOWED_AUDIO_ROOTS[0]/.upgrade-snapshots/`? Disk-cost vs discoverability.
5. Re-analyse policy: always re-run `analysis_engine` after replace, or only if duration/bit-depth changed?
6. Quality scoring weights — strict ordering (lossless ≫ MP3-320 ≫ MP3-256) or composite score (container 40 % / sample rate 20 % / bit depth 15 % / spectral cutoff 25 %)?
7. Bandcamp/Beatport/Qobuz: do we ship a search adapter MVP, or local-folder + SoundCloud only for v1 and external stores as follow-ups?
8. UI surface: standalone "Quality Audit" view, or extend existing Library view with a per-row badge + "find upgrade" action?

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-15 — initial audit

**Quality dimensions, ordered**
- Container/codec: FLAC / WAV / ALAC > AIFF > MP3-320 > MP3-256 > MP3-V0/V2 > MP3-192 > MP3-128 > MP3 < 128 / OGG-low / AAC-low.
- Sample rate: 44.1 / 48 kHz baseline; 88.2 / 96 / 176.4 / 192 kHz hi-res.
- Bit depth (lossless only): 16-bit standard, 24-bit hi-res, 32-bit float rare.
- Channels: stereo standard; mono is a downgrade flag regardless of container.
- True bitrate vs declared: a "320 kbps MP3" with ABR or padding can have a true mean bitrate well below 320; check via ffprobe `bit_rate` on the stream, not container.

**Transcoded-from-lossy detection (the core anti-fraud check)**
- Lossy encoders apply a low-pass; cliff height encodes the source bitrate.
- Heuristic cutoff frequencies (approximate, encoder-dependent):
  - MP3 128 kbps: ~ 16 kHz
  - MP3 192 kbps: ~ 17 – 18 kHz
  - MP3 256 kbps: ~ 19 kHz
  - MP3 320 kbps / V0: ~ 19 – 20 kHz
  - AAC 256 kbps: ~ 20 kHz
  - True lossless @ 44.1 kHz: energy up to Nyquist 22.05 kHz
- Algorithm sketch: full-track STFT (librosa), median over time of magnitude per FFT bin, find highest frequency bin with > -60 dBFS energy. If file claims FLAC/WAV/ALAC but cutoff < 21 kHz, flag as transcoded.
- Pitfalls: genuinely bandlimited lossless masters (some vinyl rips, classical with no HF content), 48 kHz source then resampled (Nyquist shifts to 24 kHz). Need second pass: also check noise-floor shape (lossy has a sharper transition band).
- Tools: librosa already in deps; spek/sox are external CLIs we'd avoid for headless ops. `app/analysis_engine.py` is the natural home.

**Local quality scoring pipeline (offline batch)**
- Per track: ffprobe → container/codec/declared bitrate/sample rate/bit depth/duration; librosa → spectral cutoff + noise-floor shape.
- Persist into a new table (e.g. `track_quality`) keyed by content_id, with version column so re-scans are deterministic and supersedable. Don't pollute `master.db`'s rbox-managed tables — store in our companion SQLite (`live-db` or a new sidecar DB).
- Resumable: skip tracks where `(file_path, mtime, size)` matches a prior row.

**External sources — feasibility snapshot**
- **Local "HQ folder"**: user-configured path under `ALLOWED_AUDIO_ROOTS`. Scan once with the same quality pipeline; match library track ↔ HQ candidate by ISRC then title/artist/duration. Zero auth, zero network. Highest-leverage MVP.
- **SoundCloud**: existing `app/soundcloud_*` infra; HQ/lossless gated by Go+ uploader settings. Use same matcher; threshold ~ 0.65 already calibrated for sister-doc.
- **Bandcamp**: no official search API for upgrades; artist-page scraping + user's purchase library (download-page parsing) viable. Out of MVP scope, follow-up.
- **Beatport**: API requires partner credentials; user-account-scoped library API exists. Follow-up.
- **Qobuz**: hi-res search API exists, requires user auth. Follow-up.

**Replacement workflow (proposed flow)**
1. Candidate found → download into staging dir inside `ALLOWED_AUDIO_ROOTS`.
2. Re-scan staging file through quality pipeline; reject if not strictly better on chosen weighting.
3. Same-edit check: duration delta < tolerance (open Q 2) AND mel-fingerprint correlation > threshold on first 30 s + last 30 s (catches different intros / extended mixes).
4. If pass: snapshot original → swap file in place under same filename (or update path in `master.db` if extension changes, e.g. MP3 → FLAC).
5. Migrate metadata: cue points / beatgrid / MyTag / rating / color / play count remain in `master.db` rows keyed by content_id; only the file blob changed, so most metadata is automatically preserved. Re-run `analysis_engine` if bit depth or sample rate changed (waveform overview regen).
6. If same-edit check fails: do NOT replace; surface as "candidate is a different edit — see remix-finder" and link to sister flow.

**Risk catalogue**
- Wrong-edit silent replace: every cue point shifts by intro-length delta. Mitigated by step 3 fingerprint+duration gate. Refuse-by-default if uncertain.
- Format-change cue-point drift: even same-edit, encoder padding can add 10-30 ms of silence. May need a small auto-align offset applied to cue-point times during migration.
- rbox panic on metadata reread after swap: route any rbox parsing through `SafeAnlzParser` (`app/anlz_safe.py`) — never in main process.
- User undo: snapshot folder must be human-discoverable; consider a "Restore from snapshot" UI action.
- Disk pressure: snapshots double-allocate space until user prunes. Show used-space, offer prune-older-than-N-days.

**Tie-in to sister doc**
- Shared infrastructure: external-source adapters, fuzzy matcher, quality scorer, fingerprint check.
- Diverges on intent: this doc wants same-edit; sister wants explicitly different edits/remixes/extended cuts. The fingerprint + duration gate is the same code, just inverted polarity.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Local-folder-only MVP, full pipeline

- Sketch: implement quality scorer + spectral-cutoff detector + duration/fingerprint gate + snapshot+swap. External source = one user-designated "HQ" folder. No network adapters in v1.
- Pros: zero auth/legal risk; full end-to-end flow exercised; immediate value for users who already have HQ masters elsewhere; lays the foundation sister-doc can share.
- Cons: ceiling on usefulness for users without an existing HQ archive.
- Effort: M
- Risk: medium — replacement plumbing is the hard part; doing it right once is leverage.

### Option B — Audit-only (no replace)

- Sketch: ship quality scoring + transcode-fraud detector + UI quality badges, but no upgrade flow. User decides manually.
- Pros: zero replacement-blast-radius risk; ships fast; pure read-side.
- Cons: half a feature; the user still has to do all the upgrade work by hand. Doesn't justify the spectral-analysis investment alone.
- Effort: S
- Risk: low.

### Option C — Full source matrix (SoundCloud + Bandcamp + Beatport + Qobuz + local)

- Sketch: parallel adapter implementation for every paid store + SoundCloud Go+ + local folder, behind a unified search interface.
- Pros: maximum user value; one feature that handles everything.
- Cons: huge scope; auth flows per store; legal/TOS care per adapter; long path to first user value.
- Effort: XL
- Risk: high — partial implementations rot; auth maintenance is ongoing.

### Option D — Audit MVP first, then upgrade flow (phased Option B → A)

- Sketch: ship Option B in phase 1 (audit + badges + transcode detector). Phase 2 adds local-folder upgrade flow with snapshot/swap. Phase 3 adds SoundCloud + selected paid stores.
- Pros: each phase delivers standalone value; risky replacement code lands only after scoring infra is proven; sister-doc benefits from phase-1 deliverables.
- Cons: longer total timeline; phase-1 release without "the point" of the feature may feel incomplete.
- Effort: M (phase 1) + M (phase 2) + L (phase 3)
- Risk: low-medium per phase.

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

Lean **Option D**. Ship the quality-audit + transcode-fraud detector first as a read-only feature (immediately useful and reused by the sister remix-finder), then add the local-HQ-folder replacement flow with snapshot+swap+metadata-migration once the scoring infra is battle-tested. External paid-store adapters land last and incrementally.

Blockers to resolve before `evaluated_`:
- Open Q 2 (duration tolerance) and Q 3 (fingerprint method) — these define the safety gate.
- Open Q 4 (snapshot location) — needs UX call.
- Confirmation that we won't reintroduce a backup engine; ad-hoc per-replace snapshot is the agreed path.

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
