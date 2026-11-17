# Syndicate — performance + control reference

## 1. Source + copyright note
- Source: Syndicate user guide (Untitled Audio, commercial DJ/performance app), build 0.2.0-RC2+913 era. Chapters read: mixer/FX (7), MIDI+OSC clips (9), Arrange (10), Perform/clock/NET (11), Settings (12), mapping (13), OSC API (14), troubleshooting (16), changelog (17).
- All content paraphrased. No passages copied. Cites `syndicate:§<n.n>` = guide section.
- Purpose: idea mine for LMS. LMS = library manager + USB exporter first; DAW editor second. Most Syndicate features are live-performance → relevance rated honestly in §12.
- Shape of Syndicate: 4 decks, 4-ch mixer, MIDI/OSC clips, 4-track arrangement, shared musical clock. Targets live/AV performers, not CDJ-export DJs.

## 2. Mixer + signal flow
Per-channel chain (`syndicate:§7`, §12.4):
```
deck -> TRIM(-6..+6dB) -> EQ(3-band full-kill) -> FILTER -> PRE inserts(VST3)
     -> [CUE tap, pre-fader] -> VOLUME(fader curve) -> POST inserts
     -> dest: MASTER | NONE | hw stereo pair (EXT OUT)
MASTER bus: sum -> LIMIT(-1 dBFS peak, 2ms lookahead, before master vol) -> master vol -> master out pair
CUE bus   : channel CUE taps (+ metronome/previews if cue on) -> MIX knob blends Cue<->Master -> cue out pair
```
- Trim has no own knob: modifier-drag on volume dial; shows as inner ring (`§7.1`).
- Filter/EQ share one knob row; click title toggles view; both keep state when hidden.
- EQ: Cytomic 3-band, full kill at min, 0 dB center, +6 dB max. Click band label = kill toggle. Xover defaults 250 Hz / 2.5 kHz, user-editable (`§7.1`, §12.4).
- Filter types (global setting, per-arrangement-track override): LP/HP+RES (bipolar, resonance) | ONE KNOB (sweep + WIDTH = LP/HP gap; res auto-rises as width narrows) | LP/HP (two independent knobs, no res). Mapping targets Filter1/Filter2 stay valid across types (`§12.4`, §13.6).
- Filter ranges: LP 100 Hz–16 kHz, HP 50 Hz–8 kHz.
- Fader curves: LINEAR(dB), CONSTANT POWER, DIPPED, FAST CUT. Advice: same curve in rehearsal + show (`§7.5`).
- Fader-start key (F): raise fader = start deck on quantize boundary; closed = pause.
- Mute/solo: when another ch soloed, mute lights as "suppressed"; click clears solo.
- Crossfader: only 2-deck perform; equal-power; on/off switch disables mouse+MIDI+OSC xfader input, levels stay; re-enable picks up current balance. Delta mixer (3 decks, triangle pad) + Vector mixer (4 decks, XY pad), equal power (`§7.3`).
- Gain staging recipe (`§7.7`): EQ/filter neutral -> set trim for headroom on VU -> balance with volume -> watch master. Limiter cannot repair clipping inside a plugin.
- VU: dotted, top dot red; header warns on master clip.
- Output routing (`§7.6`, 7.8): MASTER = internal mix; hw pair = external mixer/recording. Settings → MIXER → OUTPUT ROUTING = two-lane diagram; per stage (TRIM/EQ/FILTER/VOLUME) apply or bypass on EXT OUTPUTS. Default EXT: EQ+FILTER applied, TRIM+VOLUME fixed 0 dB (external mixer owns level). Bypassed stage greys out and ignores mouse/MIDI/OSC. PRE FX, mute, solo always apply. VST3 build = DAW owns device, always full chain.
- Recipes: internal mixer + headphones (master 1/2, cue 3/4, channels to MASTER); external mixer (ch1->1/2, ch2->3/4..., reserve pairs for master/cue); watch interface direct-monitor duplication.
- Booth: no separate booth bus. Master + Cue + direct pairs only.
- Limiter nuance: global header LIMIT in dev build vs per-arrangement toggle in public RC2; direct hw outs + cue get matching delay but no limiting; stems never limited.

