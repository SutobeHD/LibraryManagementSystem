# Quality gates

What CI enforces, what it costs to keep it enforced, and what the 2026-08-04
sweep found when the gates were first driven to zero.

---

## Current state

| Gate | Command | CI | Baseline before sweep | After |
|---|---|---|---|---|
| Python lint | `ruff check .` | blocking | 139 (+15 unlinted in `scripts/`, +3 in `backend_entry.py`) | 0 |
| Python format | `ruff format --check .` | blocking | 8 files (+1 never reached) | 0 |
| Python types | `mypy app/` | blocking | 154 | 0 |
| Python tests | `pytest tests/` | blocking | 730 pass / 1 skip | 777 pass / 1 skip |
| Map drift | `python scripts/regen_maps.py --check` | blocking | clean | clean |
| Rust format | `cargo fmt --manifest-path src-tauri/Cargo.toml --check` | blocking (new) | 9 files | 0 |
| Rust lint | `cargo clippy …` | **NOT blocking** | unknown | unknown |
| Rust tests | `cargo test …` | blocking | — | — |
| Frontend lint | `npm run lint --prefix frontend` (`--max-warnings=0`) | blocking | 5 errors + 195 warnings | 0 |
| Frontend format | `npm run format:check --prefix frontend` | blocking | 111 files | 0 |
| Frontend build | `npm run build --prefix frontend` | blocking | green | green |

Everything except clippy ran with `|| true` before this sweep, i.e. no gate
could fail a build.

### Why clippy is still exempt

Not an oversight. `cargo clippy` needs a full compile, and the Tauri target
pulls `gdk-3.0` / `webkit2gtk`, which are unavailable on the Linux images used
for development containers — the build dies in `gdk-sys`'s build script before
clippy sees a single lint. Its warning list therefore cannot be read, let alone
cleared, from a Linux checkout, and flipping the switch blind would just break
`main`.

To close it: on a Windows checkout run

```
cargo clippy --manifest-path src-tauri/Cargo.toml --no-default-features --all-targets
```

fix what it prints, then in `.github/workflows/ci.yml` drop the `|| true` and
append `-- -D warnings`.

### Tool versions are pinned

`.github/workflows/ci.yml` and `.pre-commit-config.yaml` both pin
`ruff==0.15.8` and `mypy==1.19.1`. This matters more now that the gates block:

- unpinned, a new ruff release turns CI red with no change to this repo;
- unpinned, the pre-commit hook and CI disagree about what "clean" means. They
  already did — CI installed latest while pre-commit pinned ruff v0.8.6.

Bump both files in the same commit, after re-clearing the gate locally.

---

## Rules for keeping them green

1. **Never re-add `|| true`.** Fix the finding, or record the exemption where
   the tool itself will show it — `pyproject.toml`, `.eslintrc.cjs`, or an
   inline `# noqa` / `eslint-disable-next-line` that states the reason.
2. **An inline suppression needs a reason.** `# type: ignore[unreachable]` with
   no explanation is indistinguishable from a bug.
3. **Never run `ruff check --select X --fix`.** With a narrowed `--select`,
   every `# noqa` for a rule outside the selection counts as unused, and
   `RUF100` strips them all. This deleted 50 legitimate directives during the
   sweep before it was caught.
4. **`ruff --statistics` over-counts.** It includes violations already
   suppressed by `# noqa`. The authoritative number is the concise output.
5. **Give ruff exactly one path, `.`** — never a list of directories. Passing
   several silently drops some: `ruff format --check app tests` reports 108
   files, `tests app` reports 55, on the same tree. The gate this sweep
   originally shipped (`ruff check app/ tests/ scripts/`) looked at 65 of 118
   files and exited 0. `extend-exclude` in `pyproject.toml` governs scope; a
   root path also reaches `backend_entry.py` and `.claude/hooks/`, which no
   invocation had ever covered — and which held 3 lint errors and a formatting
   drift when first checked.
6. **Verify with `--no-cache`.** Ruff's cache reports a stale result for a file
   whose mtime it has already seen, and it under-reports the file count while
   doing so (`65 files already formatted` against a tree of 119). During this
   sweep a cached run said "All checks passed" on a tree that had an unsorted
   import block, and a cached `ruff format` refused to rewrite a drifted file.
   CI always starts cold, so a cached local green is not evidence.

