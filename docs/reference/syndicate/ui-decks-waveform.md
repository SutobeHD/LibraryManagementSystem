# Syndicate — UI, decks, waveforms, edit mode (reference)

## 1. Source + copyright note

- Source: Syndicate user guide (Untitled Audio, v0.2.0-RC2+913, reviewed 2026-10-23), chapters 0, 1, 6, 8, 15 + guide stylesheet. Cite `syndicate:§n.n` / `syndicate:tokens`.
- Commercial docs. Facts only (hex, layout, behaviour) in own words. No passages / CSS copied. Do not ship their assets, name, logo.
- Guide says its `:root` tokens mirror the app LookAndFeel (`syndicate:tokens`) -> treat as app palette, but screenshots not seen; pixel sizes unknown.
- Gaps: waveform hex colours not in guide (only modes). Phrase/section display = Perform Loop (ch.11, not read). Arrange (ch.10), Tag Editor (ch.3) not read.
- Pairs with `docs/reference/rbxport/ui-skin.md` + `waveform.md` (Rekordbox look).

## 2. Design tokens

Dark default (`syndicate:tokens`). Light = derived (see rule below).

| Token role | Dark | Light |
|---|---|---|
| Window ground | `#171717` | `#E6E6E4` |
| Window / rail | `#1B1B1B` | `#DCDCDA` |
| Panel gradient top -> bottom | `#1E1F20` -> `#171819` | `#D6D6D4` -> `#DEDEDC` |
| Well (sunken area) | `#111213` | `#E0E0DE` |
| Slot | `#0F0F10` | `#E8E8E6` |
| Field (input) | `#0A0A0A` | `#F2F2F0` |
| Key (button) top / mid / bottom | `#232323` / `#1E1E1E` / `#191919` | `#DADAD8` / `#D6D6D4` / `#BCBCBA` |
| Key outline | `#000` | `#9A9A9A` |
| Row line / table head / rule | `#131313` / `#161616` / `#2E2E2E` | `#CDCDCB` / `#D1D1CF` / `#C7C7C5` |
| Text main (paper) | `#EDEDEA` | `#1B1B1B` |
| Text body / label / button | `#D0D0CD` / `#D8D8D8` / `#BDBDBD` | `#3A3A3A` / `#4F4F4F` / `#474747` |
| Text dim / faint | `#7E7E7E` / `#6E6E6E` | `#6F6F6F` / `#808080` |
| Selection / hover-row | `#555555` / `#2A2A2A` | `#C4C4C4` / `#CFCFCD` |
| Signal Green (brand accent) | `#00FF48` (lo `#00D93D`) | text `#007A29` |
| Text on signal | `#111111` | same |
| Sheen (top inner highlight) | white 6% | white 50% |
| Inner shadow / outer edge | black 60% / `#000` | black 12% / `#ABABAB` |

- Greys are near-neutral (no blue tint) -> contrast with our blue-tinted `mx-*` ramp.
- Paper white `#EDEDEA` is slightly warm, not pure white.
- Accent is user-chosen: COLOR 1-8 from cue palette, or skin default (orange in STANDARD). It tints Play/eject keys, lit keys, playheads, loop regions, accent text, learn state (`syndicate:§12` per c12 note, `syndicate:§1.5`).

### Cue palette "TOXIC" (8 slots, user-editable, drag to reorder)
| Slot | Hex | Role in guide |
|---|---|---|
| 1 | `#D7FF27` | acid lime; Setup group; deck colour 1 |
| 2 | not given | - |
| 3 | `#00BC78` | green; Library group; deck colour 3 |
| 4 | not given | - |
| 5 | `#168ACD` | blue; Play group; deck colour 5 |
| 6 | `#635CEB` | indigo; Author group |
| 7 | `#BE3DE4` | magenta; Perform group; deck colour 7 |
| 8 | `#F65A91` | pink; Reference group |

- Deck colours come from slots 1, 3, 5, 7 (4 decks). Cue pads 1-8 take slot colours.
- Palette slot references follow later palette edits (colour is by slot, not by hex copy).

### Light-mode derivation rule
- Not a pure invert: separate hand-tuned light surface set (above).
- Coloured text on light = palette colour mixed with black: 50% for most groups, 65% for lime (too bright otherwise).
- Coloured text on dark = palette colour as-is; indigo +25% white, magenta +20% white (lift contrast).
- Signal green text on light drops to `#007A29`. Sheen goes 6% -> 50% white, shadows 60% -> 12%.
- Rule: fill colour constant, only TEXT-use of a colour gets mixed toward bg-contrast. Cheap to copy via `color-mix()`.

