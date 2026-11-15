# Syndicate (Untitled Audio) — library, import, USB/export reference

## 1. Source + copyright note
- Source: Syndicate user guide (Untitled Audio, commercial DJ/performance app), chapters 2-5 + §12.8 (settings DATABASE).
- Own-words summary only, no copied passages. Cite `syndicate:§n.n`.
- Scope: library mgmt, import, USB/export. Skip performance/mixing/arrange features.
- Syndicate = own library + own USB format. NOT Pioneer-compatible export (`syndicate:§5.5`). LMS goal differs (CDJ-native sticks), so USB ideas = workflow/safety only.
- Core stance: never touches source audio; all analysis/cues/grids live in DB + one managed sidecar file per track (`syndicate:§2`).

## 2. Import
**Formats** (`syndicate:§2.1`)
- Audio: wav, aif/aiff (recommended), flac, mp3, m4a, aac, ogg. MIDI clips: mid/midi. Sampler sources: audio <=15 s.
- Doc pushes lossless: WAV/AIFF load fastest, exact timing. FLAC exact but decode cost. MP3 = pre-echo smears transients, decode cost, timing depends on header.
- MP3 timing: encoder delay/padding read from LAME header and trimmed on import; no double trim if platform decoder already handles it. Bad header -> keep decoder timing. Existing tracks keep their original timing convention even on re-analyse (grids/cues never shift). Rekordbox-imported tracks keep Rekordbox convention.
- Swapping a track for a converted file -> re-check grid start (converters strip padding, few-ms shift).

**Entry points** (`syndicate:§2.2`)
- Drag files / drag folders (recursive, non-audio ignored) onto track list; IMPORT button = system chooser. All open one options dialog.
- Selected playlist at drop time = import target.
- Progress phases: prepare -> collect files -> import. Cancellable.

**Import options / analysis** (`syndicate:§2.2`)
- Per-import toggles: key detection, grid detection (BPM + first downbeat; kick-start/silence tracks get onset-based first beat), auto-cue (suggested regions at musical boundaries).
- BPM preset narrows search range: none 80-180, house/techno 120-150, DnB 160-180, wubstep 135-150, downtempo <115. Remembered.
- Waveform + artwork prep always runs, single pass.
- CREATE NEW PLAYLIST toggle: **folder tree -> playlists**. One playlist per folder that directly holds audio, named by folder; dropped top folder takes the typed name; same-named folders stay separate; created at tree root. Off = All Tracks only.
- Re-analyse (`syndicate:§2.3`): context menu on selection; scope = selection or entire library; locked tracks skipped; app picks parallelism.

**Other import paths**
- M3U/M3U8 import (`syndicate:§3.6`): playlist named from `#PLAYLIST` or filename; entries absolute / relative / file:// URL; known tracks referenced, unknown audio imported in background; non-existent entries kept as MISSING placeholders (artist/title from `#EXTINF`) -> relocatable later; one summary dialog (playlists, tracks, problems).
- M3U export (`syndicate:§4`): per playlist, UTF-8 extended M3U (duration, artist, title, abs path), order kept, missing tracks still listed. Folders not exportable.
- MIDI clips (`syndicate:§2.5`): out of scope for LMS.
- Render -> optional auto-add to library (`syndicate:§2.6`).

## 3. Rekordbox/Lexicon import
**Rekordbox** (`syndicate:§2.4`, settings §12.8)
- Source = Rekordbox collection **XML** (user exports, closes Rekordbox). Merge-only into own DB; never writes to Rekordbox.
- Granular merge toggles: grids, cues, cue names, playlists, + CUE SOURCE (which Rekordbox cue set: memory vs hot).
- Track colours NOT imported (stay unassigned). Imported tracks keep Rekordbox MP3 timing convention - user told to eyeball grids/cues.
- Waveforms analysed for every imported track (slow on big libs).

**Lexicon** (`syndicate:§2.4`)
- Live read via Lexicon Local API (no file). User enables Local API in Lexicon, keeps it open. API has no password, LAN-reachable -> doc warns to turn off after.
- Conflict policy switch **CUES & GRIDS: LEXICON vs SYNDICATE** wins for tracks already in library. Lexicon-wins still respects per-track Cue Lock. Syndicate-wins = only new tracks take Lexicon data.
- Mapped: non-archived local tracks + metadata + rating + play count; hot cues/loops slots 1-16 at exact times (no grid snap); beatgrid from first tempo marker only (variable tempo -> opening tempo); playlists + folders (replace earlier Lexicon import); smartlists -> static playlists w/ current tracks; custom tag categories -> tag groups, tag colour = category colour; custom-tag import toggle.
- Lost/skipped: streaming tracks, fade-in/out/load markers, track colours, later tempo changes, smartlist rules.
- Re-import idempotent: updates same tracks/tags (renames followed); locally created tags never deleted.

