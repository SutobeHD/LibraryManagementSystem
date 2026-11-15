# rbxport UI facts — Rekordbox skin reference

Purpose: design facts for a future "Rekordbox skin" theme in our frontend. Facts only, own words, no copied code.

## 1. Sources + license

- Source repo: rbxport (Tauri/React/TS clone of rekordbox 7.x look). Cited as `rbxport:<path>`.
- rbxport = GPL-2.0-or-later. Ours = MIT. **Never paste its CSS/TS.** Record values (hex, px, order) only; re-implement from this doc.
- Hex colours / pixel metrics = measurement facts (not copyrightable expression), but keep them in tables, not as copied stylesheets.
- rbxport claims values measured from rekordbox 7.2.x captures on macOS (2x). Treat as ground truth for the look; some marked `[ASSUME]` upstream.
- Files read:
  - `rbxport:src/styles/tokens.css` (632 lines: ~170 colour tokens `--c-*`, ~380 size tokens `--s-*`, font tokens `--f-*`)
  - `rbxport:src/styles/{theme.ts,base.css,reset.css}`, `rbxport:index.html`
  - `rbxport:src/app/App.module.css` (window grid)
  - `rbxport:src/views/{browser,tree,topbar,statusbar,subbrowser,player}/*.module.css`
  - `rbxport:src/components/{ContextMenu,RatingStar}.module.css`, `rbxport:src/components/icons.tsx`
  - `rbxport:src/lib/{columns,format,camelot,layout,splitter,selection}.ts`
  - `rbxport:docs/reference/shortcut-commands.md`, `rbxport:src/lib/keyPresets.ts`
- No screenshots in `rbxport:docs/assets` — only `brand/` (app icons, wordmarks, logos, brand board PNGs). No fonts in `rbxport:public/` (only `locales/`, `os.js`).
- `rbxport:docs/development/rekordbox-parity-decisions.md` = process doc (evidence ladder), no UI values.
- Single dark design only. No light theme. No theme switcher. (rbxport:tokens.css footer comment.)

## 2. Design tokens

All from `rbxport:src/styles/tokens.css` unless noted. Token name in col 1 = rbxport CSS var.

### 2.1 Surfaces (background layers)

| Token | Hex | Used for |
|---|---|---|
| `--c-black` | `#000000` | app ground, player bg, splitters/gutters, status bar, browser pane bg, scrollbar track, even-less rows in empty area |
| `--c-top` | `#0F0F0F` | top bar, ODD track rows (row base), pad wells |
| `--c-panel` | `#1E1E1E` | tree, side rails, column header, browser head strip, EVEN track rows, deck transport rail |
| `--c-button` | `#2B2B2B` | row/node hover bg, player buttons |
| `--c-raised` | `#323232` | column dividers, bottom bar, inactive tab, splitter hover, meter track, scrollbar thumb |
| `--c-titlebar` | `#363738` | custom title bar (macOS-style, 28px) |
| `--c-select` | `#314B67` | selected row / selected tree node (desaturated steel blue) |
| `--c-field` | `#000000` | text-input interior (search, rename) |
| `--c-menu` | `#1A1A1A` | dropdown/menu bg (track-colour menus, layout menu) |
| `--c-context-menu` | `#1E1E1E` | context-menu panel |
| `--c-modal-scrim` | `rgb(0 0 0 / 55%)` | modal dim |
| `--c-device-row` / `--c-missing-manager` | `#191919` | device list rows / missing-file list rows |

Rule: odd rows `#0F0F0F`, even rows `#1E1E1E` (zebra). Gaps between regions are real black (`#000`), not borders.

### 2.2 Text + icon

| Token | Hex | Used for |
|---|---|---|
| `--c-text` | `#E6E6E6` | body text, table cells, headers |
| `--c-text-dim` | `#9A9A9A` | secondary, note nodes, cue letters |
| `--c-status-text` | `#969696` | status bar text |
| `--c-icon-off` | `#A0A0A0` | idle icon fill (rgb 160) |
| `--c-icon-on` | `#F0F0F0` | active/hover icon fill (rgb 240) |
| `--c-titlebar-text` | `#B2B3B4` | window title |
| `--c-field-placeholder` | `#4B4B4B` | search placeholder |
| `--c-search-glyph` | `#5C5C5C` | magnifier |
| `--c-context-menu-text` / `-dim` | `#FFFFFF` / `#616161` | menu item enabled / disabled |
| `--c-info-label` / `-value` | `#878787` / `#FFFFFF` | info panel label / value |

### 2.3 Accent, selection, hover, state

| Token | Hex | Used for |
|---|---|---|
| `--c-accent` | `#1373EB` | active tab, SORTED column header text + arrow, focus ring (1px), drop-line (2px), menu-item hover bg, rename-field border, column grip hover |
| `--c-select` | `#314B67` | selected row (see 2.1) |
| hover row | `#2B2B2B` (`--c-button`) | row/node hover when not selected |
| `--c-tab-active` / `--c-pad-active` / `--c-rail-lit` / `--c-filter-accent` / `--c-device-tab-on` / `--c-pref-select` | `#457FE5` / `#3571E3` x5 | blue active states in decks, rails, prefs, filters (slightly lighter than `--c-accent`) |
| `--c-search-focus` | `#4775FF` | search field focus |
| `--c-traffic-light` | `#64FF00` | "lit" cell (green cell bg, black text) — master/lit indicator in browser |
| `--c-play-ring` / `-on` | `#36642A` / `#60D330` | PLAY ring idle / playing (green) |
| `--c-cue-ring` | `#EDB751` | CUE ring |
| `--c-missing` | `#FF9600` | orange [!] mark for missing file in Attribute column |
| `--c-error` | `#E23B2E` | status error text, mute/err |
| `--c-sync-pending` | `#5BC8FF` | sync pending |
| `--c-link-loaded` | `#DD8C35` | Pro DJ LINK loaded-deck orange |
| `--c-meter-green/yellow/red` | `#2FBF4E` / `#E8C020` / `#E23B2E` | VU: green 0-70%, yellow 70-90%, red 90-100% |
| `--c-meter-fill` | `#3D72E9` | CPU meter + master knob arc |
| `--c-meter-track` | `#323232` | meter/knob track |

