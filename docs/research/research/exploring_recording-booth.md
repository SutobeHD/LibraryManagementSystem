---
slug: recording-booth
title: Recording Booth
owner: tb
created: 2026-06-01
last_updated: 2026-06-01
tags: []
related: []
supersedes: []
superseded_by: []
---

# Recording Booth

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-06-01 — `research/idea_` — created from template
- 2026-06-01 — `research/drafting_` — promoted from idea_ (entered Stage 1)
- 2026-06-01 — `research/exploring_` — drafted (scout+prior-art+risk-surface+worker+verifier), idea-verify PASS → ready for explore
- 2026-06-01 — `research/exploring_` — explore phase 1 done (tiered codebase+web+synthesis × 6 aspects); BLOCKER surfaced: PDL = Export-mode only, no live track-id in Performance mode

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

Ich will eine möglichkeit haben meine Dj sets aufzunehmen, ich möchte aber das es nicht nur simple audio aufnahmen sind. Ich möchte das der Controller erkannt wird, ein video erstellt wird, welches zeigt was der Dj am controller macht. Also ich will quasi ein Outline bild von dem controller und dann sollen dort die Fader/buttons/etc angezeigt werden und ganz wichtig soll gezeigt werden was der dj macht. wenn er bei einem die Highs raus nimmt dann soll das im video auch so dargestellt werden yk. Dazu möchte ich auch das In einer Datei fest gehalten wird, wann der dj was wie bewegt/genutzt hat, mit der Datei soll man dann genau das set im nachhinein nachmachen können per automation, das setzen wir aber nicht um! Ich will aber auch das die Tracks etc und deren lautstärke pro sekunde oder so festgehalten wird yk

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

**None — greenfield.** No prior/active research doc covers DJ-set audio recording, controller MIDI/HID capture, controller-outline video, control-timeline/replay file, or per-second track/volume logging (Agent P swept 8 archived + 14 active docs).

- **Incidental infra only (no concept overlap):** [evaluated_library-format-converter.md](evaluated_library-format-converter.md) + [accepted_download-format-setting.md](../implement/accepted_download-format-setting.md) touch ffmpeg/audio-export plumbing. Offline LUFS/RMS metering `app/analysis_engine.py:817-1129` — reuse for per-second level. Canvas viz `frontend/src/components/daw/DawTimeline.jsx` + `frontend/src/components/waveform/WaveformCanvas.jsx` — audio-only, reusable render pattern.
- **External precedent (verify Stage 2):** rekordbox/serato ship audio set-record + play-history; no known tool renders live *hardware-controller* movement video. Software-UI screen+audio capture (VirtualDJ/djay) ≠ hardware overlay.

## Problem

DJ wants sets recorded as more than audio. No tool captures *what the DJ physically does* on the controller (EQ/fader/button/jog moves) as a synced controller-outline video + machine-readable control timeline. Audio-only recordings lose every performance gesture + per-track level history. Cost: no shareable visual set, no replayable performance data.

## Goals / Non-goals

**Goals**
- Record set master audio (Rust `cpal` input stream).
- Capture controller control events (MIDI/HID), timestamped: faders, EQ, buttons, knobs, jogs.
- Render video: controller outline + controls animated to captured events (EQ-cut visibly shown).
- Write control-timeline file — format sufficient to drive *future* automated replay.
- Log track timeline + per-second volume/level.
- Target setup: USB controller + laptop; track info live from Rekordbox (Serato degraded/none).

**Non-goals**
- Automated replay/playback of the timeline (user: explicitly deferred — "das setzen wir aber nicht um").
- Standalone CDJ/DJM capture (mixer moves absent from any data stream).
- Multi-controller-model support at MVP — one model first.
- Live streaming/broadcast; editing the recorded video/timeline.

## Constraints

