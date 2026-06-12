# Übergabe: Song-Analyse-Engine verbessern

> **Eigenständiges Übergabedokument — zum Weitergeben.** Du brauchst kein Vorwissen über das Projekt; alles Nötige steht hier. Sprache: Deutsch (Code/Commits: Englisch).

---

## 0. Worum es geht

**Music Library Manager** ist ein Desktop-DJ-Tool (Tauri + React + Python-FastAPI-Sidecar), das **Rekordbox/Serato ersetzen** soll: Tracks analysieren (BPM, Tonart/Key, Beatgrid, Phrasen, Waveform), in Rekordbox-Formate schreiben und USB-Sticks exportieren, die Pioneer CDJ-3000 nativ lesen.

**Deine Mission:** Die Genauigkeit der Analyse und die Korrektheit der produzierten Rekordbox-Dateien **weiter verbessern**. Sie ist bereits gut (Zahlen unten) — Ziel ist „so gut, dass man Rekordbox nicht mehr braucht", inkl. der zwei Punkte, die nur am echten Setup des Nutzers testbar sind.

**Eiserne Regel des Auftraggebers (tb): „Teste immer selber!!!"** — Behaupte keine Verbesserung, die du nicht selbst gemessen hast. Jede Änderung muss als Netto-Gewinn belegt sein, sonst zurücknehmen.

- **Repo:** GitHub `SutobeHD/LibraryManagementSystem`
- **Arbeits-Branch (Stand dieser Übergabe):** `claude/song-analysis-rekordbox-27TV8` (noch nicht in `main` gemerged)
- **Relevante Dateien:** `app/analysis_engine.py` (Kern), `app/analysis_settings.py` (Tunables), `app/anlz_writer.py` (Rekordbox-Binärdateien), `app/analysis_db_writer.py` (master.db-Writes), `scripts/selftest_analysis.py` + `scripts/compare_rekordbox.py` (Mess-Tools).

---

## 1. Aktueller Stand — selbst gemessen

Messung mit `scripts/selftest_analysis.py` (synthetische Tracks mit bekannter BPM/Key, deterministisch). Metrik = MIREX-Standard (4 % Toleranz). **Acc-1** = exakte Oktave; **Acc-2** = oktav-tolerant (Half/Double zählt als korrekt, weil das Beatgrid identisch ist — nur das Label ist ×2).

| Metrik | alter Stand (`main`) | **aktueller Branch** |
|---|---|---|
| BPM Acc-1, voller Native-Stack | 61 % | **86 %** |
| BPM Acc-2, voller Native-Stack | 86 % | **100 %** |
| KEY exakt, voller Native-Stack | 78 % | **100 %** |
| BPM Acc-1, reiner Fallback (ohne madmom/essentia) | 61 % | **71 %** |
| KEY exakt, reiner Fallback | 96 % | **100 %** |

> ⚠️ **Wichtig:** Das sind SYNTHETISCHE Tracks. Die Half/Double-Oktav-Mehrdeutigkeit ist darauf **härter** als auf echter Musik — selbst ein trainierter RNN (madmom) erreicht nur ~88 % exakte Oktave. Acc-2 ist die musikalisch ehrliche Zahl. Die echte Real-World-Genauigkeit liefert erst der A/B-Vergleich gegen eine echte Rekordbox-Library (Schritt 4).

---

## 2. Setup — voller Native-Stack (bewährtes Rezept, NICHT improvisieren)

Die CI und übliche Container laufen **Python 3.11** → dort bauen `madmom`/`essentia` **nicht** → es läuft nur der schwächere librosa-Fallback. Für echte Messung **Python 3.10** nehmen und exakt so bauen (die Reihenfolge ist kritisch — madmom 0.16.1 baut nur so):

```bash
uv venv --python /usr/bin/python3.10 /tmp/v310
source /tmp/v310/bin/activate
uv pip install Cython numpy==1.26.4 scipy==1.11.4 setuptools wheel
uv pip install --no-build-isolation madmom==0.16.1
uv pip install "setuptools<80"          # stellt pkg_resources für madmom-Import wieder her
uv pip install librosa==0.10.1 soundfile==0.13.1 essentia==2.1b6.dev1110 \
  fastapi==0.109.0 pydantic==2.5.3 mutagen==1.47.0 httpx==0.26.0 \
  rbox==0.1.7 pyrekordbox==0.1.7 pytest==8.4.2
```

