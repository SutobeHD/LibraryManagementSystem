---
slug: download-format-setting
title: Download-Format-Setting — Standard AIFF + User-konfigurierbares Ziel-Format pro Download
owner: tb
created: 2026-05-28
last_updated: 2026-05-28
tags: [downloader, soundcloud, aiff, settings, ux]
related: [library-format-converter, downloader-unified-multi-source]
supersedes: []
superseded_by: []
---

# Download-Format-Setting — Standard AIFF + User-konfigurierbares Ziel-Format pro Download

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc by state. 4 user gates: A `ideagate_`, B `midgate_`, C `plangate_`, D PR-merge.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-05-28 — `research/idea_` — created (user request after SC-downloader security audit)
- 2026-05-28 — `research/drafting_` — Stage 1 worker filled Problem → Research Plan inline at creation time (faster than waiting for next routine cycle; same outputs the routine would have produced)
- 2026-05-28 — `research/ideagate_` — Stage 1 verifier PASS, awaiting GATE A
- 2026-05-29 — `research/exploring_` — GATE A PASSED by user; AIFF default + 6-Option-Dropdown specs confirmed; advanced for Stage 2 wave-2 verifier
- 2026-05-29 — `research/midgate_` — Stage 2 wave 1 done (4 tiered agents: code-surface + sister-delta + web-DJ-formats + UI-pattern). All 6 OQs covered; 3 doc corrections found (180s timeout not 360s, POST not PUT, current convert drops artwork). Awaiting GATE B.
- 2026-05-29 — `research/evaluated_` — GATE B PASSED (user-delegated authority) + wave-2 verification run on the wave-1 body: Adversarial (artwork-drop, remux-wording, fake-lossless, storage), Citation Quality (code PASS / web MEDIUM, Pioneer 403), Research Verification PASS; Options + Recommendation (Option A) written.
- 2026-05-29 — `implement/draftplan_`→`review_`→`plangate_` — research-plan: Implementation Plan filled, Threat Model STRIDE table (TM1-4→tests), API/UX corrected PUT→POST, Review 14/14 PASS. Pre-scaffolded Migration/Perf/Telemetry/Test-Plan/Task-Queue retained.
- 2026-05-29 — `implement/accepted_` — GATE C PASSED (user-delegated authority for PASS-verified plans). Ready for `inprogress_`; load-bearing task = the `-map_metadata 0` + mutagen art-overlay fix (gated by T3).

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1-3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

Beim Download standardmäßig in AIFF-Dateien umgewandelt (Apple Lossless, die besten für Metadaten). Soll immer einstellbar sein in Settings, in welches Format die Dateien konvertiert werden. An bestehendes Format-Konverter-Research anschließen, nichts unnötig doppeln.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Active — HIGH overlap, complementary scope:** [`ideagate_library-format-converter`](ideagate_library-format-converter.md) (GATE A) — library-weiter Batch-Konverter mit DB-Integrität (Cues, Beatgrid, Playlists). **Dieses Doc ist die per-Download-Variante**, das andere Doc ist post-hoc-Library-Migration. Geteilte Primitive: FFmpeg AIFF-Cmd, AAC-Priming-Drift (OQ 1 dort), `_convert_to_aiff` helper. Hier KEINE Snapshot/Rollback/DB-row-rewrite Logik nötig — Track ist beim Format-Convert noch nicht in `master.db`.
- **Active — bigger scope, slower ship:** [`accepted_downloader-unified-multi-source`](../implement/accepted_downloader-unified-multi-source.md) — Goal Q11 ist exakt "AIFF-as-default output". Aber das Doc bündelt SpotiFLAC + Tidal/Qobuz/Amazon + 100%-match + Quality-Ranker + Genre-sync + Provenance. **Mein Scope ist der ship-bare Subset davon**, der unabhängig vom unified-downloader-Build heute landen kann.
- **Shipped — code already there:** `app/soundcloud_downloader.py:_convert_to_aiff` (Function existiert), `_aiff_requested()` (reads `sc_download_format == "aiff"`), default `"auto"` (passthrough). UI fehlt komplett — Setting nicht in Settings.json-Schema, nicht in `SetReq`, nicht im SettingsView. → Half-built feature; dieses Doc schließt die Lücke.
- **External precedent:** Rekordbox-Editor hat keine Download-Format-Wahl (kein Download). Serato DJ Pro Default = original source format. Apple Music Match: ALAC. Tidal-Downloader-CLI: FLAC/ALAC config-flag. Convention: lossless default + user-overridable.

## Problem

Stage 1 Worker. Soft 60w cap.

SC-Downloads schreiben Source-Format (MP3 progressive / AAC HLS / Original-Upload je nach Track + Account-Tier). User will lossless AIFF als Default — beste DJ-SW-Kompatibilität, beste ID3-Tag-Surface (Rekordbox/CDJ-3000 reads ID3v2 nativ aus AIFF). Heute: `sc_download_format` Setting existiert (auto/aiff), aber kein UI, kein Default-AIFF, keine erweiterten Targets (FLAC/WAV/ALAC/MP3).

## Goals / Non-goals