---

## What the sweep found

Roughly a third of the findings were live bugs, not style. Listed because the
same classes will recur.

### Endpoints calling methods that do not exist

`RekordboxDB` (`app/database.py`) is a hand-written facade over
`RekordboxXMLDB` and `LiveRekordboxDB` with **no `__getattr__`**. Anything
missing from it is an `AttributeError` at the call site, and mypy's
`attr-defined` is the only thing that sees it. Nine were missing while being
called:

| Call | Route | Effect |
|---|---|---|
| `db.save_track_cues()` | `POST /api/track/cues/save` | hot-cue save from the waveform editor always 500'd |
| `db.save_track_beatgrid()` | `POST /api/track/grid/save` | beatgrid save from the region editor always 500'd |
| `db.get_track_cues()` | `GET /api/track/{tid}/cues` | always 500 |
| `db.get_track_beatgrid()` | `GET /api/track/{tid}/beatgrid` | always 500 |
| `db.load_xml()` | `POST /api/library/upload-xml` | XML upload failed after writing the file |
| `db.save_xml()` | analysis save, duplicate merge | silent no-op / 500 |
| `db.get_analysis_writer()` | `POST /api/analysis/write-to-db` | always failed |
| `db.get_unanalyzed_track_ids()` | `POST /api/analysis/write-to-db` | always failed |
| `db.update_track_title()` | `POST /api/library/clean-titles` | always 500'd |

Reads and the XML-mode writes are implemented now. Live-mode cue/beatgrid
writes return `{"status": "error"}` — persisting them means rewriting ANLZ
sidecars and no such path exists in the codebase yet.

The ninth, `db.update_track_title()`, exists on no class at all and was found
*after* the mypy pass, by `tests/test_db_facade_contract.py` — mypy missed it
because `check_untyped_defs = false` and `LibraryTools.clean_track_titles` is an
untyped function body. Live-mode `update_track_metadata()` did not handle a
`Title` key either, so the fix covers both halves.

> **If you add a method to `RekordboxXMLDB` or `LiveRekordboxDB` and want it
> reachable from a route, add it to the facade too.** Two things guard this
> now: `mypy app/`, and `tests/test_db_facade_contract.py`, which AST-scans
> `app/main.py` + `app/services.py` for every `db.<attr>` and checks it against
> the facade. The test catches what mypy cannot — untyped function bodies —
> and names the offending file and line.

### Other live faults

- `app/main.py` `POST /api/library/format-swap/execute` called `uuid.uuid4()`
  with `uuid` imported only inside two *other* functions → `NameError` on every
  request. (ruff `F821`.)
- `LiveRekordboxDB.delete_track()` read `playlists_tracks` as if it held row
  objects (`str(t["ID"])`) while it holds content-ID strings. Indexing a `str`
  raises `TypeError`, outside the `try` right below it, so `DELETE
  /api/track/{tid}` blew up on the first non-empty playlist. (mypy `index`.)
- `TimelineCanvas` never destructured `onRegionDrop` although its parent passes
  it and `handleDrop` called it. `onRegionDrop?.()` on an *undeclared* name
  throws `ReferenceError` — optional chaining does not guard that — so every
  palette drop onto the timeline failed, swallowed as a console line. (eslint
  `no-undef`.)
- `RekordboxBridge.export_xml()` does not exist; the method is
  `export_collection()`. Auto-export after import was dead.
- `db.get_tracks()` (4 sites) does not exist anywhere; the method is
  `get_all_tracks()`. One site hid it behind `hasattr()` and quietly processed
  an empty list.
- `AudioEngine.get_duration()` has never existed either. `render_segment()`
  called it behind `hasattr(AudioEngine, "get_duration")`, so the branch was
  permanently dead and ffprobe was always the path taken. A `hasattr()` guard
  around a method that does not exist is not defensive — it is a silent
  no-op. Found by generalising the facade scan to every `app.*` object.
- `PlaylistBrowser` had two byte-identical `useEffect`s loading the playlist
  tree, one keyed on `libraryStatus?.loaded` and one on `[]` — every mount with
  a loaded library fetched the tree and all tracks twice.