- **External APIs / rate limits:** Pro DJ Link = local UDP broadcast, no rate limit, but reverse-engineered protocol (breaks on Pioneer firmware changes). Serato = no open live API → live track-ID needs audio-fingerprint (heavy) → Rekordbox-only at MVP.
- **Data shape / on-disk:** control-timeline = new on-disk format (no `master.db`/ANLZ/PDB change). Recordings/video/timeline MUST write inside `ALLOWED_AUDIO_ROOTS` via `validate_audio_path` (`app/main.py:186,208`). Played-track logging to library DB acquires `_db_write_lock` (`app/database.py:22`).
- **Schicht-A pinning:** new cargo deps land with committed `Cargo.lock` (`.claude/rules/coding-rules.md:9`); py deps pinned `==X.Y.Z` (`coding-rules.md:7`); node `save-exact` + `lint:lockfile` (`coding-rules.md:8`).
- **Perf / capacity:** realtime audio-input + MIDI/HID capture = Rust audio thread (`coding-rules.md:21`); cpal `Stream` is `!Send` → confine to thread, no `unsafe impl Send` (`coding-rules.md:43`; pattern `src-tauri/src/audio/playback.rs:13-20`). Offline frame-render + ffmpeg mux off the realtime path.
- **Legal / compliance:** `resvg`/`usvg`/`tiny-skia` MPL-2.0 (file-level copyleft — OK, no app-wide infection); `python-prodj-link` Apache-2.0 but pulls PyQt5/PyOpenGL (GPL/commercial + bloat) → extract UDP-listener only.
- **Concurrency / security invariants:** start/stop-record routes = mutations → `Depends(require_session)` (`coding-rules.md:15`); live MIDI→UI stream over WebSocket → `require_session_ws` + `ws.close(1008)` (`docs/SECURITY.md:168`); ffmpeg subprocess always `timeout=` (`coding-rules.md:36`; callers `app/services.py`, `app/soundcloud_downloader.py`); Rust no `unwrap()`/`println!` in fallible/non-test paths (`coding-rules.md:44-45`).

## Dependencies

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| `cpal` | cargo | existing (~0.15) | Apache-2.0/MIT | no (in tree) | Audio **input** capture via `build_input_stream`; today output-only (`playback.rs`). No new dep to record audio. |
| `midir` | cargo | TBD (~0.10) | MIT | low | Realtime class-compliant MIDI input from controller. RtMidi-based, mature. |
| `hidapi` (hidapi-rs) | cargo | TBD (~2.6) | MIT | med | Pioneer proprietary-HID read (HID-mode controllers ≠ class-MIDI). Bundles C `hidapi`; prefer Windows-native backend. **Crux dep.** |
| `midly` | cargo | TBD (~0.5) | Unlicense/MIT | low | Write `.mid` control-timeline. no_std, zero-copy. |
| `resvg`+`usvg`+`tiny-skia` | cargo | TBD (~0.4x) | MPL-2.0 | med | Render controller-outline SVG → PNG frames offline. Pure-Rust, no system deps. Alt: JS/canvas headless render. |
| ffmpeg | system | existing | LGPL/GPL (binary) | no (in PATH) | Mux PNG frames + recorded audio → video. Reuse subprocess pattern. |
| `python-prodj-link` (sliced) | py | TBD | Apache-2.0 | **high** | Live track/now-playing from Rekordbox-as-PDL-node. Full lib pulls PyQt5/PyOpenGL/netifaces/Construct + reverse-engineered + single maintainer → extract only UDP listener. |
| `netifaces` | py | TBD | MIT | low | PDL needs host iface/broadcast to join UDP net (transitive of PDL path). |

`rekordcrate` (cargo) does **NOT** fit — parses static USB PDB/ANLZ exports, not live UDP Pro DJ Link. Noted so the planner doesn't mistake it for a PDL reader.

## Open Questions

1. **Co-read (the crux):** Can the app read the controller's HID input reports concurrently while Rekordbox/Serato owns the device on Windows (shared HID), or is the port exclusive — especially in class-MIDI mode? (spike on real DDJ; yes/no per HID-mode and per MIDI-mode)
2. **HID vs MIDI:** Does the target controller talk class-compliant MIDI or Pioneer proprietary HID to Rekordbox? Determines capture lib (`midir` vs `hidapi`) + decode effort.
3. **Control mapping:** Reuse community maps (Mixxx / DJ-software mappings) for the per-model control→value table (which CC/HID-byte = which fader/EQ/button), or hand-map one device?
4. **Track identity:** Does Rekordbox broadcast loaded-track + position over Pro DJ Link when driving a *controller* (not standalone)? Serato fallback = none vs fingerprint? (yes/no)
5. **Per-second volume:** capture as fader control-value, vs measured RMS/LUFS per second from recorded master (reuse `app/analysis_engine.py`), vs both?
6. **Video render path:** offline Rust `resvg`→PNG frames + ffmpeg mux, vs JS/canvas headless render, vs realtime canvas + MediaRecorder? (determinism/quality vs complexity)
7. **Timeline format:** Standard MIDI File (universal, replayable) vs custom JSON/JSONL (richer: tracks, levels) vs both (SMF + JSON sidecar)? Must suffice for *future* replay.
8. **Audio input source:** which device exposes the controller's master out for capture, and does cpal `build_input_stream` capture it on Windows WASAPI? (yes/no + device kind)
9. **PDL slimming:** can `python-prodj-link`'s UDP listener (Construct structs) be extracted without PyQt5/PyOpenGL? (yes/no)