## 3. Typography + surface look

| Item | Value |
|---|---|
| UI font | Inter, system fallback; optical sizing off |
| Mono font | IBM Plex Mono |
| Body | 14px / 1.6, weight 400 |
| Labels / keys | 9-11px, weight 700, UPPERCASE, letter-spacing .03-.1em |
| Micro labels | 7.5-8.5px, 700, tracking .1-.16em |
| Big numerals (position) | 20px, 800, tabular-nums |
| Header bar height | 48px; keys 28px; wells 34px |
| Radii | 2px everywhere (almost square) |
| Focus | 2px signal-green outline, 2px offset |

Surface look (`syndicate:tokens`):
- Panels = vertical gradient + 1px outer edge + 1px top inner highlight ("sheen"). Gives hardware-bevel feel, no drop shadows.
- Buttons ("keys") = 3-stop vertical gradient (light top, dark bottom), 1px dark outline, inset top highlight 5% white + inset bottom shadow 30% black, 1px text-shadow. Pressed = brightness .9 + inset dark top.
- Cue-style nav keys = radial gradient (ellipse centred 50%/10%) not linear -> subtle dome.
- LED strip: 2px-high rounded bar under a key; dim `#2A2A2A` off, group colour on. Used for active/seen state, FX slot segments (lit=running, dim=bypassed, red=missing).
- Note: items below marked (guide) are the guide site's own chrome built from the app tokens; app equivalents assumed, not confirmed.
- Wells (guide) = darker sunken boxes with top inner shadow; sit in header bottom-aligned so they look like tabs cut into the bar.
- Active key = 1px inset ring in accent colour; no fill change.
- Tick row: 5x3px segments, first one signal-green (position-in-list indicator).
- Selector tokens `--sel #555`, row hover `#2A2A2A` -> gradient fade left-to-right for active sub-item.
- Skins: Standard, Midnight, Ember, Moss, Orchid, Steel + Light Mode (`syndicate:§1.5`).
- Tabular nums used for every number readout.

## 4. Modes

Switch via Mode dropdown (header, right after logo), F1-F4 / Cmd+1-4 (`syndicate:§1.4`). One header, workspace swaps.

| Mode | Key | Workspace shows |
|---|---|---|
| Edit | F1 | Detail waveform (centred on playhead) + full-track overview + transport + metadata panel; toolbar with 4 submodes GRID/CUES, TEMPO MARKERS, MIDI, OSC. Drop zone "drop a track here to edit" |
| Perform | F2 | 1-4 decks + mixer (+ optional crossfader / vector mixer) + Browser. Sub-view Perform Loop (cue-section shelf, loop timeline) |
| Tag Editor | F3 | Tag groups; keys 1-0, Q-P toggle tags on Browser selection |
| Arrange | F4 | Timeline of audio, MIDI, VST, OSC, macro automation; play or render. Can be loaded back onto a deck as one object |
| Mapping | menu only | MIDI/keyboard learn table, OSC API window |

- Deck content types in Perform: track, MIDI clip, OSC clip (AutomationDeck), sampler (8 lanes x 16 steps), arrangement, empty (`syndicate:§6.1`). Same deck frame adapts per content.
- Engine Mode: fixed 400x200 tiny window, UI drawing + meters suppressed, audio + MIDI/OSC keep running; saved across launches (`syndicate:§1.5`).
- Scale: UI scales from 1400x840 baseline, View -> Scale 50-125%.
- Window size, Browser sections, selected playlists restored on relaunch.

## 5. Interface layout

Four stacked parts: header (always), workspace (per mode), Browser (embedded / hidden / detached window), footer (`syndicate:§1.5`).

```
+--------------------------------------------------------------------------------+
| menu bar (native): Syndicate | Mode | View                                    |
+--------------------------------------------------------------------------------+
| [logo] [MODE v] [LOCAL/USB] [LIMIT|MASTER lvl] [CUE|MIX] [clock/Link/metro]    |
|   [M][lock] [ TEMPO 128.00 ·midi·osc ] [Q 1/4] [beat] [learn]                 |
+--------------------------------------------------------------------------------+
|  WORKSPACE (mode)                                                              |
|  Perform default "Compact Paired Mixer":                                       |
|  +---------------+ +---------+ +---------------+                              |
|  | DECK 1        | | MIXER   | | DECK 2        |   (3-4 decks: grid; deck 1   |
|  | rail|wave|... | | ch1 ch2 | | rail|wave|...  |    spans top with 3 decks)   |
|  +---------------+ +---------+ +---------------+                              |
|  BROWSER (embedded: collections ALL TRACKS / SEQ / ARR / STATES, track list)   |
+--------------------------------------------------------------------------------+
| footer: hover help text (left)            NET status+tempo | track count (right)|
+--------------------------------------------------------------------------------+
```