Playing-row colour: NOT a row background. Playing state shows in deck (green PLAY ring) and "lit" cell; the loaded track gets no tinted row in rbxport tokens. (No `--c-playing-row` token exists.)

### 2.4 Track colour labels

Two sets in tokens (both 8 colours: Pink, Red, Orange, Yellow, Green, Aqua, Blue, Purple, order = rekordbox colour menu order).

Browser "Color" column ball (8px dot) — `--c-comment-*` (`rbxport:src/views/browser/TrackTable.module.css`):

| Name | Hex |
|---|---|
| Pink | `#F870F8` |
| Red | `#F80000` |
| Orange | `#F8A030` |
| Yellow | `#F8E330` |
| Green | `#00E000` |
| Aqua | `#00C0F8` |
| Blue | `#0050F8` |
| Purple | `#9808F8` |

Info-panel / deck colour picker — `--c-label-*` (slightly softer):

| Name | Hex |
|---|---|
| Pink | `#E778F1` |
| Red | `#E33122` |
| Orange | `#EBA44A` |
| Yellow | `#F4E458` |
| Green | `#66DD42` |
| Aqua | `#56BDF3` |
| Blue | `#204FEF` |
| Purple | `#8B1EEF` |

Colour column render: 8px filled circle at x=5px, vertically centred; colour NAME text starts x=16px in normal text colour. Row itself is NOT tinted.

### 2.5 Waveform + cues + phrases

| Token | Hex | Notes |
|---|---|---|
| `--c-wave-low` | `#0055E1` | 3-band: low (blue) |
| `--c-wave-mid` | `#FFA600` | mid (amber/orange) |
| `--c-wave-high` | `#FFFFFF` | high (white) |
| `--c-wave-low-mid` | `#B4690A` | low+mid overlap |
| `--c-wave-low-high` | `#D2DCFA` | low+high |
| `--c-wave-mid-high` | `#FFF0D7` | mid+high |
| `--c-wave-all` | `#F5EBD7` | all three |
| `--c-pcm-blue` | `#5BA0FF` | "Blue" waveform mode |
| `--c-pcm3-band` | `#FFA600` | "3Band" mode |
| `--c-pcm-rgb` | `#F266DC` | "RGB" mode (pink) |
| `--c-vocal` | `#3FA9F5` | vocal strip |
| `--c-scrub` / `-played` | `#6B6B6B` / `#C8C8C8` | position bar unplayed / played |
| `--c-beat` / `-beat-head` | `#4C4C4C` / `#7C7C7C` | beat ticks / head |
| `--c-downbeat` / `-downbeat-head` | `#FFFFFF` / `#EA3323` | bar-1 line / head (red) |
| `--c-cue-head`, `--c-playhead-armed` | `#EA3323` | cue marker head / armed playhead |
| `--c-cue-point` | `#F1A84C` | memory cue point |
| `--c-cue-hot` (+ text) | `#3CEB50` (+ `#000`) | hot cue default green |
| hot cue palette | teal `#10B176`, orange `#FF8C00`, blue `#305AFF`, yellow `#E1AA00`, pink `#F51E8C`, aqua `#50B0F2`, lime `#9BD723`, purple `#AA72FF` | `--c-cue-*`, also `rbxport:src/styles/theme.ts` |
| `--c-cue-loop-icon` / `-active` | `#FF8205` / `#E63737` | loop icon |
| phrase: intro | `#B83F1D` | |
| phrase: up / up2 / up3 | `#8138F6` / `#6B36F6` / `#5534F5` | |
| phrase: chorus | `#4EA730` | |
| phrase: down | `#95753A` | |
| phrase: outro | `#6886AB` | |
| phrase: verse / bridge | `#2F6FBF` / `#7A4FA8` | |
| `--c-bars-label` | `#367BDA` | bars counter |
| `--c-tempo-annotation` | `#75CBD8` | tempo annotation |

### 2.6 Key / Camelot / rating / BPM

- Key colours: **none.** Key column = plain text in `--c-text`. rbxport has a camelot.ts (key <-> Camelot code mapping, transpose, compatible keys) but no colour wheel. (Our app colours Camelot cells — see §10; skin should decide to keep or neutralise.)
- Key text = classical names as stored (`Ebm`, `Am`, `C`). Camelot only if library is set so.
- Rating stars: 5 star SVGs (`StarLitIcon` / `StarEmptyIcon`), aspect 14:13.31, icon height 14.26px, 1px gap, colour = `--c-text` (white-ish), hover = `--c-accent`. Lit stars = filled, empty = outline. Click on already-set star clears rating.
- BPM col: right-aligned, tabular figures, 2 decimals (`128.00`).
- Key col: left-aligned text. Time col: right-aligned, tabular.
- Sort arrow: 9x9 px, `--c-accent`; sorted header text also `--c-accent`.

### 2.7 Controls / menus / misc

