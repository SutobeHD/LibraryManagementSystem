# Übergabeprotokoll — Analyse-Engine Verbesserung

**Empfänger**: Nächste KI-Instanz (frische Session, kein Vorwissen)
**Auftraggeber**: tb (User) — spricht Deutsch, Caveman-Protokoll, Devise: **„Teste immer selber!!!"**
**Branch**: `claude/song-analysis-rekordbox-27TV8` (Stand dieses Protokolls; noch nicht in `main` gemerged)
**Scope**: Genauigkeit + Korrektheit der Song-Analyse (BPM / Key / Beatgrid / Phrasen) und der **produzierten Rekordbox-Dateien** weiter verbessern.

> Pflicht-Reads zuerst: `CLAUDE.md`, `.claude/rules/*.md`, `docs/architecture.md` (Datenfluss „BPM/Key Analysis"), `docs/FILE_MAP.md`. Dann dieses Protokoll.

---

## 0. MISSION

Die Analyse soll Rekordbox **ersetzen** (nicht 1:1 nachbauen — besser, wenn möglich). Aktueller Stand: auf dem Branch deutlich besser als `main`. Deine Aufgabe: noch näher an „perfekt auf echter Musik" + die zwei Hardware-/Library-Lücken schließen, die im Container nicht testbar sind.

**Eiserne Regel (vom User): Behaupte nichts ohne es selbst gemessen zu haben.** Jede „Verbesserung" muss mit `scripts/selftest_analysis.py` (oder echten Tracks) als Netto-Gewinn belegt sein, sonst zurücknehmen (`git revert`). Ich habe diese Session einen Fix (`octave-snap`) genau deshalb wieder verworfen.

---

## 1. AKTUELLER STAND — gemessene Baseline

Self-Test: `scripts/selftest_analysis.py -n 60 --seed 7 --dur 14` (deterministisch, synthetische Ground-Truth, MIREX-Metrik 4 % Toleranz; Acc-2 = oktav-tolerant).

| Metrik | main | **dieser Branch** |
|---|---|---|
| BPM Acc-1 (exakte Oktave), voller Native-Stack | 61 % | **86 %** |
| BPM Acc-2 (oktav-tolerant), voller Native-Stack | 86 % | **100 %** |
| KEY exakt, voller Native-Stack | 78 % | **100 %** |
| BPM Acc-1, reiner librosa+K-S-Fallback | 61 % | **71 %** |
| KEY exakt, reiner Fallback | 96 % | **100 %** |

Branch-Engine-Methoden bei vollem Stack: `beat=madmom RNN`, `key=essentia KeyExtractor`.

**Wichtig**: Das sind SYNTHETISCHE Tracks. Die Half/Double-Oktav-Mehrdeutigkeit ist darauf **härter** als auf echter Musik (selbst madmom-RNN schafft nur ~88 % exakte Oktave). Acc-2 (oktav-tolerant) ist die musikalisch ehrliche Metrik — identisches Beatgrid, nur Label ×2. Die absolute Real-World-Zahl liefert erst Schritt 5.3.

---

## 2. SETUP — voller Native-Stack (bewährtes Rezept, NICHT improvisieren)

CI + dieser Container laufen Python **3.11** → madmom/essentia bauen dort **nicht** → nur librosa-Fallback. Für echte Messung den py3.10-Stack bauen:

```bash
uv venv --python /usr/bin/python3.10 /tmp/v310
source /tmp/v310/bin/activate
uv pip install Cython numpy==1.26.4 scipy==1.11.4 setuptools wheel
uv pip install --no-build-isolation madmom==0.16.1
uv pip install "setuptools<80"          # restauriert pkg_resources für madmom-Import
uv pip install librosa==0.10.1 soundfile==0.13.1 essentia==2.1b6.dev1110 \
  fastapi==0.109.0 pydantic==2.5.3 mutagen==1.47.0 httpx==0.26.0 \
  rbox==0.1.7 pyrekordbox==0.1.7 pytest==8.4.2
```

Verifizieren: `python -c "import sys;sys.path.insert(0,'.');from app import analysis_engine as ae;ae._ensure_libs();print(ae.AnalysisEngine.capabilities())"` → erwartet `'beat_method':'madmom RNN'`, `'key_method':'essentia KeyExtractor'`.

`rbox` (Rust-Paket, ≠ pyrekordbox!) liefert `MasterDb/Anlz/OneLibrary`. `pyrekordbox` (pure-Python) liefert den unabhängigen `AnlzFile`-Parser + `mysettings`.

---

## 3. MESS-WERKZEUGE (alle diese Session gebaut)

| Tool | Zweck | Lauf |
|---|---|---|
| `scripts/selftest_analysis.py` | Autonome Accuracy gg. synthetische Ground-Truth, MIREX Acc-1/Acc-2 + BPM-Band-Breakdown + **Beat-F-Measure/Phase-Error** (Grid-Qualität) | `-n 100 --seed N [--full]` |
| `scripts/compare_rekordbox.py` | **A/B gegen echte Library** (BPM/Key/Beatgrid vs. Rekordbox' gespeicherte Werte) | `--db <master.db> -n 10` — **nur lokal beim User** |
| `tests/test_anlz_reference_parse.py` | Produziertes ANLZ vs. unabhängigem pyrekordbox-Parser + Byte-Struktur-Walk | pytest |
| `tests/test_analysis_db_writer.py` | master.db-Schreibwerte (Key-Map, BPM-Centi-Int, Beatgrid-Shape) | pytest |
| `docs/research/routines/analysis-accuracy-watchdog.md` | **Wöchentliche** Routine: baut Stack, misst gg. Baseline, validiert Dateien | claude.ai/code |

Volle Suite: `pytest tests/` (537 passed / 1 skip in 3.11; 538 / 0 im venv).

---

## 4. WAS BEREITS GEFIXT IST (nicht nochmal machen)

1. **madmom war toter Code** auf py3.10+ (`from collections import MutableSequence` / `np.float`). `app/analysis_engine.py:_apply_madmom_compat_shims()` aktiviert den RNN. Auch in `backend.spec` gebündelt (72 Modell-Dateien).
2. **essentia-Key gab leeres Camelot** für 5 Tonarten (b- vs. #-Schreibweise). `_FLAT_TO_SHARP` in `detect_key_essentia`. Auch in `backend.spec` gebündelt.
3. **2× falsche PCPT-Cue-Konstanten** (`0x100000`→`0x10000`, fehlende `u2=1000`) → ANLZ war nicht spec-konform. Fix in `app/anlz_writer.py:_build_pcpt_entry`.
4. **`minor_bias` 1.10→1.0** — der Moll-Daumen machte Dur-Dreiklänge zur Mollterz (D-Dur→F#-Moll).
5. **Onset-Density zählte Frames statt Events** → verdoppelte langsame Tracks fälschlich. Jetzt `librosa.onset.onset_detect`.
6. **BPM-Output-Range 180→215** (schnelle DnB/Footwork nicht mehr auf Halftime gefaltet).
7. **PSSI phrase-IDs bank-korrekt** pro Mood (crate-digger-Enum).
8. **`rbox==0.1.7` fehlte in requirements.txt** (nur pyrekordbox war gepinnt — Clean-Installs waren für Live-DB/ANLZ/USB kaputt).
9. **16-Takt-Memory-Cue-Grid** (Feature, `memory_cue_grid`-Setting).
10. **Verworfen** (Lehre): `octave-snap` gg. coarse-tempo — half hohe BPM, regredierte aber ~80-BPM-Tracks; Autokorrelations-Stützung trennt die Fälle nicht. Synthetik-Tuning ohne echte Tracks ist eine Sackgasse.

### 4b. Gemessen & verworfen — NICHT erneut versuchen (Synthetik, v310-Stack)
Zwei naheliegende Grid-Hypothesen empirisch widerlegt (madmom RNN, seeds 7/11/21, n=40):
11. **Even-Grid-Regularisierung** (madmom-Beats durch gleichmäßiges Raster ersetzen: robuste Periode + Zirkulär-Median-Phase). **Schlechter**: Beat-F 0.921→0.900, Phase-|err| 4.5→18.6 ms. madmom-Rohbeats sitzen bereits besser als ein global gleichmäßiges Raster (lokale Platzierung > globale Phase). Rohbeats behalten.
12. **Octave-Window deaktivieren** (DBN auf volle Range statt coarse-Oktave). **Schlechter**: Acc-1 seed11 31→28, seed21 36→34 (seed7 unverändert), Acc-2 bleibt 100 %. Das Window aus `_octave_window` ist netto-positiv und bestätigt — nicht entfernen.

**Konsequenz**: Engine ist auf der Synthetik an der Decke (BPM Acc-2 100 %, KEY 100 %, Grid-Phase signed-median ~0…−4 ms, kein systematischer Offset). Restlicher Acc-1-Gap = irreduzible Halb/Doppel-Oktav-Ambiguität auf synthetischem Material. **Weitere BPM-Genauigkeit braucht echte Tracks (5.3), nicht mehr Synthetik-Tuning.**

---

## 5. OFFENE PROBLEME / NÄCHSTE SCHRITTE (priorisiert)

### 5.1 — Half/Double-Oktav-Mehrdeutigkeit (das harte Kernproblem)
BPM Acc-1 bleibt bei ~86 % (voller Stack), weil ~12 % der Tracks auf der falschen Oktave (×2/÷2) landen. **Bewiesen unentscheidbar** aus reiner Periodizität auf Synthetik — sogar madmom-RNN scheitert daran. Echte Musik hat timbrale/melodische Cues, die das lösen.
**Richtung**: (a) Genre-/Spektral-Prior (Bass-Energie, Onset-Muster) als Oktav-Tiebreaker; (b) madmom liefert auch `key_cnn`/Downbeat-Modelle — evtl. nutzbar; (c) ehrlich akzeptieren, dass Acc-2 (oktav-tolerant) das richtige Ziel ist und nur an den Rändern (≤85, ≥190) nachschärfen. **Verifizieren NUR mit echten Tracks (5.3), nicht Synthetik.**

### 5.2 — Synthetischer Test ist als Oktav-Maßstab unfair  ✅ realistic-Generator gebaut
`synth_track` (drone) nutzt Kick/Bass auf jeder Zählzeit → künstlich oktav-mehrdeutig. **Erledigt**: `synth_track_realistic` + `--style realistic` (Backbeat-Snare 2&4, 8th-Hats, 16th-Ghosts, Humanize ~4ms, Noise-Floor).

**Gemessen (madmom RNN, n=40, seeds 7/11/21):** realistic ist HÄRTER, nicht leichter:
- Acc-1: drone 90/78/90 % → realistic **75/52/67 %**; Acc-2 bleibt **100 %**; KEY **100 %**; Grid-Phase **~5 ms**.
- Band-Breakdown: 100–180 BPM nahezu perfekt; alle Fehler an den Rändern — 75–100 → verdoppelt, 180–210 → halbiert.
- **Ursache**: dichte 8th-/16th-Subdivision erzeugt starke Periodizität bei Double-Time → zieht langsame Tracks hoch (echte Eigenschaft busy-elektronischer Musik). **Grid ist immer korrekt** (Acc-2 100 %, 5 ms) — nur das Oktav-LABEL kippt an den Rändern.
- **Lehre/Warnung**: Threshold-Tuning (`onset_density_*`, coarse-Prior) auf DIESEN Generator wäre Overfit auf meine willkürliche Subdivisionsdichte → **nicht tun**. Der realistic-Generator ist ein Stress-Test/Benchmark, kein Tuning-Target. Oktav-Fix braucht echte Tracks + timbrale/Genre-Modelle (5.1).

### 5.3 — Echte-Library-Validierung (NUR beim User möglich)
`compare_rekordbox.py` über ~10–50 echte Tracks laufen lassen (Rekordbox geschlossen). Bestätigt, ob die synthetischen Zahlen auf echter Musik halten. **Bitte den User um die Summary-Ausgabe** — erst diese Daten rechtfertigen weiteres BPM-Heuristik-Tuning. Attribut-Zugriffe sind gegen die echte rbox-0.1.7-API verifiziert.

### 5.4 — Live `master.db`-Write (NUR beim User)
`app/analysis_db_writer.py` schreibt via `rbox.update_content`. `rbox.MasterDb(path)` kann **keine** leere DB anlegen (braucht existierende SQLCipher-DB). Schreibwerte sind unit-getestet; der echte Write braucht die User-`master.db` + Key. Der `rbox`-Schreibmechanismus selbst ist durch `tests/test_onelibrary_wal_flush.py` abgedeckt.

### 5.5 — CDJ-3000-Hardware-Load (NUR beim User)
Byte-Layout ist gegen pyrekordbox-Referenz + `test_pdb_structure.py` verifiziert; die letzte Meile ist ein echter Stick im echten CDJ.

### 5.6 — Weitere Engine-Ideen (mit Self-Test messen, dann commit)
- Key: 3-Profil-Ensemble (Shaath zusätzlich), Tuning-robustere Chroma.
- Beatgrid: dynamische Tempo-Anker für Tracks mit Tempodrift (`detect_tempo_changes` existiert, prüfen ob im Write-Pfad genutzt).
- Phrasen: `detect_phrases` ist energie/MFCC-heuristisch — evtl. madmom-Downbeat/Segment-Modelle.

---

## 6. HARTE CONSTRAINTS

- ⚠️ **Byte-Format ist heilig**: `app/anlz_writer.py` + `app/usb_pdb.py` byte-verifiziert. Jede Konstante/Offset-Änderung gg. crate-digger-Spec **und** pyrekordbox-Parser prüfen (`tests/test_anlz_reference_parse.py` im venv). Falscher Wert korrumpiert Sticks lautlos.
- Nach jeder Audio-Stack-Änderung: `audio-stack-reviewer`-Subagent (läuft cargo/ruff/mypy aktiv).
- Kein Synthetik-Overfit: Branch-Fix nur behalten, wenn er Self-Test verbessert **ohne** die passenden Bänder zu regredieren; echte Tracks sind der finale Gate.
- `git`-Identität, Commit-Stil, Auto-Push: siehe `.claude/rules/commit-and-git.md`. Atomare Commits, `style`-Reformat von Logik trennen (der Format-Hook reformatiert ganze Dateien — separat committen).
- Doku-Sync (`regen_maps.py --check`, CHANGELOG) nach Symbol-/Datei-Änderungen.

---

## 7. SCHNELLSTART für die nächste KI

```bash
# 1. Stack bauen (Abschnitt 2)
# 2. Ist-Stand bestätigen:
source /tmp/v310/bin/activate
python scripts/selftest_analysis.py -n 60 --seed 7 --dur 14   # erwartet Acc-2 100%, KEY 100%
python -m pytest tests/test_anlz_reference_parse.py -q        # beide grün im venv
# 3. Ein Verbesserungsziel aus Abschnitt 5 wählen, ändern, RE-MESSEN, vergleichen, erst dann commit.
# 4. Bei BPM-Heuristik: NICHT ohne echte Tracks (5.3) shippen.
```
