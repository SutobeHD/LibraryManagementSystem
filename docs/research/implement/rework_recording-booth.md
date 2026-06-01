---
slug: recording-booth
title: Recording Booth
owner: tb
created: 2026-06-01
last_updated: 2026-06-01
tags: [recording, audio, midi, tauri, rust, video, dj, timeline]
related: [library-format-converter, download-format-setting]
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
- 2026-06-01 — `research/evaluated_` — explore phase 2 done (adversarial + citation PASS, research-verifier PASS); recommendation = spike-gate (3 device spikes) → Option A else B; PDL track-id unmet (Performance mode)
- 2026-06-01 — `research/evaluated_` — goals expanded (G1–G7 + success criteria + MVP-done) per user request; intent unchanged vs Original Idea
- 2026-06-01 — `implement/draftplan_` — Stage 3 plan filled (Planner+Threat+Migration+Perf+Test-Plan+Task-Queue). Target locked to user's gear: DDJ-FLX4 lead + DDJ-400/DDJ-GRV6 siblings (all class-MIDI) + Rekordbox. Capture path = MIDI (`midir`), `hidapi` deferred. Live path = Tauri events → no WebSocket / no `require_session_ws` (supersedes Constraints WS assumption). Track-id = post-hoc Rekordbox-history reconcile (read-only, no `_db_write_lock`).
- 2026-06-01 — `implement/review_` — Plan-Reviewer 15/15 PASS. Loud caveat carried to Approval Summary: class-MIDI controllers → harder co-read (WinMM single-client); build branches A/B/C on the 3 hardware spikes (co-read / audio / EQ-on-wire).
- 2026-06-01 — `implement/approvalgate_` — Mockup (`mockups/recording-booth.html`) + plain-English Approval Summary filled; awaiting user `/approve` or `/reject` (THE single gate).
- 2026-06-01 — `implement/approvalgate_` — pre-approval refinement (user request): spike specs (1a/1b/1c PASS/PARTIAL/FAIL + A/A′/B/C decision matrix), Task Queue DoD + deps (Task 11 split → 11a/11b), measurable Goal success criteria + goal↔spike map, mockup fidelity (FILTER + tempo + spike-1c EQ caveat). **State unchanged — still at the gate, not advanced.**
- 2026-06-02 — `implement/rework_` — **REJECTED at gate** (user, via scope review): re-scope **lead model FLX4 → DDJ-GRV6**. GRV6 = 4-channel / STEMS-native / GROOVE CIRCUIT (drum-sampler) + Sound-Color/Beat-FX + 4 decks — materially richer than the FLX4 the plan had picked. Re-plan needed: GRV6 outline, full control map (incl. stem-ISO + drum section + FX), spike 1c extended to stem-ISO/sound-color/GROOVE-CIRCUIT on-the-wire, 4-deck timeline. Capture mechanism unchanged (GRV6 is class-MIDI → `midir`).

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

- **Incidental infra only (no concept overlap):** [evaluated_library-format-converter.md](../research/evaluated_library-format-converter.md) + [accepted_download-format-setting.md](accepted_download-format-setting.md) touch ffmpeg/audio-export plumbing. Offline LUFS/RMS metering `app/analysis_engine.py:817-1129` — reuse for per-second level. Canvas viz `frontend/src/components/daw/DawTimeline.jsx` + `frontend/src/components/waveform/WaveformCanvas.jsx` — audio-only, reusable render pattern.
- **External precedent (verify Stage 2):** rekordbox/serato ship audio set-record + play-history; no known tool renders live *hardware-controller* movement video. Software-UI screen+audio capture (VirtualDJ/djay) ≠ hardware overlay.

## Problem

DJ wants sets recorded as more than audio. No tool captures *what the DJ physically does* on the controller (EQ/fader/button/jog moves) as a synced controller-outline video + machine-readable control timeline. Audio-only recordings lose every performance gesture + per-track level history. Cost: no shareable visual set, no replayable performance data.

## Goals / Non-goals

**Goals** — each = capability + success criterion. MVP minimum = G1+G2+G4+G5; **G3 (video) = headline, spike-gated**. Target setup throughout: USB controller + laptop running Rekordbox/Serato (not standalone CDJ/DJM).

*Primary (each traces to Original Idea):*
- **G1 — Set audio recording.** Full-set master audio → one lossless file (WAV/AIFF; format configurable later). *Success:* one gapless file, duration within ±1 audio-buffer of wall-clock, **0 dropped callbacks** (Test T1/T3). *Acquisition (research):* explicit loopback / virtual-cable input device via cpal `build_input_stream` — **not** naive `default_output` loopback (silent under exclusive-WASAPI/ASIO — Adversarial 2026-06-01, OQ10).
- **G2 — Controller control capture.** Every control event — channel faders, EQ hi/mid/lo, crossfader, play/cue/pad buttons, knobs, jog touch+turn — with monotonic timestamps. *Success:* each physical move on the mapped controller = one timestamped event carrying normalized (0–1) **and** raw value; **no missed event** under a 10-moves/s sweep; timestamps monotonic + strictly increasing (Test T2). *Spike-gated:* co-read of the in-use controller (OQ1) + EQ-on-wire (OQ11).
- **G3 — Controller-outline performance video (headline).** Static controller outline + every mapped control animated to its captured value over time (Highs-knob visibly turns down on an EQ cut), muxed with G1 audio. *Success:* in frame(t) every mapped control sits within **±1 frame** of its `set.jsonl` value; **A/V drift ≤1 frame** end-to-end (Test T4). **Gated on spikes 1a+1c** — if EQ is not on the wire (1c FAIL) the headline Highs-cut cannot be animated → **Option A′** (animate faders/pads/jogs only). *Pipeline (research):* offline resvg→PNG→ffmpeg, deterministic.
- **G4 — Replay-capable control-timeline file.** All events + track loads + level envelope in a documented format rich enough that a *future* automated replay could re-perform the set. *Success:* file round-trips every event with raw bytes + normalized value + controller-map version + monotonic clock + pitch (Test T5). Replay itself is **not** built (Non-goal). *Format (research):* JSONL source-of-truth + optional SMF export.
- **G5 — Track + per-second level timeline.** Which track played per deck over time + a per-second volume/level envelope. *Success:* per-deck track changes + a per-second RMS/LUFS series from the recorded master (reuse `app/analysis_engine.py:917-922,1572-1599`); per-second RMS/LUFS within **±0.5 dB** of the offline `analysis_engine` reference (Test T6). *Constraint (research):* live track-id from Rekordbox is unavailable in Performance mode (PDL = Export-only — Finding "Track identity ⚠") → MVP = level live, track-id via **post-hoc reconcile from Rekordbox history** (audio-fingerprint later).