## Research Plan

- Agent 1 (codebase + web): Controller co-read feasibility — Windows HID shared-access vs MIDI exclusivity; concurrent read while Rekordbox/Serato owns device; specify the hardware spike. [OQ1, OQ2]
- Agent 2 (codebase + web): Capture libs — `midir` vs `hidapi-rs` into `src-tauri/src/audio/`; cpal `build_input_stream` for master audio on Windows WASAPI; threading vs `!Send` Stream pattern. [OQ2, OQ8]
- Agent 3 (codebase + web): Control-mapping sourcing — community MIDI/HID maps (Mixxx etc.), per-model coordinate+CC tables; effort to model one controller. [OQ3]
- Agent 4 (codebase + web): Track identity — Rekordbox Pro DJ Link broadcast contents in controller mode; slim `python-prodj-link` UDP listener vs PyQt5 bloat; Serato fallback. [OQ4, OQ9]
- Agent 5 (codebase + web): Video pipeline — `resvg`/`usvg`→PNG+ffmpeg vs canvas/MediaRecorder; reuse offline metering for per-second level; determinism + perf. [OQ5, OQ6]
- Agent 6 (codebase + web): Timeline format — SMF vs JSON sidecar vs both; replay-sufficiency; schema for control events + track + level envelope. [OQ7]

## Idea Verification

