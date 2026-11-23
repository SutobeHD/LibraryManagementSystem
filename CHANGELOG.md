# Changelog

## [Unreleased]

- Logging:
  - Fixed: user paths reached the logs with the account name whenever they were
    not spelled exactly like the home folder — forward slashes (a third of the
    library), other case, URL-encoded query strings in uvicorn access lines,
    doubled backslashes from a list repr, UNC paths. The scrub now matches every
    spelling, and uvicorn's own access and error loggers (which do not propagate
    to the root logger) get scrubbing formatters via `log_config`.

- Library:
  - Added: every track column sorts, Date Added and Colour included; Key sorts
    on the Camelot wheel (Camelot and musical spellings mixed), missing values
    stay at the bottom. New optional columns: Genre, Label, Year, My Tags,
    Format (right-click the table header).
  - Fixed: text columns sorted by code point, so titles with umlauts or accents
    landed after Z. They now sort in the language's order, numbers inside
    names by value ("Track 2" before "Track 10").
  - Fixed: 23 tracks without a Rekordbox stock date showed "-" under Date
    Added; they now show the day they were added to the library.
  - Fixed: the Collection search found nothing for `rating:>=4` or
    `genre:"deep house"`. Ratings, BPM and year take `>`, `>=`, `<`, `<=`
    and `=`, BPM ranges like `bpm:138-142` still work, quoted values may
    contain spaces, `key:8A` and `key:Am` find the same tracks (`key:A`
    finds A and Am), and `artist:` / `title:` / `album:` filter their field.
    A token the search cannot read is searched as plain text instead of
    hiding every track; `12" mix` and `4:44` still find those titles.
  - Fixed: "Delete from Collection" in the live Rekordbox library only hid the
    track until the next restart (and answered 500) while the dialog promised a
    permanent delete. rbox 0.1.7 cannot delete a track row, so the live mode no
    longer offers it: the menu item is hidden and `DELETE /api/track/{id}`
    answers 409 with a hint to remove the track in Rekordbox. XML mode still
    removes tracks, now with one confirmation instead of two.
  - Fixed: editing several tracks at once is all or nothing. A batch naming a
    track the library does not hold answers 404 with that id and writes nothing
    (the live library had already written the valid tracks and answered 500); a
    write the live database refuses partway puts the tracks already written back.
    Editing an unknown track answers 404 instead of 500.
  - Fixed: Title / Artist / Album edits from the track table and the batch bar
    now reach the audio file's tags too (setting `write_tags_to_files`, on by
    default), as single-track edits already did; the answer reports each file.
  - Fixed: a track edit no longer replaces the file's own cover art with the
    library thumbnail (a back cover was deleted, a PNG relabelled JPEG), a
    colour-only edit leaves the file untouched, and two quick edits of one track
    write the file in the order they reached the library.
  - Fixed: imported MP3s got FileType 0 in master.db instead of Rekordbox's 1.
    Every import now gets the code of its format (MP3 1, M4A 4, FLAC 5, WAV 11,
    AIFF 12).

- Rekordbox XML export:
  - Fixed: the export held no playlist (PLAYLISTS was an empty ROOT), so an
    imported file lost the playlist and its order. `POST /api/rekordbox/export`
    now takes `playlist_id` (a playlist, or a folder with its subfolders) or
    `track_ids` + `playlist_name` and writes the playlist nodes in playlist
    order. A plain track list (the whole-library push) still has no playlist.
  - Fixed: SoundCloud and other streaming tracks got a made-up local
    Location (`<backend folder>/soundcloud:tracks:…`). They are now left out,
    and the response says how many were skipped.

