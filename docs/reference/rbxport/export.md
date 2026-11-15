# rbxport USB export — lessons for LMS

Reference notes. Source: open-source rekordbox USB exporter "rbxport". Goal: CDJ-correct + efficient stick export. Facts only, own words.

## 0. Sources + license

- Repo read: `rbxport` (Rust/Tauri). Read-only, nothing executed.
- **License: GPL-2.0-or-later. LMS = MIT. No code, no long passages copied.** Only facts: offsets, flags, constants, algorithms, decisions. Re-implement from facts, never port source.
- Citation form: `rbxport:<path>`. Main docs:
  - `rbxport:docs/reference/usb-export-db.md` (format, 1704 l)
  - `rbxport:docs/reference/usb-export-pipeline.md` (pipeline, 1180 l)
  - `rbxport:docs/development/rekordbox-parity-decisions.md`, `rbxport:docs/user/usb-export.md`
  - Code: `rbxport:crates/rbl-pdb`, `rbl-export`, `rbl-anlz`, `rbl-onelibrary`
- Evidence tags used upstream: `[OBS]` observed on real rekordbox output, `[static]` firmware/binary analysis, `[ASSUME]`, `[UNKNOWN]`. Kept here where it matters.
- Reference hardware/software upstream: rekordbox 7.2.x exports, CDJ-3000 fw 3.20 (emulated, AtEmu), XDJ-AZ/RX2/700 static + emulated. **No physical-CDJ proof of rbxport output** (`rbxport:usb-export-pipeline.md` §10). Treat as strong hints, not truth.
- Our invariants (`.claude/rules/coding-rules.md`) were byte-verified on a real stick. Contradictions are recorded in §8/§9, not resolved.

## 1. Stick layout

```
<vol>/
  Contents/<Artist>/<Album>/<file>            audio, one tree, all playlists
  PIONEER/   (or .PIONEER on blank HFS+)
    rekordbox/export.pdb  exportExt.pdb  exportLibrary.db
              playlists3.sync  playlists3Plus.sync   (identical bytes)
              RBFLTR.DAT  <- written BY the CDJ on first browse
    USBANLZ/P###/########/ANLZ0000.{DAT,EXT,2EX}
    Artwork/#####/{a,b}<id>.jpg  {a,b}<id>_m.jpg
    DEVSETTING.DAT  MYSETTING.DAT  MYSETTING2.DAT  DJMMYSETTING.DAT  djprofile.nxs
```