**Goals**
- **Default-Setting** `sc_download_format = "aiff"` (statt heutigem `"auto"`).
- **Settings-UI** (Settings-Tab) mit Dropdown — 6 Targets, AIFF preselected:
  1. **AIFF** (uncompressed PCM, ~30 MB / 3 min, CDJ-3000 nativ) ← Default
  2. **ALAC** (Apple Lossless, .m4a Container, ~15 MB / 3 min)
  3. **FLAC** (Free Lossless Audio Codec, ~15 MB / 3 min, best DJ-SW compat outside Rekordbox)
  4. **WAV** (uncompressed PCM, RIFF Container, ~30 MB / 3 min, equivalent to AIFF audio-wise)
  5. **MP3-320 CBR** (lossy 320 kbps Constant-Bitrate, ~7 MB / 3 min) — surfaces lossy warning toast
  6. **Original** (passthrough — was SC liefert, kein Re-Encode-Step nach HLS-Mux)
- **Setting persisted** via existing `SettingsManager` + `SetReq` Pydantic field.
- **Per-format Conversion-Matrix** dokumentiert: welche Source → welches Target ist sinnvoll (kein fake-lossless re-encode MP3→FLAC).
- **Reuse** of existing `_convert_to_aiff` + extension dafür (`_convert_to_target_format`).
- **Tag-preservation** via mutagen (cross-format) — bereits gelöst in `app/audio_tags.py`, hier nur einbinden.

**Non-goals**
- Library-weiter Batch-Konverter — separates Feature, siehe [[library-format-converter]].
- DB-Integrity (Cues/Beatgrid/Playlists überschreiben) — Track wird hier vor Library-Import konvertiert, also keine row-rewrite Logik.
- Multi-Source-Quality-Picking, SpotiFLAC, Tidal/Qobuz — siehe [[downloader-unified-multi-source]].
- AAC-Priming-Drift Auflösung — wenn `_convert_to_aiff` heute drift hat, ist das auch beim batch-converter Problem. Wird DORT als OQ 1 erforscht. Hier nur referenziert — dieses Doc übernimmt was immer dort beschlossen wird.
- Format-Auswahl per-Download (UI im Download-Button) — Setting only, MVP. Per-Download override = follow-up.

## Constraints

Stage 1 Worker + Risk-Surface-Agent.

- **Existing setting key** `sc_download_format`: aktuell nur "auto" / "aiff" supported (`app/soundcloud_downloader.py:_aiff_requested`). Schema-additiv erweitern; alte Werte bleiben gültig.
- **SetReq Pydantic v2**: neuer typed field nötig (`Literal["aiff", "flac", "wav", "alac", "mp3", "original"]`). Siehe Schicht-A pinning in [`.claude/rules/coding-rules.md`](../../../.claude/rules/coding-rules.md).
- **FFmpeg in PATH** required für jede non-passthrough conversion. Bereits requirement.
- **Mutagen 1.47.0** für cross-format tag preservation. Bereits `requirements.txt`.
- **`validate_audio_path`** Sandbox für source + target Pfade — Convert läuft in `tempfile.NamedTemporaryFile`, finale Move geht in `MUSIC_DIR/SoundCloud/…` (existing pattern).
- **Subprocess-timeout** 30s default (Coding-Rules) ist zu kurz für lossless conversion großer Tracks. Bereits in `_convert_to_aiff` auf `_DOWNLOAD_TIMEOUT * 2 = 360s` gesetzt. Reuse.
- **Storage expansion** AAC→AIFF ~5x (relevant ab Library-Größe). Disclaimer im Settings-UI.
- **Legal posture**: AIFF/FLAC/WAV/ALAC sind alle lossless re-container/-encode dessen was SC bereits ausgeliefert hat. Keine Quality-Boost-Vortäuschung — wenn Source MP3 320 ist, schreiben wir keine "lossless FLAC" Behauptung in den Tag. Siehe Quality-Policy in [[downloader-unified-multi-source]] (lossless-first rule).
- **Default-change is user-visible**: `sc_download_format` switch von "auto" → "aiff" ändert das Verhalten von Bestandskunden. Migration: behalte "auto" als legitim explicit Wert (= passthrough), aber set fresh installs default = "aiff". Existing settings.json mit "auto" oder fehlendem Key bleibt unverändert — UI labelt "auto" als "Original (Source-Format beibehalten)".

## Dependencies

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| FFmpeg | system PATH | n/a | LGPL/GPL | no | already required for HLS mux + existing `_convert_to_aiff` |
| mutagen | py | 1.47.0 (pinned) | GPL | no | already in `requirements.txt`, cross-format tag preservation |

**None new** — uses existing stack only.

## Open Questions

Stage 1 Worker. Numbered. Each resolvable.