- API route hygiene:
  - Fixed: a suffix range (`Range: bytes=-500`) on `/api/stream` returned the
    first 501 bytes of a non-AIFF file instead of the last 500. Both stream
    routes now share one RFC 7233 range
    handler (single range -> 206, multi-range or malformed -> whole file,
    unsatisfiable -> 416).
  - Fixed: `/api/audio/stream` (DAW editor) ignored Range for MP3/FLAC/M4A/WAV
    and sent FLAC/M4A with the wrong Content-Type. It now answers exactly like
    `/api/stream`. Both routes answer `HEAD`.
  - Fixed: `POST /api/audio/analyze` analysed any existing file; it now has the
    same folder sandbox as playback (403 outside the library folders).
  - Fixed: analysis responses (`analyze-batch` progress lines, `analyze-full`)
    no longer contain absolute file paths.
  - Fixed: play-count sync (`/api/usb/playcount/resolve`) wrote a fixed
    `%APPDATA%` master.db in every mode, even while Rekordbox was running. With
    the live library it now refuses while Rekordbox runs, writes the library's
    own master.db and holds the database write lock; with an XML library it
    updates only the USB stick and says so. Errors show the backend's reason
    instead of "Request failed with status code 409".

- USB export:
  - Fixed: every exported track lost its album and kept the OneLibrary
    template's file type (M4A), sample rate (48 kHz), bit depth and file size,
    in `exportLibrary.db` and `export.pdb`. They now come from the file itself.
  - Fixed: ratings are stored as 0-5 stars instead of x51 (CDJ-3000X / XDJ-AZ
    showed no stars).
  - Fixed: artwork landed in folder `00000`; folders now hold 20 images each and
    start at `00001`, and every image is also written as the `b` copy Rekordbox
    writes.
  - Fixed: re-syncing a stick never updated `exportLibrary.db` / `export.pdb`
    on Windows while the app reported success. A plain sqlite3 probe of the
    SQLCipher file failed and kept it locked, so the writer could not replace
    it. The probe is gone, a still-locked file now ends the sync with an error,
    and any failed stage makes the whole sync report "Sync incomplete".
  - Fixed: the sync preview compared the stick with the whole library and read
    the stick with plain sqlite3 (always empty). It now reads it through rbox and
    compares the profile's selected playlists (plus their folders).
  - Fixed: BPM on the stick was cut instead of rounded (127.96 became 127.95)
    in `exportLibrary.db` and `export.pdb`.
  - Changed: the sync message counts files that were already on the stick
    separately instead of as "copied".
  - Fixed: a stick sync wrote at most 16 tracks into `exportLibrary.db` and
    `export.pdb` (B9) — the cap was the row count of the bundled OneLibrary
    template. The writer now adds the missing content slots before it writes
    (rbox 0.1.7 workaround) and falls back to the old cap with a warning only
    if that fails. Verified on fake sticks with 17 / 100 / 1000 tracks; real
    CDJ-3000 check pending.
  - Fixed: one track missing on the stick (skipped, failed, filtered out) left
    every later track of its playlist unlinked in `exportLibrary.db` — playlist
    links are now numbered without gaps.
  - Fixed: `property.numberOfContents` in `exportLibrary.db` always said 16; it
    now matches the tracks on the stick.
  - Changed: `export.pdb` data pages hold at most 255 rows, so big playlists
    never produce the >255-row page header that crashes rekordbox 6.8.6.