Header controls left -> right: logo (opens About) · mode · LOCAL/USB library source · LIMIT + Master level/meter · Cue level + Cue/Master mix · clock panel (metronome, role e.g. MASTER, Link peers, bar progress, RAMP catch-up) · M + lock keys · tempo readout · Q + value · beat display · Learn.

| Header item | Behaviour |
|---|---|
| Tempo readout | drag = 0.01 BPM/px, Shift = 0.1; double-click = type 20-999; dimmed read-only when editor/DAW/other machine owns tempo; shows effective tempo incl. bend |
| MIDI/OSC dots | left dot = input, right = output activity |
| Q | global quantize on/off (accent when on); value None, 2, 1, 1/2, 1/4, 1/8, 1/16, 1/32 bars |
| M / lock | clock ownership: M lit = header owns clock; lock = wallclock mode (only header owns) |
| Clock panel | hideable (View -> Clock Status, Cmd+M); metronome keeps working |
| Footer | hover-help line left (context hint under mouse), network + count right |

Performance views (`syndicate:§6.11`): Compact Paired Mixer (default, decks flank mixer) · Decks Only (external mixer) · Stacked/Synced Decks (full-width decks, synced phrase zoom). Deck count 1-4 via View or header cycle button; hidden decks unload. 3-deck = deck 1 top, 2+3 below.

## 6. Deck anatomy

Track deck regions (`syndicate:§6`): header (top), tempo rail + Play (left), main scrolling waveform (centre) with full-track preview + cue buttons below, loop row (bottom).

| Region | Contents |
|---|---|
| Header | deck badge (pulses last 30 s), title, artist + duration; REMAIN, ORIGINAL BPM, CURRENT BPM, KEY (in key colour), per-deck QUANTIZE (USE GLOBAL / NONE / value), MIDI/OSC activity, EJECT top-right |
| Tempo fader | +-12 semitone range (half..double speed); WIDE PITCH setting adds full stop on lower half; Cmd-drag snaps whole BPM; handle lights at native tempo |
| FOLLOW / MASTER | toggle: deck follows clock or becomes tempo master; click again hands back. First loaded deck auto-master; master passes to lowest-numbered playing synced deck |
| SYNC | follow master tempo + phase; off = free |
| EARLY / LATE | phase nudge, Shift = 4x finer; PHASE CORRECTION = TRIGGER or HOLD |
| BEND < > | master deck only, +-2 BPM while held |
| /2 x2 | half/double speed on quantized boundary; option: multiplier retains clock |
| PLAY/PAUSE | bottom of rail. Play waits for quantize boundary; pause immediate with tape-stop (25 ms default, per-deck, optional jitter) |
| Reverse arrow | points playback direction; click = reverse; Cmd-hold = backspin |
| SLIP | underlying playhead keeps running through cues/loops/speed/tape-stop; release returns to "where it would be" |
| Cue / Grid-start jump | no on-screen buttons; mapped only |
| Hot cues | 8 pads, cue-palette colours; click empty = set (captures active loop exactly); Ctrl-click = momentary; Cmd-click = delete (unlocked only); Cmd-Shift-click = loop cue->next cue |
| Loops | LOOP toggle (default length 8 bars..1/4 bar); IN/OUT (while looping IN halves, OUT doubles); free-loop knob (ms scale); skip -/+ (1,2,4,8,16,32 beats, global, right-click chooses; moves active loop with playhead); slip loops by bar fraction, D dotted, T triplet |
| Pitch / key | P = key lock (Elastique), 4 ms blend on toggle; PITCH LOCK ON LOAD; pitch -/0/+ semitones; Cmd-click = formant (manual mode) |
| SIMPLE MODE | setting hides advanced deck controls |