*Cross-cutting (how, not what):*
- **G6 — One controller model end-to-end first.** Ship the full chain (capture → timeline → video) for the user's actual model before generalizing. Mapping = own JSON schema (`control_id → {midi|hid, kind, outline x/y}`), re-authored from reference facts — **not** copied from GPL Mixxx data (Finding "Control-mapping").
- **G7 — Non-destructive, sandboxed, off-the-realtime-path.** All outputs written inside `ALLOWED_AUDIO_ROOTS` via `validate_audio_path`; record start/stop behind `require_session`; the timeline writer runs on a dedicated `mpsc` thread, never in the audio/MIDI callback (Adversarial 2026-06-01).

**MVP "done":** a real set on the target controller produces (a) the audio file, (b) the timeline file, (c) the synced controller video. If the three spikes don't all pass → Option-B subset: (a)+(b) ship, (c) video explicitly deferred.

**Goal ↔ spike gate:** G1→spike 1b (audio path); G2→spike 1a (co-read); G3→spikes 1a+1b+1c (full video; EQ needs 1c → else A′); G4 · G5 · G6 · G7 = spike-independent (ship in Option B regardless of hardware outcome).

**Non-goals**
- **Automated replay/playback** of the timeline — explicitly deferred by the user ("das setzen wir aber nicht um"); only the *format* must support it later (G4).
- **Standalone CDJ/DJM capture** — mixer EQ/faders/crossfader aren't in any data stream; controller+laptop only.
- **Live track-identity in Performance mode** beyond post-hoc/fingerprint — PDL can't deliver it; no live now-playing readout at MVP.
- **Multi-controller-model support** at MVP — one model first; the mapping schema is designed to extend.
- **Mixing / playing through this app** — it records an *external* DJ rig; it does not become a 2-deck player.
- **Editing** the recorded video or timeline (trim, recolor, re-mix) — capture/render only.
- **Live streaming / broadcast / OBS integration.**

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
10. **Audio-capture path (SPIKE):** does cpal WASAPI loopback on the output device capture the controller's master, or **silence** when Rekordbox/Serato hold the device in exclusive WASAPI / ASIO? If silence → which device / virtual-cable yields the master? (per-device spike; from Adversarial 2026-06-01)
11. **EQ on the wire (SPIKE):** on the target controller, is channel EQ (esp. Highs) emitted as MIDI/HID, or applied audio-first in hardware DSP and NOT on the stream? Determines whether the headline EQ-animation has a data source. (per-model spike; from Adversarial 2026-06-01)

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

### 2026-06-01
- **Failure mode — audio loopback** (vs Finding "Capture libs + audio input", 2026-06-01): cpal WASAPI loopback is **shared-mode only**; exclusive-mode streams can't be loopback-captured + bypass the mixer ([MS Learn](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)). Rekordbox/Serato routinely open the controller out in **ASIO / WASAPI-Exclusive** for low latency → loopback captures **silence**. Downgrades that Finding's "high" confidence; capture likely needs the controller's dedicated loopback device or a virtual cable, not `default_output_device`. → OQ10.
- **Counter-example — EQ in hardware** (vs Original Idea "Highs raus" + Finding "Control-mapping", 2026-06-01): on several DDJs (e.g. DDJ-800/1000) channel EQ is "audio-first", hardwired, can't unlink from audio ([Pioneer forum](https://forums.pioneerdj.com/hc/en-us/community/posts/16914047357977)). If EQ is in-controller DSP and not on the MIDI/HID stream, the headline "show Highs cut" has **no data source** on those models. Finding assumed every control emits CC — unverified for EQ. → OQ11.
- **Weak assumption — resvg perf** (vs Finding "Video pipeline", 2026-06-01): "faster-than-realtime" unproven — ~55-66 ms / modest frame; 60-min set @30fps = 108k frames × ~60 ms ≈ 108 min single-thread + 10-50 GB PNG scratch. Needs dirty-region/diff render or low fps. Budget it.
- **Failure mode — realtime JSONL writer** (vs Finding "Timeline format", 2026-06-01): per-event file write must NOT run in the realtime audio/MIDI callback (`!Send` thread) — blocking I/O = xruns. Plan must mandate `mpsc` → dedicated writer thread.
- **Compounding risk:** co-read + EQ-in-DSP + loopback-exclusive are **correlated on the exact stated target** (Pioneer DDJ + Rekordbox). All three failing together = MVP delivers neither video nor clean audio. The crux Finding ("Co-read", medium) gates the headline feature — its spike must precede `/approve`, not implementation.
- **PDL blocker** (vs Finding "Track identity ⚠", 2026-06-01): survives — correctly flagged; consequence understated. User's stated goal "track-info live from Rekordbox" is **unmet at MVP** (Performance mode = no PDL). Approval Summary must state this plainly, not bury it.

## Citation Quality

### 2026-06-01 — PASS
- **PASS:** Findings 2, 3, 5, 6 — all `file:line` + load-bearing URLs verified (cpal LOOPBACK-on-eRender; `app/services.py:279` confirmed missing `timeout=`; SMF 7-bit/no-float; MediaRecorder realtime-only; `validate_audio_path` at `app/main.py:186,208`).
- **PASS (caveat):** Finding 1 "Co-read" — codebase ref + HID ring-buffer + MIDI single-client (`MMSYSERR_ALLOCATED`) confirmed; teragonaudio URL unreachable → that one unverified, claim corroborated by MS-Learn.
- **PASS (weak citation):** Finding 4 "Track identity" — Export-mode / Performance=HID claim corroborated by the Pioneer Performance-mode guide + dysentery, **but the lead djtechtools URL does not contain the assertion** → demote to secondary / replace; the claim itself stands.
- No hard FAIL → no re-research round triggered.

---

> ↓ Stage 2 phase 2 (autonomous; no user gate) — `research-explore` deepens findings, runs Adversarial + Citation verifiers, then the Research-Verifier gates the whole body before Options-Synthesis advances the doc to `evaluated_`.

## Research Verification

### 2026-06-01 — PASS
- **OQ coverage:** OQ1–9 each have ≥1 Finding; OQ10–11 added from adversarial (audio-capture-path + EQ-on-wire spikes) — open by design (hardware-resolvable only).
- **Internal consistency:** findings agree; no contradictions. cpal pin (`0.15`) supports the loopback claim; metering line refs cross-checked by Citation.
- **Citation quality:** PASS (see `## Citation Quality`); one weak URL (Finding 4) non-load-bearing — claim holds on two other sources.
- **Adversarial concerns addressed:** carried forward as acknowledged risks + spikes (co-read, loopback-exclusive, EQ-in-DSP, resvg perf, realtime-writer threading). None are knowledge gaps closeable by more web research — all are device-spikes that must gate `/approve`. PASS → `evaluated_` with these flagged in `## Recommendation`.