| Token | Hex | Notes |
|---|---|---|
| `--c-outline` | `#646464` | toggle outlines (filter button) |
| `--c-context-menu-border` | `#979797` | 1px hairline; plus inner 0.5px `#272727` ring |
| `--c-context-menu-separator` | `#191919` | 1px rule |
| `--c-menu-border` | `#8C8C8C` | dropdown menu border |
| `--c-deck-button` | `#282828` | deck buttons |
| `--c-mixer-band` / `-knob` / `-knob-pointer` | `#282828` / `#1C1C1C` / `#D0D0D0` | EQ band bg / knob / pointer |
| `--c-pad-well` / `-label` | `#0F0F0F` / `#646464` | pad wells |
| `--c-scroll-thumb` / `-track` | `#323232` / `#000000` | scrollbar |
| `--c-shadow-soft` / `-panel` | `rgb(0 0 0 / 45%)` / `55%` | popup shadows |
| `--c-pref-button-top/bottom/border` | `#323336` / `#19191C` / `#0B0B0B` | prefs gradient button |
| `--c-pref-text` | `#AAAAAA` | prefs body |
| `--c-link-*` | `#282828` strips, `#191919` buttons, `#FFFFFF` ink | Pro DJ LINK strip |

## 3. Typography

| Aspect | Value | Source |
|---|---|---|
| UI font stack | Arial, "Helvetica Neue", Helvetica, sans-serif (`--f-ui`) | rbxport:tokens.css; font "measured as Arial"; no webfont, no bundled font |
| Window-title stack | -apple-system, system-ui, "Segoe UI", sans-serif; 13px bold | title bar only |
| Base UI size | **16.5px** (`--f-size-ui`) for tree, table rows, headers | tokens |
| Weight | 400 everywhere; 700 for status bar, title bar, clock, traffic master button, knob value | module css |
| Menu size | 12.5px (context menus, dropdowns, search text, dual readout) | |
| Small sizes | 10px xs, 11px (filter strip, deck info, dual field), 11.5px status, 12px sm/info-label, 14px (bars, info, device, cue tempo), 17px title, 18px pref title | |
| Deck button label | 9px | `--f-size-dual-button` |
| Letter-spacing | none set (default) | |
| Numerics | `font-variant-numeric: tabular-nums` on right-aligned cols (`.right`), clock, knob value, cost readout | base.css `.tabular` |
| Line-height | cells use line-height = row height (25px) for vertical centring; body `1` | |
| Selection | `user-select:none`, `cursor:default` app-wide (desktop feel); text selectable only in inputs | base.css |
| Focus | `:focus-visible` = 1px solid accent, offset -1px (not on tabindex=-1) | base.css |
| Motion | `prefers-reduced-motion` kills animations | base.css |

Note vs ours: rbxport text is LARGE (16.5px) with tight row (25px). Our 12-13px DM Sans/36px rows is a very different density.

## 4. Density / metrics

| Metric | px | Token |
|---|---|---|
| Track row height | **25** | `--s-row-height` |
| Tree node height | 25 | same token |
| Context/dropdown menu row | 25 | `--s-menu-row-h` |
| Column header height | **24** | `--s-col-header-h` |
| Browser head strip (title + search) | 26 (+1px black gap below) | `--s-browser-head-h`, `--s-browser-head-gap` |
| Top bar | 30 | `--s-top-bar-h` |
| Title bar (macOS only; hidden on Linux) | 28 | `--s-title-bar-h` |
| Status bar | 27 | `--s-status-bar-h` |
| Bottom bar | 72 | `--s-bottom-bar-h` |
| Cell padding (x) | 6 (cells), 8 (header cells) | module css |
| Column divider | 1px right border `#323232` (black on selected rows) | |
| Scrollbar | **12px** wide/tall, always visible, track `#000`, thumb `#323232` inset 2px (8px visible), radius ~3px, no end buttons, hover thumb `#6B6B6B`; corner = thumb-colour with 1px black inset | `--s-scrollbar-w` |
| Prefs scrollbar | 6px | |
| Search field | 212w x 24h, 20px from pane right edge, glyph at x9/y5 (13px), text at x37, placeholder `#4B4B4B`, black interior | `--s-search-*` |
| Twisty (tree arrow) | CSS triangle 5px border, `--c-text` | tree css |
| Tree icon | 14x12 | |
| Tree node gap | 6px between twisty/icon/label | |
| Column-grip hit area | 5px wide, at col right edge -2px, blue on hover | |
| Splitter gutter | 1px tree gutter (black), 5px extra grab area each side (`::after inset 0 -5px`); sub-browser grab 3px; hover = `#323232` | |
| Radius | 2px (buttons, tags, inputs), 3px (report button, LINK buttons) — near-flat UI | |
| Shadows | menus only: `0 4px 12px rgb(0 0 0/45%)`, dropdown `0 6px 18px rgb(0 0 0/55%)` | |
| Borders | almost none; separation by black gaps + zebra | |
| Context menu | 1px `#979797` border; padding 1px 0; text inset 25px; submenu arrow 6x8 at 17px from right; separator 1px with 5px margin above/below, inset l4/r16 | |

## 5. Window layout

Root = CSS grid, one column, rows top-to-bottom (`rbxport:src/app/App.module.css`):

| Row | Content | Height |
|---|---|---|
| 1 | Title bar (macOS only; 0 on Linux) | 28 |
| 2 | Top bar | 30 |
| 3 | Decks (layout dependent) | auto: 279 (1 PLAYER) / 420+4 (2 PLAYER) / 59 (SIMPLE) / 0 (FULL BROWSER) |
| 4 | Body (tree + browser + optional panels) | 1fr |
| 5 | Pro DJ LINK strip (optional) | auto (68 + margin) |
| 6 | Status bar | 27 |