- `ToastContext` built its context value as a fresh object literal per render,
  so every `useToast()` consumer re-rendered whenever any toast appeared or
  expired. `addToast` also closed over a `removeToast` declared below it from an
  empty-dep `useCallback`, which worked only because `const` resolves at call
  time.
- `UsbProfileEditor` passed `usbTracks[flatKey] || []` into two `useMemo`s. The
  fallback minted a new array every render, so both memos recomputed every
  render.
- `RekordboxDB.get_all_labels/get_all_albums` used `@lru_cache` on instance
  methods. The cache keys on `self`, so every library the sidecar ever loaded
  stayed reachable for the process lifetime; and `load_xml()` never invalidated,
  so reloading a second XML into a live instance served the first library's
  rollups.
- `.claude/hooks/*.py`: both PostToolUse hooks were invoked by relative path, so
  a single `cd frontend` in a Bash call broke them — auto-push died with ENOENT
  and format-on-edit silently no-op'd (its `relative_to()` raised and was caught
  as "file outside the repo").
- `scripts/validate_research_docs.py`: the opening backtick sat inside the
  optional `research/` group, so a lifecycle line written as `` `drafting_` ``
  never parsed and the doc read as still being in its previous state. The
  pre-commit hook was failing on a correct document.

### Known-broken, left alone

- **`SoundCloudProgressModal` is unreachable.** `PlaylistBrowser` declares
  `const [showScProgress, setShowScProgress] = useState(false)` and never calls
  the setter, so the modal never opens. It also has no dismiss control of its
  own — no close button, no backdrop handler — and ignores the `onClose` its
  parent passes. Wiring it up is a feature decision, not a lint fix.
- **Live-mode cue/beatgrid persistence.** See the facade table above.

---

## Regression cover

None of the bugs above had a test. They do now:

- **`tests/test_db_facade_contract.py`** — the general guard. AST-scans every
  `db.<attr>` in `app/main.py` and `app/services.py` against `RekordboxDB`, plus
  named pins for the nine methods that shipped missing and one that asserts
  `get_tracks` is not reintroduced as a confusing alias of `get_all_tracks`.
  A second scan generalises this to every module-level `app.*` object reached
  by attribute in those two modules — that one caught
  `AudioEngine.get_duration`.
- **`tests/test_regression_gate_sweep.py`** — one pin per specific fault: the
  `uuid` import, the `delete_track` string-indexing, `TimelineCanvas`'s
  `onRegionDrop` prop, `PlaylistBrowser`'s duplicate effect, the `lru_cache`
  removal and `load_xml` invalidation, the thread-local import binding
  (including that a fresh thread does not inherit a task and unbinding twice
  does not raise), `_is_streaming_pseudo_path` against 13 inputs incl. Windows
  drive letters, `$CLAUDE_PROJECT_DIR` in the hook wiring, and the lifecycle
  regex against both backtick forms.

Suite: 730 → 777 tests.

## Judgement calls worth knowing about

- **`allowed-confusables = ["–", "—", "×"]`** in `pyproject.toml` rather than
  muting `RUF001/002/003`. The en dash is a real `Artist – Title` delimiter the
  tag parsers split on (`app/audio_tags.py`, `app/services.py`); the rules stay
  live for genuine homoglyphs like a Cyrillic `а`.
- **`# noqa: E402` on 14 imports in `app/main.py`** rather than moving them.
  `app.config` reads `os.environ` and `mkdir()`s at import time, so it must load
  *after* `load_dotenv()`. Reordering them would make a repo-local `.env` stop
  working. The block says so in place.
- **4 frontend modules carry a file-level `react-refresh/only-export-components`
  disable** (`UsbControls`, `ConfirmModal`, `PromptModal`, `ToastContext`).
  Each deliberately co-exports helpers with components — `UsbControls`' header
  says "Kept in one file on purpose" — and the rule only costs HMR granularity.
- **7 dependency arrays carry an `eslint-disable-next-line` with a reason**
  (polling keyed on `batchId`, load-once-per-track, a guard flag the effect
  itself sets). Silent narrow deps became explicit reviewed ones.
- **`requests` sits in the mypy overrides.** `types-requests` would fix it
  properly, but adding a stub-only package to the pinned `requirements.txt` is a
  dependency decision, not a typing one.