## 3. FX
- Architecture: VST3 inserts per channel, max 4. PRE (post EQ/filter, pre-fader, audible in cue) or POST (after fader). PRE always before POST (`syndicate:§7.4`).
- Window: + ADD INSERT (list filtered by Settings → VST enabled checkmarks, grouped by maker, search/category), drag-reorder, ON bypass, EDIT, menu (replace/move/remove), BYPASS ALL.
- Macros: 8 per channel, each -> any param of any insert; MAP = move a control to assign; label shows owning insert. Mappable to MIDI/keyboard (`Mixer n / FX Macro 1-8`) + fixed OSC addresses.
- Presets: whole chain (order, PRE/POST, state, bypass, macros) saved as encrypted `.sdfx` in Database/FX. Saved "States" also embed channel chains.
- Latency compensation per insert up to an alignment budget; window shows chain latency, orange for late part.
- Failure handling: in-process hosting (lowest latency) -> plugin crash can kill app; erroring effect bypassed + red. Missing plugin keeps slot + settings, shown missing. Intel-only plugins unsupported on Apple Silicon inserts.
- Instruments (VSTi) differ: run in separate helper processes, crash-isolated (`§9.5`). Scan also per-plugin helper process, 10 s "waiting for licence" hint, 90 s auto-skip, ISSUES list with retry.
- Global kill switch ENABLE VST/VSTi: saves + unloads all, removes related latency. Built-in native FX removed in favour of VST3.
- Per-plugin classification override (Instrument/Effect/Automatic).

## 4. MIDI / OSC clips
MIDI clip `.sdc` (`syndicate:§9`):
- = imported SMF + loop + cues + quantize + key + metadata + destination (MIDI device+ch OR VST3 instrument + patch) + optional OSC lanes + 8 instrument macros.
- Editor level = quantize (1/1..1/32), loop (beat-anchored, whole beats), cues (normal/loop, rename, drag-snap), routing. NO note/velocity editing — write in DAW, import.
- Autosave on leave; no Save button. Undo/redo for quantize/loop/cue.
- Deck controls: transpose, swing 0-100%, length 1-200%, early/late ±100 ms, restart, cues 1-8, fader start, quantize.
- Stuck-notes policy: note-offs on jump/stop/reroute/unload/quit; recommend all-notes-off mapping for hanging synths.
- Render clip -> WAV/AIFF 48k/24-bit via VSTi only; optional import to library + `.sdd` cue sidecar; no overwrite (numeric suffix). Perform-deck "R" button renders in background with separate instance, then crossfades deck onto the rendered track at same position (`§9.5`).
- Patches stored in Database/VST3 States; Arrange lane picks up clip's latest instrument/patch.

OSC clip `.oscClip` (`§9.9`):
- Control data, not audio. 1 envelope (0..1 normalised, address/type int|float/range) + N timed message lanes. Sent to 5 senders A–E (hosts/ports in Settings → OSC).
- 34 factory shapes (Basic: sine/tri/ramp/pulse; Creative: steps/easing/bell/AD/bounce/S&H), 1-bar loops, locked until unlocked; COPY TO CUSTOM SHAPES. Curved shapes use authored Bezier anchors.
- Reuse: drop on track OSC lane, Arrange OSC lane, or a parameter-automation lane (only normalised shape used; address ignored).
- Deck overrides (sender buttons, address) are live, do not rewrite the library clip.
- Pitfall: message clips re-fire on every loop pass; scene triggers belong on a non-looped timeline.
- Browser: fixed roots MIDI Clips / OSC Clips; TYPE column.

