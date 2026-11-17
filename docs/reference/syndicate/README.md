# Syndicate study — library, look, decks, performance

Source: Syndicate user guide (Untitled Audio), `untitledaudiosyndicate.com/user-guide/index.html` (the `/docs` page is an iframe shell). Version covered: up to 0.2.0-RC2. Studied 2026-11-04. 17 chapters, ~36k words.

**Copyright:** commercial docs. The docs here summarise facts and behaviours in our own words. No passages or CSS were copied. Cite as `syndicate:§<n.n>`.

**What Syndicate is:** a DJ + performance app with 5 modes, track/MIDI/OSC-clip/sampler/arrangement decks, a VST3-hosting mixer, Arrange mode, Ableton Link + its own NET clock, MIDI/keyboard mapping and a ~594-address OSC API. Its USB export is **its own format**, not Pioneer-readable, so it offers nothing for CDJ export (see `../rbxport/` for that).

| Doc | Covers |
|---|---|
| [`library-export.md`](library-export.md) | import pipeline, Rekordbox/Lexicon import, tag model + filters, DB maintenance, backup/move, browser, playlists, USB libraries |
| [`ui-decks-waveform.md`](ui-decks-waveform.md) | design tokens, modes, interface layout, deck anatomy, waveform styles, edit mode (grid/cues/tempo markers), shortcuts, Syndicate vs Rekordbox vs LMS |
| [`performance-control.md`](performance-control.md) | mixer signal flow, FX, MIDI/OSC clips, arrange + render, clock/Link, settings, mapping, OSC namespace, troubleshooting, roadmap signals |

## Essentials

Library:
- The Library Manager scans for missing files, playlist orphans, unreadable data and orphaned sidecars. "Relink all found" after one folder search, plus an exportable report.
- Tag Shelf: chips with live counts, shift-click to exclude, ALL/ANY switch.
- Lexicon import reads the running app live. A "who wins" switch decides cues/grid for existing tracks, and track locks are respected.
- M3U import keeps unresolved paths as MISSING placeholders to relink later.
- USB: reuses audio already on the stick, replaces one playlist at a time, and a cancel keeps the last good catalogue.

Look + decks:
- Neutral greys `#171717`–`#1E1F20` plus Signal Green `#00FF48`. Bevelled gradient buttons, top sheen on panels, 2px radius. Inter + IBM Plex Mono. Light mode is a hand-tuned set, with colour text mixed toward black.
- Cue colours come from palette **slots**, not raw hex: 8 cues, each a point or a loop.
- Grid model: Grid Start + BPM + stepped tempo markers. The grid-diagnosis rule of thumb:

  | Symptom | Fix |
  |---|---|
  | Constant offset | Move Grid Start |
  | Drift | Fix BPM or add tempo markers |
  | Wrong bar number | Shift by beat or bar |
  | Exactly half or double | X2 or /2 |

- Track lock flag freezes all edits. Edits autosave to a sidecar when you leave the track, and a failed save offers retry, discard or keep.
- Waveform styles are Simple, RGB and 3 Band. The guide gives no band hex values; Rekordbox's are in `../rbxport/waveform.md`.

Performance (mostly out of scope for LMS):
- Mixer chain: trim → EQ → filter → PRE inserts → cue tap → volume → POST inserts. Per-output trim/volume bypass.
- One clock owner at a time, clamped to 20–999 BPM (the Link range). A wallclock lock stops ownership handoffs.
- Mapping lacks LED feedback, relative encoders, soft takeover and shift layers.
- Render = library feature: auto-import into a Renders playlist, markers become cuepoints, stems.
- Troubleshooting rule: "timing → grid, silence → routing", backed by live monitors (underruns, OSC log, plugin issues).

## Ideas for LMS

Registered as `idea` in the feature map:

| Feature id | Idea |
|---|---|
| `missing-file-relink` | problem scan + relink-all-found |
| `tag-shelf-filter` | include/exclude chips, counts, ALL/ANY |
| `m3u-import-export` | M3U/M3U8 in/out with MISSING placeholders |
| `track-lock-flag` | freeze cues/grid/metadata per track |
| `variable-bpm-tempo-markers` | stepped tempo markers + grid-diagnosis help |

Not registered (lower priority, listed in the docs):
- Lexicon live importer.
- Hotcue presets: 8 named, coloured, hotkeyed.
- Cue colours by palette slot.
- In-app diagnostics page.
- DAW render → library + markers as cues (`daw-export`).
- Scheduled library backup (`rekordbox-write-backups`).
