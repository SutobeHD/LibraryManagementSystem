# Research & Implementation Pipeline — INDEX

Live dashboard. Each entry mirrors a file under `docs/research/{research,implement,archived}/`. Update on every `git mv`.

Format per line:
`<state>_<slug>.md — one-line hook (YYYY-MM-DD)`

If this index drifts from the file system, the file system wins — re-derive with `ls docs/research/*/`.

---

## research/

### idea
- [idea_analysis-underground-mainstream-classifier.md](research/idea_analysis-underground-mainstream-classifier.md) — Underground vs Mainstream classifier / certifier for tracks (2026-05-15)
- [idea_recommender-similar-tracks.md](research/idea_recommender-similar-tracks.md) — Similar-tracks recommender for a given seed track (2026-05-15)
- [idea_analysis-remix-detector.md](research/idea_analysis-remix-detector.md) — Detect remix / edit / bootleg variants of a track (2026-05-15)
- [idea_metadata-name-fixer.md](research/idea_metadata-name-fixer.md) — Normalise artist/title metadata (artist-in-title, featuring, parentheses) (2026-05-15)
- [idea_library-extended-remix-finder.md](research/idea_library-extended-remix-finder.md) — Find Extended / Club / Long versions of every track in library (2026-05-15)
- [idea_library-quality-upgrade-finder.md](research/idea_library-quality-upgrade-finder.md) — Find higher-quality replacement files for tracks already in library (2026-05-15)
- [idea_mobile-companion-ranking-app.md](research/idea_mobile-companion-ranking-app.md) — Mobile companion app (soft client) focused on Ranking mode, requires main app running on server/PC (2026-05-15)

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
_(none)_

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