- Analysis accuracy + engine fixes:
  - Improved: exact-octave BPM accuracy (Acc-1). `detect_beats_madmom` now
    constrains the madmom DBN tempo window to the octave of a robust coarse
    estimate (librosa log-normal prior) — an "octave prior" that stops the
    tracker locking onto half-/double-time. Measured (synthetic, n=50, madmom):
    seed 11 Acc-1 72%→78%, seed 12 82%→94%; Acc-2 and KEY stay 100%; the
    180-210 BPM band's half-time errors are largely eliminated. (Window never
    binds when coarse + DBN already agree, the common real-music case.)
  - Fixed: `requirements.txt` was missing `rbox==0.1.7` (the Rust-backed package
    that `import rbox` resolves to across 10 modules — MasterDb/Anlz/OneLibrary).
    Only `pyrekordbox==0.1.7` (a *different*, pure-Python package used solely for
    my-settings structs) was pinned, so a clean install left live-DB / ANLZ /
    USB-export features in their soft `rbox=None` fallback.
  - Fixed: produced ANLZ cue entries (PCPT) wrote two wrong constants
    (0x00100000 instead of 0x10000; zero instead of the u2 const 1000), so the
    `.DAT`/`.EXT` files diverged from the Rekordbox cue layout and were rejected
    by strict ANLZ parsers. Now spec-conformant — independently verified by
    pyrekordbox `AnlzFile.parse_file()` parsing all three produced files.
  - Fixed: essentia key names normalized flats→sharps (Eb→D#, …); the active
    essentia path otherwise returned empty Camelot/key_id for ~5 of 12 keys.
  - Fixed: `madmom` RNN beat tracking was dead code on Python 3.10+ (the
    project target) — `import madmom` raised on removed `collections`/`numpy`
    symbols and was silently swallowed, so the librosa fallback always ran.
    `_apply_madmom_compat_shims()` restores the symbols; RNN path now active.
  - Fixed: octave disambiguation counted onset-envelope frames (inflated on
    sharp signals → falsely doubled slow tracks); now counts discrete onset
    events (true onsets-per-beat).
  - Fixed: neutral `minor_bias` (1.10→1.0) — the minor thumb made major triads
    read as their mediant minor (D major→F# minor).
  - Fixed: PSSI phrase ids written per the track mood bank (crate-digger enum);
    previously-invalid ids showed blank/wrong phrase labels on CDJ/Rekordbox.
  - Added: optional 16-bar memory-cue grid for beatmatching
    (`memory_cue_grid` setting / `RB_ANALYSIS_MEMORY_CUE_GRID`).
  - Changed: BPM output range raised to 215 (fast DnB/footwork/hardcore no
    longer octave-folded to half-time).
  - Added: `scripts/compare_rekordbox.py` (A/B accuracy vs a real library) +
    `scripts/selftest_analysis.py` (autonomous synthetic-ground-truth accuracy,
    MIREX Acc-1/Acc-2). Self-test with RNN: BPM Acc-2 100%, KEY exact 100%.
  - Fixed: BPM on constant-tempo tracks where the beat tracker slips in a
    break, intro or outro. The single regression line failed there and the BPM
    fell back to a value quantised to 1.25 ms per beat (135.0 → 135.21,
    170.0 → 170.21). A second "comb" fit now takes the beats that share one
    phase: exact BPM, and a uniform grid when at least 85 % of the beats sit on
    that line. A/B against Rekordbox on 60 real tracks: BPM identical 40 → 56,
    median grid error 11.3 → 6.0 ms. Analysis cache version 5 — tracks are
    re-analysed once.
  - Fixed: a uniform beat grid that sat on the off-beat (tracker locked onto
    open hi-hat + off-beat bass) moves half a beat onto the kicks — only when
    the kick band (150–2000 Hz) is at least twice as strong between the beats
    as on them, on most beats, and the track's first sound sits between the
    beats too. 1 of 50 real uniform grids moved (210 → 20 ms against
    Rekordbox); two more at a 1.4× margin stay put because Rekordbox agrees
    with the shift for one and not for the other.
  - Fixed: beat grids of `.m4a` / `.mp4` files sat about 48 ms late. The
    47.9 ms AAC encoder-delay shift was applied although the decoder already
    drops the priming samples; 8 of 8 real `.m4a` tracks went from 49–56 ms
    to 1–8 ms against Rekordbox. Raw `.aac` and files with an iTunSMPB tag
    keep their shift (no such file measured).
- Reliability hardening (codebase-wide bug-hunt — 16 fixes + 15 new test files,
  full pytest suite 658 passing):
  - Fixed: Rekordbox XML import called a non-existent `db.update_track`, so every
    already-present track silently failed to update. Now uses the real
    `update_tracks_metadata`; empty `AverageBpm`/`TotalTime` on un-analyzed
    tracks no longer drop the track (was `float("")` → ValueError).
  - Fixed: live (master.db) load aborted entirely — zero tracks — if any single
    rbox metadata accessor (artists/genres/albums/labels/keys) raised; now each
    map degrades independently. An unnamed playlist (name `None`) no longer
    crashes the playlist tree.
  - Fixed: folder auto-import imported half-copied files (the stability check
    returned "ready" on timeout) and could `RuntimeError` on a stop()/submit
    race; both closed.
  - Fixed: a corrupt `.rbep` project file crashed `to_dict()` (attrs unset after
    ParseError); childless `<edit>`/`<section>` elements were silently dropped
    (ElementTree truthiness misuse).
  - Fixed: library normalization crashed the whole USB sync on one non-numeric
    tag (e.g. `BPM="n/a"`); Live `duration_ms`-only tracks had their duration
    multiplied by 1000.
  - Fixed: analysis cache crashed on a legacy/corrupt index entry (missing
    `cache_id`); `stats()` could raise `FileNotFoundError` under a concurrent
    cache clear (TOCTOU).
  - Fixed: download registry leaked a SQLite connection on every call (now
    closed via context manager); audio-analysis worker-pool creation race +
    `os.cpu_count()` edge + malformed-beat crash all guarded.
  - Fixed: produced ANLZ sidecar reported failure on a *successful* write
    (sanity-check evaluation-order bug — `any()` before its `isinstance` guard).
  - Perf: log redaction resolves the data-dir prefixes once at import instead of
    on every log line (3 filesystem calls per line removed).
- Added: Phase-1 Bearer-token authentication on 84 mutation endpoints.
  New `app/auth.py` self-generates session token at sidecar boot, captured
  by Tauri stdout reader + dev-middleware fallback. Frontend attaches
  `Authorization: Bearer` via bootstrap promise. New `safe_compare` helper.
  `SHUTDOWN_TOKEN` query-string scheme deleted (redundant under `require_session`).
- Added: **Artist Hub** — an overview of your favourite artists and their music.
  - Favourites picked from a browse column listing every artist in the library,
    with a configurable minimum track count (Settings -> Analysis).
  - **Merge** for the same artist spelled several ways (`boys noize` /
    `Boys Noize`). Deterministic folds only — case, whitespace, `.`/`-`/`_`,
    apostrophes, `&` vs `and`. Never fuzzy: an initialism or a typo stays a
    separate group on purpose, because a false merge cannot be told apart again
    afterwards. Apply repoints `master.db` **and** rewrites the audio file tags,
    and every row is journalled so Revert restores both.
  - **Rekordbox projection** — a flat `Artists` folder with one playlist per
    favourite, holding every alias variant, so a merged artist is one playlist.
    Diff-in-place: re-syncing an unchanged artist writes nothing. Refuses to run
    when `masterPlaylists6.xml` is missing, because rbox silently skips that file
    and the playlists would vanish on the next Rekordbox restart.
  - **SoundCloud catalogue per artist**, linked manually. The artist is
    identified by **name** — title prefix, uploader name, remixer credit — not by
    the uploading account, because labels, promo channels and DJs upload most of
    a signed artist's catalogue. Remixes are handled explicitly: their own
    remixes count as theirs; a remix of their track by someone else is listed
    separately and never auto-queued. What is missing from the library is split
    the same way.
  - **Discover** — artists you do not have yet, from one related-artists hop per
    linked favourite plus a zero-call tier over catalogues already cached.
    Already-owned and already-favourited names are filtered out.
  - **Background sync** (off by default, Settings -> Network) refreshes
    favourites' catalogues while the app is idle, under a per-pass call budget,
    stopping the moment you start anything. It never downloads — that stays a
    button.
  - Persistent SoundCloud login: the refresh token is stored in the OS keyring
    and renewed silently, so closing the app (or a day away) no longer means
    logging in again. **Existing users must log in once more** to store a refresh
    token.
  - USB export moves files instead of re-copying them when only the artist
    folder changed, including the two-step rename a case-only change needs on
    Windows. Both relocation branches verify file content before moving
    or deleting anything on the stick — the whole file is hashed up to 128 KiB,
    above that its first and last 64 KiB — and an unreadable file counts as
    unproven and is skipped. Hashing only the edges would have read the head
    twice for a file under 128 KiB, so two different short recordings sharing an
    oversized cover-art frame fingerprinted identically.
  - **Tracks belong to artists by their credits, not only by the Artist field.**
    An artist's page lists their own tracks, **their remixes of other people's
    tracks** (Remixer column, `(X Remix)` / `X Remix` / `X VIP` in the title),
    remixes of their tracks by others, and features (`feat. X`) — each row says
    why it counts. Right-click a row to change its role or take it away from the
    artist; "Add tracks" searches the library for what the credits miss, and
    "Artist zuordnen…" in every track table's context menu does the same from
    anywhere. The artist's Rekordbox playlist holds exactly this set, so their
    remixes land in it on the next sync; exclusions leave it.
  - **Find their social media.** A links strip on every favourite: "Find links"
    reads the profiles the artist lists on their own SoundCloud page and their
    MusicBrainz entry (Instagram, Bandcamp, Beatport, Resident Advisor, Spotify,
    YouTube, …). MusicBrainz is only trusted through the linked SoundCloud
    profile or an entry you confirm — a name match is offered, never applied.
    Links spotted in a bio are marked as unverified. Add your own, hide wrong
    ones (a hidden link stays hidden). "Find their SoundCloud" suggests accounts
    by name for an artist that is not linked yet — you pick the right one.
  - **Downloads recognise the artist and get the right names.** Every SoundCloud
    download now checks who it is by — label metadata, then `Artist - Title` in
    the title, then the uploader — against your artists (favourites, merged
    spellings, the SoundCloud account an artist is linked to) and your library.
    A label upload of an artist you have lands as `Boys Noize — Starter`, not
    `Boysnoize Records — Boys Noize - Starter`; a re-cased name takes your
    library's spelling. Only certain corrections are applied on their own; a
    split nothing vouches for (an artist you do not have yet) shows up as a
    suggestion on the download — "Übernehmen" writes it to the library and the
    file, "Rückgängig" puts SoundCloud's names back. The Download Manager shows
    per download who is credited, as what (artist / remix / original / feat.),
    and whether they are a favourite, known or new. A track downloaded from an
    artist's "missing" list now counts as owned even when its title changed.
  - Fixed: external links never opened in the desktop app — the shell plugin
    intercepted them but was not allowed to open anything (`shell:allow-open`
    was missing from the Tauri capability). This also fixes "Auf SoundCloud
    öffnen" in the track context menu.
  - Fixed: on a case-sensitive stick filesystem, merging `boys noize/` into an
    existing `Boys Noize/` re-copied the audio instead of moving it.
  - Changed: the smart-playlist button generates **labels only**. Its old
    `By Artist` branch grouped on the raw artist string (so two spellings became
    two folders) and duplicated every playlist on each re-run. An existing
    `By Artist` folder is reported but never deleted.
  - Fixed: Settings could silently overwrite every stored value — a timed-out
    `GET /api/settings` left the form showing defaults, and Save posted them.
    Saving is now disabled until a load succeeds.
- Fixed: in live mode, hot cues read from Rekordbox's `djmdCue` table loaded as
  nameless memory cues — the loader asked rbox for attribute names `DjmdCue`
  does not have. Libraries that fall back to the `djmdContentCue` mirror were
  not affected. Cues now also carry Rekordbox's colour / active-loop values.
- USB stick export (OneLibrary) fixes:
  - Fixed: the export missed an existing `.lms_anlz` analysis whenever the
    track's stored path was not already in resolved form (a `..` segment, a
    relative path, different letter case on Windows) and re-analysed the track.
  - Changed: ANLZ files go onto the stick the way Rekordbox exports them — the
    embedded path (PPTH) is the stick's audio path instead of your local one,
    and the phrase data (PSSI) is masked. Grid, waveforms and cues are unchanged.
  - Fixed: analysis backups (`ANLZ0000.DAT.bak-*`) were copied onto the stick,
    and a slot reused by another track kept that track's old `.EXT`/`.2EX` next
    to the new `.DAT`. Only `.DAT`/`.EXT`/`.2EX` are written now, other ANLZ
    files in the track's folder are removed, and a half-written analysis is
    rejected instead of copied.
- Track-metadata edits no longer report success for changes that never land:
  - Fixed: in a live (master.db) library, editing BPM, Key, Label or any field
    master.db cannot take through this path answered success and changed
    nothing; an empty field was saved as the text "None", and a Rating or
    colour outside 0-5 / 0-8 was written as is. Such an edit is now refused
    before anything is written.
  - Fixed: in an XML library, a value the file cannot hold (a number where
    text belongs, a control character, a non-number BPM) could truncate the
    library file — unloadable from then on — while the edit reported success.
    Saves now go to a temporary file that replaces the library only once
    complete, and such values are refused.
  - Fixed: in an XML library, an edit whose save failed (read-only or locked
    file) still reported success; it now fails and the in-app library is
    rolled back to what the file holds. A batch naming an unknown track
    changes nothing instead of editing the others.
  - Fixed: every XML save dropped all track ratings, and colours set in the
    app; both are now kept. Fields an XML library cannot store (Remixer, Year,
    a misspelt key) are refused instead of vanishing on the next reload.
  - Fixed: the track-edit endpoints answered 200 for an edit that failed or
    was silently dropped, so the app showed success. A refused field or value
    is now a 400 that names it (shown in the error toast, e.g. "Edit BPM/Key"
    in a live library), an unknown key in the single-track edit a 422, and a
    failed save a 500.
  - Fixed: the Rekordbox XML export marked every file "WAV File", wrote
    un-encoded file locations (a space, `&` or `#` made Rekordbox miss the
    file), stamped today's date as Date Added, numbered tracks 1..N and wrote
    the beat number as `Battuta`. It now writes the real file type, a
    percent-encoded location, the track's own date added and track id, the
    beat number as `Battito`, plus key, rating, comment and bit rate. An XML
    library track with an empty field no longer crashes the export, and
    importing an XML now decodes encoded locations.
  - Fixed: the Rekordbox XML export wrote the file name as sent: `../x.xml`
    or an absolute path landed outside `exports/` (e.g. over the XML
    library), and no name was a server error. The name is now reduced to a
    plain `.xml` file inside `exports/`; an unusable name is refused.
  - Fixed: in a live library, track edits, MyTags, track delete, every
    playlist change, imports (folder scan, drag-drop, upload, Rekordbox XML),
    duplicate merges, title cleaning, label playlists and SoundCloud
    sync/merge wrote master.db while Rekordbox was open, which overwrites or
    corrupts those rows. They now answer "Rekordbox is running. Close it
    before ..." (409) and write nothing. XML libraries are unaffected.
  - Fixed: creating a playlist answered success even when nothing was
    created, and returned the whole playlist instead of its id, so
    "Duplicate playlist" made an empty copy. It now returns the id and
    reports a failed create as an error.
- Performance (backend):
  - Perf: artist/label lists and drill-downs no longer re-read
    `metadata_mappings.json` once per track — the mappings are cached; a hand
    edit to the file is picked up within 2 s, and a merge whose write fails is
    not applied in memory either.
  - Perf: drag-drop import and folder scan no longer re-resolve every library
    path for every file (30 files over 2,000 tracks: ~75k → ~2k `resolve()`
    calls, ~12 s → ~0.4 s); a track added meanwhile is still skipped.
  - Added: `GET /api/library/tracks?light=true` returns the track list without
    beat grids, cues, position marks and phrases (no view requests it yet; the
    default response is unchanged).

## v1.0.0-beta — 2026-05-07

First public **beta**. Standalone DJ-library manager that competes with
Rekordbox/Serato while staying open and local-first.

### Workflows fully supported

1. **SoundCloud → Library → USB → Club**
   - SC OAuth login, playlist + likes browser
   - Per-playlist Download button — full pipeline with anonymous fallback
     when SC's v2 API rejects the token
   - Auto-analyse (BPM / Key / Beatgrid / Phrases / Auto-Hot-Cues / Auto-
     Memory-Cues / Waveform via librosa+scipy+numba)
   - Auto-import into library + auto-add to `SC_<playlist-name>`
   - USB-Sync to CDJ-3000 ready stick
2. **Local Files → Library → USB → Club**
   - Drag-drop / folder picker
   - Folder name becomes the playlist; every file (incl. duplicates) is
     bundled into one coherent playlist
   - Same full analyse + ANLZ + auto-add pipeline as SC
   - USB-Sync end-to-end

### Library

- **Standalone XML mode** — full feature parity with Live: create / rename /
  move / delete / duplicate / reorder, folders, smart playlists with
  Rekordbox-XML-spec conditions (BPM, Key, Genre, Rating, DateAdded, …),
  cues + beatgrid persisted on save
- **Live mode** — direct master.db via pyrekordbox
- DBWrapper routes every CRUD operation to the active mode without API
  duplication

### USB Export

- `PIONEER/rekordbox/exportLibrary.db` via rbox.OneLibrary
- `PIONEER/USBANLZ/<bucket>/<hash>/ANLZ0000.{DAT,EXT,2EX}` per track
- Audio copy under `Contents/<Artist>/<Title>`
- Cover artwork copy
- Mode-agnostic LibrarySource abstraction so Standalone-XML works for export
  the same as Live

### UI

- 4-card XML submode picker (New Empty / Standalone / Import / Defined Path)
- Import Manager with 7-stage live pipeline + per-stage timestamps
- Sticky import progress banner — visible on every screen, click to open
  manager
- Click-to-rate (5 stars) + Pioneer color-tag picker (9 colors) inline in
  the track table
- Tokenized search: `bpm:120-130 key:Am genre:techno year:2024 rating:>3`
- Right-click context menus on tracks (9 actions) and playlists (7 actions)
  — both via React portal + document-level capture-listener so they actually
  work in Tauri WebView2
- Edit-mode toggle removed — everything is always editable
- Playlist drag-reorder works (Tauri main-window `dragDropEnabled: false`)
- Player drag-seek with `track.TotalTime` fallback for chunked streams
- Pane height fills full window when no player is shown

### Tauri / Dev

- Debug build auto-spawns Python backend + Vite if their ports are free —
  direct exe launch behaves like `npm run tauri dev`
- Children killed on `RunEvent::Exit`

### SoundCloud

- Optional **Aggressive Download Mode** (hidden setting) — bypasses the
  default snipped-preview gate. Reveal by tapping the dot under "SoundCloud
  Sync" in Settings 5×. Use only for tracks you have a personal right to.

### Known limitations

- USB-Sync requires `pyrekordbox` (`rbox.OneLibrary`) — bundled with the
  release binary
- Manual Hot-Cue editing is post-MVP (auto-cues from analysis only for now)
- Master.db creation without an existing Rekordbox install is post-MVP

### Build & install

- Windows MSI + NSIS installers via `scripts/local-release.ps1`
- No code-signing — SmartScreen warning on first run is expected
- SHA256SUMS published with each release