## 5. Arrange
(`syndicate:§10`)
- 4 tracks total (each audio OR MIDI/VST, any mix) + unlimited OSC ENV + OSC MSG lanes. File `.sda`. F4.
- Tools (radio group): Move (modifier-drag copies), Split, Fades. Fade shapes LIN/LOG/EXP, vertical drag bends. FADE EDGES = auto 2 ms min fade on every clip edge.
- Placement: drop over clip overwrites, keeps uncovered remainder; clips repeat with source timing; edits live during playback.
- Split at selection / cuepoints (source track cues) / marker.
- Automation: one shared lane per track, curves overlaid in own colours; focused curve solid, others dashed; eye = hide (still plays). Targets audio: volume, EQ H/M/L, Filter1/2, pitch (semitone snap); VST: macros 1-8. Bezier-style segment bend. Per-parameter enable/disable; READ MACRO AUTOMATION (read off = live controller takes macro).
- LOCK AUTOMATION: automation fixed in time/read-only while clips move/split/delete. Unlocked: automation travels with clips.
- Per-track filter type override (cycle GLOBAL -> RESONANT -> ONE KNOB -> LP/HP).
- Markers: START at 0 + coloured named markers (uppercase); become pageable buttons on arrangement deck; can export as cues.
- Render range auto-fits content; set via modified clicks on ruler; cyan brace.
- Render: STEREO MIX or MULTITRACK (stem per track), WAV/AIFF, add to library into auto "Renders → Arrangements" playlist, markers -> cuepoints. Includes tempo markers, automation, fades, mute/solo, DSP. VST tracks rendered from timeline zero (preserve held notes/FX history), latency compensated; missing plugin aborts render.
- Arrangement as deck object in Perform (`§10.8`): marker buttons, per-track trims + routing. In Perform Loop, markers = region boundaries.

## 6. Clock + sync (Link / NET)
(`syndicate:§11.4-11.5`)
- One shared musical clock; exactly one owner. Everything follows: SYNC decks, quantized launches, metronome, MIDI clips, samplers, arrangements, Link.
- Owners: header (default) | a deck (deck MASTER) | another machine (NET, header shows FOLLOW, local tempo locked). Status: MASTER / FOLLOW / NO MASTER / OFFLINE.
- Auto handoff: first loaded deck becomes master (pitch reset to native BPM); master stops/ejects -> lowest-numbered playing synced deck, else header.
- Master deck turns its own SYNC off (master does not follow).
- Wallclock lock: header is only possible owner; no auto handoff; decks may still SYNC to header. For click/band/MIDI-gear/lighting/long arrangement sets. Off for DJ mixing. Auto-claims NET clock at start if none exists, never steals.
- Range 20–999 BPM hard floor = Ableton Link clamp; below it Link and local clock would drift. Option LIMIT MIN BPM TO 20 applies the floor to free-running decks so handoffs don't jump.
- Quantize: global (header) vs per-deck override; NONE = immediate; launch waits for boundary (1/4 etc.). Quarter-note boundary != bar/phrase start — verify phrase alignment. Pause not quantized. Sync settings: BPM MULTIPLIER RETAINS CLOCK, PHASE CORRECTION TRIGGER|HOLD, RESYNC RATE.
- Backspin/reverse never move the clock backward.
- Ableton Link: always on, joins sessions automatically; tempo + bar phase only, NO start/stop sync. Only clock owner sends tempo. Panel: peer count, 4-beat bar progress, RAMP (catch-up). Device output latency compensated.
- Syndicate NET (off by default): LAN-only, clients list (role/interface/last-seen), master can disconnect clients, MAKE MASTER claims clock, clean-quit handoff prefers synced playing app. Library share (read-only) + remote tracks streamed in verified chunks; "Sync Library" copies tracks/playlists/cues/grids/waveforms/artwork/clips/arrangements with checksum, preserves last good catalogue on failure; library source selector LOCAL / SYNCED / host / AUTOMATIC. Pairing + encryption currently disabled -> trusted LAN only.
- VST3 plugin build: DAW transport owns clock; 4 stereo outs; MIDI out single or separate per deck (host-dependent); no Link, no VST hosting.
- Before-doors checklist (`§11.7`): save/back up; mount real drives + load representative items; trace audio at show rate/buffer; verify mapping + MIDI/OSC dests; choose clock owner; rehearse timed output; recovery plan (spare output, local copies, rendered audio); power/sleep off.

## 7. Settings catalogue
Nine pages; Save and Close / Cancel; unsaved prompt on window close; audio routing applies immediately (`syndicate:§12`).
| Page | Notable |
|---|---|
| GENERAL | skin (6) + light mode; highlight colour; 8-colour cue palette (deck colours from slots 1,3,5,7); waveform SIMPLE/RGB/3-BAND; browser app/control mode; track history + play counts; suppress warnings; controller-perform mode; folders (rendered audio, backups — backups must be outside app + db dirs); no db folder chooser |
| AUDIO | driver/out/sample rate/buffer; test tone; master + optional cue pair; named output pairs; status shows buffer ms, driver latency, underruns |
| DECKS | cue behaviour (schedule only), default loop, autoplay on load, pitch lock, tape stop (25 ms, jitter, pitch mode), wide pitch, Camelot key, min-BPM limit, sync opts, Elastique (algo, startup quality, formant mode/detail, stereo mode) |
| MIXER | output-routing diagram, filter type, EQ crossovers (+DEFAULTS), fader curve |
| MIDI | enable inputs (only enabled can learn), enable outputs (for clips only), refresh, per-deck default out device+ch |
| OSC | enable input, listen port 9090, status, 5 senders A–E |
| OSC FEEDBACK | dest IP + port 9096, resend state, subscription picker |
| DATABASE | db reveal, Rekordbox XML import, Lexicon import (+which side owns cues/grids), clear/full reset, USB initialize (mac exFAT) |
| VST | global enable, scan folders, scan with isolation, ISSUES list, instrument/FX checklists |

