---
tags: [bpm, pitch, key, trick, cheatsheet]
aliases: [BPM Key Change, BPM-Sprung, Key-Änderung durch BPM]
---

# BPM-Sprung und Key-Änderung

**Die Kernfrage:** *Ab welchem Tempo-/BPM-Sprung ändert sich der Key — und um wie viel?*

Voraussetzung: **[[Master Tempo (Key Lock)|Key Lock]] ist AUS**. Mit Key Lock an bleibt die Tonart fix, egal wie stark gepitcht wird.

## Die eine Formel

$$\text{Halbtöne} = 12 \times \log_2\!\left(\frac{\text{neue BPM}}{\text{alte BPM}}\right)$$

Umgekehrt für ein bestimmtes Halbton-Ziel:

$$\text{neue BPM} = \text{alte BPM} \times 2^{(\text{Halbtöne}/12)}$$

**1 [[Halbton und Ganzton|Halbton]] = Faktor 2^(1/12) ≈ 1,05946.**

## Wie viel Prozent = 1 Halbton

| Sprung | Faktor | Pitch-Fader |
|---|---|---|
| +1 Halbton | ×1,05946 | **+5,95 %** |
| +2 Halbtöne | ×1,12246 | +12,25 % |
| −1 Halbton | ×0,94387 | **−5,61 %** |
| −2 Halbtöne | ×0,89090 | −10,91 % |

> [!note] Asymmetrie
> Rauf braucht **+5,95 %**, runter nur **−5,61 %** — weil's multiplikativ ist, nicht additiv. Faustregel am Pult trotzdem: **~6 % ≈ 1 Halbton**.

## BPM-Tabelle (Basis 128 BPM)

| Ziel-Key | neue BPM | Δ BPM | [[Camelot Wheel\|Camelot]]-Shift |
|---|---|---|---|
| +3 HT | 152,2 | +24,2 | +21 → +9 |
| +2 HT | 143,7 | +15,7 | +14 → +2 |
| **+1 HT** | **135,6** | **+7,6** | **+7 (−5)** |
| ±0 | 128,0 | 0 | 0 |
| **−1 HT** | **120,8** | **−7,2** | **−7 (+5)** |
| −2 HT | 114,0 | −14,0 | −14 → −2 |
| −3 HT | 107,6 | −20,4 | −21 → −9 |

→ Andere Ausgangs-BPM? **Δ ≈ 6 % der Basis-BPM pro Halbton.** Bei 174 BPM (DnB) sind das ~+10,3 BPM für +1 HT (→ 184,3).

## Ab wann hört man's?

| Pitch | Cents | Hörbarkeit |
|---|---|---|
| ±1 % | ±17 ct | in Melodie-Layern wahrnehmbar |
| ±2 % | ±34 ct | klar hörbar, leicht „daneben" |
| ±3 % | ±51 ct | ~halber Halbton, deutlich verstimmt |
| ±6 % | ±100 ct | voller Halbton, neue Tonart |

> [!tip] Faustregel fürs Pult
> Reine **Drum-Intros/Outros** ([[Akkorde und Harmonien|tonal leer]]) verzeihen **jeden** Pitch — kein Key-Konflikt. **Melodien/Vocals** vertragen je nach Ohr nur **±2–3 %**, bevor's schief klingt. Mehr Tempo-Differenz überbrücken? → [[Master Tempo (Key Lock)|Key Lock]] an **oder** vorher harmonisch passenden Track ([[Key-Mixing-Regeln]]).

## Der Camelot-Trick

+1 Halbton = **+7 Camelot-Positionen** (oder −5). Beispiel: Track in **8A**, +6 % gepitcht → klingt jetzt wie **3A**. So lässt sich ein Track durch Pitchen **in eine andere harmonische Nachbarschaft** schieben → [[Energy Boost Mixing]].

## Siehe auch

- [[Pitch Fader und Tonhöhe]] — das Warum
- [[Semitone-Pitch-Tabelle]] — volle Referenztabelle
- [[Master Tempo (Key Lock)]] — abschalten
- [[Pitch-zu-Semitone Cheatsheet]]