- Locked track = cue set in Perform used for this load only, not saved. Unlocked = saved immediately (`syndicate:§6.5`). Lock-before-gig pattern.
- LOAD FIRST CUE per track: deck loads parked at first cue.
- Saved States: snapshot of deck content refs + mixer + routing + tempo + sync; recall loads without autoplay; no playhead snapshot (`syndicate:§6.10`).
- Other deck types: sampler = 8 lanes, 16-step sequencer, per-step velocity (VEL toggle), A/H/R/curve envelope, MONO/POLY, direction, N/D/T rate, per-lane step count (polyrhythm), samples <= 15 s. Arrangement deck = one row per used track, markers as pads (5/page), ROUTING view with per-track trim + 2x2 channel keys. AutomationDeck = shape display + value meter + OSC address + A-E send toggles.

## 7. Waveforms

(`syndicate:§6.7`, `§8`; hex values for waveform bands not in guide.)

| Aspect | Syndicate |
|---|---|
| Styles (setting WAVEFORM MODE) | SIMPLE (single), RGB (low/mid/high -> R/G/B), 3 BAND (layered; colour by Deck Color, Cue Colors, or Custom) |
| Detail view | scrolling, centred on playhead, beat grid overlaid, current position marked |
| Overview | full-track strip under detail; dims what has already played; drag = scrub |
| Zoom | wheel / trackpad or -/+ ; up to full track in; Edit can zoom to ~3400x for transient-level grid work |
| Seek | click on paused waveform; snapped if Q on |
| Scrub | "like vinyl", stopped or playing (Edit) |
| Cue regions | waveform can be coloured per cue region (Edit COLORIZE toggle, default off = light-grey bg waveform); deck waveforms "cue-coloured" |
| Beat grid | labels bars + beats; negative numbers before Grid Start; tempo-marker segments |
| Cue markers | palette-coloured; loop cues = regions 1-128 beats; E-LOOP safe loop near end |
| MIDI / OSC lanes | audio shown behind lanes at WAVEFORM OPACITY (default 50%) |
| Stacked deck view | phrase zoom synchronized across decks |
| Phrase / section | Perform Loop "cue sections" shelf (drag section onto deck, double-click = quantized launch); sections derive from cues. No auto phrase-label bar seen in read chapters |
| Arrangement display | rows per track, clips in colour, marker lines with names, playhead fixed mid |

- Idea: waveform colour is a user choice axis (deck / cue / custom) rather than fixed frequency palette.
- Playhead centred, material scrolls under it (same as Rekordbox detail).

## 8. Edit mode

Entry: drop track on workspace or load from Browser. Submodes GRID/CUES · TEMPO MARKERS · MIDI · OSC share detail + overview waveform, transport, metadata panel (`syndicate:§8`).

### Grid (`syndicate:§8.1`)
| Tool | Action |
|---|---|
| SET GRID START | first downbeat at playhead; must sit on transient leading edge, not loudest peak |
| BPM spinner | drag or double-click to type |
| X2 / /2 | fix double/half-time detection |
| NUDGE -/+ (Shift+Left/Right) | fine shift, BPM unchanged |
| BEAT -/+ (Cmd+Shift+Left/Right), BAR -/+ | shift origin by whole beat/bar |
| REANALYZE | opens Browser Analyze tool with track selected |
| Lock / Unlock | freezes grid, cues, markers, MIDI/OSC, artwork, metadata |
| MOVE CUES WITH GRID | option deciding if cues follow grid shifts |

Diagnosis table pattern (UX gem): constant offset -> move Grid Start; drift -> fix BPM / add tempo markers; right beats wrong bar number -> beat/bar shift; exact half/double -> X2 or /2.

### Cues (`syndicate:§8.2`)
- 8 slots. Cue = point or loop region 1-128 beats. Press populated cue = play from there (even when editor stopped); loop cue also arms loop.
- SET CUE at playhead in selected slot. Right-click = CUE EDIT: name, palette colour, make loop/normal, loop length.
- AUTOCUE regenerate suggestions; QUANTIZE snaps all cues to grid; REORDER renumbers by time; DELETE ALL (confirm).
- HOTCUE PRESETS: 8 presets (name + optional colour + hotkey); hotkey drops named cue in next free slot. Reserved keys: E , . Space Esc Return Tab Delete F1-F4, Cmd/Ctrl combos.
- E-LOOP: key E sets emergency loop start at playhead (snapped) and enables it.
- Only one cue kind (no memory-cue vs hot-cue split like Rekordbox).