## 8. Controller + keyboard mapping
(`syndicate:§13`)
- Catalogue > 1000 controls over areas: DECKS (~230/deck, filters PLAYBACK&SPEED, CUES, LOOPS&SKIPPING, PITCH&PHASE, WAVEFORM + sampler/arrangement/clip player), MIXER (ch1-4), HEADER, BROWSER, ARRANGEMENT (track vol + macros), LOOP PERFORM.
- Inputs: MIDI note, CC 0–119 absolute, pitch wheel 14-bit, computer keys with modifiers. 1 control : N inputs, 1 input : N controls (amber xN badge).
- Not supported: CC 120-127, aftertouch, program change, NRPN, 14-bit CC pairs, relative/encoder CC, soft takeover/pickup, shift layers/banks, built-in controller presets, ANY LED/motor feedback over MIDI.
- Quick learn: header MAP key; all mappable controls tinted; click control -> move hardware; adds, never removes; refuses only exact duplicate pair. Some controls learn-only via this path (FX key, BYPASS ALL).
- Mapping page: three columns (profile+control list | assignments with LED status green/aqua/grey/red-unavailable | learn+configure). Per assignment: enabled, toggle-on-press, invert, min/max (0-100%), response chart, recent-input log. While page open, inputs are shown but do not fire.
- Control types (fixed, decide behaviour): Value, Button, Trigger, Momentary, Selection (spread options across range), Step (invert = back), Bend. Non-value types: any value >0 = pressed.
- Profiles `.sdcmap`: autosave with app + export/load; max 512 assignments / 1 MB; failed load keeps current. Migration: old OSC assignments dropped (OSC is fixed API), retired filter targets skipped.
- Keyboard: modifier combos distinct; works in Perform + Loop Perform only; not while typing/dialog/learn; mapped key beats built-in shortcut; autorepeat ignored; focus loss releases; Escape unmappable.
- Flood protection: if MIDI outruns handling, release all held controls + status warning, mappings stay.
- Hardware: no list of supported controllers; generic MIDI learn. Former DDJ-FLX4 preset retired into plain assignments. Feedback goes via OSC only.