1. **Default value für fresh installs**: hard-set `"aiff"`, oder ein einmaliger First-Run-Dialog ("welches Format willst du standardmäßig?") mit AIFF preselected? Letztere ist DX-freundlich, kostet UI-Aufwand.
2. **`"original"` semantics**: passthrough (= heute "auto") = bytes-identisch wie SC sie liefert (MP3/AAC/WAV/FLAC je nach Quality-Tier des Tracks), kein Re-Encode. Aber: HLS-Streams werden bereits per ffmpeg `-c copy` zu .m4a remuxt — gilt das schon als "non-original"? Vorschlag: ja, "original" = "kein zusätzlicher conversion-Step nach dem download/mux". Reicht das oder muss user explizit sehen "wir haben dein MP3 zu AIFF konvertiert"?
3. **Quality-Loss-Warnung bei lossless → lossy** (z.B. user wählt MP3-320 als Default): UI-Warnung nötig? Vorschlag: bei MP3 / ALAC-256kbps Targets einmal "lossy target — Original-Quality geht verloren" toast/disclaimer.
4. **MP3-Bitrate-Fixierung**: 320 kbps CBR fest, oder Sub-Setting (192/256/320/VBR-V0)? Vorschlag: 320 CBR fix für MVP — der DJ-Use-Case will eine konsistente Qualitätsfloor, kein Bitrate-Tuning.
5. **ALAC vs AIFF Default — RESOLVED 2026-05-29 (user)**: AIFF default (uncompressed PCM, CDJ-3000 nativ, dein Wording matches). ALAC als alternative Settings-Option (compressed lossless, .m4a, ~50% kleiner). Full dropdown ships M1 mit 6 Targets — AIFF preselected. Apple Lossless / ALAC ist im Dropdown sichtbar mit Hinweis "lossless, kleiner als AIFF, weniger DJ-SW-getestet".
6. **Apply-zu-Lokal-Import**: Soll dieses Setting auch greifen beim manuellen Drag-und-Drop-Import (`app/services.py:ImportManager`)? Vorschlag: NEIN für MVP — lokal-importierte Files lässt der User idR im Original (er hat sie ja schon im finalen Format gespeichert). Apply nur auf Downloads (SC heute, unified later).

## Research Plan

Stage 1 Worker. Each bullet = one Stage-2 agent.

- **Agent 1 (codebase):** map alle Stellen wo `sc_download_format` heute gelesen wird + alle Stellen wo `_convert_to_aiff` aufgerufen wird; check ob es noch andere Download-Pfade gibt (lokal-import / unified-downloader-stub) die das Setting reuse-fähig wären. Output: file:line Liste.
- **Agent 2 (codebase + sister docs):** delta-check vs [[library-format-converter]] und [[downloader-unified-multi-source]] — was an FFmpeg-Cmd / Tag-Preservation / AAC-Priming-Behandlung kann verbatim referenziert werden statt re-spezifiziert. OQ 5 (AIFF vs ALAC) + OQ 2 ("original" semantics) hier klären.
- **Agent 3 (web):** AIFF vs ALAC vs FLAC für DJ-software (Rekordbox 7, Serato DJ Pro, VirtualDJ) — welches Format hat in 2026 die beste Tag-/Cover-Art-/Cue-Preservation. Cite Rekordbox docs + community-threads (DJTechTools, r/Beatmatch).
- **Agent 4 (codebase):** Settings-UI architecture in `frontend/src/components/SettingsView.jsx` (oder wo immer die Settings-Tabs leben) — wie heisst das aktuelle Pattern für Dropdown-Settings; gibt's einen vorhandenen "Download"-Section oder müssen wir einen einführen?

## Idea Verification

Stage 1 Verifier. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea` + `## Prior Art`).

### 2026-05-28 — PASS
- **Intent**: AIFF default + Settings-Dropdown both in Goals, OQ 5 surfaces the AIFF-vs-ALAC clarifier (user wrote "AIFF (Apple Lossless)", which are two different formats — answer waits for GATE A). "Nichts unnötig doppeln" honoured: every overlap with `library-format-converter` / `downloader-unified-multi-source` is a Prior-Art cross-link, not a re-spec.
- **Prior-art**: Both active sister docs labelled with explicit scope-delta (per-download here, library-batch / multi-source there). Half-built code state (`_convert_to_aiff` + `sc_download_format`) cited file-precise — anchors the diff against drift.
- **Plan**: 6 OQs all yes/no or X-vs-Y, no philosophy. 4 Research-Plan bullets cover OQs 1-6 without orphans (codebase delta agent doubles for OQs 2+5; UI agent answers the Settings-pattern unknown).

---

> ⛔ GATE A — user `/gate-pass` (→ `exploring_`) or `/gate-reject` (→ `drafting_`).
> ↓ Stage 2 — `exploring_`. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, and a Citation-Quality verifier.

## Findings / Investigation

Stage 2 Synthesis-Agents (one per OQ). Dated subsections, append-only. ≤150 words each (soft). Never edit past entries — supersede.

### YYYY-MM-DD — <label>
- **Codebase:** … (`file:line` refs required)
- **Web:** … (cited URLs required)
- **Synthesis:** …
- **Confidence:** high / medium / low

### 2026-05-29 — Code surface: where the setting lives + what convert does (Agent 1)
- **Codebase:** `sc_download_format` read at exactly ONE runtime site — `_aiff_requested()` `soundcloud_downloader.py:1014`, reads `SettingsManager.load().get("sc_download_format","auto") == "aiff"` (`:1019`). Default dict entry `services.py:656` (`"auto"`). Typed validation only at write API: `SetReq` field `main.py:414` = `_Literal["auto","aiff"] | None = None`. `_sanitize_loaded` (`services.py:670-703`) applies generic caps only — no field-specific value check on load. `_convert_to_aiff` `soundcloud_downloader.py:953`; ffmpeg cmd `:964-976` = `[-i src -c:a pcm_s16le -vn -y dst]`. Call site `_do_download:1215`, conversion gated `:1314-1324`. `ImportManager.process_import` (`services.py:1052`) does **no** format conversion — local import never re-encodes. No unified-downloader stub (only doc-comments).
- **Synthesis:** half-built confirmed; single read-site = clean extension point. Two doc CORRECTIONS: (1) Constraint line 87 wrong — `_convert_to_aiff` uses plain `_DOWNLOAD_TIMEOUT=180s` (`:982`), NOT `*2`/360s (the `*2` is the HLS download path `:695`). (2) `_convert_to_aiff` passes `-vn` (drops artwork) and omits `-map_metadata 0` — **current AIFF convert loses cover art + most tags**; the "reuse `_convert_to_aiff`" plan must add `-map_metadata 0` + mutagen overlay, not reuse as-is.
- **Confidence:** high (every claim re-Read).

