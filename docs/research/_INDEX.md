# Research & Implementation Pipeline — INDEX

Live dashboard. Each entry mirrors a file under `docs/research/{research,implement,archived}/`. Update on every `git mv`.

Format per line:
`<state>_<slug>.md — one-line hook (YYYY-MM-DD)`

If this index drifts from the file system, the file system wins — re-derive with `ls docs/research/*/`.

---

## research/

### idea
- [idea_api-route-auth-model.md](research/idea_api-route-auth-model.md) — Local FastAPI mutation routes have no route-level auth gate; deliberate decision needed (spun off from downloader OQ-A) (2026-05-13)

### exploring
- [exploring_recommender-rules-baseline.md](research/exploring_recommender-rules-baseline.md) — Teil 1: BPM/Key/Genre/MyTag/Energy ranking + Camelot harmonic mixing; local + SoundCloud modes (2026-05-11)
- [exploring_recommender-taste-llm-audio.md](research/exploring_recommender-taste-llm-audio.md) — Teil 2: LLM/embedding-based recommender that learns taste from listening behaviour + audio features (2026-05-11)

### evaluated
_(none)_

### parked
_(none)_

---

## implement/

### draftplan
_(none)_

### review
_(none)_

### rework
_(none)_

### accepted
- [accepted_downloader-unified-multi-source.md](implement/accepted_downloader-unified-multi-source.md) — Unified downloader: **owner sign-off granted 2026-05-13.** Plan accepted; ready for `inprogress_` when implementation is unblocked. D3 feasibility proven (PASS) (2026-05-13)

### inprogress
_(none)_

### blocked
_(none)_

---

## archived/

### implemented
_(none yet)_

### superseded
_(none)_

### abandoned
_(none)_

---

## How to update

When a doc changes state:
1. After `git mv` (or `mv` for new files), move its line to the new section
2. Update the date at the end of the line
3. If the file moved across stages (e.g. `research/` → `implement/`), also update the markdown link path
