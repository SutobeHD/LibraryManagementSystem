# Routine Deploy-Checkliste — claude.ai/code

> Zum Abhaken beim Einrichten. Quelle der Prompts: `docs/research/routines/<name>.md` (alles **unterhalb** des `---`). Schnell holen: `python scripts/print_routine.py <name>`. Repo überall: `SutobeHD/LibraryManagementSystem`. Timezone überall: **Europe/Berlin**.
>
> **Status-Spalte:** 🆕 neu anlegen · ✏️ geänderter Prompt (neu einfügen) · ⬚ unverändert (nur falls noch nicht deployed; Charter wird beim Start aus README gelesen).

## Alle 12 Routinen

| ✓ | Routine | Cron | Status | Schreibt | Perm-Klasse |
|---|---|---|---|---|---|
| ☐ | `research-draft` | `0 5 * * *` | ⬚ | docs → main | DOCS |
| ☐ | `research-explore` | `0 6,14 * * *` | ⬚ | docs → main | DOCS +Web |
| ☐ | `research-plan` | `0 13 * * *` | ⬚ | docs → main | DOCS |
| ☐ | `research-implement` | `0 3,15 * * *` | ✏️ | code → `routine/*` + PR | CODE |
| ☐ | `research-triage` | `30 7 * * *` | ✏️ | nichts (Issue) | READ+ISSUE |
| ☐ | `research-spawn` | `0 4 * * 0,3` | ✏️ | nichts (Idea Backlog) | READ+ISSUE +Web |
| ☐ | `research-watchdog` | `0 4 1 * *` | ⬚ | Lifecycle-Zeilen + Issue | NARROW+ISSUE +Web |
| ☐ | `research-cross-linker` | `30 4 * * 2` | ⬚ | `related:` + Cross-links | NARROW+ISSUE |
| ☐ | `analysis-accuracy-watchdog` | `30 4 * * 3` | 🆕 | nichts (Issue) | READ+ISSUE +NATIVE |
| ☐ | `analysis-explore` | `0 6 * * 4` | 🆕 | analysis-docs → main | DOCS +NATIVE +Web |
| ☐ | `analysis-implement` | `0 3 * * 5` | 🆕 | code → `routine/analysis-*` + PR | CODE +NATIVE |
| ☐ | `verification-sweep` | `0 5 * * 1,4` | 🆕 | nichts (Verification Sweep Issue) | READ+ISSUE +NATIVE |

**Diese Session zu tun:** 4× 🆕 anlegen + 3× ✏️ neu einfügen = **7 Routinen anfassen**. Der Rest läuft (Charter greift automatisch).

## Permissions je Klasse

- **DOCS** — Datei read/edit · `git add/commit/mv` · `git push origin main` · `git pull --ff-only` · Agent-Tool. **Kein** PR, **kein** merge.
- **CODE** — alles aus DOCS **plus** `git checkout -b` · `git push -u origin routine/*` · `gh pr create` · `gh pr view`. **NIEMALS** `gh pr merge` / `git merge` / `git rebase` / `git push --force` (du testest + mergest lokal).
- **READ+ISSUE** — Datei read · `python` · `gh issue list/view/create/edit/comment`. **Keine** Repo-Writes, kein commit/PR.
- **NARROW+ISSUE** — read · enge `git add/commit/push origin main` (nur die erlaubten Doc-Zeilen) · `gh issue edit/comment`. Keine neuen Dateien, kein `git mv`.
- **+Web** — zusätzlich WebSearch / WebFetch.
- **+NATIVE** — zusätzlich `uv` / `pip install` + `python`/`pytest` ausführen (baut den py3.10-Native-Stack: madmom + essentia + rbox + pyrekordbox). **Budget großzügig** (~25 min, der Stack-Build dominiert).

## Pro Routine (immer gleich)

1. https://claude.ai/code/routines → **New routine** (bzw. bestehende öffnen bei ✏️).
2. Name **exakt** wie in der Tabelle (die Prompts referenzieren ihren eigenen Namen).
3. Cron aus der Tabelle, Timezone **Europe/Berlin**.
4. Repo `SutobeHD/LibraryManagementSystem`.
5. Prompt einfügen: `python scripts/print_routine.py <name>` → alles unterhalb `---`.
6. Permissions gemäß Perm-Klasse setzen.
7. Speichern.

## Kernprinzip (im Charter festgeschrieben)

**Forschen · Erkunden · Verifizieren = automatisch. Umsetzen = nur hinter deinem Approval-Gate.** Nur `research-implement` + `analysis-implement` schreiben Code, nur für von dir genehmigte Tasks, nur auf `routine/*`-Branches, **nie nach `main`** — du testest + mergest selbst.

## Was die neuen/geänderten Routinen bringen

- **`research-spawn`** (✏️): aggressiver Opportunity-Scanner — 7 Scouts inkl. unfertiger/Stub-Code + Test-Lücken, 2×/Woche. → „findet mehr".
- **`verification-sweep`** (🆕): fährt die Suite wirklich + prüft Coverage-Lücken / schwache Tests / Drift / Debt-Trend → `Verification Sweep`-Issue. → „verifiziert mehr".
- **`research-implement`** (✏️): harter Test-Gate — rote Suite blockiert den PR, vacuous Tests = FAIL.
- **`research-triage`** (✏️): macht `Verification Sweep`- + `Analysis Accuracy Watchdog`-Verdikte täglich sichtbar.
- **`analysis-*`** (🆕×3): bauen den Native-Stack und messen Genauigkeit echt — was generische Routinen nicht können.

## Erste Issues, die entstehen werden

`Idea Backlog` · `Verification Sweep` · `Analysis Accuracy Watchdog` · `Pipeline Digest` (von triage). Die ersten beiden Audit-Issues geben dir sofort eine Bestandsaufnahme „was kann noch gemacht werden" + „wo ist's untested".