| Item | Rule |
|---|---|
| FS | FAT32 names. exFAT works. HFS+ works (rekordbox picks `.PIONEER` on blank HFS+ [OBS]). |
| Root | Reuse whichever root already holds `rekordbox/export.pdb`, `exportLibrary.db` or `DEVSETTING.DAT`. Both present = hard conflict. Every `/PIONEER/` literal in DB rows rewritten to chosen root. |
| Paths in DBs | volume-relative, leading `/`. Reject `.`, `..`, absolute parts. |
| Audio dir | `/Contents/{artist}/{album}/{file}`. Empty artist/album -> `UnknownArtist`/`UnknownAlbum`. Dir names: sanitize, cut to **48 chars** (rekordbox's own cut), strip trailing dot/space, empty -> `Unknown`. |
| Filename | keep source basename. Replace `/ \ : * ? " < > |` and ctrl <0x20 with `_`. Strip trailing dot/space. Cut to 120 bytes on char boundary, keep extension. NFC-normalize. |
| Collisions | compare on `path_key` = NFC + lowercase. First dup gets `-{export_id}`, then `-{export_id}-{serial}`. Reuse suffixed name from prior manifest so resync does not rename. |
| Always created | `Contents/`, `<root>/USBANLZ/`, `<root>/Artwork/`, `<root>/rekordbox/` even for empty export. |
| Player writes | CDJ mounts RW and creates `RBFLTR.DAT`. Stick is not byte-stable after use. |
| Required vs optional | needed: audio, export.pdb, ANLZ `.DAT`. `.EXT`/`.2EX` needed for detail/colour waveforms. Optional: exportExt.pdb (My Tags in Track Filter), exportLibrary.db (rekordbox 7 device panel; **tested CDJ-3000 path is export.pdb + ANLZ**; CDJ-3000X fw1.40 static analysis suggests it reads only exportLibrary.db [hypothesis]), Artwork, *SETTING files, `.sync` (rekordbox Sync Manager). |
| Conversion (opt-in "max compat") | MP3 + integer-PCM WAV/AIFF at 44.1/48k copied as-is. Else convert to 16-bit/44.1k stereo WAV/AIFF or 320k CBR MP3, rename `{stem}-rbx-cdj-{export_id}.{ext}`. Refuse surround, refuse >4 GiB WAV/AIFF. Converted track: DAT gets empty PVBR (source VBR table invalid for new encoding). Dup path produced by conversion = conflict, never overwrite. |
| File size field | clamp to u32 max in DBs. |

## 2. export.pdb (DeviceSQL)

`rbxport:docs/reference/usb-export-db.md` §4, `rbxport:crates/rbl-pdb/src/build.rs`, `rows.rs`, `reference.rs`.

All little-endian. Page size 4096 (header field makes it variable; readers accept pow2 512..64K).

### 2.1 File header (page 0)

| Off | Size | Value |
|---|---|---|
| 0x04 | u32 | page size |
| 0x08 | u32 | table count (20 for export.pdb, 9 for exportExt.pdb) |
| 0x0c | u32 | next unused page index |
| 0x10 | u32 | const **1** (rbxport) |
| 0x14 | u32 | header sequence = (highest page seq) + 1 |
| 0x1c+ | 16 B each | per table: `type`, `empty_candidate_page`, `first_page` (= INDEX page), `last_page` |

Header sequence matters: DeviceSQL treats header seq as "transaction in progress"; on open for write (player records history) it rolls back every page stamped with that seq. Header seq must exceed every page seq. Fresh export: one above (21 over 20) [OBS]. `rbxport:build.rs committed_sequence`.

### 2.2 Page header (0x28 bytes)

| Off | Meaning |
|---|---|
| 0x04 | page index |
| 0x08 | table type |
| 0x0c | next page |
| 0x10 | sequence (increments as pages written; index pages seq 1) |
| 0x18 (u24) | low 13 bits = row-index length (rows), high 11 bits = present-row count. Both = row count for fresh pages |
| 0x1b | flags. **0x24 = data page, 0x64 = index page** (bit 0x40 = not data) |
| 0x1c | free bytes = 4096 - 0x28 - used - (2*rows + 4*groups) (NOT the 36-byte group size) |
| 0x1e | used heap bytes, rounded up to 4 |
| 0x20 / 0x22 | "last write" record: see 2.3 |

### 2.3 Row-group bookkeeping (crash trap)

0x20/0x22 and the second mask word of each row group are DeviceSQL's last-write record, not counts. Before rekordbox adds/frees a row it walks groups from `0x22/16`, clearing 2nd words until it has cleared `0x20` bits. Bad values = walk runs off the page = **rekordbox 6.8.6 crash** (rbxport #349, playlist-entry pages >255 rows).

| Page rows | 0x20 | 0x22 | each group's 2nd mask word |
|---|---|---|---|
| 1..255 | row count | 0 | = presence mask (same as 1st word) |
| >255 | 1 | index of last row | 0 except last group = bit of last row only |
| index page | 0x1fff | 0x1fff | n/a |

`exportExt.pdb` type-4 pages use the ">255" style at any size (222 rows/page, 4 B free).
Playlist-entry rows are 12 B -> ~284 rows/page, so ">255" is reachable in normal libraries.

### 2.4 Row index (end of page)

- Rows = heap from 0x28 forward, **4-byte aligned**.
- Offsets: groups of 16 rows, stride 0x24, growing backwards. Group g: `base = 4096 - g*0x24`; row r's u16 offset at `base - (6 + 2r)`; presence mask u16 at `base-4`, second word at `base-2`.
- **Row offsets are relative to 0x28**, not page start. Deleted rows keep index slot; honour presence bit.
- Rollover: start new page when free < next row + 8 B. Row cannot span pages: max row = 4096-0x28-0x24-8; refuse longer rows with a message naming the track/playlist.

### 2.5 Index page (mandatory, first page of EVERY table)

- flags 0x64; 0x20 and 0x22 = 0x1fff; u16 0x03ec at 0x24; page seq 1.
- Body at 0x28: own page idx; first data page (or 0x03ffffff if none); 0x03ffffff; zeros; u16 0x1fff at body+0x12; then 4-byte pattern `f8 ff ff 1f` to page end (rbxport writes it as 1004x`ff 1f f8 ff` from body+18, ending on half pattern). Same bytes as our writer.
- Table starts with plain data page => rekordbox: "Device library is corrupted", volume hidden until relaunch.

### 2.6 Allocation order + empty candidates

1. Header page, then for **each table in table order**: index page + first data page.
2. Then remaining data pages per table in *write order* (export.pdb: type 19 first, rest in table order; exportExt.pdb: type 7 then 3, rest in order). Each table's zeroed **empty-candidate** page is allocated right after its last data page.
3. Empty table: index page + one zeroed page = candidate; `first == last == index`.
4. Last data page `next` -> that table's candidate. Candidates are **distinct per table**.
5. Trailing all-zero pages are **not written**; header names candidates past EOF (41 pages written, 45 named [OBS]).
6. Re-run rekordbox acceptance after any allocation change.

### 2.7 Tables (type -> meaning)

0 tracks, 1 genres, 2 artists, 3 albums, 4 labels, 5 keys, 6 colors, 7 playlist tree, 8 playlist entries, 9-10 empty, 11 played-history playlists, 12 played-history entries, 13 artwork, 14-15 empty, 16 browse **columns**, 17 browse-category settings, 18 browse-sort settings, 19 **property**. All 20 must exist, empty ones included (player looks up by type). (Upstream notes the reader enum calls 17/18 "history" - wrong; real history is 11/12.)

Types **16, 17, 18** are written from captured rekordbox bytes (27 / 22 / 17 rows; UTF-16 names wrapped in U+FFFA/U+FFFB). Not re-encoded, to avoid drift. Rows: `rbxport:crates/rbl-pdb/src/reference.rs`, `usb-export-db.md` App. A.

Type 19 `property`, one row (`rbxport:usb-export-db.md` §4 "property row"):

| Off | Content |
|---|---|
| 0x00 | `80 02` |
| 0x02 | u16 slot*32 |
| 0x04 | u32 numberOfContents |
| 0x09 | u8 background colour (device library) 0..8 (0 default, 1 Pink .. 8 Purple) |
| 0x0c | string createdDate `YYYY-MM-DD` |
| next | `19 1e` (unknown const) |
| next | string dbVersion `1000`, string deviceName, 8 zero bytes, pad to 4 |

rekordbox adds a new row + clears old presence bit on change; rbxport rewrites one row in place.

### 2.8 Strings

| Form | Encoding |
|---|---|
| short ASCII | 1 byte `(len+1)*2+1`, text. Use when len < 0x7e (126) |
| long ASCII | `0x40`, u16 len (**counts the 4 header bytes**), pad 0, text. For ASCII >=126 chars |
| UTF-16LE | `0x90`, u16 len (4 header bytes + text), pad 0, UTF-16LE text, **NO terminator**. Any non-ASCII |

- Long forms start on a **4-byte boundary within the row**, zero gap before. Artist name offset 0x0c (not 0x0a), album 0x18 (not 0x16) [OBS: 346/346 long strings].
- Old rbxport wrote a counted `00 00` terminator and unaligned long strings: **CDJ-2000NXS froze (E-8709)** (#321). Fixed to match rekordbox.
- Empty string = byte `0x03`. Unused string slots MUST point at a real empty string, not offset 0.

### 2.9 Row layouts

**Track** (subtype 0x24): 0x5e fixed bytes + 21 u16 string offsets at 0x5e. **Offsets relative to row start.**

| Off | Field | Off | Field |
|---|---|---|---|
| 0x00 | u16 subtype **0x24** | 0x38 | tempo x100 |
| 0x02 | u16 slot*32 | 0x3c | genre id |
| 0x04 | content_link (rbxport leaves 0; rekordbox 0xc0700) | 0x40 | album id |
| 0x08 | sample rate | 0x44 | artist id |
| 0x0c | composer id | 0x48 | track id |
| 0x10 | file size | 0x4c | u16 disc |
| 0x14 | master_content_id | 0x4e | u16 play count |
| 0x18 | master_db_id | 0x50 | u16 year |
| 0x1c | artwork id | 0x52 | u16 bit depth |
| 0x20 | key id | 0x54 | u16 duration s |
| 0x24 | original artist id | 0x56 | u16 **0x29** (required) |
| 0x28 | label id | 0x58 | u8 colour id |
| 0x2c | remixer id | 0x59 | u8 rating (stars 0-5) |
| 0x30 | bitrate | 0x5a | u16 audio format |
| 0x34 | track number | 0x5c | u16 **3** (required) |

- Subtype 0x24 + trailers 0x29/3 required: zeroing them gave a named-but-empty playlist on CDJ-3000 even though a semantic reader found all tracks.
- `audio_format` derives from the FINAL filename extension: MP3=1, M4A/AAC=4, FLAC=5, WAV=11, AIFF=12. Converted track = destination format.
- 0x14/0x18 = same numbers as `exportLibrary.db content.masterContentId/masterDbId` (agree on all 1563 tracks of an rb7 stick [OBS]).
- String slots: 0 ISRC, 7 hot-cue auto-load (`"ON"` iff enabled, else empty; must agree with OneLibrary `isHotCueAutoLoadOn`; REKORDBOX SETTING deck mode ignores cues without it), 10 date added, 11 release date, 12 mix name, 14 analyze path (**DAT only**, player swaps ext for EXT/2EX), 15 analyze date, 16 comment, 17 title, 19 filename, 20 file path.

**Other rows**

| Table | Layout |
|---|---|
| artist | u16 0x60, u16 slot*32, u32 id, `0x03`, u8 name offset (0x0a). Subtype 0x64: name offset becomes u16 at 0x0a (used when long-string alignment pushes it) |
| album | u16 0x80, u16 slot*32, ..., artist id @0x08, **album id @0x0c**, `0x03` @0x14, name offset @0x15. (id/artist swap once read as "all albums id 0") |
| playlist tree | 5 words: parent, **0**, sort_order, id, folder flag; name at offset 20 |
| playlist entry | 12 B: entry index, track id, playlist id. Entry index dense, **1-based** |
| color | 8 B prefix, id, name @8. Fixed 8 labels: Pink Red Orange Yellow Green Aqua Blue Purple |
| artwork | u32 id + inline string `/PIONEER/Artwork/00001/a1.jpg` (names only the small `a` file) |
| genre/label/key | id + name (key writes id twice) |

- Rows with a subtype carry **slot-on-page x32** in the u16 at +2, restarting at 0 per page (tracks, artists, albums, property, ext tags). CDJ-3000 ignores it; NXS-era (XDJ-RX engine reads `row[2..4]>>5`) use it. CDJ-900NXS locked up on all-zero slots [UNKNOWN if that or sort numbering was the cause].
- `sort_order` = position among siblings under same parent, from 0, no gaps. OneLibrary `sequenceNo` same number. (Old rbxport numbered globally from 1.)
- Browse sort order comes from fixed `columns`, not data.

### 2.10 exportExt.pdb (My Tags)

9 tables (types 0-8, names `DJDBEX*`), same page format. Populated: 3 tags, 4 song-tags, 7 master. Others empty.

| Type | Row |
|---|---|
| 3 | per tag/category: u16 0x0680, u16 slot*32, u32 parent @0x0c (0 for category), u32 Seq-1 @0x10, u32 id @0x14, u8 category flag @0x1b, empty-string bytes; categories in Seq order each followed by own tags, orphans last |
| 7 | one master row, 39 B padded to 60; u32 `myTagMasterDBID` @0x18 |
| 4 | 16 B, **no row header**: u32 0, track id (export.pdb id), tag id, `0x03`+3 zeros. Ordered by track id asc, tags in type-3 order, each pair once. A tag only lists in Track Filter if a type-4 row ties it to a track on stick |

`myTagMasterDBID`: derivation unknown. rbxport uses library DBID; **same value must appear in exportExt master row and OneLibrary `property.myTagMasterDBID`**. Type 0 (`RECOMMENDLIKE`) left empty; type 5 empty.

## 3. exportLibrary.db (OneLibrary)

`rbxport:usb-export-db.md` §6 + App. B, `rbxport:crates/rbl-onelibrary`.

- **SQLCipher 4**. Open order is load-bearing: `PRAGMA cipher=sqlcipher`, `PRAGMA legacy=4`, `PRAGMA key=...` before any other statement, else created as plain SQLite (unreadable by players) or key misread. Passphrase is a fixed public constant (same on all sticks; deobfuscated base85 -> XOR -> zlib; constants as documented by pyrekordbox; prefix check `r8gd`). See `rbxport:crates/rbl-onelibrary/src/key.rs` for the derivation steps (do not copy blob; take from pyrekordbox, MIT).
- **Built from scratch**, not from a template: schema of 22 tables created via SQL (list in `usb-export-db.md` App. B, incl. intentional typos `isComplation`, `OutFileOffsetInBlock`). All tables must exist even if empty. `dbVersion` = `"1000"`.
- Built in a temp file next to target, in ONE transaction, then flush -> rename (persist_new) -> fsync dir.
- Durability pragmas: `synchronous=EXTRA`, `fullfsync`, `checkpoint_fullfsync`, **`journal_mode=DELETE`** (verified returned). Result: no `-wal`/`-shm`. Publish deletes inherited `-wal/-shm` so stale WAL pages cannot ride along. rekordbox itself leaves them.
- Tables: `content`, `artist/album/genre/label/key/color` (interned, deduped, **empty name = id 0**), `image(image_id, path)` (**same id as export.pdb artwork table**), `myTag`, `myTag_content`, `playlist`, `playlist_content`, `history`, `history_content`, `cue`, `hotCueBankList*`, `recommendedLike`, `property`, `menuItem`, `category`, `sort`.
- `menuItem/category/sort` = browse columns + sort options. Missing => opens but browses wrong. Names wrapped in U+FFFA/U+FFFB (display-time-translation marker) else player shows English regardless of language. Initial rows: `usb-export-db.md` App. B (27 menu items, 22 categories, 17 sorts). Existing stick values (renamed colours, reordered categories, sub-column, bg colour) are read back and kept on rebuild.
- `property` one row: deviceName, dbVersion, numberOfContents, createdDate (`YYYY-MM-DD`, date not timestamp), backGroundColorType (0..8), myTagMasterDBID.
- **`content.rating` = 0..5 star count, NOT x51.** DeviceSQL too. 255 shows no stars on XDJ-AZ / CDJ-3000X [OBS #347]. rbxport <=1.6.0 wrote x51.
- `content` fields rbxport sets: content_id, title(+ForSearch), bpmx100, length, trackNo, discNo, artist/album/genre/label/key/color ids, image_id, djComment, rating, releaseYear/Date, dateAdded, dateCreated, path, fileName, fileSize, fileType (final ext), bitrate, bitDepth, samplingRate, isrc, djPlayCount, isHotCueAutoLoadOn, analysisDataFilePath, `analysedBits = Analysed & ~64`, masterDbId, masterContentId. `contentLink` left empty.
- Cue rows: from `djmdCue`. kind as source (gap at 4). `inUsec/outUsec` = ms x1000 (absent end = -1); `in150FramePerSec` = floor(ms*150/1000); loop fraction hi/lo 16 bits of BeatLoopSize; rest NULL. Cue rows of retained device-only tracks survive rebuild.
- One-of-two-DBs: if only `export.pdb` or only `exportLibrary.db` exists, convert by reading the one present; never publish an empty sibling over a populated one.
- rekordbox treats Device Library (export.pdb) and OneLibrary as separate libraries; playlist ids numbered independently in each; edits made in one don't touch the other.

## 4. ANLZ files

`rbxport:usb-export-db.md` §7, `rbxport:crates/rbl-anlz/src/{write,encode,cues,phrase,grid}.rs`.

### 4.1 Directory = hash of final USB audio path (critical)

CDJ-3000 fw 3.20 **computes the analysis dir itself** from the audio path. Pointing the DB at an arbitrary dir did not load waveforms [OBS]. Algorithm:

1. Take leading-slash path, case preserved, as UTF-16 code units up to first NUL.
2. `h = 0`; for each unit c: `h = (h * 0x34F5501D + c * 0x93B6) mod 2^32`.
3. `hash = h mod 0x30D43` (200003).
4. shard = hash bits `[0,2,6,7,9,13,16]` packed into bits 0..6.
5. dir = `/{root}/USBANLZ/P{shard:03X}/{hash:08X}/`, uppercase hex.

Compute AFTER sanitize + collision suffix + conversion. Matched all 61 reference tracks. Hash collision between different audio paths: suffix filename, recompute (also vs retained dirs). Verifier flags an analysis path != computed one as "not discoverable by the CDJ".

### 4.2 Framing

- `PMAI`, BE u32 header len @4 (28 = 12 + 16 extra), u32 total file len @8, 16 extra bytes constant `00000001 00010000 00010000 00000000` (reproduced, meaning unknown). Sections back-to-back, no padding.
- Section: fourcc, u32 len_header, u32 len_tag, header extra, payload. **len_header differs per tag.**
- **Every companion's PPTH = final USB audio path** (UTF-16BE, NUL-terminated, header ext = byte length). Not the desktop share path (`?/filename`). Must rewrite in DAT+EXT+2EX.
- Unknown sections: carry raw framing through byte-exact.

### 4.3 Tag set + order (rekordbox 7.2.19 own files [OBS])

| File | Order |
|---|---|
| .DAT | PPTH, **PVBR**, PQTZ, PWAV, PWV2, PCOB(hot=type 1), PCOB(memory=type 0) |
| .EXT | PPTH, PWV3, PCOB x2, PCO2 x2, PWV5, PWV4, then carried (PSSI, ...). PQT2 appears in some (36/400); rbxport can't author its payload -> drops/empties it |
| .2EX | PPTH, PWV7, PWV6, PWVC (+PVDI carried) |

- PVBR: rekordbox 6/7 reject a DAT lacking it (1558/1558 have it). Empty form = zero header word + 401 zero words (65/400 files). Keep real VBR table if source has one; empty it for converted audio.
- Empty cue-list headers: PCOB 12 B = type u32, 0, 0, `ffffffff`; PCO2 8 B = type, 0, 0.
- What CDJ-3000 needs: DAT (grid, preview wf, cues) + EXT (detail/colour wf, extended cues) + 2EX (3-band wf). Track row analyze-path names only DAT.

### 4.4 Tag layouts

| Tag | Header (after 12 B frame) | Payload |
|---|---|---|
| PQTZ | u32 0, u32 0x00080000 (low 16 bits = **signed ms grid shift**, rekordbox grid-shift edits only this), u32 beat count | 8 B/beat: u16 beat# (1-4), u16 BPMx100, u32 ms. Per-beat tempo. BPM clamp 40..499, ties-to-even |
| PWAV | u32 400, u32 0x00010000 | 1 B/col: 3 bits whiteness + 5 bits height. Max height **25**. Min **2** |
| PWV2 | u32 100, u32 0x00010000 | 1 B/col: height only, **no whiteness**, range **1..15** |
| PWV3 | u32 stride 1, u32 n, u32 0x00960000 | 150 col/s, height 0..31 = round(31*(peak/255)^2) |
| PWV5 | stride 2, n, 0x00960305 | BE u16 `rrrgggbbbhhhhh00`; r/g/b = **low/mid/high** band; colour normalised (strongest ~7, green <=5) |
| PWV4 | stride 6, 1200 cols, 0 | 6 B: `peak>>1`, 0, 0, low, mid, high (7-bit; max 127) |
| PWV6 | stride 3, n (**20-byte header, no 3rd word**) | 1200 cols, low/mid/high |
| PWV7 | stride 3, n, 0x00960000 | 150/s, low/mid/high, 7-bit (`>>1`) |
| PWVC | len_header 14 | colour meta, values unknown; carried |
| PQT2 | 44 B header (const 0x01000002 @4 of header) | payload derivation unknown; empty form safe |

- **PWV2 byte >15 => Nexus-era players (XDJ-RX2 1.43, same code base XDJ-1000MK2) reject the whole 900-byte preview incl. PWAV** [static]. Deck then never creates waveform cache entry; detail wf + cue markers not shown until playback.
- **No preview column may be 0** (reads as "not analysed"; player rebuilds preview from audio and overwrites the stick's).
- Resample = keep loudest column per bucket.
- XDJ-AZ/CDJ-3000 draw PWV5 bits un-normalised => unnormalised colour draws dim.

### 4.5 Cues

- Source: master.db `djmdCue`, NOT the share-tree ANLZ (its cue lists are empty even when library has cues). Always replace cue lists on export.
- Split: **DAT** = PCOB memory + hot **A-C**. **EXT** = PCOB hot **D-P** + empty legacy memory list, then full **PCO2** hot + memory lists.
- Slot numbering: memory 0, A-C = 1-3, D-P = 4-16 (source kind 5-17 minus 1; kind 4 reserved/excluded). Entries ordered by descending source rowid. Cap 65535/list. Hot list written before memory.
- PCOB header 24: type @0x0c, count u16 @0x12, u32 @0x14 = `ffffffff` for hot/empty else count-1.
- PCPT (56 B): hdr 28; slot u32 @0x0c; **@0x10 = 4 only when loop active, else 0**; @0x14 0x00010000; prev/next u16 @0x18/0x1a (memory entries link adjacent; hot/absent = ffff); kind u8 @0x1c (1 cue, 2 loop); `00 03 E8`; start ms @0x20; loop end @0x24 (ffffffff = none).
- PCO2 header 20: type @0x0c, count u16 @0x10.
- PCP2 (**88 + L bytes**): hdr 16; slot @0x0c; kind u8 @0x10; `00 03 E8`; start ms @0x14; loop end @0x18; memory colour id u8 @0x1c (**hot cues 0**); const **0x01 @0x1d**; loop numer/denom u16 @0x24/0x26; comment byte len L u32 @0x28; comment UTF-16BE incl. NUL @0x2c; then 4 B: colour code + R,G,B at 0x2c+L; zero tail to 88+L.
- Colour: captured 65-entry device palette (code -> RGB; table in `usb-export-db.md` §7; code 0 = default per slot: A/I->43, B/J->8, C/K->23, D/L->60, else 0). Don't use UI display palette for export.
- Hot-cue auto-load flag must match between export.pdb slot 7 and OneLibrary.

### 4.6 PSSI (phrases, Lighting)

Export form is **XOR-masked**. Offsets from section start (12 B frame included), BE:

| Off | Field |
|---|---|
| 0x0c | u32 entry size 24 |
| 0x10 | u16 phrase count n |
| 0x12 | u16 mood 1 high / 2 mid / 3 low (plaintext) |
| 0x14 | 6 B unknown |
| 0x1a | u16 **end beat** |
| 0x1c | 2 B unknown |
| 0x1e | u8 lighting bank |
| 0x20 | n x 24 B entries |

Entry (24 B): u16 index (1-based) @0; u16 first beat @2; u16 kind @4 (read with mood); u8 k1 @7, k2 @9, k3 @0x13; u8 extra-beat variant @0x0b; u16 lighting beat hints @0x0c/0x0e/0x10; u8 fill flag @0x15; u16 fill start beat @0x16.

Mask: for each byte at section offset `0x12+i` to end: XOR with `(base[i mod 19] + (n & 0xff)) & 0xff`. base = `CB E1 EE FA E5 EE AD EE E9 D2 E9 EB E1 E9 F3 E8 E9 F4 E1`. Self-inverse. Apply only when unmasked mood at 0x12 is 1/2/3 (else already masked, leave). Bytes before 0x12 untouched.

### 4.7 Other

- PVDI (vocal) rekordbox-only, carry. LINK server uses PWAV+PWV2 (DAT), PWV3 (EXT), PWV6/7 (2EX).
- PQT2 preserved only if checksum over old times/beats/tempos/offset still matches, else written empty.
- Cue/grid edits made on a player are **overwritten** by library on sync; Import is the way back.

## 5. Artwork

- `/PIONEER/Artwork/{id/20 + 1 :05}/{a,b}{id}{,_m}.jpg`. **4 files per image**, 20 images per folder, folders start `00001`.
- `a<id>.jpg` = library 80x80 small (byte-identical). `a<id>_m.jpg` = 240x240 medium. `b*` = same bytes as `a*` (md5-verified over 61 images). DB row names only the small `a`; player derives the others [ASSUME].
- Over PRO DJ LINK a player is served the medium file; full-size left list art missing on CDJ-3000.
- One interned image id per source image; same id in export.pdb type 13 and OneLibrary `image`.
- Skip rewrite if source revisions match recipe and outputs trusted.

## 6. Settings files + sync records

- `DEVSETTING.DAT`: exactly **140 B**. u32LE 0x60; 32 B "PIONEER DJ"; 32 B "rekordbox"; 32 B version string; u32LE 32; 32 B body; u16LE CRC-16/XMODEM (poly 0x1021, init 0, no reflect) over body; u16 0. Body: `78 56 34 12 01 00 00 00 01` then waveform/overview/key-format/position bytes, zeros. Four prefs: waveform colour (Blue/RGB/3Band), position (Center/Left), overview (Half/Full), key display (Classic/Alphanumeric). Not created by the exporter library; created by device panel/app layer if absent. Existing kept.
- `MYSETTING*.DAT`/`DJMMYSETTING.DAT`/`djprofile.nxs`: copy from rekordbox settings dir **only if stick lacks them** (player may have written them). CRC: XMODEM over body for DEVSETTING/MYSETTING/MYSETTING2; over header+body for DJMMYSETTING.
- `playlists3.sync` + `playlists3Plus.sync`: identical, UTF-8 XML, **CRLF + blank line after declaration**. `<Sync DBID AutomaticSync AllPlaylists IncludeCue ForcedSync Timestamp>` with `<NODE Id(hex upper) ParentId Attribute(0 pl/1 folder/4 smart) Lib_Type Dev_ID Timestamp CheckType(1 ticked/2 folder with ticked child)>`. Node Timestamp = time the library playlist's **entries last changed** (rekordbox recomputes; not export time). Drives Sync Manager re-tick and device-edit detection.
- rekordbox sync rule [ASSUME, observed]: device-added track in a synced playlist survives until library copy of that playlist changes; then playlist rewritten from library, track stays on stick in no playlist. No merge, never imported back. Auto-sync did not fire by itself.

## 7. Efficiency / incremental pipeline

`rbxport:usb-export-pipeline.md` §1,4,5,6; `rbxport:crates/rbl-export/src/{plan,incremental,manifest,reconcile,cache,estimate,snapshot,verification}.rs`, `rbl-core/src/durable.rs`.

### 7.1 Stage order (linear on purpose)

1. cancel check, volume identity check, dest is dir.
2. choose root; create dirs; **recover** any interrupted publication.
3. take exclusive lock (`.rbxport-write.lock`), create stage dir `.rbxport-staging-*` ON THE STICK (same FS => rename later).
4. load manifest; optional full-content verify.
5. digest request (tracks, playlists, tags, options) + inputs (source file revisions) + stick DBs; if all equal manifest generation and every output still matches its receipt => **"Already up to date", nothing staged**.
6. read baseline snapshot (reuse manifest's normalized snapshot if DB signatures match; parsing both DBs is the costly part of cold sync).
7. baseline checks (conflicts, see 7.7).
8. plan: reconcile + estimate + peak space; refuse if free < peak.
9. hash only tracks whose source revision changed.
10. shared preparation (probe, convert, copy to cache) once per input+profile across all sticks.
11. assign ids: playlists first, then tracks (pinned to manifest).
12. per track: layout path, analysis dir, reuse/move/copy, analysis, artwork.
13. playlist rows AFTER tracks (entries name export ids; skipped tracks leave no gap).
14. write `export.pdb` -> `exportExt.pdb` -> `exportLibrary.db`; settings; sync records.
15. **manifest last** (failed run leaves older record; next run re-copies instead of trusting half stick).
16. re-read stage, verify (7.6); recheck device unchanged ("device changed during sync").
17. last cancel check (no cancel after "publishing"), commit.
18. verify published DBs; on failure roll back. Seal receipts. Finalize journal. Remove emptied dirs.

### 7.2 What "unchanged" means

- `FileRevision` per input: size + ns mtime (+ ctime + dev/ino on Unix). Outputs: size + mtime only (ctime/inode don't survive remount/rename).
- Matching revision = no content read. Changed/uncertain revision = hash, reuse only if equal.
- Audio reuse needs: same path, same source size AND ns mtime, same conversion profile, and stick copy still has recorded `copy_stamp` (size + non-zero mtime). Stamp ok => trust recorded `audio_hash`, read nothing. Stamp off => hash copy against `audio_hash`. Wrong stamp costs one hash, never a wrong reuse.
- Known accepted gap: same size + same ns mtime rewrite (e.g. MP3Gain preserving mtime) undetected; FAT 2 s mtime granularity. Opt-in "Verify all files" hashes everything.
- rekordbox itself does NO file check: compares DB rows only (`overwrite_export`).
- Analysis reuse: **recipe digest** = audio path + cues + analysis location/revisions + audio revision + `TRANSFORM_VERSION`; plus per-companion hashes + expected-extension list (deleted EXT detected + repaired). Artwork same idea. Bump `MANIFEST_VERSION` / `TRANSFORM_VERSION` when semantics change.
- Digest hash: BLAKE3.

### 7.3 Playlist-only change

Rebuild + republish the 3 DBs + sync record + manifest only. **Zero audio/analysis/artwork reads or writes** (test-asserted). 200 tracks ~0.8 s, 2000 ~3.9 s, 10000 ~14 s (debug build, synthetic).

### 7.4 Manifest (`PIONEER/rbxport/manifest.json`, v2)

Outside `rekordbox/` so no player/rekordbox version cares. Holds: library `db_id`, tracks (stable `export_id`, source key `#libraryId` or source path, audio hash, copy stamp, companion hashes, `preserved` flag), playlists (library entries for device-edit detection), `loose` track ids, baseline `Snapshot`, `generation` (request/inputs/outputs receipts/DB signatures/recipes/warnings). Unknown/old version => ignored/downgraded, reconcile from stick DBs; losing it is harmless.

- **Export ids pinned across syncs**: decks cache waveforms/artwork against them.
- Carry what we didn't write: device-only playlists (ids from `1<<63`), their tracks, history tracks, other writers' tracks (`preserved`, never deleted, never converted). Selected track with unavailable source but usable USB copy keeps copy + warning.
- Adopt rekordbox-written stick: no manifest, but `exportLibrary.db` has masterDbId/masterContentId; same path + same size + byte-equal => keep file, don't recopy (progress "checking" in bytes).
- Library files already living on the stick = **in place**: DB points at them, never copied/moved/deleted.
- Moved track (artist renamed): same source/size/profile -> same-volume rename, analysis rewritten for new path.

### 7.5 Copy, cache, parallelism

- Copy: reader thread + writer thread, bounded queue 4 x 1 MiB; **hash while copying** (no read-back). Data-only copy (no xattr/AppleDouble `._`).
- Shared preparation cache (`<state>/cache/usb-export`): one worker per (source, profile) via per-key gate, max 2 preparations at once, prune to 8 GiB at start/end. Cache unwritable => stage directly. Cache is disposable; recovery never needs it.
- Multiple sticks: one scoped thread each, one shared selection built once under library edit locks. Same physical volume twice refused. Per-stick reservation refuses concurrent export to same volume.
- Probe once per source revision (conversion need, duration) and share.
- Progress: stages (preparing, recovering, planning, checking, converting, copying, database, verifying, publishing, finalizing, ejecting); throttle same-stage events to 100 ms; job id + sequence to drop stale events; units differ per stage (bytes copy/check, ms audio convert, tracks else).

### 7.6 Estimate / space

- Preview never writes, never recovers a journal, debounced 200 ms in UI, stale responses dropped.
- Fields: `net_additional`, `projected_free`, `peak`, `enough_space`, counts new/changed/kept/removed/missing, `unknown_size`/`approximate`.
- `peak` = staged bytes + 64 KiB + uncertain adoptions. Old generation stays until verified, so removals are NOT counted as free during staging. Assets rounded to 4 KiB blocks. Convert size = cached size or duration estimate (PCM math; MP3 ~40 kB/s).
- Commit rule: free >= required + largest + 1 MiB.
- Unknown size (conversion, same-size source change) => no hard refusal, mark uncertain.

### 7.7 Publication, atomicity, recovery

- Everything staged on the stick, then **commit = rename within one FS** (atomic per file; audio never copied twice). Whole set not atomic, made safe by a journal:
  1. write `.verification-required` marker, flush every staged file, then every dir children-first.
  2. write `publication.json` (paths, has-new-image, target-existed), rename stage -> `.rbxport-publication` (journal), flush root.
  3. roll forward: move old target to `.previous/`, rename new in, flush parent dir each step. Entry without image = delete.
  4. verify published DBs. Fail => rollback (restore `.previous`, move created files to `.rejected/`). Ok => seal manifest, finalize (retire + delete journal).
- Next run recovers first: complete or roll back. Lost image = error + `.incomplete`, never treated as deletion. `inspect`/`estimate`/`eject` refuse a stick with pending journal.
- FS quirks handled: FAT32 + exFAT-on-macOS have no exclusive rename (check absent, plain rename); exFAT rejects F_FULLFSYNC (fall back to fsync); macOS lists NFD names (map back to NFC, retry both forms on rename/remove); FAT stores local time without zone (clock-skew: own commit skips external-change check; 2 s grace); `._` files skipped.
- Per-track `check_root` re-checks mount dev/ino; ENXIO/ENODEV/EIO -> `DeviceGone` ("USB disconnected; sync picks up from there").
- Cancel points: start, preparation/hash (every 64 KiB), copy chunks, per track, just before commit. Dropping publication deletes stage.
- Obsolete owned files deleted only after commit and only if still trusted/stamped as ours; analysis dirs never removed recursively; `remove_dir` (empty only).
- Rekordbox-running guard: refuse USB write if the rekordbox **app** runs (it rewrote stick DBs within a minute of seeing the stick). The `rekordboxAgent` alone is fine for USB (agent touched no stick file).
- Eject only after verified, warning-free sync; drop open volume handle first; eject refused during export / pending recovery; sync success and eject success reported separately.

### 7.8 Perf numbers (upstream, debug, synthetic 8 KiB audio)

| Tracks | Cold | No-op p95 | Playlist edit | Preview |
|---|---|---|---|---|
| 200 | 5.9 s | 48 ms | 0.8 s | 0.1 s |
| 2000 | 55 s | 1.1 s | 3.9 s | 1.5 s |
| 10000 | 450 s | 2.8 s | 14 s | 7.8 s |

Real sticks (macOS): 10000-track first export 16 min FAT32, 32 min journaled HFS+.

## 8. Verification

`rbxport:crates/rbl-export/src/verification.rs`, `usb-export-db.md` §11.

- Read back staged generation BEFORE publish and published DBs AFTER commit. Remount before manual read-back.
- Checks: both DBs present + agree (first difference named: track/field/playlist); unique ids; case-folded unique audio paths; every referenced file exists; playlist tree + membership valid; retained history intact; My Tag / cue edits on stick not silently dropped.
- Player-specific raw checks: track subtype == 0x24; trailers non-zero; audio-format code matches filename extension; hot-cue auto-load agrees across DBs; analysis dir == computed hash dir; DAT/EXT/2EX parse; PPTH == USB audio path; declared PCO2 count == parsed entries.
- Counts reported: overview wf, detail wf, beat grids, hot cues, memory cues, missing files, errors (must be 0). Makes incomplete source bundle visible; does not invent analysis.
- Parity ceiling: two rekordbox exports of same playlist agree on 556/562 files; differ in export.pdb, exportExt.pdb, exportLibrary.db(+wal/shm), random-uuid `DeviceLibBackup`. Compare those by content.
- Physical acceptance list: playlist browse, load+play, both waveforms, beat markers, saved hot-cue/loop recall (pad press, not just marker), memory-cue recall, settings. Marker shown != pad recalls (slot-7 "ON" lesson).
- Evidence ladder (parity decisions): rekordbox observation/manual > diff vs known rekordbox result > capture/static analysis > emulator/fixture > physical device. Lack of a device = `[UNKNOWN]`, not "compatible". Data integrity + playback timing outrank everything.

## 9. Gotchas (collected)

- Every table: index page first + distinct empty-candidate page; all 20 tables exist.
- Row offsets relative to 0x28; track string offsets relative to row start; presence bitmask decides live rows.
- Track subtype 0x24, trailers 0x29/3, format code from destination extension.
- Unused string slots -> real empty string. Slot 7 "ON" iff auto-load.
- Long strings: 4-aligned within row; UTF-16 has no terminator.
- Album id at +0x0c. Playlist tree 5 words.
- >255-row page header shape (crash). Slot*32 at +2 for NXS players.
- Header seq > all page seqs.
- PWV2 <=15, no whiteness. PWAV 2..25. No zero preview column.
- PWV6 header 20 B. PQTZ header offset = signed ms grid shift.
- PPTH = USB path in all 3 companions. Analysis dir = path hash.
- OneLibrary: cipher/legacy/key pragma order; `journal_mode=DELETE`; rating 0-5; marker-wrapped menu names.
- Colour names in `color` table also live in export.pdb type 6: renaming must update both.
- Settings files never overwritten if present.
- IDs stable across syncs.
- CDJ writes RBFLTR.DAT: give test sticks copies.
- A track removed from a playlist on the device stays in All Tracks; rekordbox delete-playlist keeps tracks unless "Delete Tracks" pref.

## 10. Gap analysis vs LMS

Legend: P0 = likely breaks a CDJ or loses data. Line refs: current tree.

| # | Item | rbxport | ours (file:line) | action |
|---|---|---|---|---|
| 1 | ANLZ dir | UTF-16 path hash -> `P{shard:03X}/{hash:08X}`; CDJ-3000 computes it | `usb_one_library.py:938-950,993-1011` uses `P{id//256}/{id:08X}`; comment claims "path read from DB" | P0. Implement hash; apply after path final; also put in `analysisDataFilePath` + PDB slot 14 |
| 2 | PPTH | rewrite to `/Contents/...` in DAT/EXT/2EX | `anlz_sidecar.py` passes `str(file_path)` (desktop abs path) to `anlz_writer.py:59`; sidecar copied verbatim `usb_one_library.py:997-1004` | P0. Re-emit sidecars with USB path at export (cheap: patch PPTH section + total len) |
| 3 | UTF-16 strings | no terminator; long strings 4-aligned; long ASCII `0x40` form; short ASCII up to 125 | `usb_pdb.py:159` adds `00 00` + counts it; `:152` short<64; `:164-167` align 2 only; heap even-pad `:277` | P0. NXS freeze E-8709 cause upstream. Fix terminator, 4-align rows + long strings, add 0x40 form |
| 4 | >255-row page header | 0x20=1, 0x22=last idx, 2nd words 0 but last | `usb_pdb.py:361-367` writes (n,0) for >16 rows; `:297` last-bit in every group | P0 (rekordbox 6.8.6 crash, playlist entries >255/page). Emit rekordbox shape |
| 5 | Template slot cap | schema built from scratch via SQLCipher | `usb_one_library.py:173-181,307-309,486-496` hard cap = template slots (16). Rest only in XML | P0 capability. Build DB from schema (App. B) with sqlcipher python binding; drop template + rbox write path |
| 6 | Rating scale | 0..5, no x51 (CDJ-3000X no stars) | `usb_one_library.py:352` `*51`; PDB copies it `:727` -> u8 0x59 = 255 | P1. Store 0..5 in both |
| 7 | Stale placeholder fields | all content columns written | `usb_one_library.py:344-365` leaves file_size, sampling_rate, bit_depth, file_type, track_no, disc_no, play_count, date_*, master ids, analysedBits, isHotCueAutoLoadOn = template placeholder values; PDB reads them back `:728-755` | P1. Set every column. `file_type` drives PDB format code at 0x5a (wrong = wrong decode path) |
| 8 | OneLibrary journal | `journal_mode=DELETE`, synchronous=EXTRA, no -wal/-shm | WAL kept; `del db; gc; sleep` hack `:463-483` | P1. Convert to DELETE after build (sqlcipher) and delete -wal/-shm |
| 9 | PDB tables 16/17/18/19 | columns/browse-settings/sort captured rows + property row | `usb_pdb.py:801-812` only 10 tables fed; 16-19 empty; module doc `:42` says history empty | P1. Embed captured rows (own capture from our F: stick or re-derive) + property row |
| 10 | Waveform preview contract | PWAV 2..25, PWV2 1..15 no whiteness, never 0 | `analysis_engine.py:1180-1188` heights 0..31 + whiteness on PWV2; `:1286-1287` zero previews | P1 (Nexus players reject preview). Clamp/rescale at export, repair existing sidecars |
| 11 | PWV4/PWV5 channels | PWV4 `peak>>1,0,0,low,mid,high`; PWV5 rgb=low/mid/high | `analysis_engine.py:1198-1228` PWV4 `[hi,mid,low,height,mid/2,low/2]`; PWV5 r=high g=mid b=low; `anlz_writer.py:423-449` | P2. Colours look wrong on CDJ-3000 (R/B swapped); rewrite per 4.4 |
| 12 | PWV6/7 ranges | 7-bit (PWV7 `>>1`); PWV6 low scale | `analysis_engine.py:1236-1247` 0..255 | P2 |
| 13 | Playlist entry index | dense 1-based | `usb_one_library.py:804-807` 0-based in PDB; `:1098-1107` 0-based `sequenceNo` | P1. Verify vs real stick first; our invariants don't pin this |
| 14 | Artwork path | `{id/20+1:05}`, `a`,`a_m`,`b`,`b_m`; 80px/240px | `usb_artwork.py` bucket `id//1000:05d` (id<1000 -> `00000`), only a+a_m, medium 500px; own docstring `usb_pdb.py:480-486` cites `00001/a1.jpg` | P1. Contradicts our own F: reference. Fix bucket, add `b` copies, 240px |
| 15 | Cue export | DB cues; DAT=mem+A-C, EXT=D-P; 16 slots | `anlz_writer.py:260,353` cap 8 hot; all in DAT; `:223` status 4 on every hot cue; `:224-238` prev/next always ffff; cues from analysis not master.db | P2. Re-source cues from library; split lists |
| 16 | PCP2 shape | 88+L bytes, 0x01 @0x1d, hot colour id 0 | `anlz_writer.py:311-333` total 48+L, `B7x` so @0x1d = 0, colour id on hot cues | P2 |
| 17 | PSSI | layout above + XOR mask | `anlz_writer.py:570-661`: end_beat @0x16 (not 0x1a), fill @+8 (not 0x15), no mask | P2. Likely invalid for rekordbox 7 / CDJ-3000 lighting; mood plaintext @0x12 = unmasked |
| 18 | PQT2 | empty 44 B header or omit (payload unknown) | `anlz_writer.py:664-710` invents 56 B header + 2 B/beat | P2. Risk: bad extended grid. Omit or empty until verified vs real EXT |
| 19 | PDB row slots | slot*32 at +2 | `usb_pdb.py:608` from dict (0); `:396` artist u16 0 | P2 (NXS-era browse lockups) |
| 20 | Artist 0x64 variant | used with long names | only 0x60 `usb_pdb.py:396` | P2 |
| 21 | Hot-cue auto-load | slot 7 "ON" iff enabled | `usb_pdb.py:561` always "ON" | P2 |
| 22 | myTagMasterDBID | library DBID, equal in ext + OneLibrary | `usb_one_library.py:233-237` sha1(usb_root path); ext writer has no master param (`usb_pdb.py:1231`) | P2 |
| 23 | Audio layout | `Artist/Album`, 48-char cut | `usb_manager.py:1413-1450` `Artist/Title`, 40-char cut; FAT32 total-path cut; md5 flatten fallback | P2 contradiction, see 11 |
| 24 | Name collisions | `-{export_id}` suffix, NFC+lowercase key | none; same artist/title/filename overwrites or is skipped by size-only dedupe `usb_manager.py:1457`, `usb_one_library.py:51-63` | P1 data loss: second track silently skipped |
| 25 | Incremental sync | manifest, revisions, hashes, stable ids, no-op, playlist-only | none: DB rebuilt from template every run (`:213-218`), size-only skip, no stale-file cleanup, ids reassigned from slot order `:312` (ids shift between syncs; decks cache by id) | P1 efficiency+correctness. Persist manifest on stick; pin ids |
| 26 | Atomic publish | stage -> verify -> journal -> rename; recover | per-file `.part`+replace `usb_one_library.py:28-48`; `usb_pdb.py:947-966` fsync+replace; DB written in place; lock file only `usb_manager.py:152-172` | P2. Stage DBs next to target, rename at end, PDB last-but-verified |
| 27 | fsync | files + dirs, F_FULLFSYNC fallback | `_copy_file_atomic` no fsync; artwork `write_bytes` plain | P2 |
| 28 | Post-export verify | staged + published read-back, 2-DB agreement | none | P1. Port the checklist in section 8 as a pytest-able verifier |
| 29 | Rekordbox-running guard | refuse USB write if app runs | none in `usb_manager.py` | P2 |
| 30 | Free-space / estimate | peak = staged+64K; commit needs required+largest+1MiB | `usb_manager.py:1461-1468` per-file check only | P2 |
| 31 | Settings files | DEVSETTING valid 140 B + CRC; MYSETTING only if absent | `usb_mysettings.py:517-583` MYSETTING ok (only_create_missing); `usb_manager.py:2051-2062` writes 140 zero bytes for DEVSETTING (appears uncalled, remove) | P2 |
| 32 | `.sync` records | playlists3(.Plus).sync | not written | P3 optional (Sync Manager interop) |
| 33 | exportExt type 4/7 | track-tag rows ordered; master row | tag-track rows `usb_pdb.py:1115`; no master id | P3 |
| 34 | Conversion/compat | opt-in convert to PCM16/44.1 or 320k MP3; surround refuse | none | P3 |
| 35 | Parallel/cached copy | reader/writer threads, hash-while-copy, shared cache | serial `shutil.copy2` | P3 (USB bound anyway; hash-while-copy gives free manifest hashes) |

## 11. Contradictions with our byte-verified invariants (recorded, not resolved)

Do not assume rbxport right. Our F: stick may have been a used (edited) stick; rbxport used fresh rekordbox 7.2.11/7.2.14 exports.

| Topic | Our rule / code | rbxport |
|---|---|---|
| Data-page flag | rule text: 0x34 on every data page. Code `usb_pdb.py:180-188,820-822`: 0x34 only tracks, 0x24 rest (code comment says rule text is wrong) | 0x24 on all fresh-export data pages; 0x34 only on pages rekordbox edited in place (delete/re-insert). **Three-way mismatch; update rule text at minimum.** |
| Empty candidate | rule: `empty_candidate = next_unused_page` (past EOF) | code + rbxport: distinct zeroed page per table, allocated after the table's last data page; only trailing zero pages truncated. Rule text stale vs code |
| Header u32 @0x10 | `usb_pdb.py:914` = 4 (F: observed); ext `:1208` = 5 | 1 (constant) |
| Page 0x20/0x22 (<=16 rows) | `usb_pdb.py:361-367` (1, n-1); >16 rows (n,0) | <=255 rows (n,0); >255 (1, last idx). Opposite on small pages |
| Group 2nd mask word | `usb_pdb.py:297` last-row bit, every group | = presence mask normally; last-row-bit only for >255-row pages |
| Page sequence | `usb_pdb.py:837-851` all pages incrementing in table order | same idea, but allocation order differs (index+first data of all tables first, then overflow pages, type 19 first) |
| String encoder | rule: short ASCII / long UTF-16-LE | plus long ASCII 0x40, no terminator, 4-align; short ASCII to 125 chars |
| Audio dir | `Contents/<Artist>/<Title>/` "verified vs real stick" | `Contents/<Artist>/<Album>/`; 48-char dir cut (ours 40) |
| ANLZ dir | `P{id//256}/{id:08X}` "verified vs F: export" | path-hash; CDJ-3000 computes. (Possible: our F: ids happened to map? Test: recompute hash of our reference tracks' paths and compare to F: dirs.) |
| Artwork bucket | `id//1000` zero-padded (docstring in same file cites `00001/a1.jpg`) | `id//20 + 1` |
| Rating | x51 into OneLibrary and PDB | 0..5 both |
| PWV4 channel order | `[R_high,G_mid,B_low,height,...]` | `[peak,0,0,low,mid,high]` |
| PCPT status @0x10 | 4 for all hot cues (crate-digger "active") | 4 only for active loop (golden-tested vs rekordbox) |
| Index page | matches (0x64, 0x1fff x2, 0x03ec, 1004 pattern) | same |
| Row-group stride/offset math, free-space formula, track layout, album/playlist/key/color rows | matches | same |

Cheap discriminating tests on our reference stick (do before changing rules): (a) hash the stick's audio paths with the 4.1 algorithm, compare to existing `USBANLZ` dirs; (b) scan data-page flags per table; (c) read 0x20/0x22 on small pages; (d) check UTF-16 string terminators and 4-alignment; (e) check Artwork folder numbering for ids 1..30.

## 12. Top priorities

1. **ANLZ path hash + PPTH rewrite** (#1, #2): without it CDJ-3000 may not load waveforms/cues. Run test (a) first.
2. **PDB string/page fidelity** (#3, #4, #19): remove UTF-16 terminator, align long strings, fix >255-row header. Crash/freeze class. Add tests to `tests/test_pdb_structure.py` only after confirming vs reference.
3. **Drop the 16-slot template cap** (#5, #7, #8, #6): build exportLibrary.db from schema with SQLCipher, set all columns, rating 0..5, `journal_mode=DELETE`.
4. **Stable ids + manifest + collision handling** (#24, #25): silent skipped tracks + id churn are correctness bugs; manifest gives no-op/playlist-only fast paths.
5. **Post-export verifier** (#28) + **atomic stage/journal publish** (#26): catch 1-4 before the user plugs in.
6. Waveform byte contracts + channel order (#10, #11, #12), artwork layout (#14), PDB tables 16-19 (#9), cue/PSSI/PQT2 (#15-#18).