## 9. OSC API
(`syndicate:§14`)
- Transport: UDP, listen port default 9090 (status shows port-in-use error). Master switch off = no receive, no feedback, no lane senders.
- Fixed address per control, no mapping. ~594 addresses. Configurable ADDRESS ROOT (default `/Syndicate/`, letters/digits/-/_/. , <=48 chars) so multiple machines get own prefix; old root stops working at once, no alias.
- Built-in OSC API window: area filter, search, click-to-copy address, live highlight of incoming value, last 5 messages incl. malformed in red, example per address.
- Rules: case-insensitive; no wildcards; <128 bytes; one int32/float32 arg (3 multi-arg routes); string/no-arg/NaN ignored; bundles applied in order, time tags ignored; route no-ops if control unavailable (e.g. header BPM when a deck owns clock).
- Argument kinds: Value (0..1 or native units, clamped) | Switch (>=0.5 = on, absolute not toggle) | Trigger (non-zero fires) | Hold (1 press / 0 release) | Step (signed int = direction+amount) | Bend (±1 then 0) | Index (0-based list, clamped).
- Namespace tree:
```
/Syndicate/Header/{Mode,Browser,PerformanceView,MasterSection,Decks,Metronome,LoopPerform,MetronomeVolume,BPM,BPMStep,TempoBend,Quantize,MasterVolume,CueVolume,CueMix}
/Syndicate/Browser/{Up,Down,Left,Right,Enter,Back,L1..L4}
/Syndicate/Deck/{1-4}/...            track + arrangement decks
/Syndicate/Deck/{n}/Clip/...         MIDI clip decks
/Syndicate/Deck/{n}/Sampler/...      sampler decks (8 lanes)
/Syndicate/Deck/{n}/Automation/{Restart,Previous,Next}
/Syndicate/Mixer/CH{1-4}/...
/Syndicate/Arrangement/Lane{1-4}/{Volume,Macro/1-8}   (editor, not deck)
/Syndicate/Feedback/Resend           (outbound state mirror lives under same tree)
```
- Key addresses (paraphrased):
| Address | Kind | Effect |
|---|---|---|
| Header/BPM | value 20–999 | master tempo (only if header owns clock) |
| Header/Quantize | index 0–7 | none, 2 bar … 1/32 |
| Header/TempoBend | bend | nudge tempo while held |
| Deck/n/PlayPause · Playing | trigger · switch | toggle · absolute play |
| Deck/n/HotCue | 1–2 ints | tap cue 1–8; 2nd arg 1/0 = hold |
| Deck/n/SetCueLoop | int | launch cue as loop to next cue |
| Deck/n/TempoSync · TempoMaster | trigger | toggle sync / master |
| Deck/n/TempoSlider | value -1..1 | pitch fader, 0 = native |
| Deck/n/BeatSkip · BarSkip | step | signed beats / bars |
| Deck/n/SlipLoop/{size} | hold | slip loop 1/32 bar … 4 bars |
| Deck/n/PhaseBend | bend | early/late nudge |
| Deck/n/WaveformSeek | value 0–1 | quantized seek |
| Deck/n/Quantize | index 0–8 | 0 = use global |
| Deck/n/Sampler/LaneSet | i,s,f | set any lane param w/o changing selection |
| Mixer/CHn/Volume | value 0–1 | maps to -60..0 dB |
| Mixer/CHn/Trim | value | 0=-6, .5=0, 1=+6 dB |
| Mixer/CHn/EQ/{High,Mid,Low} | value | 0.5 neutral |
| Mixer/CHn/Filter1 · Filter2 | value | meaning follows filter type |
| Mixer/CHn/Output | index | 0 master, then enabled pairs |
| Mixer/CHn/FX · FX/Macro/1-8 | switch · value | chain bypass · macros |
- Feedback (`§14.10`): separate dest IP + port (default 9096), per-value subscription tree (all 4 decks/channels per item), send-on-change only, time at most 1/s, beat-clock messages on every beat (`Header/Clock` 1–4, `Deck/n/Transport` bar+beat), cue events instant (`CuePress`, `CueFire`, `CuePass`), meters, `TrackInfo` (title/artist/key/BPM/duration/bars/type), `Cues` (8 colour+name pairs), `ColorPalette` on every resend. Resend via button or `/Feedback/Resend`. Enabled-flags (`Filter1Enabled`) tell surface which knobs apply.
- Outgoing authored OSC (`§14.11`): lanes in tracks/clips/arrangements -> 5 senders A–E (default 127.0.0.1:8001-8005); envelopes send on change only, scaled min..max, int or float; messages send text.
- Design lessons: absolute Switch (idempotent) beats toggle for network control; Hold needs explicit release; separate in/out ports avoid loops; fixed namespace + in-app browser removes learn step.

## 10. Troubleshooting patterns
(`syndicate:§16`) Rule of thumb in the guide: timing problems = grid; silence = routing. Check those first.
| Symptom | Cause class | Pattern to steal |
|---|---|---|
| crackles | buffer / power saving | raise buffer first; test at show rate; show underrun count + driver latency in UI |
| no sound / no cue | master pair, ch output NONE, mute, cue disabled, cue send is pre-fader | "follow the signal" walk: loaded -> playing -> meter moves -> dest -> device |
| sync drift, off-beat launch | wrong BPM / grid start / missing tempo markers | fix in grid/tempo-marker editor, not in sync settings |
| MISSING track | file moved / drive offline | dedicated relink tool (problems list, relink all found) |
| MIDI device absent | OS permission/driver/port held by other app | per-OS hint + REFRESH |
| mapping does nothing | input disabled, channel mismatch, control not on screen | status line + RECENT INPUT log shows NOT MAPPED |
| OSC never arrives | firewall, port, subnet | STATUS line, incoming-message monitor with sender IP |
| plugin missing | crashed/timeout/skipped/wrong arch | ISSUES list with reason + retry + scan log |
| controls greyed | EXT OUTPUT stage bypassed | show flow diagram; grey + ignore input consistently |
| USB disabled | no validated library on mount | do not init drive to diagnose; wait for validation |
| track edits not saved | write failed | RETRY SAVE + disk/permission check |
| offline licence expiry | 60-day token | refresh once online |
- Recovery doctrine (`§16.2`): prepared local media/render + spare output; do not rescan plugins mid-set; State restores content/mixer, not audio device or external gear; resume at known cue after checking clock owner.
- Bug report template: OS, app version (About), exact error, repro steps, library report export.

