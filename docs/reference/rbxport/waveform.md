# Waveforms — ANLZ encoding, DSP, rendering (rbxport study)

Reference for waveform-overhaul + ANLZ writer fixes. Facts only, own words.

## 1. Sources + license note

- Studied: rbxport (GPL-2.0-or-later). Repo is MIT. **No code copied.** Facts (rates, bit layouts, freqs, formulas, render rules) re-expressed; short pseudocode only. Cite as `rbxport:<path>`.
- Files read:
  - `rbxport:docs/reference/waveform-analysis.md` (PWV6 calibration)
  - `rbxport:crates/rbl-analysis/src/waveform.rs` + `docs/algorithms/waveform.md` (DSP)
  - `rbxport:crates/rbl-anlz/src/encode.rs`, `write.rs` (tag encoders, section headers)
  - `rbxport:docs/reference/usb-export-db.md` §Waveforms (tag table)
  - `rbxport:src/canvas/waveform.ts` (+ `waveform.test.ts`), `src/views/browser/WaveformPreview.tsx`, `src/views/player/WaveformDetail.tsx`, `Player.tsx`, `Player.module.css`, `src/lib/player.ts`, `src/lib/canvasSize.ts`, `src/styles/tokens.css`
  - `rbxport:docs/user/waveform-scrubbing.md`
- Evidence tags in rbxport: `[OBS]` measured on real rekordbox files, `[static]` read from player firmware / rekordbox binary, `[DOC]` documented, `[UNKNOWN]` unresolved. Keep that distinction when porting.
- Caveat: rbxport's own DSP is an **empirical approximation**, calibrated on 9 tracks (not held-out). Not recovered rekordbox DSP.
- `rbxport:crates/rbl-link/tests/fixtures/captured-waveform-{preview,detail}.bin` (904 B / 43,538 B): bytes captured from a real player/rekordbox over the Pro DJ Link blob request; used as golden outputs of `waveform_preview()` / `waveform_detail()` in `rbl-link/tests/blobs.rs`. Not parsed here. Useful as a template for our own golden-file tests (we have none for waveform bytes).
- `waveform_probe.rs` = read-only dump of decoded mono + PWV6/PWV7 payloads. `repair_waveforms.rs` = rewrites only PWV6 in an existing library, backs up, keeps grid/cues. `colourwave.rs` = dumps PWV4-7 header words + band stats from a real library to reverse the colour mapping. Dev tools; no format facts beyond below.

## 2. Tag overview