## 4. Library model + tags + filters
**Model** (`syndicate:§3, §5`)
- SQLite DB + managed per-track data file (analysis, cues, grid, artwork, automation). Source audio untouched, referenced by path.
- Collections: All Tracks, Playlists (folder tree), MIDI/OSC clips, States, Arrangements, Samplers, History. Only tracks/playlists/history relevant to LMS.
- Playlists = references; track stored once. No dynamic/smart playlists in Syndicate (Lexicon smartlists flattened on import).
- Per-track: lock (protects grid/cues/markers; bulk re-analyse + Lexicon import honour it), colour (8 cue colours), rating 0-5, play count, status OK/MISSING/NETWORK.
- Remove from library = delete DB row + sidecar; audio file never deleted.
- Play history (`syndicate:§3.5`): per-session list, in play order, track played twice appears twice; optional; played rows dimmed for session; reset play status / reset counts.

**Tag model** (`syndicate:§3.2`)
- Tags live in **groups** (one group per dimension, e.g. Energy, Role, Texture). Virtual groups: ALL TAGS, UNGROUPED. Deleting a group ungroups its tags.
- Tag props: name, group, colour (auto-cycles 10 colours), shortcut key (1-0, Q-P; one key = one tag, reassign moves it).
- Tag applies to tracks/clips/arrangements/samplers/states; usage counts per type.
- Ops: rename, move by drag onto group, **merge into** another tag (re-points all items), delete everywhere.

**Tag editor UX** (F3)
- 3 columns: groups | tag tiles | inspector; browser below supplies the selection.
- Tri-state tile checkbox against selection: filled = all selected have it, dash = some, empty = none. Click on dash first adds to all.
- Hotkey toggles tag on selection while editor open, even with browser focused -> rapid tagging.
- "Show in browser" jumps to tag-filtered view.

**Filter model** (`syndicate:§3.3`) - Tag Shelf
- Slide-out panel on browser edge; filters current collection (after text search).
- Chip per tag grouped by group (groups foldable); chip shows live count in current collection; zero-count dimmed.
- Click = include, shift-click = exclude (red, struck). ALL/ANY switch for includes; excludes always hide.
- Find-tag box, CLEAR, footer "86 of 2,412".
- Collapsed shelf shows active-filter strip: white edge, count, colour swatches (minus for excluded), item count, x to clear.
- Search, shelf, sort work inside playlists too.

## 5. DB maintenance + backup/move
**Library Manager** (`syndicate:§3.1`) - 3 tabs: STATUS / PROBLEMS / BACKUPS
| Check | Fix offered |
|---|---|
| SQLite integrity | - |
| Track files exist at saved path | locate one (relink), search a folder, remove from library |
| Found elsewhere (search hit) | **relink all found** in one click |
| Unsupported (undecodable) | remove |
| Track data unreadable | rewrite track data (re-derive) |
| Playlist entries -> removed tracks | fix playlists (drop dead entries) |
| Orphaned sidecar files | clean up unlinked files |
| Per-source-folder status | ONLINE / DRIVE OFFLINE / FOLDER OFFLINE |
- Single SCAN LIBRARY (cancellable); EXPORT REPORT to text file; PROBLEMS tab shows count badge.
- Warns: do not remove "missing" tracks when whole drive is merely offline (removal discards entries).
- No dedupe feature documented. No cleanup of tags beyond tag merge.

**Backups** (`syndicate:§3.1, §3.7`)
- Back up now; automatic daily/weekly with retention count; backup folder chooser (must be separate from app-support + DB folders).
- Option: safety copy before bulk relink / orphan cleanup / restore.
- Content: consistent DB snapshot + app-support + DB folders (track data, docs, config). Excludes activation/device identity. Excludes audio files.
- Restore = replace (not merge); app prepares restore, quits, applies on relaunch. Then reconnect drives, scan, relink.
- Move computer: install + activate separately, copy backup + media, restore, if paths changed -> search folder + relink all found, re-pick audio devices.
- Doc checklist of what to keep alongside (audio, renders, plugins, presets) - useful pattern.

**Reset ops** (`syndicate:§3.6`, §12.8): clear database (confirm, audio untouched); full reset / factory reset (app-support folder only); reveal DB file. No auto-migration of old library formats.

## 6. Browser (columns, preview, layout, context menus)
**Source rail** (`syndicate:§4.1`): vertical button strip ALL / PLIST / CLIPS / STATES / ARR / SEQ / HIST; last selection restored on relaunch.

**Perf/cache** (`syndicate:§4`)
- In-memory cache of visited lists incl. artwork; bounded, not persisted; invalidated by any library edit/import/delete. Background worker loads first visit.
- Per-section memory of selection + scroll (even per playlist / history session); restores surviving selection and keeps same row at top when rows change.