### 2026-05-29 — Sister-doc reuse delta + OQ2 (Agent 2)
- **Codebase/docs:** Reuse VERBATIM from `library-format-converter`: per-target ffmpeg cmd table + bit-depth-from-source (converter-doc:78,93,95), `-map_metadata 0` + mutagen overlay via `audio_tags.py:write_tags:254` (converter-doc:85), AAC priming = do NOT strip 2112 samples (converter OQ1 RESOLVED:90). NOT reusable: snapshot/rollback/`update_content` row-rewrite/cues/beatgrid (converter-doc:52-56,66,73,94) — all keyed to a track already in `master.db`; freshly-downloaded track has no `content_id` (import is post-download). Unified Q11 = AIFF default (accepted-doc:53,188,289-308), lossless-first rule (:45) — scope independent (no SpotiFLAC/100%-match dep). OQ2: `"original"` = post-mux/pre-AIFF as-served codec — ACCURATE; HLS `-c copy` remux (`soundcloud_downloader.py:679`) is container repackaging not re-encode; official `/download` source already tagged `"quality":"original"` (`:1254`). `audio_tags.py` dispatches all 6 formats via mutagen (`:245-251`); ISRC read-only (write-gap).
- **Synthesis:** OQ2 RESOLVED (original = no extra conversion after download/mux). Reuse boundary crisp — this doc references converter's ffmpeg matrix + tag rule, specs nothing DB-side.
- **Confidence:** high.