```
+--------------------------------------------------------------------------------+
| title bar 28 (centered "rekordbox" bold 13, #363738)  [macOS only]            |
+--------------------------------------------------------------------------------+
| top bar 30 #0F0F0F : layout menu | ... | gear | headphones | knob | VU 80w | CPU |
+--------------------------------------------------------------------------------+
| DECKS (black) 279 tall (1P) / 424 (2P)                                         |
| +-----+-----------------------------------------------------+---------------+  |
| |trans|  overview 49 (wave 30) + phrase 14 + scrub 3         | right panel   |  |
| |port |  detail waveform 146                                | 209w          |  |
| | 80w |  pad bar 48 (hot cue pads)                          | info/cues     |  |
| +-----+-----------------------------------------------------+---------------+  |
|  (4px black gutter)                                                            |
+----------------+-+-----------------------------------+-----+------+--+--------+
| TREE           |g| BROWSER                            |SUB  |INFO  |RR|        |
| 305w (drag)    |1| head 26: title .... [filter][search 212x24]| 878w?| <=557|24|        |
| #1E1E1E        |p| col header 24 #1E1E1E              |     |(<=25%|w |        |
| rows 25        |x| rows 25 zebra #0F0F0F/#1E1E1E     |     |  )   |  |        |
| (rail 57w left)| | scrollbar 12                       |     |      |  |        |
+----------------+-+-----------------------------------+-----+------+--+--------+
| status bar 27 #000: "rekordbox"-style label  ...  "N Tracks, 5 hours 2 minutes, 759.7 MB" |
+--------------------------------------------------------------------------------+
```

Body grid columns (`.body`): `tree-w | 1px gutter | 1fr [| sub-browser auto] [| info min(557px, 25-33%)] | right-rail 24px (implicit)`.

| Region | Width / rule |
|---|---|
| Tree | default **305px**; drag via splitter; bounds min 140, max 50% of window, other side keeps >=360 (`rbxport:src/lib/splitter.ts`); double-click/reset restores 305 |
| Tree source rail (left of tree, vertical icon+label buttons) | 57px (`--s-tree-rail-w`); selected = `#323232` bg + icon-on |
| Splitter | 1px black gutter; hover `#323232` |
| Sub-browser | 878px token default, clamps to row; its own inner tree 298px + 1px gutter + list 1fr |
| Info panel | 557px max, capped to 25% (with sub) / 33% (alone) of window |
| Right rail (icon strip: filter/sub-browse/info toggles) | 24px wide, 18px buttons, 34px pitch, lit = `#3571E3` |
| Deck right panel | 209px; deck transport column 80px (1P) / 70px shared (2P) |
| Prefs window | 798x828; sidebar 159; Sync window 1440x620 |

Layout modes (top-left dropdown, `rbxport:src/lib/layout.ts`): `1 PLAYER`, `2 PLAYER`, `SIMPLE PLAYER`, `FULL BROWSER`. Browser is identical in all; only deck count/size changes.

Top bar content (left to right): layout dropdown, spacer, clock (12px bold), settings gear (14px, 24px hit), headphone/cue, master knob 28px (blue arc 2.6 stroke, `#323232` track, round pointer), VU 80w x 3px x2 channels (3px gap), CPU/dropout meter 35w. Icons `#A0A0A0` idle, `#F0F0F0` hover, `#1373EB` when on.

Status bar: bold 11.5px `#969696`; left = app label + version (10px, 400); right (ml:auto) = list totals or selection; right padding 34.5px.
- Totals format: `61 Tracks, 5 hours 2 minutes, 759.7 MB` (hours/minutes always plural: "1 minutes"; size 1 decimal, binary units).
- Selection: only when >=2 rows: `Selected: N Tracks`; 0-1 selected = blank.

## 6. Track browser columns

Source `rbxport:src/lib/columns.ts`, formatting `rbxport:src/lib/format.ts`.

### 6.1 Default visible (in order) + width

| # | Column | Width px | Align | Sortable | Format |
|---|---|---|---|---|---|
| 0 | `#` (fixed, always first) | 47 | right | yes (default sort, `# ↑` = playlist order) | row number |
| 1 | Preview | 128 | left | no | mini waveform; click row waveform to audition |
| 2 | Artwork | 80 | left | no | thumbnail |
| 3 | Track Title | 387 | left | yes | text (required, cannot be hidden) |
| 4 | Key | 73 | left | yes | classical name (`Ebm`) |
| 5 | BPM | 80 | right | yes | `128.00` (stored x100, 2 decimals) |
| 6 | Time | 80 | right | yes | `MM:SS` zero-padded, no hours (`04:26`) |
| 7 | Rating | 101 | left | yes | 5 stars |
| 8 | Artist | 301 | left | yes | text |
| 9 | Comments | 210 | left | yes | text |
| 10 | Label | 128 | left | yes | text |
| 11 | Date Added | 128 | right | yes | `M/D/YY` no leading zeros (`9/6/26`) |
| 12 | Release Date | 128 | right | yes | `M/D/YY` |

Attribute column (67px, not default-visible): analysed star (10px white star shape), cue marker, orange `[!]` for missing file (3.5px stroke + dot, `#FF9600`).

### 6.2 Optional columns (header context menu; checkboxes)

Menu order: Attribute, Preview, Artwork, Track Title, Release Date, Artist, Genre, Comments, Size, Disc number, Album Artist, Track number, BPM, Rating, Composer, Lyricist, Time, File Type, Year, Mix Name, Remixer, Label, Original Artist, Key, Sample Rate, Bitrate, Bitdepth, File Name, Location, Date Added, Date Created, Hot Cue, Publish track information, Message, Color, DJ Play Count, My Tag, Album, Cloud, (+ File Created, rbxport-only).

Notable widths: Album 240, Genre 160, File Name 260, Location 320, Album Artist 200, Size 90 (`144.8 GB` / `15.2 MB`), Year 70, Sample Rate 110 (`44.1 kHz`), Bitrate 90 (`320 kbps` or `VBR` when 0), Bitdepth 90 (`16 bit`), Color 90 (ball + name), Hot Cue 110 (letters `A, B`), DJ Play Count 120.