### 2026-06-01 — PASS
- **Intent fidelity:** Goals cover all 5 idea elements (audio record · controller-move capture · outline video w/ animated EQ · replay-capable timeline file · track + per-second volume). Non-goals correctly defer replay (user's own words) + standalone CDJ. No scope-creep, no dropped intent.
- **Prior-art handling:** greenfield; incidental infra (ffmpeg/metering/canvas) flagged for reuse, not duplicated.
- **Research-Plan tractability:** OQ1–9 all resolvable (yes/no or X-vs-Y); every Research-Plan bullet maps to ≥1 OQ; no orphan questions.

---

> ↓ Stage 2 — `exploring_` (autonomous; no user gate). On Idea-Verifier PASS, `research-draft` advances `drafting_` → `exploring_` directly. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, a Citation-Quality verifier, and a Research-Verifier — one autonomous pass to `evaluated_`.

## Findings / Investigation

### 2026-06-01 — Co-read feasibility (Windows) [OQ1, OQ2]
- **Codebase:** greenfield — no HID/MIDI code anywhere. `!Send` Stream confinement pattern `src-tauri/src/audio/playback.rs:13-20`.
- **Web:** HID class driver buffers input reports in a per-handle ring buffer, shared-open allowed ([MS Learn](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/obtaining-hid-reports); [hidapi #302](https://github.com/signal11/hidapi/issues/302)); hidapi opens `FILE_SHARE_READ|WRITE` by default. WinMM MIDI input = single-client per driver unless vendor ships multi-client → "Device is busy" ([teragonaudio](http://midi.teragonaudio.com/tech/share.htm); [midiInOpen](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-midiinopen)). Fan-out: [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html).
- **Synthesis:** HID-mode = best odds (per-handle ring buffer → two readers *plausibly* both get reports; but MS doesn't guarantee duplicate delivery, and DDJ proprietary HID may use drainable feature-reports). MIDI-mode = single-owner → second open fails. loopMIDI fan-out still needs one app owning the hardware port → can't coexist with Rekordbox. Recommend HID shared-read primary path; **spike before committing.** SPIKE: real DDJ+Win11, Rekordbox owning device, run `hid_open`+`hid_read` loop, move fader — pass = our process logs report bytes WHILE Rekordbox still reacts; repeat MIDI-mode via `midir`.
- **Confidence:** medium.

### 2026-06-01 — Capture libs + audio input [OQ2, OQ8]
- **Codebase:** output `Stream` thread-confined (`src-tauri/src/audio/playback.rs:78-138`; `!Send` rationale `:11-25`); decoder→ring-buffer `src-tauri/src/audio/engine.rs:114-206`; pinned `cpal="0.15"`,`ringbuf="0.3"` (`src-tauri/Cargo.toml:30,33`); no input/MIDI/HID today.
- **Web:** cpal v0.15.3 sets `AUDCLNT_STREAMFLAGS_LOOPBACK` when `data_flow()==eRender` → pass the **output** device to `build_input_stream` to capture master-out ([device.rs:509-513](https://raw.githubusercontent.com/RustAudio/cpal/v0.15.3/src/host/wasapi/device.rs)); loopback forces shared-mode+polling ([cpal#476](https://github.com/RustAudio/cpal/issues/476)). `midir` MIT/active, µs-timestamp callback, no virtual ports on Windows ([docs.rs/midir](https://docs.rs/midir/)). `hidapi-rs` MIT/active, dedicated `read_timeout` thread ([github](https://github.com/ruabmbua/hidapi-rs)).
- **Synthesis:** new `src-tauri/src/audio/recorder/` — `audio_in.rs` (cpal loopback on `default_output_device`, own thread mirroring `playback.rs` confinement), `midi_in.rs` (midir callback→`mpsc`), `hid_in.rs` (hidapi blocking-read thread→same channel), `clock.rs` (shared monotonic `Instant` epoch). Stamp every audio callback + event against that epoch; merge in a collector thread. No `unsafe impl Send`.
- **Confidence:** high.

### 2026-06-01 — Control-mapping sourcing [OQ3]
- **Codebase:** greenfield — no control-map code.
- **Web:** Mixxx mapping format ([wiki](https://github.com/mixxxdj/mixxx/wiki/Midi-Controller-Mapping-File-Format)); real [DDJ-FLX4.midi.xml](https://github.com/mixxxdj/mixxx/blob/main/res/controllers/Pioneer-DDJ-FLX4.midi.xml) (~800 entries); [HID-mapping wiki](https://github.com/mixxxdj/mixxx/wiki/Hid-Mapping) (script-only byte parse, `--controllerDebug`); Mixxx [GPLv2+](https://github.com/mixxxdj/mixxx/blob/main/LICENSE); [Serato maps](https://github.com/marscanbueno/serato-dj-pro-midi-maps); [djtechtools maps](https://maps.djtechtools.com/).
- **Synthesis:** Mixxx MIDI XML covers most DDJ + encodes CC/note (`<status>0xB0</status>`+`<midino>0x07</midino>`) but has **no x/y** → outline coords always hand-authored. HID-mode DDJ has no semantic byte-map → byte offsets read from `incomingData`. Reuse = read assignments as **reference facts** + re-author; do NOT copy Mixxx XML/JS into our tree (GPLv2+ copyleft). Single MIDI fact not copyrightable; bulk file is. Hand-map one 2-ch DDJ ≈40-60 controls via MIDI-Learn/`--controllerDebug`. Own JSON schema: `control_id → {midi{status,cc} | hid{byte,mask}, kind, outline{x,y,w,h}}`.
- **Confidence:** high.

### 2026-06-01 — Track identity (Pro DJ Link) + dep-slimming [OQ4, OQ9] ⚠ BLOCKER
- **Codebase:** greenfield — no PDL/UDP listener (all `udp|socket` hits are SoundCloud HTTP / unrelated math).
- **Web:** **(a) BLOCKER:** Pro DJ Link runs in rekordbox **EXPORT mode only, NOT Performance mode.** Controller+laptop = Performance mode = HID → no PDL broadcast ([djtechtools](https://djtechtools.com/2018/10/08/pro-dj-link-5-secret-features-of-pioneer-djs-protocol/); [Pioneer Performance-mode guide](https://cdn.rekordbox.com/files/20200312171207/rekordbox5.3.0_connection_guide_for_performance_mode_EN.pdf)). Even on PDL, rekordbox sends mixer-style packets, not per-deck status ([dysentery vcdj](https://djl-analysis.deepsymmetry.org/djl-analysis/vcdj.html)). Hardware CDJ status (port 50002, type `0a`) carries beat/tempo/position/play; track-id in status, title/artist via separate NFS/dbserver ([packet analysis](https://djl-analysis.deepsymmetry.org/djl-analysis/packets.html)). **(b)** Slimmable: protocol = `prodj/network/packets.py` (Construct) + `prodj/core/*` + `prodj/network/*`; GUI isolated in `prodj/gui/*` (PyQt5/PyOpenGL); core needs `construct`+`netifaces` only ([repo](https://github.com/flesniak/python-prodj-link)). **(c)** Serato = no open live API → fingerprint-vs-library only.
- **Synthesis:** PDL gives **nothing** for the stated controller+laptop Performance-mode target. Live track-id there → audio fingerprint (heavy, separate aspect) OR user switches to Export mode / hardware CDJs later (then vendor `prodj/{network,core,data}`, drop `gui`; deps `construct`+`netifaces`). MVP options: (1) defer track-id to manual/post-hoc reconcile, (2) fingerprint the recorded master.
- **Confidence:** high.

### 2026-06-01 — Video pipeline + per-second level [OQ5, OQ6]
- **Codebase:** metering `app/analysis_engine.py:917-922` `rms_array` (hop=`sr/detail_fps`; set hop=`sr` → 1 RMS/sec), `:1572-1599` `calculate_lufs` (`pyloudnorm.Meter` `:1587`, `integrated_loudness` `:1593`). ffmpeg mux pattern `app/services.py:271,279` — **note `:279` lacks `timeout=`, new mux MUST add it** (`coding-rules.md:36`). No resvg crate (greenfield). Canvas reuse `frontend/src/components/daw/DawTimeline.jsx`, `WaveformCanvas.jsx`.
- **Web:** resvg = pure-Rust, deterministic, `render`→tiny-skia Pixmap→PNG ([docs.rs](https://docs.rs/resvg/), [github](https://github.com/linebender/resvg)); ffmpeg `-framerate N -i frame%05d.png -i audio -c:v libx264 -pix_fmt yuv420p` ([ffmpeg.org](https://ffmpeg.org/ffmpeg.html)); MediaRecorder = realtime-only, drops frames under load, no non-realtime export ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/MediaStream_Recording_API), [w3c #213](https://github.com/w3c/mediacapture-record/issues/213)).
- **Synthesis:** resvg→PNG→ffmpeg = deterministic, faster-than-realtime offline, reuses existing subprocess pattern; headless browser = ships Chromium, heavy, non-deterministic; realtime MediaRecorder = wall-clock-bound + WebM, unfit for archival. **Recommend (i):** Rust `resvg`/`usvg`/`tiny-skia` SVG-template-per-frame → PNG seq → ffmpeg mux (+`timeout=`). Per-second level: `rms_array(y, hop=sr)` primary; optional `pyloudnorm` per 1s for true LUFS/sec.
- **Confidence:** high.

### 2026-06-01 — Timeline file format [OQ7]
- **Codebase:** greenfield; `midly` already proposed; per-second level reuse `app/analysis_engine.py:817-1129`; write inside `ALLOWED_AUDIO_ROOTS` via `validate_audio_path` (`app/main.py:186,208`).
- **Web:** SMF = 7-bit CC (0-127), tick time tied to quarter-note, tempo µs/qn — **cannot** carry float levels or arbitrary metadata ([midispec](https://midimusic.github.io/tech/midispec.html), [somascape](http://www.somascape.org/midi/tech/mfile.html)). Mixxx records audio only, no control persistence ([manual](https://manual.mixxx.org/2.3/en/chapters/advanced_topics)). Ableton stores controller envelopes + automation in proprietary `.als/.alc` ([ableton](https://www.ableton.com/en/manual/clip-envelopes/)).
- **Synthesis:** **Recommend BOTH** — JSONL source-of-truth (one event/line, append-only, crash-safe, floats, metadata) + optional SMF export (DAW/host interop). Schema: `hdr{v,t0_unix_ms,sr,controller,map_version,decks}`; `ev{t_ms,deck,control_id,type,value(0-1),raw{ch,cc,v7}}`; `trk{t_ms,deck,track_id,title,artist,bpm,key,pitch_pct,dur_ms}`; `lvl{t_ms,deck,rms,lufs}`. Replay needs (capture NOW, don't under-collect): raw MIDI/HID bytes+channel, normalized **and** native value, versioned controller-map ref, monotonic clock, `pitch_pct`, fader-vs-measured-level distinction (OQ5). Keep `raw` even when `control_id` known → unmapped controls replay verbatim.
- **Confidence:** high.

## Adversarial Findings

Stage 2 Adversarial-Agent (phase 2). Devil's-advocate — what could go wrong, what assumptions are weak, what dependencies betray us. ≤120 words. Append-only.

### YYYY-MM-DD
- **Weak assumption:** …
- **Failure mode:** …
- **Counter-example:** …

If none survive scrutiny: **"No surviving objections — proceed with caution flags above."**

## Citation Quality

Stage 2 Citation-Verifier (phase 2). Checks every `file:line` ref + URL in `## Findings` exists + says what the Finding claims. PASS / FAIL list. ≤80 words.

### YYYY-MM-DD — <PASS|FAIL>
- PASS: Findings 1, 2, 4 — citations verified
- FAIL: Finding 3 — `app/main.py:123` no such symbol, replace or remove

---

> ↓ Stage 2 phase 2 (autonomous; no user gate) — `research-explore` deepens findings, runs Adversarial + Citation verifiers, then the Research-Verifier gates the whole body before Options-Synthesis advances the doc to `evaluated_`.

## Research Verification

Stage 2 wave-2 verifier over whole research body. ≤120 words. PASS → `evaluated_`; gaps → more Findings.

### YYYY-MM-DD — <PASS|GAPS>
- Coverage of Open Questions: …
- Internal consistency: …
- Citation quality (cross-ref `## Citation Quality`): …
- Adversarial concerns addressed: …

## Options Considered

Stage 2 Synthesis-Agent (phase 2 PASS). Per option: sketch ≤5 bullets, pros, cons, S/M/L/XL, risk, prior-art match.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

## Recommendation

Stage 2 Synthesis-Agent (phase 2 PASS). ≤120 words. Which option + what blocks commit + which OQ each Finding answers.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review. On Review PASS, the Mockup+Summary-Agent fills `## Approval Summary` + `## Mockup`, then advances to `approvalgate_`.

## Implementation Plan

Stage 3 Planner-Agent. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
Path + role (read / edit / new):
- `<path>` — <role> — <why>

### Testing
High-level (see `## Test Plan` for concrete pytest/cargo cases):
- …

### Risks & rollback
- …

## Threat Model

Stage 3 Threat-Modeller-Agent. Required when feature touches: auth, `require_session`, filesystem (paths in / out), `master.db` writes, network, secrets, user-supplied paths. Otherwise: **"N/A — no security surface."**

### Assets
- … (data, secrets, attacker goal)

### Trust boundaries
- … (which layer trusts which input)

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | … | step N / file X | test_… |

### Residual risk
- ≤60 words — what cannot be eliminated, why acceptable.

## Migration Path

Stage 3 Migration-Path-Agent. Required when feature changes: DB schema, file layout, settings/config shape, IPC contract, on-disk caches, USB export bytes. Otherwise: **"N/A — no migration."**

### Before → After
- Data shape today: …
- Data shape after: …
- Existing-data handling: in-place migrate / lazy on read / one-shot backfill

### Backfill / forward-compat
- Migration script: `<file>` (or "no script — schema-additive")
- Old client reads new data: yes/no — how degraded
- Rollback: restore via `<backup>` / re-run reverse migration `<file>`

### User-visible behavior during migration
- … (downtime, progress UI, can app start before complete?)

## Performance Budget

Stage 3 Perf-Budget-Agent. Numbers, not "fast". If feature has no perceptible runtime cost: **"N/A — analysis-only / one-shot."**

| Path | Budget | Measured today | Source |
|---|---|---|---|
| <e.g. POST /api/duplicates/scan> | p95 ≤ 800ms / 50MB peak | … | `tests/perf/…` or "untested" |

### Worst-case scenario
- Input shape: <e.g. 50k tracks, 200 dupes>
- Expected impact: …
- Mitigation if exceeded: …

## API / UX Surface

Stage 3 Planner-Agent. What is added / changed at every layer the user / frontend touches.

### Backend (FastAPI)
- New routes: `<METHOD> <path>` — auth: `require_session`? rate-limited? lock?
- Changed routes: `<METHOD> <path>` — what changed in request/response shape

### Frontend (React)
- New components / hooks / IPC calls (axios + invoke):
- Changed components: …

### Tauri (Rust commands)
- New `#[tauri::command]`s: …
- Changed signatures: …

### CLI / sidecar logs
- New stdout markers (e.g. `LMS_TOKEN=`-style): …

## Telemetry

Stage 3 Planner-Agent. How we know it works after ship. ≤80 words. Otherwise: **"N/A — no runtime behavior to observe."**

- Log markers (`logger.info("op=… …")`): …
- Counters / timing: …
- Health-endpoint surface: …
- User-visible status (toast, statusline, dashboard tile): …

## Test Plan

Stage 3 Test-Plan-Agent. Concrete test cases, one row per. Must cover Threat Model + Migration + Perf budgets.

| ID | Layer | Test file | Case | Covers (Threat / OQ / Step) |
|---|---|---|---|---|
| T1 | py | `tests/test_<area>.py::test_<case>` | … | Threat T1 |
| T2 | rust | `src-tauri/src/audio/.../tests` | … | Step 3 |
| T3 | js | `frontend/src/**/*.test.js` | … | OQ 2 |
| T4 | integration | `tests/test_<integration>.py` | end-to-end happy path | full flow |
| T5 | perf | `tests/perf/<file>.py` (new) | p95 budget vs target | Perf table row N |

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at the Approval Gate. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Keep tasks small — a task too big to review in one PR must be split.
Each task should map back to a Step in ## Implementation Plan and have ≥1 row in ## Test Plan.
-->

- [ ] <task — small, single-purpose, independently testable> — covers Step N, tests T<m>, T<n>

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Plan matches `## Original Idea` — no scope-creep
- [ ] Open questions answered or deferred
- [ ] Prior Art referenced — no duplicated past work
- [ ] Threat Model present + each threat has a test (or N/A justified)
- [ ] Migration Path present + rollback documented (or N/A justified)
- [ ] Performance Budget set + worst-case scenario documented (or N/A justified)
- [ ] API / UX Surface enumerated for every layer touched
- [ ] Telemetry defined for shipped behavior (or N/A justified)
- [ ] Test Plan covers every Threat + every Step + every Perf row
- [ ] Task Queue items are small + independently committable + reference Steps + Tests
- [ ] Dependencies audited — new libs have Schicht-A entries
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Approval Summary

Stage 3 Mockup+Summary-Agent (after Plan-Reviewer PASS). **Plain user-facing English — NOT Caveman.** This block is what the user reads to decide yes/no. ≤200 words. No `file:line` jargon — describe effects, not internals.

- **What it does:** 1–2 sentences, plain language. What the feature gives the user.
- **What you'll notice:** bullet list of user-visible effects (new button, faster scan, new export option, …).
- **Scope:** N files touched · N tasks · effort S/M/L · risk low/med/high.
- **Rollback:** one line — how it's undone if you dislike it after merge.
- **Mockup:** see `## Mockup` below.

## Mockup

Stage 3 Mockup+Summary-Agent. Adaptive to feature type — decide from `## API / UX Surface`:

- **UI feature** (has frontend components): write a self-contained static wireframe to `docs/research/mockups/<slug>.html` (inline CSS, no build step, no external assets — open in a browser locally). Fill the **UI** block below. Leave the **Backend** block empty/removed.
- **Backend / DSP / USB / DB feature** (no visible UI): fill the **Backend** block with a concrete example — sample API request/response, CLI/log output, or before→after data (metadata tags, USB tree, DB rows). Show the shape the user will actually see. Leave the **UI** block empty/removed.

### UI — mockup file
- `docs/research/mockups/<slug>.html` — <one-line layout + key-interaction description>

### Backend — concrete example
```text
<sample response / CLI output / before→after — the user-visible shape>
```

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`). The single sign-off: read `## Approval Summary` + `## Mockup`. After approval, nothing is re-researched.
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item via 5 agents (Approach-Probe, Code, Standard-Review, Security-Review, Test-Coverage-Review, Doc-Sync) on a `routine/*` branch. You test + merge the branch yourself.

## PR Log

Stage 4. One row per task PR. `research-implement` appends; user notes merge after local testing.

| Task | Branch | PR | CI | Std Rev | Sec Rev | Test Cov | Doc Sync | Merged |
|---|---|---|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | pass/fail | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

Stage 4 Code-Agent + Approach-Probe. Dated entries. What built / surprised / changed-from-plan.

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

Required by `archived/*`. Stage 4 Doc-Sync-Agent populates the checklist; user signs off after testing the branch locally + merging.

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

- Code: <file:line or PR>
- External docs: <url>
- Related research: <slugs>
- Supersedes: <slug or none>
- Superseded by: <slug or none>