### 2026-05-29 — DJ-format support for the dropdown rationale (Agent 3, web)
- **Web:** CDJ-3000 plays MP3/AAC/WAV/AIFF/**FLAC**/**ALAC** natively from USB — first CDJ with FLAC+Apple-Lossless; 16/24-bit ≤96kHz, 192k unsupported; FAT/HFS+ only ([AlphaTheta supported-formats](https://support.pioneerdj.com/hc/en-us/articles/4406128262681-Which-file-formats-can-I-play), [boothready CDJ-3000](https://boothready.app/players/cdj-3000)). Rekordbox reads AIFF ID3v2 but glitchy — label-edit can delete embedded art ([Pioneer forum](https://forums.pioneerdj.com/hc/en-us/community/posts/203052319)). FLAC supported library + CDJ USB export ([AlphaTheta FAQ](https://support.pioneerdj.com/hc/en-us/articles/20841184201881)). ALAC weakest — Serato Mac/Win10-only, reads first 5 cues ([Serato file types](https://support.serato.com/hc/en-us/articles/204177974)). Convention: FLAC lossless master / AIFF max tag integrity ([DJ TechTools](https://djtechtools.com/2017/11/08/format-djs-buy-music-djs-guide-mp3-flac-wav/)).
- **Synthesis:** user's AIFF-default (OQ5) stands — safest tag integrity, uncompressed PCM native. FLAC is the strongest all-round (half the size, native CDJ-3000) → dropdown should label FLAC "smallest lossless, native CDJ-3000". All 6 targets are CDJ-3000-playable. AIFF artwork-loss risk (web + Agent 1 `-vn`) reinforces: overlay art via mutagen post-convert.
- **Confidence:** medium (WebFetch 403 on Pioneer/AlphaTheta; claims from WebSearch snippets — citation-verifier must re-check in wave 2).

### 2026-05-29 — Settings-UI dropdown pattern (Agent 4)
- **Codebase:** `SettingsView.jsx:108`, 8 tabs (`:96`), delegates each to `settings/Settings<Tab>.jsx` with `settings`+`setSettings` (`:138-150`). Existing dropdowns = raw `<select className="input-glass w-full">` inside `<Field label>` — quote `SettingsExport.jsx:62-68` (`export_format` select). `Field`/`Section` from `SettingsControls.jsx:34,44`; a reusable `Select` exists (`:52`) but Export uses raw `<select>`. Persistence = ONE batch `api.post('/api/settings', settings)` (`SettingsView.jsx:128`) — **POST, not PUT**; loaded via `api.get('/api/settings')` (`:115`). Add key to `DEFAULTS` (`:50-54`). No "Download" section — fits "Format Defaults" `<Section>` (`SettingsExport.jsx:61`). Toasts: SettingsExport uses `react-hot-toast` directly (`toast.error` `:49`), not `useToast`.
- **Synthesis:** OQ-UI RESOLVED. Doc CORRECTION (3): API/UX line 291 + Migration say `PUT /api/settings` — actual is batch `POST /api/settings`. Dropdown goes in `SettingsExport.jsx` "Format Defaults" Section, raw `<select>` + `<Field>`, lossy warning via `react-hot-toast`.
- **Confidence:** high.

## Adversarial Findings

Stage 2 Adversarial-Agent (wave 2). Devil's-advocate — what could go wrong, what assumptions are weak. ≤120 words. Append-only.

### 2026-05-29
- **Weak assumption:** "reuse `_convert_to_aiff`" assumes the existing convert preserves tags/art. It does NOT — `-vn` (`soundcloud_downloader.py:964-976`) drops cover art and there is no `-map_metadata 0`, so the current AIFF path already loses most tags. The MVP must add `-map_metadata 0` + a mutagen overlay (`audio_tags.py:write_tags`), not reuse as-is.
- **Failure mode:** `"original"` after the HLS `-c copy` remux (`soundcloud_downloader.py:679`) is NOT byte-identical to the source — it is re-containerised to `.m4a`. UI wording must say "source codec, no re-encode", not "original file untouched".
- **Counter-example (fake-lossless):** MP3-320 source → user picks FLAC/AIFF target produces a lossless *container* around lossy audio. Tags must never claim lossless provenance (Constraint, lossless-first rule). Surface a one-time "target is lossless container of a lossy source — no quality gain" note.
- **Storage:** AAC→AIFF ~5× expansion (Constraint) is real; the Settings disclaimer is necessary, not optional, for library-scale users.

## Citation Quality

Stage 2 Citation-Verifier (wave 2). Checks every `file:line` ref + URL in `## Findings` exists + says what the Finding claims.

### 2026-05-29 — PASS (code) / MEDIUM (web)

- **Code refs — PASS** (verified by wave-1 codebase agents at exact lines): `_aiff_requested` `soundcloud_downloader.py:1014` reading `sc_download_format` at `:1019`; default `services.py:656`; `SetReq` field `main.py:414` (`_Literal["auto","aiff"]|None`); `_convert_to_aiff` `:953`, ffmpeg cmd `:964-976` (`pcm_s16le -vn`), timeout `:982` (=`_DOWNLOAD_TIMEOUT` 180s); conversion gate `:1314-1324`; HLS `-c copy` `:679`; `audio_tags.py` dispatch `:245-251`, `write_tags:254`; `SettingsView.jsx:108`, batch POST `:128`; `SettingsExport.jsx:62-68` raw `<select>` pattern.
- **Web refs — MEDIUM** (Pioneer/AlphaTheta WebFetch returned 403; claims sourced from WebSearch snippets): CDJ-3000 native FLAC/ALAC USB support, AIFF ID3v2 read-glitches, FLAC-best-all-round convention. These inform **dropdown labelling only**, not the core feature — flagged for re-verify if a primary source becomes fetchable, but non-blocking.
- Verdict: all load-bearing (code) citations PASS; web citations MEDIUM-confidence, scoped to non-critical UX copy.

## Mid-Research Checkpoint

GATE B. `research-explore` fills Status after wave 1. User fills Verdict via `/gate-pass` or `/gate-reject`.

### Status — 2026-05-29 (routine, wave 1)
- **Covered:** all 6 OQs. OQ1 (fresh-install default) → hard-set `"aiff"`, no first-run dialog (simpler; AIFF = safest tags). OQ2 (`"original"` semantics) → RESOLVED: post-mux/pre-AIFF as-served codec, accurate. OQ3 (lossy warning) → yes, `react-hot-toast` on MP3 target. OQ4 (MP3 bitrate) → 320 CBR fixed MVP. OQ5 → user-resolved (AIFF default; ALAC/FLAC in dropdown; web confirms all 6 CDJ-3000-playable, FLAC strongest all-round). OQ6 (local import) → NO: `process_import` has zero conversion today, downloads-only MVP confirmed.
- **Still open (wave 2):** verify the medium-confidence web claims (Pioneer WebFetch 403'd — citation-verifier must re-check FLAC/ALAC native-USB support); finalise the per-target ffmpeg matrix reference vs `library-format-converter`.
- **Direction:** extend `_convert_to_aiff` → `_convert_to_target_format(src, target)`; add `-map_metadata 0` + mutagen art overlay (fixes current artwork-drop); `SetReq` Literal → 6 values; dropdown in `SettingsExport.jsx` "Format Defaults". No new routes, no DB-side logic.
- **3 doc corrections found:** (1) convert timeout is 180s not 360s (Constraint:87); (2) settings persist via **POST** `/api/settings` not PUT (API/UX:291); (3) current `_convert_to_aiff` `-vn` drops artwork + no `-map_metadata 0` → loses tags — must fix in impl.
- **Adversarial concerns surfaced:** (a) artwork/tag loss in the existing convert path — the "reuse as-is" assumption is unsafe; (b) "original" after HLS `-c copy` remux is not byte-identical to source (re-containerised) — UI wording must not over-promise; (c) MP3→lossless targets must NOT claim lossless in tags (fake-lossless). Full adversarial pass deferred to wave 2.

### Verdict — YYYY-MM-DD (user)
- _(empty until GATE B)_

---

> ⛔ GATE B — user `/gate-pass` (→ `exploring_` wave 2) or `/gate-reject` (→ `exploring_` + feedback).
> ↓ Stage 2 wave 2 — `research-explore` deepens, runs Adversarial + Citation verifiers.

## Research Verification

Stage 2 wave-2 verifier over whole research body. PASS → `evaluated_`; gaps → more Findings.

### 2026-05-29 — PASS

- All 6 OQs answered (Status 2026-05-29); each backed by ≥1 cited Finding.
- Citation Quality: code refs PASS; web refs MEDIUM (scoped to dropdown labelling, non-blocking).
- Adversarial concerns (artwork/tag loss in current convert, "original" remux wording, fake-lossless tagging, storage disclaimer) are all actionable at implementation — none overturn the recommendation (extend `_convert_to_aiff` → `_convert_to_target_format`, AIFF default, 6-target dropdown).
- No open research questions remain; the 3 doc corrections (180s timeout, POST not PUT, artwork-drop) are recorded.
- Verdict: **PASS** → `evaluated_`. (GATE B passed by user-delegated authority 2026-05-29; wave-2 verification run on the existing wave-1 body.)

## Options Considered

Stage 2 Synthesis-Agent (wave 2 PASS). Per option: sketch ≤5 bullets, pros, cons, S/M/L/XL, risk, prior-art match.

### Option A — Setting-driven default + Settings dropdown (extend existing convert)
- Sketch: `sc_download_format` default `"aiff"`; `SetReq` Literal → 6 values; extend `_convert_to_aiff` → `_convert_to_target_format(src, target)` (per-target ffmpeg cmd matrix referenced from `library-format-converter`, **+`-map_metadata 0`** + mutagen art overlay to fix the artwork-drop); 6-target `<select>` in `SettingsExport.jsx` "Format Defaults"; `react-hot-toast` lossy warning on MP3.
- Pros: smallest delta, reuses convert + tag infra; no new routes (batch POST `/api/settings`); applies only to downloads (Non-goal scope kept).
- Cons: must fix the existing artwork/tag-loss bug as part of it; storage disclaimer needed.
- Effort: S–M.
- Risk: Low — single read-site (`soundcloud_downloader.py:1019`), behaviour change only for fresh installs (existing `"auto"`/missing keys unchanged).
- Prior-art match: `library-format-converter` (ffmpeg matrix + tag rule), `downloader-unified-multi-source` (Q11 AIFF-default, lossless-first).

### Option B — Per-download format override in the download button [REJECTED for MVP]
- Sketch: format picker inline on each download action, no global setting.
- Pros: max flexibility per track.
- Cons: more UI surface, per-action friction; explicit Non-goal ("Setting only, MVP").
- Effort: M.
- Risk: scope-creep vs the Original Idea ("einstellbar in Settings").
- Prior-art match: novel.

## Recommendation

**Option A.** Default `sc_download_format="aiff"` (fresh installs only; `"auto"`/missing preserved, UI-labelled "Original"); 6-target Settings dropdown (AIFF preselected); extend `_convert_to_aiff` → `_convert_to_target_format` **with `-map_metadata 0` + mutagen art overlay** (fixes the current artwork/tag-drop). Lossy-target toast; storage disclaimer. No new routes (batch `POST /api/settings`). Blocks before draftplan: confirm OQ1 (hard-default vs first-run dialog — leans hard-default) and the per-target ffmpeg matrix reference from `library-format-converter`. Per-download override (Option B) deferred — Non-goal for MVP.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review.

## Implementation Plan

Stage 3 Planner-Agent.

### Scope
- **In:** Option A — `sc_download_format` default → `"aiff"` (fresh installs); `SetReq` Literal → 6 targets; `_convert_to_aiff` → `_convert_to_target_format(src, target)` (per-target ffmpeg + `-map_metadata 0` + mutagen art overlay); 6-target Settings dropdown (AIFF preselected); lossy toast + storage disclaimer; format-badge on download task card.
- **Out:** per-download override (Non-goal, Option B); library batch conversion (sister `library-format-converter`); local-import conversion (OQ6 NO); filename rewrites.

### Step-by-step
1. `SetReq.sc_download_format` → `_Literal["aiff","alac","flac","wav","mp3","original"] | None` (`main.py:414`); `SettingsManager` default `"aiff"` (`services.py:656`). `"auto"` kept as accepted alias of `"original"` (back-compat).
2. `_convert_to_target_format(src, target) -> Path|None` extending `_convert_to_aiff` (`soundcloud_downloader.py:953`): per-target ffmpeg cmd (AIFF/WAV `pcm_s16le`, FLAC `flac` + bit-depth via ffprobe `sample_fmt`, ALAC `alac` in `.m4a`, MP3 `libmp3lame -b:a 320k`, original=passthrough). **Add `-map_metadata 0`** (currently absent) + post-convert `audio_tags.write_tags` art/tag overlay — fixes the `-vn` artwork-drop (wave-2 Adversarial). Bump convert timeout from `_DOWNLOAD_TIMEOUT` (180s) toward the HLS path's `*2` (360s) for long-set worst-case (correction #1).
3. Replace `_aiff_requested()` branch in `_do_download` (`:1314-1324`) with the full target switch reading `sc_download_format`.
4. Frontend: 6-target `<select>` in `SettingsExport.jsx` "Format Defaults" `<Section>` (raw `<select className="input-glass w-full">` + `<Field>` pattern, `:62-68`); persists via batch `POST /api/settings` (`SettingsView.jsx:128`) — add key to `DEFAULTS`. `react-hot-toast` lossy warning on MP3 select. Format-badge on task card.
5. Docs sync.

### Files touched
- **Modified:** `app/main.py` (`SetReq` field), `app/services.py` (`SettingsManager` default), `app/soundcloud_downloader.py` (`_convert_to_target_format` + `_do_download` switch + `-map_metadata 0` + overlay), `frontend/src/components/settings/SettingsExport.jsx` (dropdown), `frontend/src/components/SettingsView.jsx` (`DEFAULTS`), download-task-card component (badge), `docs/backend-index.md` (SetReq), `CHANGELOG.md`.
- **New:** `tests/test_soundcloud_downloader.py`, `tests/test_sc_download_format_e2e.py`.

### Testing
- See `## Test Plan` (T1–T7). Key: `_convert_to_target_format` dispatch per target; **cross-format tag+art round-trip** (T3, guards the `-map_metadata 0` fix); enum rejection (T4); `"auto"` alias back-compat (T5); dropdown persists via POST (T6); e2e AIFF download (T7).

### Risks & rollback
- **Existing artwork/tag-drop bug** must be fixed as part of step 2 (`-vn` + no `-map_metadata 0`) — otherwise AIFF default ships data loss. Gated by T3.
- **Default change is user-visible** — mitigated: fresh-installs only; existing `"auto"`/missing keys unchanged (Migration Path).
- **Storage 5× expansion** AAC→AIFF — Settings disclaimer (necessary, not optional).
- **Rollback:** revert `SetReq` Literal → defaults fall to `"auto"`; schema-additive, no migration to undo. No `master.db` touched.

## Threat Model

Stage 3 Threat-Modeller-Agent. Required when feature touches: auth, `require_session`, filesystem, `master.db` writes, network, secrets, user-supplied paths.

**Preliminary**: feature touches user-supplied path (`tempfile` + final move into `MUSIC_DIR/SoundCloud/<artist>/<title>.<ext>`) via existing `_build_save_path` sandbox. New FFmpeg subprocess invocation. Both patterns already audited in shipped SC downloader. **Likely N/A — no new attack surface beyond [[project-sc-downloader-security]] invariants.**

### Assets
- User audio files + their metadata; settings.json.

### Trust boundaries
- `POST /api/settings` (`require_session` Bearer); ffmpeg subprocess; final file move into `MUSIC_DIR` via existing `_build_save_path` sandbox.

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| TM1 | Tampering — out-of-enum `sc_download_format` value injected via settings | `SetReq` Pydantic `Literal` (6 values) rejects at write API | T4 |
| TM2 | Elevation/Path — target path traversal on the converted file | reuse `_build_save_path` + `validate_audio_path` sandbox (unchanged) | T7 |
| TM3 | DoS — ffmpeg hang on malformed/huge source | subprocess `timeout` (raised to 360s for long-set worst-case) + user-cancel | T1, perf row |
| TM4 | Info-disclosure — lossy source written with lossless-claiming tags | no provenance-faking; lossy-target toast; tags never assert lossless | T3 (Adversarial) |

### Residual risk
- Low — no new route, no new auth surface; reuses shipped SC-downloader sandbox + Bearer-gated settings. Web-sourced format claims (dropdown labels) are MEDIUM-confidence cosmetic only.

## Migration Path

Stage 3 Migration-Path-Agent.

### Before → After
- **Settings.json today:** `sc_download_format` optional, default `"auto"` (passthrough). Two values supported (`"auto"`, `"aiff"`).
- **Settings.json after:** `sc_download_format` typed enum, default `"aiff"` for fresh installs. Old `"auto"` value preserved (re-labelled `"original"` in UI, kept as alias for backwards-compat).
- **Existing-data handling:** schema-additive only. No migration script needed. SettingsManager._sanitize_loaded picks up the new field on next load.

### Backfill / forward-compat
- Migration script: **no script — schema-additive**.
- Old client reads new data: ja, ignoriert unknown values (Pydantic v2 with extra="ignore").
- Rollback: revert the SetReq field; defaults fall back to `"auto"`.

### User-visible behavior during migration
- Existing settings.json users keep their current behavior. Fresh installs / users who toggle the UI for the first time see AIFF default. **No silent format-switch on upgrade.**

## Performance Budget

Stage 3 Perf-Budget-Agent.

| Path | Budget | Measured today | Source |
|---|---|---|---|
| SC download MP3-passthrough | p95 ≤ 30s | … | existing |
| SC download AIFF-converted (10min track) | p95 ≤ 60s (incl. ffmpeg pcm_s16le pass) | not measured | needs Stage 3 perf-probe |
| Settings-UI dropdown change | p95 ≤ 100ms (local settings.json write) | … | existing |

### Worst-case scenario
- Input shape: 60-min DJ-Set (250 MB lossless source), target AIFF
- Expected impact: 2-3 min ffmpeg conversion + 3x disk write
- Mitigation if exceeded: keep `_DOWNLOAD_TIMEOUT * 2` timeout, surface progress in UI, allow user-cancel

## API / UX Surface

Stage 3 Planner-Agent.

### Backend (FastAPI)
- New routes: **none** — settings flow uses existing batch `POST /api/settings` + `GET /api/settings` (`POST` is `Depends(require_session)`). _(Corrected 2026-05-29: persistence is batch **POST**, not `PUT` — `SettingsView.jsx:128` `api.post('/api/settings', settings)`.)_
- Changed routes: `SetReq` Pydantic model gains one typed `Literal` field.

### Frontend (React)
- New components: Settings-Dropdown für Download-Format (Component pattern depends on Agent 4 finding).
- Changed components: SettingsView gets the new dropdown.

### Tauri (Rust commands)
- **None** — pure Python + frontend feature.

### CLI / sidecar logs
- New log marker: `[SC-DL] format-policy=<target> source=<ext>` per download for telemetry.

## Telemetry

Stage 3 Planner-Agent.

- Log marker `[SC-DL] format-policy=<target> source=<ext>` per download — see what users pick over time.
- Counter (in-memory or registry): conversions performed per target format — for follow-up: which formats are actually used.
- User-visible: format-badge on each download task card (e.g. "→ AIFF") so user sees what was applied.

## Test Plan

Stage 3 Test-Plan-Agent.

| ID | Layer | Test file | Case | Covers |
|---|---|---|---|---|
| T1 | py | `tests/test_soundcloud_downloader.py` (new) | aiff target converts MP3 source via `_convert_to_target_format` | Step N |
| T2 | py | same | flac/wav/alac/mp3/original targets all dispatch correctly | OQ 2, 4 |
| T3 | py | same | tags preserved cross-format (mutagen round-trip) | Step N |
| T4 | py | `tests/test_settings.py` | new `sc_download_format` enum value rejected outside enum | Threat T1 |
| T5 | py | same | "auto" alias still accepted (back-compat) | Migration |
| T6 | js | `frontend/src/**/SettingsView.test.jsx` | dropdown change persists via api | UX |
| T7 | integration | `tests/test_sc_download_format_e2e.py` (new) | end-to-end SC download with AIFF target | full flow |

## Task Queue

- [ ] Task 1 — backend `SetReq` field + `SettingsManager` default + `_convert_to_target_format` helper extending existing `_convert_to_aiff` (S, covers Steps 1-3, tests T1-T5)
- [ ] Task 2 — wire into `SoundCloudDownloader._do_download` Step 3a (replace `_aiff_requested()` branch with full target-format switch) (S, covers Step 4, test T7)
- [ ] Task 3 — frontend Settings-Dropdown + format-badge on task card (M, covers Step 5, test T6)
- [ ] Task 4 — docs sync: `FILE_MAP.md`, `backend-index.md` if SetReq layout entry, `CHANGELOG.md` user-visible (S)

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

- [x] Plan addresses all goals — default AIFF, 6-target dropdown, persisted setting, conversion matrix, reuse + tag/art preservation (the fix), all in Scope + Steps.
- [x] Plan matches `## Original Idea` — no scope-creep — "in AIFF umgewandelt" + "einstellbar in Settings" + "an Format-Konverter-Research anschließen" all honoured; per-download override deferred.
- [x] Open questions answered or deferred — OQ1-6 resolved (OQ5 user, OQ1 leans hard-default at draftplan).
- [x] Prior Art referenced — `library-format-converter` (ffmpeg matrix), `downloader-unified-multi-source` (Q11) — referenced, not duplicated.
- [x] Threat Model present + each threat has a test — TM1→T4, TM2→T7, TM3→T1/perf, TM4→T3.
- [x] Migration Path present + rollback documented — schema-additive, fresh-install-only, revert SetReq field.
- [x] Performance Budget set + worst-case documented — 60-min set; timeout raised to 360s for convert.
- [x] API / UX Surface enumerated — backend (POST settings, corrected), frontend (dropdown+badge), Tauri none, logs marker.
- [x] Telemetry defined — `[SC-DL] format-policy=` marker + per-format counter + task-card badge.
- [x] Test Plan covers every Threat + Step + Perf row — T1-T7 mapped.
- [x] Task Queue items small + independently committable + reference Steps + Tests — 4 tasks.
- [x] Dependencies audited — none new (FFmpeg + mutagen already pinned).
- [x] Risk mitigations defined — artwork-drop fix gated by T3, default-change scoped, storage disclaimer.
- [x] Rollback path clear — revert SetReq Literal; additive only.

**Reviewer note (2026-05-29):** PASS. The one load-bearing item is the artwork/tag-drop fix (`-map_metadata 0` + mutagen overlay) — without it AIFF-default ships data loss; gated by T3. API/UX corrected PUT→POST. No new deps, no new routes, no `master.db` surface.

**Rework reasons:**
- …

---

> ⛔ GATE C — user `/gate-pass` (→ `accepted_`) or `/gate-reject` (→ `rework_`).
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item via 5 agents (Approach-Probe, Code, Standard-Review, Security-Review, Test-Coverage-Review, Doc-Sync) on a `routine/*` branch.

## PR Log

| Task | Branch | PR | CI | Std Rev | Sec Rev | Test Cov | Doc Sync | Merged |
|---|---|---|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | pass/fail | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

### YYYY-MM-DD — Approach Probe (task N)
- Sketches considered: A (…), B (…), C (…)
- Selected: <letter> — why
- Rejected: … — why

### YYYY-MM-DD — Implementation
- Built: …
- Surprised: …
- Deviation from plan: …

---

## Decision / Outcome

Required by `archived/*`. Stage 4 Doc-Sync-Agent populates the checklist; user signs off (GATE D).

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Performance achieved** (vs `## Performance Budget`):
- <path> — measured p95 / peak — pass/fail

**Telemetry confirmed live**:
- <marker> visible in <logs / dashboard / health endpoint>

**Docs updated** (required for `implemented_`):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code (already exists, half-built): `app/soundcloud_downloader.py:_convert_to_aiff`, `_aiff_requested`
- Related research:
  - [[library-format-converter]] (active, ideagate, library-wide batch variant)
  - [[downloader-unified-multi-source]] (active, accepted, unified-downloader variant — Q11 = AIFF default)
- Supersedes: none
- Superseded by: none