- Min column width 32, max 1200. Right-align: `#`, BPM, Time, Size, Year, dates, sample rate, bitrate, bit depth, counts.
- Explorer (folder) layout: Preview 200, Artwork 80, Title/Artist/Album/Genre/Key/File Name 128, BPM 80, Rating 90, Time 80.
- Header: click = sort (toggle asc/desc, arrow 9px blue + blue text); drag header = reorder (ghost copy at 85% opacity, original goes blank); drag right-edge grip = resize; right-click = column menu.

## 7. Tree / sidebar

- Source rail buttons (icon 16px + 10px label, stacked, 57px wide): **Collection**, **Playlists** (folder icon), **Explorer**, **Devices**, **Histories**, plus Tag List, Related Tracks, Sync (pinned bottom). Idle `#A0A0A0`, selected `#F0F0F0` on `#323232`, empty source 45% opacity.
- Tree node kinds: collection, playlist, smartPlaylist (Intelligent), folder, device, devicePlaylists, deviceFolder, devicePlaylist, history, directory (Explorer), note (dim, not hoverable), related / relatedCriterion (e.g. "BPM + KEY", "Same artist", "Same genre in 30 days", "Track Suggestion"), tagList.
- Node row: 25px; [twisty 10px] [icon 14x12] [label ellipsis]; depth indent via nested rows. Icon colour `#E6E6E6`; Explorer directory icons `#A0A0A0`.
- Twisty: right-pointing triangle (closed), down (open), none for leaf.
- Devices: label + eject button (24x22, 11x12 glyph) appearing on hover/focus; sync-able USB sticks listed with their own Playlists tree.
- States: hover `#2B2B2B`, selected `#314B67`, drop-above/below = 2px accent line, drop-into-folder = 1px inset accent ring.
- Inline rename: field 18px tall, 1px accent border, radius 2, black bg.
- Tree search box at top of tree (scoped options dropdown, menu 154px wide).
- Tree gets its own thin scrollbar (12px, same look as table).

## 8. Player / deck area

Dimensions (`--s-player-*`, `--s-mixer-*`):

| Part | Value |
|---|---|
| 1-deck height | 279; 4px black gutter under |
| 2-deck band | 420 (+4 gutter); each deck 210; shared transport column 70 + 3px gutter + mixer strip 48 |
| Simple player | 59 tall |
| Layout | transport 80 / waveforms 1fr / right panel 209 |
| Title row | 21 (1P) / 42 (2P); artwork 45 (1P) / 36 (2P); simple 48 |
| Overview waveform | band 49 (wave 30); 2P 51 (wave 27); 12px inset both sides |
| Vocal strip | 5px; phrase bar 14px; scrub (position) bar 3px |
| Detail waveform | 146 (1P); ~76 (2P); insets top 20 / bottom 16 |
| Beat markers | top 5 / bottom 1; head 4 |
| Pad bar | 48; pad tab 80x24; hot-cue pad 27x28 gap 5.5; edit pad 23.5x26 gap 5 |
| Buttons | 26x22 (1P); jog rings 40 (1P) / 32 (shared); jump 24.5x22, gap 4.5; size box 54x27 |
| Mixer EQ | band 36x15 gap 5; knob 19; fader 53 tall, track 2 wide, handle 28x3 |
| Cue marker | 16x11 (flag), badge 11 |
| Deck B | mirrored vertically (title at bottom, detail waveform flipped `scaleY(-1)`) |

Deck behaviours: CUE ring (hold), PLAY ring (green when playing), Q quantize, SYNC / MASTER / MASTER TEMPO / RST, 1-32 beat loops, loop in/out/reloop, memory cues + 8 hot cues A-H, jump menu, key shift, tempo slider, DUAL CONTROL glyph on centre line between decks, waveform zoom cluster (magnifier +/-). Black dominant; deck panel `#000`, transport rail `#1E1E1E`.

Canvas colours come from `rbxport:src/styles/theme.ts` (JS mirror of key tokens for canvas drawing): waveLow..waveAll, pcm*, cue*, vocal.

## 9. Interaction patterns

| Pattern | Behaviour |
|---|---|
| Selection | click = single; shift = range (anchor); cmd/ctrl = toggle (`modifierFor`); shift+up/down extend; cmd+A all; cursor/page/home/end keys move |
| Load track | double-click row, or Enter -> deck 1 (shift+Enter -> deck 2); or drag row onto deck |
| Drag tracks | rows draggable (custom drag ghost `dragGhost.ts`); drop on tree playlist/folder/device; drop above/below row = reorder line; edge autoscroll (`dragAutoscroll.ts`) |
| Drag files in | OS file drop on browser = import; outline `2px #314B67` while over |
| Tree move | drag node: above/below line (accent 2px), into folder (inset 1px ring) |
| Context menu | row, tree node, header each have their own; submenus w/ arrow; disabled `#616161`; 25px rows; enabled hover = accent bg `#1373EB` + `#F0F0F0` text |
| Inline edit | second single click on title/artist/album/genre/label/key/bpm = edit in place (black field); double-click on title still loads; key edits via a list of existing keys; Enter commits |
| Rating | click star sets; click same star clears; double-click swallowed |
| Sort | header click; arrow 9px blue; sorted header text blue; `#` default = playlist order |
| Column ops | drag-resize (grip 5px), drag-reorder, menu toggles; layout persisted |
| Preview | click the Preview-column waveform to audition from that position |
| Filter | filter toggle (18px outlined square, blue border when on) opens Track Filter bar (BPM / key / rating / colour / tag lists, AND/OR switch) between head and list |
| Search | 212x24 field, scope dropdown, Esc clears |
| Splitters | drag col-resize cursor; pointer-capture; re-clamped on window resize; reset -> 305 |
| Lit cell | `data-lit` cells paint green `#64FF00` w/ black text (selected or not) |
| Missing file | orange `[!]` in Attribute column; Missing File Manager window |
| Window | custom title bar draggable (`data-tauri-drag-region`); Linux uses native bar |
| Feedback | status-bar error text flashes (300ms x2, opacity 1 -> .3) |