## Options Considered

### Option A — Full vision, spike-gated
- Sketch: Rust recorder (`audio_in` loopback + `midi_in`/`hid_in` co-read + shared `clock`) → JSONL+SMF timeline → offline `resvg`→PNG→ffmpeg controller-outline video; best-effort track log.
- Pros: delivers the whole idea — audio + animated controller video (incl. EQ) + replay-capable timeline + per-second level.
- Cons: high, **correlated** hardware risk (Adversarial 2026-06-01: co-read + loopback-exclusive + EQ-in-DSP all on the stated target); largest surface; resvg perf budget.
- Effort: XL.
- Risk: high.
- Prior-art match: novel.

### Option B — De-risked incremental (audio + timeline first, video later)
- Sketch: Phase 1 = reliable master capture via an **explicit** loopback/virtual-cable device (not naive `default_output`) + control-timeline (HID/MIDI co-read) + JSONL/SMF; defer video render + live-track-id (manual/post-hoc reconcile from Rekordbox history).
- Pros: each piece independently useful; sidesteps loopback-exclusive (explicit device) + PDL blocker (post-hoc); ships sooner; spikes de-risked one at a time.
- Cons: headline controller-video deferred; track-id not live (Adversarial 2026-06-01: stated goal unmet at MVP).
- Effort: L.
- Risk: medium.
- Prior-art match: novel.

### Option C — Reconfigure-rig capture (MIDI-mode + virtual cable)
- Sketch: user routes master to a virtual audio cable + runs the controller in class-MIDI mode via a virtual-MIDI fan-out → app reads both deterministically; build the full vision on that known-capturable base.
- Pros: removes the co-read + exclusive-WASAPI unknowns (deterministic capture).
- Cons: imposes rig reconfiguration on the user (may clash with how they DJ); MIDI-mode loses HID richness; setup friction.
- Effort: L–XL.
- Risk: medium (technical) / high (UX adoption).
- Prior-art match: novel.

## Recommendation

**Spike before committing — then Option A if spikes pass, else Option B.** Three device-spikes gate the headline feature and MUST run on the user's real DDJ+Rekordbox before `/approve`: (1) **co-read** (OQ1) — read controller HID while Rekordbox owns it; (2) **audio-capture path** (OQ10) — loopback vs exclusive/ASIO silence; (3) **EQ-on-wire** (OQ11) — is Highs emitted as MIDI/HID. All three pass → **Option A** (full vision). Any fail → **Option B** (audio+timeline now, video/live-track-id deferred). **Option C** is the fallback if co-read/loopback fail but the user accepts rig reconfiguration. **Track-id live from Rekordbox is unmet** (PDL = Export-mode only, Finding "Track identity ⚠") → manual/post-hoc reconcile at MVP regardless of option. Findings→OQ map: OQ1/2→co-read; OQ2/8→capture libs; OQ3→mapping; OQ4/9→PDL; OQ5/6→video+level; OQ7→timeline; OQ10/11→spike gaps.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review. On Review PASS, the Mockup+Summary-Agent fills `## Approval Summary` + `## Mockup`, then advances to `approvalgate_`.

## Implementation Plan

