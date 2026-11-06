# rbxport study — Rekordbox export, look, waveforms

Source: `github.com/chrisle/rbxport` @ `b739d36` (2026-10-21). Rust/Tauri/React clone of rekordbox 7.x: USB export, browser UI, waveform analysis. Studied 2026-11-04.

**License:** rbxport = GPL-2.0-or-later, ours = MIT. **Never copy its code/CSS.** These docs hold facts only (byte layouts, constants, hex values, metrics, algorithms) in own words. Re-implement from the docs, not from rbxport source.

**Trust level:** rbxport facts are tagged `[OBS]` (measured against rekordbox captures) or `[ASSUME]` upstream. Our own F:-drive byte-verified invariants (`.claude/rules/coding-rules.md`, `app/usb_pdb.py` comments) win until a check on the reference stick says otherwise.

| Doc | Covers |
|---|---|
| [`export.md`](export.md) | stick layout, export.pdb, exportLibrary.db, ANLZ per file, artwork, incremental sync + verification, gotchas, gap analysis, invariant contradictions |
| [`waveform.md`](waveform.md) | PWAV..PWV7 encoding, DSP chain, colour palettes, preview/detail rendering, perf tricks, gap analysis, input for `waveform-overhaul` |
| [`ui-skin.md`](ui-skin.md) | design tokens (hex), typography, metrics, window layout, browser columns, shortcuts, mapping to our Tailwind tokens, Rekordbox-skin plan |

## Essentials — export

- CDJ-3000 derives the `USBANLZ/Pxxx/xxxxxxxx/` folder from a hash of the **USB audio path**. DB entry must name the same folder. `PPTH` in every ANLZ file = USB path, never desktop path.
- PDB strings: UTF-16-LE long strings **without terminator**, long strings start 4-byte aligned. Terminated/unaligned strings froze a CDJ-2000NXS.
- Data page with > 255 rows needs special header values at `0x20`/`0x22`. Old shape crashed rekordbox 6.8.6.
- `exportLibrary.db`: built from schema (SQLCipher, `journal_mode=DELETE`), no template → no 16-track cap. Rating stored 0–5 (not ×51).
- Incremental sync: manifest + stable export ids + size/mtime stamps (hash on doubt) → stage → verify → journaled rename → read-back verify.
- Artwork bucket: id 1 lives in `Artwork/00001/` (also our own F: fixture, `usb_pdb.py:480`).

## Essentials — waveforms

| Tag | File | Count | Entry | Notes |
|---|---|---|---|---|
| PWAV | .DAT | 400 | 1 B | height 2..25, 3 bit whiteness |
| PWV2 | .DAT | 100 | 1 B | height 1..15, **no** whiteness bits (Nexus rejects > 15 or 0) |
| PWV3 | .EXT | 150/s | 1 B | height `round(31*(peak/255)^2)` |
| PWV4 | .EXT | 1200 | 6 B | `peak>>1, 0, 0, low, mid, high`, 7-bit |
| PWV5 | .EXT | 150/s | 2 B | `rrrgggbbbhhhhh00`, R=low G=mid B=high |
| PWV6 | .2EX | 1200 | 3 B | low/mid/high 0..127, own energy pass, 20 B header |
| PWV7 | .2EX | 150/s | 3 B | low/mid/high 0..127 |

- Crossovers 200 Hz / 2 kHz. Detail = per-band peak per 1/150 s window. Previews = bucket max.
- RGB mapping: **R = low, G = mid, B = high**.
- 3Band render: 7 opaque combination colours, outermost band first. Detail drawn once over 2x visible span, scrolled by `translateX` at whole device pixels.

## Essentials — Rekordbox look

- Dark only. Layers `#000` / `#0F0F0F` / `#1E1E1E` / hover `#2B2B2B` / divider `#323232`. Selection `#314B67`, accent `#1373EB`.
- Arial 16.5px/400, tabular figures for numbers. Row 25px, header 24px, top bar 30px, status bar 27px, scrollbars always visible 12px. Radius 2px. Regions split by black gaps + zebra rows, not borders.
- Layout: top bar / decks (279px, 420 for 2 decks) / tree (305px, min 140, draggable) + browser / status bar.
- Columns: `# | Preview | Artwork | Title | Key | BPM | Time | Rating | Artist | Comments | Label | Date Added | Release Date`. BPM 2 decimals, `MM:SS`, `M/D/YY`, key uncoloured.
- Shortest skin path: Tailwind keys → CSS vars, `[data-theme="rekordbox"]` override sheet, theme picker in `SettingsAppearance.jsx`.

## Open — verify before acting

Confirmed in our code (2026-11-04), not yet fixed:
- `app/analysis_engine.py:1219-1230` PWV5 puts high band in R, low in B (swapped). PWV4 `:1197-1217` wrong byte order + 0..255 range. PWV2 `:1184-1188` carries whiteness bits. Crossover `:1095` 2500 Hz (rbxport 2 kHz).
- `app/usb_artwork.py:38-40` `_bucket_for(1)` → `00000`, reference stick has `00001`.

Unresolved contradictions rbxport vs our F:-verified PDB (page flags, header `0x10`, small-page `0x20/0x22`, audio folder naming, ANLZ folder by id vs path hash): `export.md` §11 lists five cheap checks on the reference stick. Run those before changing `app/usb_pdb.py` or the rules.