**Modes** (`syndicate:§4, §4.6`)
- Edit allowed only in edit-ish modes; performance mode = read-only browser (browse, search, filter, preview, load, import-to-library).
- App mode (mouse; tree + table + split) vs Control mode (focus nav for hardware: up/down, left/right between tree and list, enter, back; split disabled).

**Toolbar** (`syndicate:§4.2`): search (live filter), zoom (row height + thumb size; shared by split panes), import, SPLIT (two independent panes), tag shelf tab, L1-L4 load buttons.

**Columns** (`syndicate:§4.3`)
- Header right-click toggles; drag reorder/resize; click sort. Layout saved **separately per collection type**.
- Identity: title, artist, album, label, genre, year, artwork, colour.
- Musical: BPM, key (colour-coded, Camelot or standard, shows alternatives for uncertain estimates), duration.
- File: sample rate, bitrate, file location, size, date added, status (OK / MISSING / NETWORK).
- Use: rating, play count, lock, order (in playlist), data (attached automation).
- Preview: waveform thumbnail coloured by cue region (grey optional).

**Preview** (`syndicate:§4.4`)
- Click waveform thumb = audition on cue bus (headphones).
- In performance mode previews lock to master tempo + beat phase, start on quantize boundary. Setting disables preview in perform mode. Space stops preview.

**Layout** (`syndicate:§4.7`): browser hidden / embedded (resizable) / detached window (2nd screen).

**Context menus** (`syndicate:§4.8`)
- Tracks: add/remove playlist, lock, set colour, show in file manager, remove from library, load to deck 1-4 (disabled if beyond deck layout), analyse.
- Export playlist (M3U) on playlist rows, any mode.

## 7. Playlists
(`syndicate:§5`)
- Tree of folders + playlists; refs only. Right-click: new playlist / folder (root or sibling), new playlist in folder, new subfolder, rename, set colour, delete (tracks stay).
- Colour: 8 cue colours on icon; none = grey playlist / orange folder; duplicates keep colour.
- Multi-select (ctrl/shift) + drag moves group in displayed order. Drop in middle of folder = into it; insertion marker = reorder; empty space or header = root. Folder carries children; cycle (into self/descendant) blocked; selection stays after move.
- Fill: drag from All Tracks, add-to-playlist menu, import with playlist selected, folder-import auto-playlists, Rekordbox XML/Lexicon playlists, M3U.
- Inside playlist: ORDER column, drag to reorder, remove-from-playlist, search + tag shelf + sort still work.
- History = auto per-session playlist-like list.

## 8. USB libraries
(`syndicate:§5.5`, §12.8) - Syndicate-own format, NOT Pioneer-readable.
- Contents: selected playlists (folders pull descendants) + audio + metadata, grids, cues, analysis. Plays directly from stick without importing into local library.
- Prepare: right-click playlist/folder -> SEND TO USB -> pick drive. No erase needed. Separate INITIALIZE (macOS) = erase whole physical disk, format exFAT, create empty library; confirmation shows disk name, size, all volumes; back up first.
- Re-send same playlist from same computer: asks before replacing that playlist; other playlists on drive remain; **audio already on stick reused** (incremental).
- Missing source audio: skipped + reported. Cancel keeps previous completed catalogue (atomic-ish).
- Not exported: clips, arrangements, samplers, states, history.
- Play: header LOCAL / USB switch; USB option appears only after library validated. USB browser read-only; edits happen in local library then re-export. Several drives -> first by name.
- Network share follows the selected source (USB vs local), remote peers see source label.
- Eject: dedicated eject button; first returns browsing/sharing to local source, then requests unmount; busy -> close users and retry; stop playback first.
- No Rekordbox/Engine export mentioned; doc explicitly says its format is separate.

## 9. Gap analysis vs LMS
LMS locations checked via `docs/features/*.toml` + `docs/MAP.md`. Claims about "none" = nothing found by grep of `app/` (m3u, relink, integrity, library backup) - verify before building.