Target locked (user, 2026-06-01): **DDJ-FLX4 lead model**, **DDJ-400 + DDJ-GRV6 (Groove6) siblings** (all class-compliant USB-MIDI → `midir` path; `hidapi` deferred to future HID models). Software = **Rekordbox**. Layering per `coding-rules.md`: realtime capture + offline render = **Rust**; per-second level + Rekordbox-history reconcile + REST = **Python**; view = **React**. **Live status flows Rust→frontend via Tauri events** (`app.emit`, pattern `commands.rs:142-148`; frontend `listen`, `SoundCloudSyncView.jsx:10,293`) — **no WebSocket, no `require_session_ws`** (doesn't exist; supersedes the Constraints WS line).

### Scope
- **In — MVP-B baseline (ships regardless of spike outcome):**
  - Rust `src-tauri/src/audio/recorder/`: master-audio capture (cpal input/loopback, confined thread mirroring `playback.rs:78-139`) + MIDI capture (`midir` callback→`mpsc`) + shared monotonic `clock` + collector→**append-only JSONL writer on a dedicated thread** (never in the realtime callback). Output `set.wav` (via existing `hound`) + `set.jsonl` (+ optional `set.mid` via `midly`).
  - Controller mapping schema + hand-authored `ddj-flx4.json` (re-authored from Mixxx FLX4 reference facts, **not copied** — GPLv2; outline x/y hand-measured) + `ddj-400.json`/`ddj-grv6.json`.
  - Python per-second level (reuse `analysis_engine.rms_array` hop=sr + `calculate_lufs` per 1s) → `lvl` lines.
  - Python read-only Rekordbox-history track reconcile over the session window → `trk` lines (best-effort + manual fallback).
  - React **Recording Booth** view: audio + MIDI device pickers, record start/stop, live meter + live control-activity (Tauri events), recordings list.
  - Sidecar `recording_booth.db` index (platformdirs, mirror `auth_db.py:51-53`).
- **In — Option A headline (spike-gated; built only if Tasks 1-3 pass):**
  - Offline controller-outline video: Rust `resvg`→raw-RGBA frames→ffmpeg-stdin mux → `set.mp4`, animated from `set.jsonl` (EQ-knob turns down on a cut). Frontend video player.
- **Out:** automated replay/playback (Non-goal — format only); standalone CDJ/DJM capture; live track-id (Performance-mode = no PDL); models beyond FLX4/400/GRV6; HID controllers (DDJ-1000/etc — `hidapi` deferred); timeline/video editing; streaming/OBS; mixing through the app.

### Step-by-step
1. **Spikes (hardware-gated — run on real DDJ-FLX4 + Rekordbox before Option A).** Dev-only Tauri commands, log PASS/FAIL into `## Implementation Log`:
   - **1a Co-read (OQ1, the crux):** `midir` open FLX4 input *while Rekordbox owns it* — test default WinMM **and** WinRT multi-client. PASS = our process logs CC while Rekordbox still reacts.
   - **1b Audio path (OQ10):** cpal loopback on the FLX4 audio-out device vs ASIO/exclusive **silence**; enumerate inputs; find the device/virtual-cable that yields master.
   - **1c EQ-on-wire (OQ11):** move Hi/Mid/Lo, confirm CC on the MIDI stream (data source for the Highs animation).
   - → **Branch:** all pass → **A** (full vision). Co-read or audio fail → **B** (audio+timeline+level now; video + live control-preview deferred). Co-read fails but user accepts a virtual-MIDI bridge → **C** (rig reconfig).
2. **Rust capture core** — `recorder/{mod,clock,audio_in,midi_in,collector}.rs`. `clock.rs` shared `Instant` epoch; `audio_in.rs` cpal input on named thread + WAV via `hound`; `midi_in.rs` `midir` callback→`mpsc`; `collector.rs` drains channel → append-only JSONL on its own writer thread. `hid_in.rs` = stub (deferred). No `unsafe impl Send`.
3. **Mapping** — `src-tauri/resources/recorder/maps/ddj-flx4.json` (+400/grv6) `control_id → {midi:{status,cc} | hid:{byte,mask}, kind, deck, outline:{x,y,w,h}}` + `map_version`; `outline/ddj-flx4.svg`; Rust loader.
4. **Tauri commands + events** — `list_midi_inputs`, `list_recording_inputs`, `start_recording`, `stop_recording`, `recording_status`; events `recording-meter`/`recording-control`/`recording-status`/`recording-error`. Register at `main.rs:502-513`; state via `.manage` (`main.rs:500-501`).
5. **Python analysis** — `app/recording_booth.py`: sidecar DB + `POST /api/recording/analyze-levels` (`require_session`, `validate_audio_path` on the wav) → per-second RMS/LUFS (reuse `analysis_engine.py:915-927,1572-1597`) → append `lvl` lines.
6. **Python reconcile** — `POST /api/recording/reconcile-tracks` (`require_session`) → read-only Rekordbox history over `[t0,t_end]` via existing pyrekordbox infra (**no `master.db` write, no `_db_write_lock`**) → append `trk` lines, best-effort + manual.
7. **Recordings index** — `GET /api/recording/list`, `GET /api/recording/{id}`.
8. **React view** — `frontend/src/components/RecordingBoothView.jsx` (mirror `SettingsView.jsx:108`); register in `main.jsx:71` `buildWorkspaces()` + `:140` `TAB_WORKSPACE` + lazy import + render block (`:893-962`). Pickers via `invoke`; record/stop via `invoke` (+`confirmModal` on stop); live meter+control canvas reuse `WaveformCanvas`/`DawTimeline` RAF pattern fed by `listen(...)`; recordings list. Constants → `frontend/src/config/constants.js`.
9. **Option A video** — `recorder/video.rs` + `render_recording_video(session_id, fps)` Tauri command (`spawn_blocking`): `resvg`/`usvg`/`tiny-skia` render the FLX4 outline per frame from `set.jsonl`, **stream raw RGBA → ffmpeg stdin** (`-f rawvideo`, no PNG scratch) mux with `set.wav` → `set.mp4`. ffmpeg subprocess **with timeout** (Rust wait-with-timeout). Diff-render unchanged controls; 30fps default, fallback 15/10. Frontend `<video>` player.
10. **Docs sync** — rust-index, backend-index, frontend-index, FILE_MAP, architecture data-flow, CHANGELOG.

### Spike specifications (Tasks 1–3 — run on real DDJ-FLX4 + Rekordbox before Option A)

Dev-only Tauri commands (behind a debug `cfg`/dev build, no production surface). Each logs one verdict line to stdout + appends to `## Implementation Log`. Run order: 1a → 1c (after 1a, or standalone) → 1b (independent).

**Spike 1a — MIDI co-read (OQ1, the crux).** `spike_midi_coread`
- *Setup:* FLX4 USB → Win11; Rekordbox in **Performance mode** owning the FLX4; a track loaded + playing so Rekordbox visibly reacts.
- *Steps:* open FLX4 input via (i) `midir` default **WinMM** backend, then (ii) `midir` **WinRT** backend; callback logs `(t_us,status,d1,d2)`; move one channel fader; watch our log **and** Rekordbox's on-screen fader.
- *PASS:* our process logs the fader CC **while** Rekordbox still moves its on-screen fader (both clients receive).
- *PARTIAL:* only WinRT opens (WinMM → `MMSYSERR_ALLOCATED`) → co-read possible, **pin the WinRT backend**.
- *FAIL:* both backends fail to open, or open but log 0 events while Rekordbox holds the port.
- *Log:* `op=spike.coread backend=<winmm|winrt> opened=<bool> events=<n> rbox_reacting=<bool> verdict=<PASS|PARTIAL|FAIL>`.
- *Branch:* PASS/PARTIAL → live controller capture viable. FAIL → **Option C** (virtual-MIDI bridge) or ship Option B without live controller capture.

**Spike 1b — audio-capture path (OQ10).** `spike_audio_loopback`
- *Setup:* FLX4 as the audio device; Rekordbox outputting master through it; audio playing.
- *Steps:* enumerate cpal input + output devices (log names); attempt cpal loopback `build_input_stream` on the FLX4 **render** endpoint (eRender → `AUDCLNT_STREAMFLAGS_LOOPBACK`); measure captured RMS over ~3 s; if silent, retry on any virtual-cable input + the FLX4 dedicated capture endpoint.
- *PASS:* some device yields non-silent buffers (RMS > −60 dBFS) tracking the playing audio → record that device name as the capture source.
- *FAIL:* every candidate returns silence (Rekordbox holds the device exclusive WASAPI/ASIO).
- *Log:* `op=spike.audio device=<name> mode=<shared|exclusive> rms_dbfs=<x> verdict=<PASS|FAIL> capture_device=<name|none>`.
- *Branch:* PASS → audio capture viable on the named device. FAIL → audio needs a documented virtual-cable setup step before video/clean-audio.

**Spike 1c — EQ-on-wire (OQ11).** `spike_eq_onwire`
- *Setup:* as 1a; if 1a FAIL, run standalone (FLX4 **not** owned by Rekordbox) to confirm EQ emits CC at all.
- *Steps:* full-sweep Hi, then Mid, then Lo, on deck A then deck B; log every CC `(status,cc,min..max)`.
- *PASS:* each of Hi/Mid/Lo emits a distinct CC with a continuous 0–127 sweep → data source for the EQ animation exists.
- *PARTIAL:* some bands emit, others don't.
- *FAIL:* EQ moves produce no CC (EQ is hardware-DSP, audio-first) → the headline Highs-cut **has no MIDI data source** on this controller.
- *Log:* `op=spike.eq band=<hi|mid|lo> deck=<a|b> cc=<n|none> range=<min..max> verdict=<PASS|PARTIAL|FAIL>`.
- *Branch:* PASS → full EQ animation. PARTIAL/FAIL → **Option A′** — animate everything on the wire **except** EQ; report "Highs raus" as not animatable for this model.

**Decision matrix — set the build branch from the 3 verdicts before Task 13:**

| 1a co-read | 1b audio | 1c EQ | Build branch |
|---|---|---|---|
| PASS/PARTIAL | PASS | PASS | **A** — audio + timeline + full controller video (incl. EQ) |
| PASS/PARTIAL | PASS | PARTIAL/FAIL | **A′** — same, video animates all-but-EQ (headline gesture flagged unavailable) |
| PASS/PARTIAL | FAIL | any | **B** — controller timeline + post-hoc levels ship; audio + video blocked until a capture device is found |
| FAIL | PASS | (standalone) | **C** — virtual-MIDI bridge for controller capture, else B-no-ctrl (audio + levels only) |
| FAIL | FAIL | — | **B-minimal** — manual rig setup (virtual cable + virtual MIDI) before anything past level analysis |

Same shipped code across all branches; they differ only in which Task-Queue blocks run (core always; video 13–15 only on A/A′).

### Files touched
- **New (Rust):** `src-tauri/src/audio/recorder/{mod,clock,audio_in,midi_in,collector}.rs` (capture), `recorder/hid_in.rs` (stub), `recorder/video.rs` (Option A), `src-tauri/resources/recorder/maps/{ddj-flx4,ddj-400,ddj-grv6}.json`, `src-tauri/resources/recorder/outline/ddj-flx4.svg`.
- **New (Python):** `app/recording_booth.py` (sidecar DB + levels + reconcile + REST), `tests/test_recording_booth.py`, `tests/test_recording_jsonl_schema.py`, `tests/test_recording_e2e.py`, `tests/perf/test_recording_render.py`.
- **New (Frontend):** `frontend/src/components/RecordingBoothView.jsx` (+ subcomponents under `components/recording/`).
- **New (docs):** `docs/research/mockups/recording-booth.html`.
- **Edit (Rust):** `audio/mod.rs:1-8` (+`pub mod recorder`), `main.rs:500-513` (manage + register), `Cargo.toml:33` (+`midir`,`midly`,`resvg`,`usvg`,`tiny-skia`; `hidapi` behind a deferred feature), `Cargo.lock` (committed).
- **Edit (Python):** `app/main.py` (include recording router), `app/analysis_engine.py` (expose a per-second helper if needed — reuse-only).
- **Edit (Frontend):** `frontend/src/main.jsx:71,140,893-962`, `frontend/src/config/constants.js`.
- **Edit (docs):** rust-index, backend-index, frontend-index, FILE_MAP, architecture, CHANGELOG.

### Testing
High-level (concrete cases in `## Test Plan`): JSONL schema round-trip with **raw bytes preserved** (replay G4); collector never blocks the audio callback (xrun guard); MIDI CC→`control_id` via FLX4 map; per-second level parity vs `analysis_engine`; reconcile maps history→deck windows read-only; routes `require_session` + `validate_audio_path` reject escape; resvg deterministic golden frame; ffmpeg arg-vector fixed + timeout; e2e B flow; render perf ≤1× realtime.

### Risks & rollback
- **Co-read = #1 risk (elevated for this gear).** FLX4/400/GRV6 are class-MIDI; WinMM is single-client → naive open fails while Rekordbox owns the port. Spike 1a tests WinMM **+ WinRT multi-client**. Fail → Option C (virtual-MIDI bridge) or defer controller capture. Plan branches on the spike; never assumes PASS.
- **Audio loopback exclusive/ASIO silence** — Spike 1b; fail → explicit loopback device / virtual cable, not `default_output`.
- **resvg perf** — stream-to-ffmpeg (no scratch) + diff-render + fps fallback (budget below).
- **Realtime writer xruns** — mandated `mpsc`→writer thread, never in callback.
- **Rollback:** fully additive — new module/routes/view + new on-disk dir + new sidecar DB. **No `master.db`/ANLZ/PDB/USB change.** Revert = drop `pub mod recorder` + command registrations + view tab + router include; delete `Recordings/` + `recording_booth.db`. No migration to undo.

## Threat Model

Touches: `require_session` (new routes), filesystem (wav/jsonl/mid/mp4 write + wav read), **read-only** `master.db` (history reconcile), subprocess (ffmpeg, Option A), user-supplied device-ids/paths. No secrets. **No new network surface** (live path = in-process Tauri events, not WS).

### Assets
- Recorded audio + timeline files (user content) inside `ALLOWED_AUDIO_ROOTS`.
- Rekordbox `master.db` (read-only for reconcile — must stay unmutated).
- Existing session bearer token (never logged).
- Attacker goal: read/write outside the sandbox; ffmpeg arg/shell injection; DoS via unbounded render; corrupt `master.db`.

### Trust boundaries
- Frontend → Python routes: Bearer `require_session` (`auth.py:116-140`); every path through `validate_audio_path` (`main.py:186-224`, `is_relative_to` at `:208`).
- Frontend → Tauri commands: device-id/path validated; output dir derived **inside** `ALLOWED_AUDIO_ROOTS`, not caller-chosen-free.
- Rust → ffmpeg: fixed arg vector, **no shell**, timeout (mirror `soundcloud_downloader.py:691-696`; avoid the no-timeout `services.py:279`).
- Python → `master.db`: read-only, no write, no `_db_write_lock` needed; parameterised/ORM only (no f-string SQL).

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | Tampering/Path — out path escapes sandbox (wav/jsonl/mp4) | `validate_audio_path` on every in/out path; Rust output dir constrained to `ALLOWED_AUDIO_ROOTS` | T8 |
| T2 | Spoofing — unauth caller hits recording routes | `Depends(require_session)` on all 4 routes | T8 |
| T3 | Injection — controller-map / session-id / filename into ffmpeg args | fixed arg vector, no `shell=True`, validated `session_id`, no user string in ffmpeg filtergraph | T9 |
| T4 | DoS — ffmpeg hang / unbounded render (≥100k frames, GB scratch) | subprocess timeout; stream-to-stdin (no scratch); frame-budget guard + fps fallback + user-cancel | T9, T12 |
| T5 | Tampering — reconcile corrupts `master.db` | read-only access; results stored only in our sidecar/JSONL; zero `master.db` mutation | T7 |
| T6 | Info-disclosure — set leaks outside sandbox / token in logs | files only in `ALLOWED_AUDIO_ROOTS`; never log token; existing `RedactingFormatter` scrubs paths | T8 |

### Residual risk
- Recorded audio captures whatever the user mixes (their copyright/responsibility — out of scope). Rekordbox-history read inherits rbox read quirks but is read-only → low blast radius. No new auth/network surface; realtime path is in-process Rust. Acceptable.

## Migration Path

Touches **file layout** (new) + **new sidecar DB**. No `master.db` schema, USB-export bytes, ANLZ/PDB, or existing IPC-contract change.

### Before → After
- **Today:** no recorder; no `Recordings/` dir; no `recording_booth.db`.
- **After:** `<ALLOWED_AUDIO_ROOT>/Recordings/<ts>_<name>/` holding `set.wav`, `set.jsonl`, optional `set.mid` / `set.mp4` (A), `meta.json`; sidecar `recording_booth.db` (index: id, path, created_at, dur_ms, controller, map_version, has_video, reconciled).
- **Existing-data handling:** none — net-new, additive. No existing data read or rewritten.

### Backfill / forward-compat
- Migration script: **none — additive.** `recording_booth.db` created lazily on first record (mirror `auth_db` lazy-init).
- JSONL versioned (`hdr.v`); readers gate on `v`; `raw{ch,cc,v7}` preserved so unmapped controls survive (replay-forward, G4).
- Old client reads new data: N/A (new view); a build without the view ignores the dir.
- Rollback: delete `Recordings/` + `recording_booth.db`; no schema to reverse.

### User-visible behavior during migration
- None. No downtime, no upgrade step, no backfill. First recording creates the dir + DB.

## Performance Budget

| Path | Budget | Measured today | Source |
|---|---|---|---|
| Realtime audio+MIDI capture (callback) | **0 dropped frames**; event→JSONL off-callback; writer-thread p99 < buffer period (~10ms) | untested (greenfield) | new — Rust bench |
| Live meter/control Tauri event push | ≤ 30 Hz throttled; ≤ 1 ms serialize/emit | untested | new |
| Post-hoc per-second level (60-min wav) | p95 ≤ 20 s (reuse `analysis_engine` RMS + 1s LUFS) | RMS/LUFS untimed | T12-adjacent perf |
| Track reconcile (read Rekordbox history) | p95 ≤ 3 s for ≤ 200 history rows | untested | new |
| **Video render** (60-min set, Option A) | **≤ 1.0× realtime ceiling** (≤ 60 min), target **≤ 0.3×** (≤ 18 min) @30fps; **0 PNG scratch** (stream to ffmpeg) | untested | T12 (`tests/perf/test_recording_render.py`) |

### Worst-case scenario
- **Input:** 3-hour set, 30fps, dense control activity.
- **Expected impact (naive):** ~324k frames; disk-PNG path = 30–150 GB scratch + > 3 h render single-thread (Adversarial 2026-06-01, "resvg perf").
- **Mitigation if exceeded:** stream raw RGBA → ffmpeg stdin (**no scratch**); diff-render only changed controls; fps fallback 30→15→10; parallel frame render across cores; hard frame-budget guard + user-cancel. Realtime capture is never affected (separate threads).

## API / UX Surface

### Backend (FastAPI) — all `Depends(require_session)`, pattern `main.py:775-776`
- New: `POST /api/recording/analyze-levels` — body `{session_path}`; `validate_audio_path` on the wav; returns `[{t_ms,rms,lufs}]`; appends `lvl` lines. No lock.
- New: `POST /api/recording/reconcile-tracks` — body `{session_id, t0_ms, t_end_ms}`; **read-only** Rekordbox history; returns `[trk]`; appends `trk` lines.
- New: `GET /api/recording/list` — recordings index from `recording_booth.db`.
- New: `GET /api/recording/{id}` — session detail (paths, dur, has_video, reconciled).
- Changed: none. **No new WebSocket** (live path = Tauri events).

### Frontend (React)
- New view `RecordingBoothView` + subcomponents (`recording/`: DevicePicker, RecordButton, LiveMeter, ControlActivityCanvas, RecordingsList, VideoPlayer[A]).
- New IPC — `invoke`: `list_midi_inputs`, `list_recording_inputs`, `start_recording`, `stop_recording`, `recording_status`, `render_recording_video`[A]; `axios`: the 4 routes; `listen`: `recording-meter` / `recording-control` / `recording-status` / `recording-error`.
- Changed: `main.jsx` (workspace + tab + lazy import + render block), `config/constants.js`.

### Tauri (Rust commands) — register `main.rs:502-513`
- New: `list_midi_inputs() -> Vec<MidiPortInfo>`; `list_recording_inputs() -> Vec<AudioDeviceInfo>`; `start_recording(opts) -> SessionId`; `stop_recording() -> SessionPaths`; `recording_status() -> RecStatus`; `render_recording_video(session_id, fps) -> PathBuf`[A]; dev-only `spike_midi_coread` / `spike_audio_loopback` / `spike_eq_onwire`.
- New events: `recording-meter`, `recording-control`, `recording-status`, `recording-error`.
- Changed signatures: none (existing `list_audio_devices` untouched).

### CLI / sidecar logs
- `op=recording.start session=<id> audio=<dev> midi=<port> map=<ver>`; `op=recording.stop dur_ms=<n> events=<n>`; `op=recording.levels session=<id> secs=<n> ms=<n>`; `op=recording.reconcile session=<id> matched=<n>/<total>`; `op=recording.video session=<id> frames=<n> fps=<n> ms=<n>`. Never log token; paths scrubbed.

## Telemetry

- **Log markers:** `op=recording.*` (start/stop/levels/reconcile/video) — see usage + render cost over time.
- **Counters:** recordings created; events captured/session; reconcile match-rate; video renders + avg ×realtime.
- **Health / state:** `GET /api/recording/list` count in the view; recorder state via `recording_status` + `recording-status` event.
- **User-visible:** live elapsed timer + level meter + control-activity strip during record; start/stop/render-done toasts; recordings list with `has-video` / `reconciled` badges.

## Test Plan

| ID | Layer | Test file | Case | Covers |
|---|---|---|---|---|
| T1 | rust | `recorder/collector` tests | event→JSONL writer drains `mpsc`, never blocks the audio callback (xrun guard) | Step 2 · Adversarial realtime-writer |
| T2 | rust | `recorder/midi_in` tests | FLX4 CC bytes → `control_id`; `raw{ch,cc,v7}` preserved verbatim | Step 2/3 · G4 |
| T3 | rust | `recorder/audio_in` tests | input stream → WAV; sample-rate + clock epoch stamped | Step 2 · G1 |
| T4 | rust | `recorder/video` tests | resvg renders one frame deterministically (golden) at a knob position | Step 9 · G3 |
| T5 | py | `tests/test_recording_jsonl_schema.py` | `hdr/ev/trk/lvl` round-trip; versioned; `raw` survives an unknown control | G4 |
| T6 | py | `tests/test_recording_booth.py` | `analyze-levels` parity vs `analysis_engine` RMS/LUFS on a fixture wav | Step 5 · G5 |
| T7 | py | `tests/test_recording_booth.py` | reconcile maps history rows → deck windows; `master.db` unchanged (read-only) | Step 6 · Threat T5 |
| T8 | py | `tests/test_recording_booth.py` | all 4 routes 401 unauth; `validate_audio_path` rejects sandbox escape | Threat T1/T2/T6 |
| T9 | py | `tests/test_recording_booth.py` | ffmpeg arg vector fixed (no shell); timeout enforced (mock) | Threat T3/T4 |
| T10 | js | `frontend/src/**/RecordingBoothView.test.jsx` | pickers populate via `invoke`; start/stop dispatch; `listen()` wires meter | Step 8 |
| T11 | integration | `tests/test_recording_e2e.py` | synthetic MIDI+audio session → `set.wav`+`set.jsonl`; levels+reconcile appended | full B flow |
| T12 | perf | `tests/perf/test_recording_render.py` (new) | 60-min synthetic render ≤ 1× realtime, 0 scratch | Perf row 5 |

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at the Approval Gate. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Keep tasks small — a task too big to review in one PR must be split.
Each task should map back to a Step in ## Implementation Plan and have ≥1 row in ## Test Plan.
-->

Each line: `(size · Step · Tests)` then **DoD** (merge bar) + **dep** (must-merge-first). Sizes S/M/L. Tick `- [x]` when the PR merges.

**Spikes first — hardware-gated, you run on the DDJ-FLX4. Decide A/A′/B/C from the decision matrix before Task 13:**
- [ ] Task 1 — Spike: MIDI co-read (WinMM **+** WinRT) while Rekordbox owns FLX4 — `spike_midi_coread` (S · Step 1a · OQ1 · diagnostic, no test row). **DoD:** verdict PASS/PARTIAL/FAIL logged per backend with event count + `rbox_reacting`; result in `## Implementation Log`. **dep:** none.
- [ ] Task 2 — Spike: audio-capture path (cpal loopback vs ASIO/exclusive silence; enumerate inputs) — `spike_audio_loopback` (S · Step 1b · OQ10). **DoD:** the device name yielding non-silent master RMS logged, or FAIL-all; verdict in log. **dep:** none.
- [ ] Task 3 — Spike: EQ-on-wire — `spike_eq_onwire` (S · Step 1c · OQ11). **DoD:** CC + sweep range for Hi/Mid/Lo per deck logged, or FAIL (EQ not on wire); verdict in log. **dep:** none (standalone if Task 1 FAIL).

**Core — Option B baseline (ships regardless of spike outcome):**
- [ ] Task 4 — Rust `recorder/{clock,audio_in}` + WAV via `hound` on confined thread (M · Step 2 · T1/T3). **DoD:** start/stop → valid `set.wav` at device sample-rate; shared `Instant` epoch stamped; no `unsafe impl Send`; `cargo test`+`clippy -D warnings` green. **dep:** none.
- [ ] Task 5 — Rust `recorder/{midi_in,collector}` + append-only JSONL writer thread (M · Step 2 · T1/T2/T5). **DoD:** MIDI CC → `ev` lines with `raw{ch,cc,v7}` preserved verbatim; collector drains `mpsc` on its own thread, **never blocks the audio callback** (xrun-guard test passes). **dep:** Task 4 (clock).
- [ ] Task 6 — Mapping schema + `ddj-flx4.json` + loader (+ `ddj-400`/`ddj-grv6` stubs) (M · Step 3 · T2). **DoD:** loader resolves CC → `control_id` + outline `{x,y,w,h}`; `map_version` present; schema documented; round-trip test. **dep:** none (parallel to 4/5).
- [ ] Task 7 — Tauri commands + events + `.manage` state (M · Step 4 · T10). **DoD:** `list_midi_inputs`/`list_recording_inputs`/`start_recording`/`stop_recording`/`recording_status` callable; `recording-meter|control|status|error` emit; `Result<_,String>`, no `unwrap` in fallible paths. **dep:** Tasks 4,5,6.
- [ ] Task 8 — Python `recording_booth.py`: sidecar DB + `POST /api/recording/analyze-levels` (M · Step 5 · T6/T8). **DoD:** `require_session` + `validate_audio_path` on the wav; per-second RMS/LUFS within ±0.5 dB of `analysis_engine`; appends `lvl` lines; 401-unauth test. **dep:** none (fixture wav).
- [ ] Task 9 — Python `POST /api/recording/reconcile-tracks` (read-only Rekordbox history) (M · Step 6 · T7). **DoD:** read-only over `[t0,t_end]`, **no `master.db` write / no `_db_write_lock`** (asserted by test); appends `trk` lines; manual fallback path. **dep:** Task 8 (sidecar DB).
- [ ] Task 10 — Recordings index + `GET /api/recording/list` + `/{id}` (S · Step 7 · T8). **DoD:** both routes `require_session`; return rows from `recording_booth.db`. **dep:** Task 8.
- [ ] Task 11a — React view shell: device pickers + record/stop + status (M · Step 8 · T10). **DoD:** pickers populate via `invoke`; start/stop dispatch (+ `confirmModal` on stop); tab registered in `main.jsx` (`buildWorkspaces`+`TAB_WORKSPACE`+lazy import). **dep:** Task 7.
- [ ] Task 11b — React live meter + control-activity canvas + recordings list (M · Step 8 · T10). **DoD:** `listen('recording-meter'|'recording-control')` drives a canvas reusing the `WaveformCanvas`/`DawTimeline` RAF pattern; list from `GET /api/recording/list`; constants in `config/constants.js`. **dep:** Tasks 11a,10.
- [ ] Task 12 — docs sync B: rust/backend/frontend-index, FILE_MAP, architecture data-flow, CHANGELOG (S · Step 10). **DoD:** indices + FILE_MAP + new architecture flow + CHANGELOG land; `regen_maps.py --check` green. **dep:** Tasks 4–11b.

**Headline — Option A (only if Tasks 1-3 → branch A or A′):**
- [ ] Task 13 — Rust `recorder/video.rs`: resvg→raw-RGBA→ffmpeg-stdin mux + outline SVG (L · Step 9 · T4/T12). **DoD:** deterministic golden frame at a knob position; streams RGBA to ffmpeg stdin (**0 PNG scratch**); ffmpeg subprocess **with timeout**; `set.mp4` muxes `set.wav`; EQ animated only on branch A (A′ skips EQ). **dep:** Tasks 5 (jsonl),6 (map/outline); gate 1a+1b PASS.
- [ ] Task 14 — `render_recording_video` command + frontend `<video>` player (M · Step 9 · T4). **DoD:** command on `spawn_blocking`; view plays `set.mp4` scrubbed against the timeline. **dep:** Task 13.
- [ ] Task 15 — perf test + render budget guard (S · Perf row 5 · T12). **DoD:** 60-min synthetic render ≤1× realtime, 0 scratch; frame-budget guard + fps fallback (30→15→10) + user-cancel. **dep:** Task 13.

**Branch/PR order:** spikes 1-3 → 4 → 5; 6 parallel → 7 → 8 → {9,10} → 11a → 11b → 12; then (post-gate, A/A′ only) 13 → {14,15}. Each task = 1 branch `routine/recording-booth-task-<N>` (`11a`/`11b` keep the suffix) = 1 PR.

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

- [x] Plan addresses all goals — G1 audio (T4), G2 capture (T5/6), G3 video (T13/14, spike-gated), G4 JSONL+raw+SMF (T5), G5 level+track-id (T8/9), G6 FLX4-first + extensible schema (T6), G7 sandbox + off-callback + `require_session` (Threat, T4/5/8).
- [x] Plan matches `## Original Idea` — audio record · controller-move capture · outline video w/ EQ animation · replay-capable file · per-second track+volume. Replay deferred per the user's own words (Non-goal). No scope-creep.
- [x] Open questions answered or deferred — OQ1/10/11 = the 3 spikes (Tasks 1-3, gate A/B/C); OQ2 resolved (MIDI for FLX4/400/GRV6); OQ3 hand-author from FLX4 reference facts; OQ4 PDL=Export-only → post-hoc reconcile (Rekordbox confirmed); OQ5 both (fader event + measured level); OQ6 resvg offline; OQ7 JSONL+SMF; OQ8 cpal input; OQ9 PDL slimming **dropped** — not needed (Rekordbox history via existing pyrekordbox, no `python-prodj-link`).
- [x] Prior Art referenced — greenfield; reuse `analysis_engine` metering, ffmpeg subprocess pattern, canvas render, `hound` WAV — not duplicated.
- [x] Threat Model present + each threat has a test — T1→T8, T2→T8, T3→T9, T4→T9/T12, T5→T7, T6→T8.
- [x] Migration Path present + rollback documented — additive, lazy sidecar DB, delete-to-rollback, no `master.db`.
- [x] Performance Budget set + worst-case documented — realtime 0-drop; render ≤1× realtime stream-no-scratch; 3h worst-case mitigated.
- [x] API / UX Surface enumerated for every layer — 4 routes (`require_session`), 6+ Tauri commands + 4 events, 1 view, log markers.
- [x] Telemetry defined — `op=recording.*` markers + counters + live UI status.
- [x] Test Plan covers every Threat + Step + Perf row — T1-T12 mapped.
- [x] Task Queue items small + independently committable + reference Steps + Tests — 15 tasks, spike-first, 1 PR each.
- [x] Dependencies audited — `midir` MIT / `midly` Unlicense-MIT (low); `resvg`/`usvg`/`tiny-skia` MPL-2.0 file-copyleft (med, OK — no app-wide infection); `hidapi` deferred behind a feature; `Cargo.lock` committed (Schicht-A).
- [x] Risk mitigations defined — co-read spike-gated + Option C fallback; loopback explicit-device; resvg perf stream/diff/fps; realtime writer threading.
- [x] Rollback path clear — fully additive; revert module + routes + view + dir + DB.
- [x] Affected docs identified — rust/backend/frontend-index, FILE_MAP, architecture, CHANGELOG.

**Reviewer note (2026-06-01):** PASS (15/15) with one loud caveat carried to the Approval Summary — the user's controllers are **all class-MIDI** (FLX4/400/GRV6), landing on the harder co-read path (WinMM single-client). Co-read (Task 1) gates the headline; the build branches A/B/C on the 3 spike results. Live track-id is **unmet** (Performance mode = no PDL) → post-hoc Rekordbox-history reconcile only. Live status uses **Tauri events, not a WebSocket** — removes the `require_session_ws` surface the Constraints section had assumed.

**Rework reasons:**
- none.

## Approval Summary

- **What it does:** Records your DJ sets as far more than audio. It captures the master sound to one lossless file **and** logs every move you make on the controller — channel faders, the Hi/Mid/Lo EQ, crossfader, play/cue/pads, jogs — each with exact timing. From that it can render a video of a controller outline that replays your gestures (e.g. the Highs knob visibly turning down on a cut) perfectly in sync with the audio. It also saves a detailed timeline file rich enough that the set could one day be re-performed automatically (that auto-replay is intentionally **not** built — only the file format supports it).

- **What you'll notice:** A new **Recording Booth** tab. Pick your audio input and controller (DDJ-FLX4 first, then DDJ-400 / Groove6), hit record, and watch a live level meter plus live control activity while you play. Hit stop and you get a folder containing: the audio, the timeline file, and a per-second volume track. Track names are filled in afterwards from your Rekordbox history. If the hardware tests pass, you also get the synced controller-outline **video**.

- **Two honest caveats — please read before approving:**
  1. All three of your controllers talk **MIDI** to Rekordbox, and Windows normally lets only **one** program hold a MIDI port at a time. So "recording your moves *while* Rekordbox is driving the controller" is the single biggest unknown. That's why the plan's **first three tasks are quick hardware tests on your DDJ-FLX4**. Their result decides the outcome: all pass → we build the full vision including the video; if the MIDI co-read or the audio capture fails → we ship audio + timeline + per-second levels now, and either add a small one-time virtual-MIDI setup step or defer the video.
  2. **Live "now playing" track info is impossible** in Rekordbox's Performance mode (the protocol that carries it only runs in Export mode). Track names are therefore reconstructed *after* the recording from your Rekordbox history — accurate, just not live.

- **Scope:** ~13 new files + ~7 edits · 15 tasks (3 spikes + 9 core + 3 video) · effort **L** · risk **medium**, concentrated in the 3 hardware spikes.
- **Rollback:** Fully additive — nothing touches your library, `master.db`, or USB exports. Undo = remove the tab + module and delete the Recordings folder.
- **Mockup:** see `## Mockup` below.

## Mockup

### UI — mockup file
- [`docs/research/mockups/recording-booth.html`](../mockups/recording-booth.html) — Recording Booth view. **Left:** device-picker panel (audio input · MIDI controller · controller-map) + a big record button with live elapsed timer. **Center:** live meters (Hi/Mid/Lo + master) and a live control-activity strip that lights up as you move faders/EQ/pads. **Right:** recordings list with `has-video` / `reconciled` badges. **Bottom (spike-gated, Option A):** the controller-outline video player — an animated DDJ-FLX4 outline whose knobs/faders sit at their captured positions, scrubbed in sync with the audio. The mockup also renders the "audio + timeline only (Option B)" state so both possible outcomes are visible.

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