**Verifizieren** (muss `madmom RNN` + `essentia KeyExtractor` zeigen):
```bash
python -c "import sys;sys.path.insert(0,'.');from app import analysis_engine as ae;ae._ensure_libs();print(ae.AnalysisEngine.capabilities())"
```

Zwei verschiedene Pakete (oft verwechselt): **`rbox`** (Rust, liefert `MasterDb`/`Anlz`/`OneLibrary`) ≠ **`pyrekordbox`** (pure-Python, liefert den unabhängigen `AnlzFile`-Parser).

---

## 3. Mess-Werkzeuge

| Tool | Zweck | Aufruf |
|---|---|---|
| `scripts/selftest_analysis.py` | Accuracy gg. synthetische Ground-Truth (Acc-1/Acc-2 + BPM-Band-Aufschlüsselung) | `-n 100 --seed 1` |
| `scripts/compare_rekordbox.py` | **A/B gegen echte Library** (unsere Werte vs. Rekordbox' gespeicherte) | `--db <master.db> -n 10` (nur lokal) |
| `pytest tests/` | Volle Suite (Accuracy-Units, produzierte ANLZ/PDB/exportLibrary, master.db-Schreibwerte) | — |
| `tests/test_anlz_reference_parse.py` | Produziertes ANLZ gegen unabhängigen pyrekordbox-Parser + Byte-Struktur | pytest |

**Automatisierung (claude.ai/code-Routinen, im Repo unter `docs/research/routines/`):**
- `analysis-accuracy-watchdog` (wöchentlich, read-only): baut den Stack, misst gg. Baseline, validiert Dateien, meldet Regressionen in ein GitHub-Issue.
- `analysis-explore` (wöchentlich, docs-only): füllt Analyse-Research-Docs mit echten Before/After-Messungen.
- `analysis-implement` (wöchentlich, Code auf `routine/analysis-*`-Branches): implementiert *genehmigte* Analyse-Tasks **mess-gegated** — verwirft jede Änderung ohne Gewinn / mit Band-Regression.

---

## 4. Was bereits gefixt ist (NICHT nochmal machen)

1. **madmom-RNN war toter Code** auf Python ≥3.10 (Import scheiterte still an entfernten `collections`/`numpy`-Symbolen). Behoben per Kompatibilitäts-Shim in `app/analysis_engine.py`; zusätzlich im PyInstaller-Build (`backend.spec`) gebündelt (inkl. RNN-Modelle).
2. **essentia-Key gab leeres Camelot für 5 Tonarten** (b- statt #-Schreibweise: Eb/Ab/Bb/Db/Gb). Normalisierung `_FLAT_TO_SHARP`. Auch gebündelt.
3. **2× falsche Cue-Konstanten** im ANLZ-Writer (`0x100000`→`0x10000`, fehlendes `u2=1000`) → produzierte Dateien waren nicht spec-konform. Behoben + gegen unabhängigen Parser verifiziert.
4. **`minor_bias` 1.10→1.0**: der Moll-Daumen machte Dur-Dreiklänge zur Mollterz (D-Dur→F#-Moll).
5. **Onset-Density zählte Frames statt Events** → verdoppelte langsame Tracks fälschlich. Jetzt echte Onset-Events.
6. **BPM-Range 180→215** (schnelle DnB/Footwork nicht mehr auf Halftime gefaltet).
7. **PSSI-Phrasen-IDs bank-korrekt** pro Mood.
8. **`rbox==0.1.7` fehlte in requirements.txt** → Clean-Installs hatten keine Live-DB/ANLZ/USB-Funktion. Ergänzt.
9. **16-Takt-Memory-Cue-Grid** als optionales Feature.
10. **Lehre:** Ein Fix (`octave-snap`) wurde wieder **verworfen** (`git revert`), weil er hohe BPM half, aber ~80-BPM-Tracks regredierte — und keine Heuristik die Fälle auf Synthetik sauber trennt. **Lektion: Synthetik-Tuning ohne echte Tracks ist eine Sackgasse.**

---

## 5. Offene Probleme & nächste Schritte (priorisiert)

**5.1 — Half/Double-Oktav-Mehrdeutigkeit (Kernproblem).** ~12 % der Tracks landen auf falscher Oktave (×2/÷2). Aus reiner Periodizität **bewiesen unentscheidbar** (selbst madmom-RNN scheitert auf Synthetik). Echte Musik hat timbrale/melodische Cues, die das lösen. Richtung: Genre-/Spektral-Prior (Bass-Energie, Onset-Muster) als Oktav-Tiebreaker — **nur mit echten Tracks (5.4) verifizieren**, nicht Synthetik.

**5.2 — Synthetischer Test ist als Oktav-Maßstab unfair.** `synth_track` nutzt Dauer-Pad + Kick/Bass auf jeder Zählzeit → künstlich mehrdeutig. Richtung: realistischeres Testmaterial oder ein kleines Korpus echter, frei lizenzierter Tracks mit bekannter BPM/Key.

**5.3 — Weitere Engine-Ideen** (mit Self-Test messen, dann committen): 3-Profil-Key-Ensemble (Shaath), dynamische Tempo-Anker bei Tempodrift, madmom-Downbeat/Segment-Modelle für Phrasen.

**5.4 — Echte-Library-Validierung (NUR beim Nutzer möglich).** `compare_rekordbox.py` über echte Tracks laufen lassen (Rekordbox geschlossen). Erst diese Daten rechtfertigen weiteres BPM-Heuristik-Tuning. **Bitte den Nutzer um die Summary-Ausgabe.**

**5.5 — Live `master.db`-Write (NUR beim Nutzer).** Braucht eine echte, verschlüsselte Rekordbox-`master.db` + Key — im Container nicht erzeugbar. Die Schreibwerte sind unit-getestet, der Schreibmechanismus durch den OneLibrary-Test abgedeckt.

**5.6 — CDJ-3000-Hardware-Load (NUR beim Nutzer).** Byte-Layout ist gegen Referenz-Parser verifiziert; die letzte Meile ist ein echter Stick im echten Gerät.

---

## 6. Harte Regeln

- ⚠️ **Byte-Formate sind heilig** (`app/anlz_writer.py`, `app/usb_pdb.py`): byte-für-byte gegen echte Pioneer-Exporte verifiziert. Jede Konstante/Offset-Änderung gegen die crate-digger-Spec **und** den pyrekordbox-Parser prüfen (`tests/test_anlz_reference_parse.py` im py3.10-venv). Ein falscher Wert korrumpiert USB-Sticks lautlos.
- **Kein Synthetik-Overfit:** Eine Änderung nur behalten, wenn der Self-Test besser wird **ohne** ein Tempo-Band zu verschlechtern; echte Tracks sind der finale Maßstab.
- Atomare Commits; den automatischen Format-Hook beachten (er reformatiert ganze Dateien — Stil-Reformat getrennt vom Logik-Commit halten).
- Repo-interne Detailregeln stehen in `CLAUDE.md` + `.claude/rules/*.md` (Caveman-Stil, Subagenten, Git-Identität).

---

## 7. Schnellstart

```bash
# 1. Branch holen
git fetch origin && git checkout claude/song-analysis-rekordbox-27TV8
# 2. Native-Stack bauen (Abschnitt 2)
# 3. Ist-Stand bestätigen (erwartet Acc-2 100 %, KEY 100 %):
source /tmp/v310/bin/activate
python scripts/selftest_analysis.py -n 60 --seed 7 --dur 14
python -m pytest tests/test_anlz_reference_parse.py -q   # beide grün im venv
# 4. Ein Ziel aus Abschnitt 5 wählen → ändern → RE-MESSEN → vergleichen → erst dann commit.
#    Bei BPM-Heuristik: NICHT ohne echte Tracks (5.4) shippen.
```

**Kurz:** Stack bauen → messen → eine Verbesserung aus §5 angehen → Gewinn beweisen oder verwerfen. Die größten Hebel: das Oktav-Tiebreaker-Problem (§5.1) und die echte-Library-Validierung (§5.4).