| Item | Syndicate | LMS (feature id / file) | Idea / action |
|---|---|---|---|
| Format policy | Lossless preferred; MP3 LAME delay trimmed, timing convention pinned per track | `import-manager`, `import-quality-panel`, `quality-tiers-audit` | Store per-track timing convention; trim LAME delay when computing grids |
| Folder -> playlists on import | Optional, one playlist per audio folder | `import-manager`, `folder-watcher`, `library-folder-projections` (idea) | Add "create playlists from folders" toggle in `ImportView.jsx` |
| Import analysis options | Per-import key/grid/auto-cue + genre BPM preset | `analysis-on-import` (always-on) | Per-import checkboxes + BPM-range preset (cuts half/double-tempo errors) |
| Re-analyse scope | Selection or entire library, skips locked | `analysis-on-import`, `phrase-cue-generator` (batch) | Add lock flag + "re-analyse selection" |
| Rekordbox import | XML only; toggles grids/cues/names/playlists; cue-source choice; no colours | `rekordbox-xml-bridge` (`app/rekordbox_bridge.py`), `live-master-db` | Add field-level merge toggles + conflict policy (which side wins) |
| Lexicon import | Local API live read; custom tags -> tag groups | none in registry | New idea: Lexicon Local API importer (read-only); high DJ-migration value |
| M3U import/export | Yes, with MISSING placeholders | none (`.m3u` only in write allowlist `app/main.py:830`) | M3U in/out; placeholder tracks for unmatched paths |
| Tag model | Groups, colours, shortcuts, merge, tri-state | `mytag-management`, `ranking-genre-tree` (in build) | Add tag merge + hotkeys + tri-state bulk tagging |
| Tag filter | Shelf: include/exclude chips, ALL/ANY, live counts | `collection-view` (token search), `library-health-filters` | Tag-shelf filter panel with exclude + counts |
| Smart lists | Absent (flattened from Lexicon) | `smart-playlists` (partial, live mode RAM only) | LMS ahead; fix persistence, no copy needed |
| Missing files | Scan + relink one / folder / all found | `app/database.py:1132` (relocate deferred to Rekordbox, live mode no-op) | Library Manager "Problems": search folder + relink-all-found |
| Dedupe | Not offered | `duplicate-finder` (partial) | LMS ahead |
| Integrity checks | SQLite, files, track data, playlist orphans, sidecar orphans | `library-health-filters` | One-click SCAN + exportable report |
| Backups | Manual + daily/weekly, retention, pre-repair safety copy, restore = replace | `rekordbox-write-backups`, `app/library_format_swap.py:115` (backup before swap only) | Library-wide backup/restore (standalone XML lib + settings), scheduled |
| Move computer | Documented checklist | none | Doc/guide; relink flow covers path change |
| Track table columns | Per-collection layouts; status col OK/MISSING; key alternatives; cue-coloured preview | `track-table`; `frontend/src/components/TrackTable.jsx:9` (17 cols, localStorage `track_table_columns`) | Add STATUS (missing) + file-location/size/sample-rate cols; cue-coloured preview |
| Browser view memory | Per-list selection + scroll + cache | `collection-view` | Persist scroll/selection per playlist |
| Browser layout | Split panes, detached window | `track-table` | Split pane (compare two playlists) = low priority |
| Playlist tree | Multi-select drag, cycle guard, colours | `playlist-tree-crud` | Check multi-drag + colour parity |
| Play history | Auto per-session list | none | Idea: session history playlist (cheap) |
| USB incremental | Reuse audio on stick, replace per playlist, cancel keeps last good | `usb-sync-engine` (diff), `app/usb_manager.py:1225` | LMS already diff-based; confirm cancel keeps previous catalogue |
| USB safety | Eject returns browsing to local first; busy -> retry; init lists all volumes | `usb-drive-tools` (`UsbFormatWizard.jsx`) | Verify wizard shows disk size + every volume; eject-busy messaging |
| USB hardware format | Own format, not Pioneer | `usb-onelibrary-export`, `usb-legacy-pdb` | LMS stronger; nothing to take |
| Source switch LOCAL/USB | Browse stick as library, read-only | `usb-device-detect` | Idea: read-only browse of stick contents |

## 10. Top ideas for LMS (ranked)
Format: idea | value / effort | feature id.
1. Library Manager "Problems" tab: scan missing/unreadable, search folder, relink all found, report export | high / M | new (adjacent `library-health-filters`)
2. Library-wide backup/restore: scheduled, retention, safety copy before bulk ops | high / M | extends `rekordbox-write-backups`
3. Tag shelf filter: include/exclude chips, ALL/ANY, live counts | high / M | `mytag-management`, `collection-view`
4. Per-import analysis options + genre BPM-range preset | med / S | `analysis-on-import`
5. Folder -> playlists on import (toggle) | med / S | `import-manager`, `library-folder-projections`
6. Lexicon Local API importer (cues, grids, playlists, tags as groups, conflict policy) | high / L | new idea
7. M3U import (MISSING placeholders) + export | med / S | new idea
8. Granular Rekordbox XML merge toggles + cue-source choice | med / S | `rekordbox-xml-bridge`
9. Tag editor: merge tags, hotkeys, tri-state selection | med / M | `mytag-management`
10. Track lock flag protecting grid/cues from bulk ops | med / S | new idea
11. Per-list selection/scroll memory + STATUS column | low / S | `track-table`
12. Session play history list | low / S | new idea
13. USB: confirm cancel-keeps-last-good + eject-busy UX + disk-details in format confirm | med / S | `usb-sync-engine`, `usb-drive-tools`