## 11. Roadmap signals
(`syndicate:§17`; releases 0.1.904 -> 0.2.0-RC2, Oct 17–22 2026: very fast cadence, ~10 builds in 6 days)
- Direction = performer + AV hub, not library tool: OSC clips/AutomationDeck (clock-synced control data to lights/visuals), VSTi tracks + offline rendering, clip-based MIDI editing, Bezier shapes, Engine Mode (tiny window, keeps MIDI/OSC alive).
- Library side grows too: SEND TO USB (own self-contained USB library + checksum catalogue), Lexicon API import, Rekordbox XML import, M3U/M3U8 import/export, tag editor redesign (tile tags, ALL/ANY filters, merge), multi-select playlist moves, progressive 3-band waveform for USB/network, library over NET.
- Hardening trend: quit-confirm when unsaved, drop legacy-format compat paths (fresh-library policy), OSC send off-lock + backoff for unreachable targets, one-sample cue/note alignment, device-latency-aware scheduling.
- Removed over time: native FX (-> VST3), MIDI-clip half/double speed, learned OSC mappings (-> fixed API), DDJ-FLX4 preset, per-param filter targets (-> Filter1/2).
- Read: competitor is converging on "USB export + library import/export + sharing" = LMS's home turf; their USB export is proprietary (not CDJ/Pioneer).