| Tag | File | Entries | Bytes/entry | Payload | Used by (per rbxport) |
|---|---|---|---|---|---|
| PWAV | .DAT | fixed 400 | 1 | `wwwhhhhh` (3b whiteness, 5b height) | BLUE overview: track-list row preview, deck overview strip; fallback overview when colour/3band tag missing (rekordbox deck, rbxport#372) |
| PWV2 | .DAT | fixed 100 | 1 | height only, 1..15 (no whiteness) | tiny preview (older players; Nexus firmware validates it) |
| PWV3 | .EXT | 150/s | 1 | same as PWAV | BLUE scrolling detail |
| PWV4 | .EXT | fixed 1200 | 6 | `peak>>1, 0, 0, R, G, B` | RGB overview (NXS2-era colour); XDJ-AZ reads it |
| PWV5 | .EXT | 150/s | 2 | BE u16 `rrrgggbbbhhhhh00` | RGB scrolling detail; CDJ-3000 draws it as raw bits |
| PWV6 | .2EX | fixed 1200 | 3 | low, mid, high (7-bit) | 3Band overview (rekordbox 7, CDJ-3000) |
| PWV7 | .2EX | 150/s | 3 | low, mid, high (7-bit) | 3Band scrolling detail (rekordbox 7, CDJ-3000) |
| PWVC | .2EX | - | - | opaque, carried through | unknown; rbxport only copies it |

- Palette -> tag map in rbxport UI (View > Color > Waveform color): `blue` = PWAV/PWV3, `rgb` = PWV4/PWV5, `3band` = PWV6/PWV7.
- 150 columns/s everywhere for detail. Preview columns are fixed count regardless of duration.
- Section order rbxport writes (matches rekordbox 7.2.19 share tree): DAT `PPTH PVBR PQTZ PWAV PWV2 PCOB PCOB`; EXT `PPTH PWV3 PCOB x2 PCO2 x2 PWV5 PWV4 (PSSI)`; 2EX `PPTH PWV7 PWV6 (PWVC PVDI)`. PVBR required between PPTH and PQTZ: rekordbox 6/7 reject a .DAT without it.

## 3. Per-tag encoding

### 3.1 Section headers (big-endian)

| Tag | Header after `tag,len_header,len_tag` | len_header | Notes |
|---|---|---|---|
| PWAV, PWV2 | `u32 entries(=bytes)`, `u32 0x00010000` | 20 | |
| PWV3 | `u32 1`, `u32 entries`, `u32 0x00960000` | 24 | trailer constant in 400 ref files [OBS]; 0x0096 = 150 |
| PWV4 | `u32 6`, `u32 entries`, `u32 0` | 24 | |
| PWV5 | `u32 2`, `u32 entries`, `u32 0x00960305` | 24 | |
| PWV6 | `u32 3`, `u32 entries` | **20** | shorter header = trap |
| PWV7 | `u32 3`, `u32 entries`, `u32 0x00960000` | 24 | |

### 3.2 Bit layouts

| Tag | Layout | Ranges |
|---|---|---|
| PWAV / PWV3 | bits 7-5 whiteness, bits 4-0 height | height PWAV **2..25** (never 0), PWV3 0..31 |
| PWV2 | bits 3-0 height only | **1..15**; any byte >15 makes Nexus firmware reject whole preview incl. PWAV |
| PWV4 | b0 `peak>>1` (0..127); b1,b2 `[UNKNOWN]` write 0; b3 = **R = low**; b4 = **G = mid**; b5 = **B = high** | all 0..127 (b0 reaches 127 max; channels reach 127) |
| PWV5 | bits 15-13 R(low), 12-10 G(mid), 9-7 B(high), 6-2 height, 1-0 unused | R,B 0..7; G ceiling 5 in rekordbox output; height 0..31 |
| PWV6 | b0 low, b1 mid, b2 high | 0..127; rekordbox tops ~98 on 80 tracks; "already scaled drawing height" |
| PWV7 | b0 low, b1 mid, b2 high | 0..127 = `band>>1` of 0..255; reaches 127 on loud tracks |

Colour channel semantics (issues #158/#288 in rbxport): in PWV4/PWV5 **red = bass, green = mids, blue = highs**. Confirmed by corr(PWV4.b3, PWV6.low) = 0.83-0.96 on 11 tracks, and by Deep Symmetry sine-sweep reverse engineering.

### 3.3 Per-tag value rules (as written by rbxport, matched to rekordbox [OBS])

Inputs: per-column band peaks low/mid/high/peak, each 0..255, at 150/s.

- **Bucket reduction** for previews (PWAV 400, PWV2 100, PWV4 1200): each output bucket takes the **max** per field of the detail columns it spans (transient-preserving). `from = i*N/count`, `to = max(from+1,(i+1)*N/count)`.
- **PWAV height**: loudest of the three bands, then scaled so full-scale -> **25** (ceiling). Uses `band()` scale (below) so loud masters do not pin to the top. rekordbox actual: 10-21 of 25 typical, max 24-25.
- **PWV2 height**: same, ceiling **15**, min 1.
- **Floors**: PWAV height >= 2, PWV2 >= 1. Reason: player firmware (`TotalWaveWacher_CheckWaveDataComplete`, XDJ-RX2 1.43) treats any 0 column as "unanalysed" and rebuilds preview from audio, overwriting stick data.
- **Whiteness** (PWAV/PWV3 bits 7-5): `round(7 * high / (low+mid+high))`, clamp 7. PWV2 has none.
- **PWV3 / PWV5 height**: from the column's **sample peak, squared**: `round(31 * (peak/255)^2)`. Matches rekordbox PWV3 within 0.14-0.42 step mean error on 11 tracks. Reaches exactly 31 on every reference track. PWV5 height equals PWV3 on 63-93% of columns; same curve used for both.
- **PWV4 height byte**: raw column peak `>>1` (linear, 0..127).
- **PWV4 colour**: `low>>1` unweighted; mid = `(mid>>1)*4/5`; high = `(high>>1)*13/20`. Weights chosen by least error (mean 26-34 /255 per channel on 11 tracks). XDJ-AZ firmware rescales so strongest channel is full before drawing, so only ratios matter.
- **PWV5 colour**: normalised, not raw. Pseudocode:
  ```
  l = 2*low ; m = 2*mid ; h = 3*high        # high weighted 1.5x vs others
  s = max(l,m,h) ; if s==0 -> (0,0,0)
  R = round(7*l/s) ; G = round(5*m/s) ; B = round(7*h/s)   # green ceiling 5
  ```
  Rekordbox [OBS]: strongest channel is 7 in 80% of columns, 5-6 in most of rest; green 5 in 51%, 6 in 2.6%, 7 in 0.2%. CDJ-3000 [static, fw 3.20] and XDJ-AZ draw these 3 bits as-is shifted to a byte (`(c&7)<<5`), no normalise on device -> unnormalised bits draw dim/washed out (brightest channel avg 3.0-3.6 vs rekordbox 6.6-6.9).
- **PWV6 value**: written from an independent energy overview (see §4.3), already 0..127. Legacy fallback: `band(v)=v*44/255` (peak-derived, max 44) — peak-derived at full scale draws as a solid block (2.9x too tall).
- **PWV7 value**: `band>>1` of detail peak columns, full 0..127. Scaling PWV7 like PWV6 made scrolling envelopes only 31-41% of rekordbox height (shape r>=0.97 either way). So PWV6 and PWV7 are on **different** effective gains; renderer reads both against 127.

## 4. Analysis algorithm (DSP chain)

### 4.1 Common
- Input: mono samples (downmix before; rbxport takes already-mono decode). Any sample rate; `per_column = floor(sr/150)` samples per detail column. Last short chunk kept (ceil).
- Output per column: `low, mid, high, peak` each `clamp(v,0,1)*255` truncated to u8.

### 4.2 Detail columns (PWAV/PWV2/PWV3/PWV4/PWV5/PWV7 source)
- Band split = **cheap one-pole filters**, not Butterworth:
  - `a = exp(-2*pi*fc/sr)`, clamp 0..0.9999
  - `lp200 = LPF(200 Hz)`, `lp2k = LPF(2000 Hz)`
  - `low = lp200`, `mid = lp2k - lp200`, `high = x - lp2k`
- Crossovers: **200 Hz and 2 kHz**.
- Window: 1/150 s non-overlapping, **peak** (max |x|) per band per window, not RMS. Streaming `Builder` keeps filter state across chunks and gives identical columns to batch.
- No dB/log curve, no gamma on detail bands. Only curve = squared peak for 5-bit heights (§3.3). Normalisation: none (absolute, clamp at 1.0).

### 4.3 PWV6 overview (separate path, 1200 buckets)
Peak-reducing the 150/s detail gave spiky cream + shallow blue. So overview measures **energy**:
- Bass: one-pole LPF 200 Hz, mean of `x^2` per bucket, then `pow(., 0.45)` (= sqrt then ^0.9 "mild compression").
- Mid: cascaded 2nd-order Butterworth biquads HPF 200 Hz then LPF 2 kHz (RBJ, Q=1/sqrt2), mean `|x|` per bucket.
- High: 2nd-order Butterworth HPF 2 kHz, mean `|x|` per bucket.
- Bucket index = `((i+1)*1200-1)/len`, floor-divided; cutoff capped at 0.45*sr.
- Track gain: `target = mean over 150Hz windows of window-RMS * 92`. Per band: `value = band * target / mean(band over all buckets)`. I.e. each band's **mean** is pinned to 92x the track's mean RMS. Round, clamp 0..127.
- Two-bucket trailing average (`(cur+prev)/2`) = release + half-bucket alignment.
- Calibration result: boundary error 0.60-2.18 px at 40 px height (9 tracks), was 1.7-3.7 px. Go Back regresses. Remaining error = track-level gain. Regression gate 2.5 px.
- Silence -> all zeros; isolated impulse must not lift overview (test: total diff < 360).

### 4.4 Preview reductions
- All previews derive from the 150/s columns by bucket-max (`resample`). PWV6 is the only exception (own pass).

### 4.5 Scrub audio (not waveform data, but related)
- Drag-scrub plays audio at drag speed; stereo 2-pole Butterworth LPF cutoff = concave quadratic ease-out, **400 Hz at rest -> 19 kHz at 1x**, flat above. Coefficients glide 5 ms; cutoff capped 0.4*device sr; speed = audio seconds/s so zoom changes sensitivity. Impl lives in `rbxport:crates/rbl-deck/src/scrub.rs`.
- Drag mapping in UI: `dSeconds = -(dx/width) * span * duration` (drag right = go back). `rbxport:src/lib/player.ts` `dragSeconds`.

## 5. Colour formulas / palettes

### 5.1 3Band (PWV6/PWV7) — combination colours
Colour depends on **which bands reach a given height**, not one colour per band. 7 colours (sampled from rekordbox; mixxx#12326):

| Bands reaching | Colour |
|---|---|
| low only | `#0055E1` (blue) |
| mid only | `#FFA600` (amber) |
| high only | `#FFFFFF` (white) |
| low+mid | `#B4690A` (brown) |
| low+high | `#D2DCFA` |
| mid+high | `#FFF0D7` |
| all three | `#F5EBD7` (cream core) |

- Drawing order centred waveform: sort bands by reach desc; paint outermost stretch first in colour of cumulative combination; nearer stretches overpaint; bands with equal reach share one stretch. Result: blue outer envelope, brown/amber middle, cream core. No alpha blending, opaque fills.
- Single-value ramp (row preview with one value/column): ramp blue -> amber -> cream.
- Measured capture note: overview mid amber brighter (`#FF8C00`) than detail (`#B26505` for low+mid) — tokens use single set.
- PCM close-up trace colours (zoom beyond PWV7): blue `#5BA0FF`, 3band `#FFA600`, rgb `#F266DC`.

### 5.2 BLUE (PWAV/PWV3)
- Colour = ramp between `LOW` (`#0055E1`) and `ALL` (`#F5EBD7`) at `whiteness/7`. Height = `h/31`.

### 5.3 RGB (PWV4/PWV5)
- Colour = (R,G,B) channels **normalised so strongest = 255**, others proportional (quiet column as saturated as loud; only height differs). PWV4: bytes b3,b4,b5 (0..127). PWV5: 3-bit fields.
- Height: PWV4 `b0/127`; PWV5 `h5/31`.

### 5.4 Band weights for stacked 3Band height (measured vs 2x rekordbox capture, 1200 cols, r=0.99/0.97/0.96)
- Value-to-height divisors: **low /128, mid /256, high /128** (of full height). Predicts painted height `(2*low + mid + 2*high)/256` within 3.4% of band. Mid contributes half weight. Old flat `/150` drew amber too thin.
- `BAND_FULL_SCALE = 127`, `reach = max(0.5px, min(v,127)/127 * full)`; zero band = no stretch.

### 5.5 Other palettes
- Phrase colours (PSSI bar, 2x capture of rb 7.2.11): INTRO `#B83F1D`, UP1 `#8138F6`, UP2 `#6B36F6`(interpolated), UP3 `#5534F5`, CHORUS `#4EA730`, DOWN `#95753A`, OUTRO `#6886AB`, VERSE `#2F6FBF` (unmeasured), BRIDGE `#7A4FA8` (unmeasured).
- Hot cue default `#3CEB50`; memory-cue head `#EA3323`; cue line `#FFFFFF`; beat line `#4C4C4C`, beat head `#7C7C7C`; downbeat line `#FFFFFF`, downbeat head `#EA3323`; bars label `#367BDA`; tempo annotation `#75CBD8`; loop band `#3571E3` at 18% alpha (38% when active).
- Hot-cue colour tables (View > Color > HOT CUE color: CDJ / COLD1 / COLD2 / COLORFUL): 17-entry `ColorTableIndex` arrays per slot A-P + loop (index 36 = `#FF8C00`); uncoloured cue (index 0/NULL) takes table default by slot. CDJ = idx 22 (A-H) / 26 (I-P).

## 6. Rendering

### 6.1 Row preview (browser list) — `rbxport:src/views/browser/WaveformPreview.tsx`
- **Half height, bottom-anchored, bands STACKED**: blue slab from bottom, amber on top, white on top of that; heights = value/scale(128,256,128) * usable height. Stacking is what gives blue its flat top with amber riding above.
- Bitmap rendered once per (track,width,dpr,palette), cached as `ImageBitmap`. Cues painted after the bitmap (edits not cached).
- Cue badges: 7pt square at top, left edge on cue, bold 6pt letter, colour = cue colour or slot default. Memory cues = red 6x4pt downward triangle at top. Badge pushed inside right edge. Click on waveform previews from `x/width * duration`; click on badge starts at cue.
- Hit detection: later-drawn badge wins.

### 6.2 Deck overview strip
- Full-track, same data (PWV6 / PWV4 / PWAV). Falls back to PWAV in blue if palette's tag missing.
- Overview waveform height 30pt, strip 49pt (artwork+vocal+overview+position bar). Hot-cue badge hangs from top, left edge on cue. Memory cue = 13x10 red triangle head, no line.
- 2-PLAYER mode: "overlaid" half waveform from baseline (each band over the last, blue first, white last), reaching full band height at full scale.

### 6.3 Detail (scrolling) — `rbxport:src/views/player/WaveformDetail.tsx`
- **Centred** waveform: mirrored about centre line, each band reaches `value/127 * (usable/2)` each way. Playhead fixed; waveform moves under it. Window may hang off either track end; overhang drawn empty (not clamped, not stretched).
- Insets (rekordbox measured): 8pt clear on top (bar count + cue heads), 2pt bottom. Detail band 146pt high.
- Slice maths: shown columns = floor/ceil of window; x offset in **whole device pixels** (`round(((first/cols - from)/width)*canvasW)`) so 1-px bars never straddle two columns.
- Pixel -> column: `step = cols/width`. If `step >= 1`: per band **max** over spanned columns. If `step < 1` (zoomed in past 150/s): linear interpolation between adjacent columns, except sharp attacks (a==0&&b>0, or b-a>=16 && b>=2a) keep stepped so a kick is vertical not a diamond.
- Silent column: draw a 1px reference line at centre (or floor if half) so silence stays visible; hole only outside file span.
- Clock correction: detail clock = `cols/150` s, not audio duration (they differ by tens of ms). Window mapped `progress = (p*audioMs + originMs)/waveMs`. `originMs` = first nonzero column centre minus first beat, applied only if first beat <= 100 ms and correction in (0,50] ms (encoder delay).
- Beyond finest zoom: stereo **PCM min/max envelope** (8 bytes/col: L min,max,R min,max i16 LE) in two lanes at 25% / 75% height; fill alpha 0.26, stroke 1.0, base-line alpha 0.65; scaled to visible peak; linear interpolation; 750 ms guard reserve, request 2 s guard audio each side.

### 6.4 Zoom
- Steps in **bars across**: `[0.25, 0.5, 1, 2, 4, 8, 12, 16, 32, 64]`. rekordbox closest = 0.5 bar; 0.25 added via PCM. Span fraction = `bars*4*60/bpm / duration`, clamp [1e-4, 1]. Unknown tempo -> 0.08 of track.
- Only downbeats drawn at widest zoom (64 bars); every beat otherwise.
- Wheel zooms the waveform under the pointer.

### 6.5 Overlays (DOM over canvas, not baked into bitmap)
- **Beat grid**: 1 px line + 3px-wide triangles (4pt tall) at top and bottom ends; line does not span the band (starts ~5pt down). Downbeat line white + red heads, beat line `#4C4C4C` + `#7C7C7C` heads. Located by binary search over beat list. In PCM mode 2px, `#B3B3B3` / `#FFF`.
- **Cue markers**: hot cue = lettered badge (11pt overview, 22px@2x detail) centred on cue line; detail adds red 16x11pt triangle over badge and 1-2px white line; memory cue = red triangle only. Cues outside window not drawn (no edge pinning). Loop = translucent band in->out clipped to window.
- **Playhead**: fixed at head % of width; moved by `transform: translateX` per frame (no layout). Bars label above head.
- **Phrase bar** (PSSI): spans each phrase start -> next start, last to track end; label text only where block wide enough; unresolved phrase placed from beat number via beat length; dropped if tempo unknown. Always-show-labels preference.
- **Tempo changes**: BPM label at change, arrow + from/to for ramps, clipped to window.

## 7. Performance tricks

- **Overdraw + compositor slide**: detail canvas drawn once across **2x visible span** centred on an anchor; per frame only `transform: translateX(dx)` on the layer. Redraw only when `|progress - anchor| > span*(OVERDRAW-1)/4` (half the margin, so redraw lands before the edge arrives).
- **Whole-device-pixel slide** (`round(offset*dpr)/dpr`): fractional slides resample 1px bars -> shimmer (#346).
- **Canvas backing size** = exactly `round(css*dpr)`, dpr capped at 2, width max 16,384 (hardware limit). Preview canvases quantise width to 16 px steps to cut reallocation; scrolling canvas does NOT quantise (resampling flicker).
- Assigning canvas width/height clears it: only assign when changed.
- `useLayoutEffect` for redraw so canvas is new before the transform changes in the same frame.
- Data: raw bytes cached per track/kind; in-flight fetch shared (StrictMode safe); "edition" counter invalidates on re-analysis; old bytes kept while new load so a growing analysis does not blink.
- Row previews: bounded LRU (500) of `ImageBitmap` (explicit `.close()` on evict); 35 ms settle delay before fetch (skips hard flicks); max 16 concurrent requests; shared promise per key.
- Waveform bytes are tiny (400-1200 cols preview, 150/s detail) -> draw direct from bytes, no GPU path needed.
- Streaming builder: filters run across chunks; for very long audio overview computed per detail column then bucketed (edge shifts < 1/150 s).

## 8. Gap analysis vs our repo

Our files: writer `app/anlz_writer.py`; DSP `app/analysis_engine.py:1090-1280` (`generate_waveform_data`); API `app/services.py:527` (`generate_multiband_waveform`) via `app/main.py:788`; Rust `src-tauri/src/audio/analysis.rs`; UI `frontend/src/components/waveform/*`, `shared/WaveformMiniCanvas.jsx`, `daw/DawTimeline.jsx` + `daw/timeline/useTimelineRender.js`.

### 8.1 Encoding / DSP (CDJ-visible; correctness)

| # | Item | rbxport | ours (file:line) | Action |
|---|---|---|---|---|
| 1 | PWV4 byte layout | `peak>>1,0,0,R=low,G=mid,B=high` (0..127) | `analysis_engine.py:1206-1217`: `[high, mid, low, height, mid/2, low/2]` 0..255 | **Fix**: reorder, bytes 1-2 = 0, 7-bit; docstring `anlz_writer.py:423-433` wrong too |
| 2 | PWV5 channel order | R=low, G=mid, B=high | `analysis_engine.py:1220-1230`: R=high, B=low (swapped) | **Fix** swap; normalise to strongest (green ceil 5) |
| 3 | PWV5/PWV3 height | `round(31*(peak/255)^2)` from sample peak | dB-log of RMS, -60..0 dB -> 0..31 (`:1146-1163`, `:1190`, `:1222`) | Replace with squared-peak curve |
| 4 | PWV2 whiteness | height only 1..15; >15 makes Nexus reject preview | `analysis_engine.py:1184-1188`: `(bright<<5)\|h31` | **Fix** (hardware-breaking) |
| 5 | PWAV ceiling/floor | height 2..25 | `:1177-1182` 0..31, 0 on silence | Cap 25, floor 2 (0 = "unanalysed") |
| 6 | Zero entries | no preview column 0 | `quantize_log` yields 0 at <= -60 dB | floors per tag |
| 7 | PWV6/PWV7 range | 7-bit 0..127 | `:1232-1249` 0..255 (`anlz_writer.py:452-498` clamps to 255) | Scale to 0..127; PWV6 via energy overview |
| 8 | PWV6 algorithm | separate energy pass, track-gain pinned | resample of 150/s RMS with `np.interp` (`:1232-1240`) | Implement overview pass (§4.3) |
| 9 | Crossovers | 200 Hz / 2 kHz (one-pole detail, 2nd-order BW overview) | `:1094-1095` 200 / **2500** Hz, 4th-order BW | Move HIGH to 2000 Hz (our cutoff unsourced) |
| 10 | Detail stat | peak per 1/150 s | RMS per hop (`:1131-1141`) | Peak for detail columns; RMS only for overview |
| 11 | Preview reduction | bucket **max** | `_resample_array` linear interp (`:1273-1281`) | Max-pool; interpolation averages out transients |
| 12 | Whiteness | `high/(l+m+h)*7` of peaks | `rms_high/rms_full*7` (`:1168-1175`) | Use band share |
| 13 | Colour gamma | none on detail; normalise colour | `COLOR_GAMMA=0.65` (`analysis_settings.py:68`) on all bands | Drop gamma for CDJ tags; keep only as UI preset |
| 14 | Section headers | PWV3/7 trailer `0x00960000`, PWV5 `0x00960305`, PWV6 20 B | `anlz_writer.py:374-498` match (fps=150 packs to 0x0096) | OK; PWV4 header OK. Add golden-byte test |
| 15 | PWVC | copy from existing; unknown content | `anlz_writer.py:501-516` zero stub, `hdr_len=14` | Low risk; copy real PWVC if present |
| 16 | Mono downmix | mono input | `analysis_engine.py:2393-2403` `librosa.to_mono` mean | OK |
| 17 | Rust band FFT | n/a | `analysis.rs:26-100`: 1024-sample FFT on **interleaved** channels ignoring count, no window; bands 20-250-4000-20000 Hz (`:6-10`); ~86-172 frames/s, not 150 | Downmix first; match 150/s + 200/2000; or retire in favour of Python |
| 18 | UI/API band split | consistent 200/2000 | `services.py:540-555` 250/2500 Hz 3rd-order, 22.05 kHz, global-max normalisation, `pps=50` | Three different splits in repo (200/2500, 250/2500, 250/4000): unify via one constant |

### 8.2 Rendering

| # | Item | rbxport | ours (file:line) | Action |
|---|---|---|---|---|
| 19 | 3Band palette | combination colours (blue/brown/amber/cream/white), opaque | `useMultibandLayers.js:54-56`: 3 WaveSurfer slaves, blue/amber/white, normal blend; RGB uses `mix-blend-screen` red/green/blue | Replace by canvas `segments()` model (7 colours) |
| 20 | RGB palette | per-column colour from PWV4/5 normalised | `WaveformMiniCanvas.jsx:33-35` / `DawTimeline` low=red, mid=green, high=blue additive `screen` strokes | Per-column colour from band ratio; keep red=bass (matches) |
| 21 | Band stacking | stack heights low/128, mid/256, high/128 (row preview); centred: nested reaches | `useTimelineRender.js:415-511` max-band envelope with share slices (proportional) | Add rbxport model as a style; ours is a stylised variant |
| 22 | Height scale | 127-scale, per-band weights | peaks normalised by global max (`services.py` `glob_max`; `analysis_engine.py:1252-1255`) | Absolute scale; avoid per-track renormalisation of detail |
| 23 | Detail scroll | fixed head, overdraw 2x + transform slide, whole-pixel snap | WaveSurfer scroll + RAF writing `scrollLeft` per frame (`useMultibandLayers.js:128-170`), 3 instances synced | Canvas layer + translateX; removes 3 slave instances and sync loop |
| 24 | Beat grid | 1px line + head triangles, downbeat white/red; binary search | `WaveformCanvas.jsx:45-85`: full-height line + red triangles, 0.22/0.06 alpha, redraw on scroll via RAF, linear loop over all beats (`:50`) | Binary search window; adopt colours; beat triangles on non-downbeats |
| 25 | Zoom model | bars-across steps | WaveSurfer `minPxPerSec` zoom | Add bar-based zoom steps |
| 26 | HiDPI | exact device px, cap 2, no 16px quantise on scroller | `WaveformCanvas.jsx:35-41` dpr uncapped, resets canvas size every draw (`canvas.width=` clears) | Assign only on change; cap dpr |
| 27 | Preview cache | LRU 500 `ImageBitmap`, 35 ms settle, 16 concurrent | `DawTimeline` OffscreenCanvas cache keyed incl. scrollX (`useTimelineRender.js:136`) -> rebuild on every scroll step | Key without scroll; render width-wide bitmap once |
| 28 | Silence line | 1px baseline | none in `WaveformMiniCanvas` | Add |
| 29 | Cue/phrase overlays | DOM overlays, phrase colours | partial (`WaveformOverlays.jsx`) | Not compared in depth |

## 9. Input for waveform-overhaul (`docs/research/research/ideagate_waveform-overhaul.md` on `claude/keen-galileo-61576d`)

Doc states: 1 render style (wavesurfer bars) + 4 colour modes; 3 bands hardcoded; 200/2500 Hz at `analysis_engine.py:879-915` (stale lines; now 1094+); CDJ formats byte-locked (non-goal).

Findings feeding OQs:
- **OQ1 (styles / wavesurfer vs canvas)**: rbxport uses no wavesurfer; pure canvas, 3 geometries: centred mirrored, bottom-anchored stacked, bottom-anchored overlaid; plus PCM envelope for deep zoom. Per-pixel max reduction; interpolation only when zoomed past 150/s. Cost of N slave WaveSurfer instances (ours) vs 1 canvas pass. Recommend canvas renderer; reuse `drawBands/segments` model.
- **OQ2 (N bands)**: CDJ tags fixed at 3 bands (PWV6/7 low/mid/high). N>3 = display-only, computed from our own backend filter bank (e.g. extra band data endpoint), never written to ANLZ. Keep 3-band export path unchanged. rbxport DSP is cheap (one-pole, 1 pass) so N-band bank at 150/s is affordable; overview normalisation scheme (band mean pinned to track RMS) generalises per band.
- **OQ3 (thresholds)**: rbxport/rekordbox-like defaults: **200 Hz and 2 kHz**. Ours 2500 is unsourced. Editable thresholds must apply only to display data; the export path keeps 200/2000. Rekordbox bass is compressed (`^0.9` on RMS) — a display "gain per band" knob is more useful than raw thresholds.
- **OQ4 (palette model)**: rbxport palette = tag family (blue / rgb / 3band) + a token table. 3Band palette is combination-keyed (7 colours: low, mid, high, low+mid, low+high, mid+high, all). Schema for N bands: colour per non-empty subset is 2^N-1 (N=6: 63) — impractical; for N>3 fall back to per-band colour with alpha or ramp stops. Presets to ship: Rekordbox 3Band (table in §5.1), RGB (red/green/blue, strongest normalised), Blue (ramp `#0055E1` -> `#F5EBD7`). Hot-cue/phrase colour tables exist (§5.5).
- **OQ5 (competitors)**: rbxport = Rekordbox clone, table-stakes set = Blue / RGB / 3Band, each with overview + detail, zoom in bar units, phrase bar, cue badges, beat grid with downbeat emphasis.
- Settings: `waveform_visual_mode` options map 1:1 to rbxport palettes (`blue|rgb|3band`); `custom` is ours. Hardcoded colours at `useMultibandLayers.js:54-56` and `WaveformMiniCanvas.jsx:32-46` ignore `waveform_color_*`; RGB mapping there (low=red) is correct vs rekordbox.
- Interplay: fixing rows 1-13 (CDJ encoding) is **independent** of the overhaul but should land first or alongside since the frontend will read PWV7-equivalent data; define one backend band-data contract (absolute 0..127 per band @150/s + overview 1200) and render from it.
- Perf requirements to carry: overdraw+transform scroll, device-pixel snapping, ImageBitmap LRU for thumbnails, shared in-flight fetch, edition invalidation.