### Tempo markers (`syndicate:§8.3`)
- Marker = fixed BPM from its position, starts a new bar. Always one at Grid Start.
- ADD MARKER at playhead; select from waveform or MARKERS list; edit via spinner / EDIT EXACT BPM; nudge, move by beat/bar; Cmd-click or right-click -> DELETE.
- Piecewise-constant tempo (stepped). Drives cue snapping, quantize, deck playback, arrangement clips, renders. Old tempo envelopes import as stepped markers.

### Attached MIDI / OSC (`syndicate:§8.4-8.5`)
- MIDI: drag clip from library onto track timeline; regions move/trim/loop/split (at marker, cuepoints); Cmd+Up/Down transpose; preview via VSTi/MIDI out. DATA column in Browser flags tracks with attached data.
- OSC: envelope lanes + message lanes, address, int/float + min/max, pencil, LFO, lane M/S, Bezier handles (independent), simplify-to-Bezier.
- Timelines auto-follow playback; manual pan pauses follow until playhead crosses centre; no FOLLOW button.

### Metadata + save (`syndicate:§8.6-8.8`)
- Panel: artwork (drop image; stored in managed data, audio file untouched), TITLE ARTIST ALBUM GENRE LABEL YEAR KEY RATING COLOR, LOAD FIRST CUE, FILE INFO (duration, rate, bitrate, size, plays, status).
- Save model: sidecar `.sdd` per audio file holds grid, cues, markers, attached data; auto-save on leaving the track; failure dialog TRACK EDITS NOT SAVED -> RETRY / DISCARD / KEEP EDITING. Undo/redo for region edits.
- `,` / `.` = prev/next track in library order. Space = play/pause.
- Recommended order: unlock -> BPM+grid (check late in track) -> tempo markers -> cues + presets + E-loop -> MIDI/OSC -> metadata/tags -> lock.

## 9. Shortcuts + mouse modifiers

Cmd = Ctrl on Win/Linux; Option = Alt (`syndicate:§15`). Mapped keys override defaults; autorepeat ignored; held keys release on focus loss.

| Keys | Context | Action |
|---|---|---|
| Cmd+, | global | Settings |
| F1 / F2 / F3 / F4 (or Cmd+1-4) | global | Edit / Perform / Tag Editor / Arrange |
| 1-0, Q-P | Tag Editor | toggle tag on Browser selection |
| Space | Edit, Arrange | play/pause (stops Browser preview in Edit) |
| Left / Right | track editor | prev/next cue |
| Cmd+Left/Right | track editor | prev/next energy-change boundary |
| Shift+Left/Right | grid/cues | fine grid nudge |
| Cmd+Shift+Left/Right | grid/cues | grid by one beat |
| E | grid/cues | emergency loop start at playhead + on |
| , / . | track editor | prev / next track |
| hotcue preset keys | track editor | drop named cue |
| Delete/Backspace | Edit, Arrange | delete selection |
| Esc | global | cancel selection/gesture/learn |
| Cmd+M | global | toggle clock status panel |

| Gesture | Action |
|---|---|
| Drag header BPM | 0.01 BPM/px; Shift 0.1 |
| Double-click any BPM | type exact |
| Shift + EARLY/LATE | 4x finer phase nudge |
| Ctrl-click hot cue | momentary cue |
| Cmd-click hot cue | delete (unlocked) |
| Cmd-Shift-click cue | loop cue-to-next-cue |
| Cmd-hold reverse arrow | backspin |
| Cmd-click pitch -/0/+ | formant down/reset/up |
| Cmd + skip | move active loop |
| Right-click skip | choose skip size |
| Cmd-drag tempo fader | snap whole BPM |
| Cmd-drag mixer volume dial / double-click | trim / reset trim |
| Cmd-drag in Arrange | copy clips |
| Shift-drag Arrange/OSC/MIDI | range select |
| Cmd-wheel / Option-swipe (Arrange) | zoom at cursor / pan |
| Cmd-drag sampler knobs | all 8 lanes; Option = fine |
| Cmd-click lane / loader | mute lane / clear sample |
| Cmd-click tempo marker | delete |
| Cmd-drag OSC edge | stretch timing |
| Cmd-drag OSC nodes | node select |

Pattern: plain = act, Shift = range or finer, Cmd = destructive/global/alt-target, Option = fine/pan, double-click = reset or type value.

## 10. Syndicate vs Rekordbox vs LMS