## 12. Gap analysis vs LMS
Relevance: H = fits library/USB/editor mission, M = useful to DAW editor, L = live-performance, out of scope.
LMS refs from `docs/features/*.toml`; `python scripts/feature_map.py --who <id>`.
| Item | Syndicate | LMS (feature id / file) | Idea / action | Rel |
|---|---|---|---|---|
| Live mixer (4 ch, EQ, filter, xfader) | full | none; DAW has control strip only (`dj-edit-daw`, `DawControlStrip.jsx`) | none for performance; borrow EQ kill + curve ideas for DAW track strip | L |
| Per-clip/track EQ + filter in editor | per-lane EQ/filter, automatable | `dj-edit-daw`, `daw-state-reducer` | add 3-band kill EQ + one-knob filter lane to DAW render (also in `rust-offline-render`) | M |
| Gain staging / trim / limiter | trim ±6 dB, master limiter -1 dBFS in export | none (`daw-export` WAV/MP3/FLAC) | export-time true-peak limiter + trim; pairs with loudness analysis | M |
| Output routing master/cue/booth | stereo pairs, cue mix | `audio-output-device-picker` (partial) | single device pick enough; cue/master split only if live-mode ever planned | L |
| VST3 insert hosting | 4/ch, macros, crash-isolated VSTi | none | out of scope; Rust stack could host later. Isolation + scan-ISSUES pattern worth noting | L |
| MIDI clips | .sdc, cues, loop, render to audio | none | out of scope; "render item to audio + sidecar cues + auto-import" pattern reusable for DAW edits | L |
| OSC clips / lanes | envelope/message lanes -> A–E senders | none | out | L |
| Arrange (timeline, markers, fades) | 4 tracks + OSC, fade shapes, render stereo/stems | `daw-timeline-canvas`, `dj-edit-daw`, `daw-export`, `rbep-projects` | fade curve LIN/LOG/EXP, FADE EDGES 2 ms anti-click, markers -> cue export, multitrack stem render, render-range auto-fit, lock-automation | M |
| Markers -> cues on rendered track | export as cuepoints into library | `daw-cue-loop-grid-edit` (partial), `daw-export` | write DAW markers/cues into exported file sidecar / library cues | H |
| Auto-add render to library playlist | Renders → Arrangements | `daw-export` (file only?) | "add to library" checkbox + auto playlist | H |
| Master tempo / wallclock / quantize | shared clock, 20–999 BPM | `analysis` BPM, `bpm-octave-disambiguation` | no live clock; note 20-BPM floor / tempo markers concept for editor grid | L |
| Ableton Link | tempo-only, always on | none | out | L |
| Syndicate NET (LAN clock + library share) | LAN library sync, checksum, read-only share | `paired-device-tokens` (phone pairing), USB export | idea: LAN library share to phone via paired tokens; checksum-verified sync pattern | M |
| Settings catalogue | 9 pages, save/cancel/unsaved prompt, live colour preview | `settings-panel`, `settings-backend-store`, `appearance-settings` | adopt: unsaved-changes prompt on close, folders for renders + backups, test-output tone | M |
| Backups folder (must differ from app dir) | explicit | `rekordbox-write-backups` | validate backup dir != db dir | H |
| MIDI mapping (learn, types, profiles) | 1000+ controls, .sdcmap | none | out for now; if DAW transport gets MIDI: Trigger/Momentary/Value/Step types + learn UX | L |
| Keyboard mapping | learn, modifiers, priority over built-ins, not while typing | `keyboard-shortcuts` (DAW only, no global layer) | extend: global scope, conflict view (N controls per key), profile export/import, response of "mapped key beats default" | M |
| OSC API | fixed 594 addrs, root prefix, feedback | none; backend REST in `docs/backend-index.md` | no OSC; but "self-documenting API viewer with live incoming monitor" = dev-tool idea | L |
| Troubleshooting table | symptom/cause/fix + monitors | `.claude/rules/troubleshooting.md` (dev-facing) | in-app Health/Diagnostics page: sidecar up, ffmpeg found, audio device, last errors, export report | H |
| Missing-file relink | PROBLEMS -> RELINK ALL FOUND | `library-health-filters` (partial) | verify relink-by-search exists; add "relink all found" | H |
| M3U/M3U8 import/export | ordered, abs/rel/URL, missing placeholders | none found | add M3U import/export | H |
| Rekordbox XML import / Lexicon import | yes | rekordbox read via master.db | Lexicon import low demand; XML import as safe non-DB path (no master.db write risk) | M |
| Tag editor (tiles, ALL/ANY, merge) | yes | `mytag-management` | tag merge + ALL/ANY filter + usage counts | H |
| Track history / play counts | dim played rows, persistent counts | none | optional "recently played / exported" markers | M |
| Controller-hardware feedback | OSC only, no MIDI LED | `recording-booth` (research, DDJ-GRV6) | note only | L |

## 13. Top ideas for LMS
Ranked, value/effort (H/M/L):
1. M3U/M3U8 import + export with missing-file placeholders — value H / effort L.
2. In-app Diagnostics page (symptom->cause table style: sidecar, ffmpeg, device, last errors, report export) — H / M. Matches `troubleshooting.md`.
3. DAW export: "add to library + auto Renders playlist" + markers written as cuepoints (sidecar/library cues) — H / M (`daw-export`, `daw-cue-loop-grid-edit`).
4. Missing-file RELINK flow: scan problems, relink all found — H / M (`library-health-filters`).
5. Tag editor: merge tags, ALL/ANY filter, usage counts — H / M (`mytag-management`).
6. Export-stage trim + true-peak limiter (-1 dBFS) with lookahead, optional — M / M (`daw-export`, `rust-offline-render`).
7. DAW fades: LIN/LOG/EXP curves + 2 ms edge fade to prevent clicks; multitrack stem render — M / M.
8. Settings UX: unsaved-changes prompt, folder pickers (renders, backups), backup dir must differ from db dir — M / L (`settings-panel`).
9. Keyboard shortcut layer: global scope, conflict listing, profile export — M / M (`keyboard-shortcuts`).
10. Lock-automation toggle + per-track filter override in DAW — L / M. Only if DAW grows automation.
11. LAN library share to paired phone with checksum-verified chunk streaming — M / H (`paired-device-tokens`).
12. Track history dimming (played / exported) — M / L.
Skip (live-performance, out of scope): VST3 hosting, MIDI/OSC clips, Link/NET clock, MIDI mapping, OSC API, crossfader/vector mixer.