## 10. Shortcuts (Export preset; Cmd on macOS = Ctrl on Windows)

Source `rbxport:docs/reference/shortcut-commands.md`, `rbxport:src/lib/shortcuts.ts`.

| Area | Key | Action |
|---|---|---|
| Browser | Cmd+F | focus search |
| | Esc | clear search |
| | Cmd+A | select all |
| | Up/Down, PgUp/PgDn, Home/End, Cmd+Up/Down | cursor |
| | Shift+Up/Down | extend selection |
| | Enter / Shift+Enter | load on deck 1 / 2 |
| | Cmd+L | locate track loaded on deck |
| | Shift+Cmd+A | analyse selection (rbxport's own) |
| App | Cmd+F12 / F11 / F10 | volume up / down / mute |
| Deck A | Space | play/pause |
| | C (hold) | cue |
| | Q | quantize |
| | Left / Right | jump back / fwd |
| | M | memory cue; B / N call prev/next; X delete |
| | I / O / R | loop in / out / reloop |
| | 4-9 | 1/2/4/8/16/32 beat loop |
| | `/`, Opt+`\` | loop /2, x2 |
| | 1-3 (+Cmd) | set / clear hot cue A-C; D-H unbound |
| | F10 / F11 / F12 | show memory cues / hot cues / info |
| | F1 / F2 / F3 | SYNC / master tempo / tempo reset |
| | F9 | metronome sound |
| Deck B | Shift + deck A keys | same commands, deck B |

Presets: Export (default), Performance 1, Performance 2, None. Commands run through one registry (`commands.ts`), key and menu hit the same function.

## 11. Icons

- Own inline SVG set in `rbxport:src/components/icons.tsx` (~65 icons, TSX components). ALL paint with `currentColor` -> colour comes from CSS token of container.
- Families: library (Collection, Folder, SmartList, History, Device, Eject, Explorer, List, Note, Comment), controls (Gear, Headphones, Link/LinkOn, Sync, Record, Reload, Filter, SubBrowse, Info), layout (LayoutOne/Two/Simple/Browser/Dual), grid editing (Grid* x ~16), loop/cue (LoopIn/Out, CueLoop), zoom (MagnifierPlus/Minus), prefs (PrefAudio/Analysis/Keyboard/View/DjSystem/Advanced/About), stars (StarLit/Empty), sort (SortUp/Down), misc (Spinner, ClearCircle, ArtworkImport/Delete).
- Style: flat monochrome glyphs, no lucide/font icon library. Idle `#A0A0A0`, active `#F0F0F0`, on `#1373EB`.
- Rekordbox's own skin SVGs referenced as `skins/*_off.svg` (160 grey) / `*_on.svg` (240 grey) — we do not have them.

## 12. Light / dark

- Dark only. No `prefers-color-scheme` handling, no light variant, no theme store. Every colour explicitly set so the page never inherits host colours (also `html,body,#root` bg = `#000`, overflow hidden).
- Only runtime switches: layout (1/2/simple/browser), font-size (Browse > FontSize scales `--f-size-ui` via `--f-size-ui-base`), waveform mode.
- `rbxport:public/os.js` sets platform flag (`data-platform="linux"` hides custom title bar).

## 13. Our frontend today (for comparison)

| Aspect | Ours | Where |
|---|---|---|
| Design system | "Melodex": amber accent, DM Sans + JetBrains Mono, deep blue-grey | `frontend/tailwind.config.js`, `frontend/src/index.css` |
| Colour tokens (two parallel copies) | Tailwind `colors.mx.*`, `line.*`, `ink.*`, `amber2.*`, `ok/bad/info`; plus CSS vars `--mx-*`, `--line-*`, `--ink-*`, `--amber*` in `:root` | tailwind.config.js:20-60, index.css:16-45 |
| Fonts | `fontFamily.sans/mono`; `--font-ui`, `--font-mono`; Google Fonts `@import` in index.css line 8 | |
| Sizes | `fontSize xxs/tiny`; `spacing` keys `sidebar 220, player 72, toolbar 48, header 52, row-d 36`; `borderRadius mx-xs..xl` (2/4/6/8/12); `boxShadow mx-*` | tailwind.config.js |
| Track table | `frontend/src/components/TrackTable.jsx`; columns array `DEFAULT_COLUMNS` (line 9): index, preview, artwork, Title, Artist, Album, BPM, Key, Rating, Color, Bitrate, PlayCount, Composer, Remixer, TotalTime, DateAdded, actions; widths in px/%; header 10px uppercase tracking-wider; rows ~36px with 36px artwork, bottom border; text-[12px]; `CAMELOT_COLORS` map line 29 colours Key cells | |
| Row colours | inline `style={{ background:'var(--mx-shell)', borderBottom:'1px solid var(--line-subtle)' }}` + Tailwind `bg-mx-hover`, `bg-mx-shell`, etc.; mixed with hardcoded hex/blue-400/cyan-400/white/10 in places | TrackTable.jsx:138-180,345-533 |
| Library view | `MetadataView.jsx` (modes playlists/artists/labels/albums) -> `PlaylistBrowser.jsx` + `TrackTable.jsx`; shell in `main.jsx` (top bar + WorkspaceNav) | docs/frontend-index.md |
| Player | `Player.jsx` (72px bottom player), `WaveformEditor.jsx` | components/ |
| Appearance settings | `SettingsAppearance.jsx` (82 lines): ONLY waveform colours + locale; stores `waveform_visual_mode`, `waveform_color_{low,mid,high}` in app `settings` (defaults `#ef4444 / #22c55e / #3b82f6`) | components/settings/ |
| Theme switching | none. No `data-theme`, no theme provider, no density setting. | grep confirms |
| Light mode | none | |
| Icons | lucide-react | TrackTable.jsx:2, SettingsAppearance.jsx |
| Constants | `frontend/src/config/constants.js` (magic numbers) | |

Key structural gaps vs a Rekordbox look:
- Tailwind keys point at literal hex -> not runtime-swappable. Components mix Tailwind classes, `var(--mx-*)`, and hardcoded colours.
- No row-height/density tokens. Row height implied by padding classes.
- Fixed Google fonts; no Arial option.
- Layout is workspace-tab shell (not tree + browser + decks split).

## 14. Mapping: rbxport token -> our target

Strategy: make our existing Tailwind keys read CSS vars (`rgb(var(--x) / <alpha>)` or plain `var(--x)`), then a skin = overriding vars under `[data-theme="rekordbox"]`. Our vars first; Tailwind keys follow.

| rbxport token | Rekordbox value | Our CSS var | Our Tailwind key | Notes |
|---|---|---|---|---|
| `--c-black` | `#000000` | `--mx-deepest` | `mx.deepest` / `djdark` | body bg; also kills the body amber radial-gradient (index.css body `background-image`) |
| `--c-top` | `#0F0F0F` | `--mx-shell` | `mx.shell` | top bar + odd rows |
| `--c-panel` | `#1E1E1E` | `--mx-panel` | `mx.panel` / `djgray` | tree, header, even rows |
| `--c-button` | `#2B2B2B` | `--mx-hover` | `mx.hover` | hover |
| `--c-raised` | `#323232` | `--mx-card` (+ `--line-default`) | `mx.card`, `line.DEFAULT` | dividers, raised |
| `--c-select` | `#314B67` | `--mx-selected` | `mx.selected` | selected row |
| `--c-field` | `#000000` | `--mx-input` | `mx.input` | inputs |
| (n/a, between panel and button) | `#1E1E1E` | `--mx-surface` | `mx.surface` | set = panel |
| border / divider | `#323232` | `--line-subtle`, `--line-default`, `--line-interactive` | `line.*` | all -> `#323232` (interactive `#646464` outline) |
| `--c-text` | `#E6E6E6` | `--ink-primary` | `ink.primary` | |
| `--c-text-dim` | `#9A9A9A` | `--ink-secondary` | `ink.secondary` | |
| `--c-status-text`/`--c-icon-off` | `#969696`/`#A0A0A0` | `--ink-muted` | `ink.muted` | choose `#969696` |
| `--c-field-placeholder` | `#4B4B4B` | `--ink-placeholder` | `ink.placeholder` | |
| `--c-accent` | `#1373EB` | `--amber` | `amber2.DEFAULT` | brand accent slot -> blue. Name stays "amber" (rename later) |
| accent hover | `#4775FF` (search focus) / lighter blue | `--amber-hover` | `amber2.hover` | |
| accent press | `#0E5CC0` (derive, `[ASSUME]`) | `--amber-press` | `amber2.press` | |
| accent dim | `#314B67` | `--amber-dim` | `amber2.dim` | |
| accent glow/bg | `rgba(19,115,235,.20 / .08)` | `--amber-glow`, `--amber-bg` | — | derive from accent |
| `--c-meter-green` | `#2FBF4E` | `--ok` | `ok` | |
| `--c-error` | `#E23B2E` | `--bad` | `bad` | |
| `--c-sync-pending` | `#5BC8FF` | `--info` | `info` | |
| `--f-ui` | Arial stack | `--font-ui` | `fontFamily.sans` | |
| mono (BPM etc.) | none; use Arial + tabular-nums | `--font-mono` | `fontFamily.mono` | set to Arial stack + rely on `tabular-nums`, or keep mono for numerics |
| `--s-row-height` | 25 | NEW `--row-h` | `spacing.row-d` (36 now) | table rows + tree rows |
| `--s-col-header-h` | 24 | NEW `--head-h` | `spacing.header` (52 now: top header, different) | table header |
| `--s-top-bar-h` | 30 | NEW `--topbar-h` | `spacing.toolbar` (48 now) | |
| `--s-status-bar-h` | 27 | NEW `--status-h` | — | (we have no status bar) |
| `--s-tree-w` | 305 | NEW `--tree-w` | `spacing.sidebar` (220 now) | |
| `--s-player-h` | 279 (1P) | NEW | `spacing.player` (72 now) | our player is a docked bar, not a deck block |
| `--f-size-ui` | 16.5px | NEW `--fs-ui` | `fontSize` base | |
| `--s-scrollbar-w` | 12 | NEW `--scrollbar-w` | — | add `::-webkit-scrollbar` rules |
| radius 2/3 | 2 | NEW or override | `borderRadius.mx-*` | set mx-sm/md/lg -> 2px for flat look |
| shadow menu | `0 4px 12px rgb(0 0 0/.45)` | — | `boxShadow.mx-md/lg` | override |
| `--c-comment-*` (8) | see 2.4 | NEW `--lbl-{pink..purple}` | — | `Color` column dot; our table has a `Color` col |
| `--c-wave-low/mid/high` | `#0055E1` / `#FFA600` / `#FFFFFF` | settings `waveform_color_{low,mid,high}` | — | our waveform colours are user settings (SettingsAppearance.jsx), not CSS vars; skin = default preset for those keys (`waveform_visual_mode='custom'`) |
| `--c-cue-*`, phrase | see 2.5 | consumers in `WaveformEditor.jsx`, `waveform/`, `daw/`, `editor/` | — | check each for hardcoded hex |
| key colours | none (plain text) | `CAMELOT_COLORS` in TrackTable.jsx:29 | — | skin should render key text in `--ink-primary` (add `data-theme` guard or `var(--key-colorize)` switch) |
| rating star | `#E6E6E6`, hover accent | TrackTable star markup | — | |

## 15. Implementation plan — Rekordbox skin

Goal: opt-in theme, zero behaviour change for default Melodex.

1. **Token indirection** (prereq).
   - `frontend/tailwind.config.js`: change `mx.*`, `line.*`, `ink.*`, `amber2.*`, `ok/bad/info` from literals to `var(--...)` strings (Tailwind 3 accepts plain `var()`; opacity modifiers like `/50` then fail -> either use `rgb(var(--x-rgb) / <alpha-value>)` with space-separated channel vars, or grep for `/` alpha usage on these keys first).
   - `frontend/src/index.css` `:root`: keep Melodex values; add new vars `--row-h`, `--head-h`, `--topbar-h`, `--tree-w`, `--fs-ui`, `--fs-sm`, `--scrollbar-w`, `--radius-sm/md`, `--lbl-*`, `--key-colorize` with Melodex-equivalent defaults.
2. **Skin file**: new `frontend/src/themes/rekordbox.css` with `:root[data-theme="rekordbox"] { ... }` overriding every var via §14 table. Import in `index.css` (after `:root`). Include: Arial stack, 25/24/30/27 metrics, flat radii, black body (and `background-image: none`), 12px scrollbars (rbxport-style black track, `#323232` thumb), zebra rows (`tbody tr:nth-child(odd/even)` under the data-theme selector).
3. **Switch**: setting `ui_theme` (`'melodex' | 'rekordbox'`) in app settings; apply `document.documentElement.dataset.theme` early (in `frontend/src/main.jsx` before render; read from settings/localStorage in try/catch to avoid flash). Add selector + preview to `frontend/src/components/settings/SettingsAppearance.jsx` (new "Theme" Section above Waveform Colors; reuse `Section`/`Field` from `SettingsControls`). When rekordbox chosen, offer "apply Rekordbox waveform colours" (sets `waveform_color_*` = `#0055E1/#FFA600/#FFFFFF`).
4. **TrackTable parity** (`frontend/src/components/TrackTable.jsx`):
   - Row height via `var(--row-h)` (replace 36px artwork/padding implied height; artwork thumb shrinks to ~row-h - 4 or stays hidden in skin).
   - Header: sentence case 16.5px, no uppercase/tracking in skin; sorted header text + arrow = accent; 1px right border dividers; 5px resize grip.
   - Zebra + selected `#314B67` + hover `#2B2B2B` via vars.
   - Key cells: skip `CAMELOT_COLORS` when `--key-colorize: 0` (or `data-theme=rekordbox`).
   - Column defaults for skin: `# | Preview | Artwork | Title | Key | BPM | Time | Rating | Artist | Comments | Label | Date Added` with §6 widths; BPM `toFixed(2)` right-aligned; Time `MM:SS`; dates `M/D/YY`; tabular-nums.
   - Colour column: 8px dot + name text (hex from §2.4).
   - Sort arrow = filled triangle 9px.
5. **Shell/layout** (`frontend/src/main.jsx`, `PlaylistBrowser.jsx`): tree width var 305 with draggable splitter (min 140, max 50%); status bar (27px black) with `N Tracks, H hours M minutes, X MB` and `Selected: N Tracks`; top bar 30px `#0F0F0F`. Bigger change; do after steps 1-4 (cosmetic first, structural second).
6. **Menus/modals**: context menu 25px rows, `#1E1E1E` + 1px `#979797`, hover accent bg; replace hard-coded `hover:text-amber2`/`text-blue-400`/`text-cyan-400` in TrackTable context menu with token classes.
7. **Hardcoded colour sweep**: `rg -n "#[0-9a-fA-F]{6}|rgb\(|blue-|cyan-|white/" frontend/src` — move to tokens or the skin cannot reach them (DAW/waveform/editor components likely have many).
8. **Player** (`Player.jsx`): skin = black bg, green PLAY ring `#60D330` playing, CUE ring `#EDB751`, blue active states `#3571E3`; keep 72px dock unless a deck-block layout is wanted (279px two-row waveform layout = separate feature, research doc first per `.claude/rules/research-pipeline.md`).
9. **Verify**: `e2e-tester` on Library view with theme toggle; screenshot vs rekordbox reference; `npx eslint src --ext .js,.jsx`.
10. **Docs/registry**: `docs/features/*.toml` entry (`python scripts/feature_map.py --who theme`) first; update `docs/frontend-index.md`; `python scripts/regen_maps.py`.

Effort order: 1+2+3 (themeable skeleton, ~1 session) -> 4+6+7 (table/menus) -> 5+8 (layout/player, needs research doc).

## 16. Open questions / caveats

- rbxport `[ASSUME]` marks exist for submenu tick, menu title size; low risk.
- Playing-row highlight not in tokens; if wanted, pick `--c-play-ring-on` `#60D330` as a left marker (our design decision, not a rekordbox fact).
- Windows rendering: rbxport measured on macOS 2x and Windows 175% (issue refs in token comments); 16.5px base font is macOS-pt derived — on Windows at 100% scale may look big; test.
- Trademark: do not name the theme with rekordbox logos/wordmarks; "Rekordbox-style" label OK, no Pioneer assets.
- GPL: reimplement from this doc; do not open rbxport files side-by-side while writing CSS if strict clean-room is wanted.