Rekordbox column from `docs/reference/rbxport/ui-skin.md` + `waveform.md`; LMS from `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/src/components/WaveformEditor.jsx` (grep only).

| Aspect | Syndicate | Rekordbox | LMS today |
|---|---|---|---|
| Base palette | neutral grey `#171717`..`#1E1F20`, warm paper text | black dominant, deck `#000`, rail `#1E1E1E` | blue-tinted navy `#0D0F14`..`#2A3045` |
| Accent | Signal Green `#00FF48`, user-selectable from cue palette | blue/red/orange per function | single amber `#E8A42A` |
| Fonts | Inter + IBM Plex Mono | (see rbxport) | DM Sans + JetBrains Mono |
| Surface style | bevelled hardware keys, gradient panels, sheen, 2px radius, LED strips | flat | flat dark cards (not verified) |
| Light mode | derived, hand-tuned set; text colours mixed w/ black | n/a in rbxport tokens | dark only seen |
| Cue palette | 8 user-editable slots, colour by slot | 8 hot colours: teal, orange, blue, yellow, pink, aqua, lime, purple | hotCues array in editor (colours unverified) |
| Cue kinds | 1 kind (8 slots; point or loop region) | memory cue + 8 hot cues A-H | hot cues + loop in/out + cuts |
| Waveform styles | SIMPLE / RGB / 3 BAND (colour by deck/cue/custom) | 3Band (blue/amber/white), Blue, RGB | multiband layers hook, WaveSurfer; simple view |
| Detail zoom | wheel, up to full track; ~3400x in Edit | bar steps 0.25..64 | WaveformZoom component |
| Overview | dims played part, drag scrub | 30pt strip, position bar | present (not audited) |
| Phrase display | cue sections shelf (Perform Loop) | PSSI phrase bar with labels/colours | none seen |
| Grid edit | Grid Start + BPM + nudge/beat/bar + X2//2 + diagnosis table | beat grid edit in Rekordbox | beatGrid state + computeBeats |
| Variable BPM | tempo markers (stepped, always one at start) | grid edit w/ multiple tempos | none seen |
| Save model | sidecar .sdd, autosave on track leave, lock flag | master.db | useEditPersistence |
| Deck count | 1-4, adaptive content types | 1-4 players | editor-centric |
| Quantize | global Q in header + per-deck override | per-deck Q | none seen |

## 11. Top ideas for LMS

Ranked (value / effort).

1. **Cue colours by palette slot, not hex** - recolour whole library by editing 8 slots. Value H / effort S.
2. **Track lock flag** - freeze grid/cues/metadata; perform-mode edits not persisted on locked tracks. Value H / S.
3. **Grid diagnosis table in editor** (offset vs drift vs bar-number vs half/double) as inline help next to grid tools, plus X2 / /2, nudge, beat/bar shift. Value H / S.
4. **Tempo markers (stepped BPM segments, one pinned at Grid Start)** for variable-BPM tracks; marker grid feeds snap/quantize. Value H / M (needs ANLZ beat-grid export mapping).
5. **Hotcue presets** (8 named + colour + hotkey; drops in next free slot). Value M / S.
6. **Extreme zoom for Grid Start** (transient-level) + "place on attack edge" guidance. Value H / M.
7. **Waveform colour mode picker**: simple / RGB / 3-band, colour by deck / cue region / custom; COLORIZE per cue region. Value M / M.
8. **Emergency loop (E key)** - one-key safe loop near end. Value M / S.
9. **Autosave on leaving track + RETRY / DISCARD / KEEP EDITING dialog**; `,` `.` prev/next track in editor. Value M / S.
10. **Skin pack via tokens**: neutral-grey ramp + bevelled "key" gradient + LED underline + 2px radius; light mode by mixing text colours with black. Value M / M.
11. **Header BPM drag (0.01 / Shift 0.1) + dbl-click type** and global Q selector with per-deck override. Value M / S.
12. **Footer hover-help line** (describes control under cursor). Value M / S.
13. **Cue QUANTIZE-all, REORDER, AUTOCUE regenerate** buttons. Value M / S.
14. **Energy-change boundary navigation** (Cmd+Left/Right) - needs section/energy analysis. Value M / M.
15. **Saved States** (deck contents + mixer snapshot, no autoplay on recall). Value L-M / M.
16. **Engine Mode** (tiny window, UI draw off) - low priority for LMS. Value L / M.
- Licence guard: take ideas, not their tokens verbatim, name, or skin names.

