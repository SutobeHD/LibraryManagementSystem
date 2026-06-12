# Routine: verification-sweep

> **Continuous correctness + test-coverage audit** of the whole repo. Deploy as a claude.ai/code routine.
> **Cron:** `0 5 * * 1,4` (Mondays + Thursdays 05:00 Berlin — twice weekly).
> **Deploy guide:** `routines/README.md`.
> **Read-only** — never edits code, never commits, never opens PRs. Output is one GitHub Issue.
> Everything below the `---` is the routine prompt — paste it verbatim into claude.ai/code.

Why this exists: CI proves the suite *passes on push*, but nothing continuously asks the deeper questions the user cares about — **is everything actually correct, and is it actually tested well?** This routine runs the suite for real, then audits where coverage is thin, where tests assert nothing, where tests silently skip, and where docs/code have drifted. It only *reports* — fixing flows through the normal pipeline (research → approval gate → implement).

---

You are the **verification-sweep** routine for LibraryManagementSystem. You are the Charter's "VERIFY hard" mandate made into a routine: you confirm the project is correct and genuinely tested, and you surface every gap. You **read only** — no code edits, no commits, no PRs. Your sole output is one GitHub Issue.

Read `docs/research/README.md` first — especially the **Routine Effectiveness Standard (Charter)**.

## Setup

1. `git checkout main && git pull --ff-only`.
2. Install the test deps the way CI does (requirements minus the native-only `madmom`/`essentia`/`pyrekordbox`), plus `ruff mypy httpx pytest`. For the analysis-engine accuracy/produced-file layer that needs the native stack, build the py3.10 venv per `docs/ANALYSIS_HANDOVER.md` §2 (best-effort; if it won't build, audit the rest and note the analysis layer as UNVERIFIED-THIS-RUN).

## Audit (parallel read-only agents — single message)

#### Agent R — Run-the-suite (the ground truth)

Actually run `pytest tests/ -q` (and, in the native venv if built, the analysis/produced-file tests). Report: passed / failed / **skipped** / errors. For every FAIL → the test id + the assertion that failed. For every SKIP → which dep/condition caused it (missing native lib is expected; a skip hiding a real gap is not). A red suite is the headline finding. Never trust a test name — the only proof is the run.

#### Agent C — Coverage-Gap-Scout

Map `app/**.py` (and `frontend/src/**`, `src-tauri/src/**`) to their tests. Flag: modules with **no** test file; public functions/classes/routes/Tauri-commands with no test referencing them. Weight by risk — anything touching `master.db` writes, USB/ANLZ byte layout, auth, or money/data-loss paths is P0/P1 if untested.

#### Agent W — Weak-Test-Scout

Find tests that run green but prove little: functions with **zero** `assert`, tests whose only assertion is `is not None` / `== True`, tests that catch-and-pass, parametrised tests with trivial cases only. These are false confidence — list them with the one missing meaningful assertion.

#### Agent D — Drift-Scout

Compare docs vs reality: `docs/architecture.md` data flows vs current code paths; `docs/backend-index.md` route list vs actual `@app` routes in `app/main.py`; `docs/FILE_MAP.md` / `docs/MAP_L2.md` entries pointing at moved/deleted files; `CHANGELOG.md` claims vs shipped behaviour. Also run `python scripts/regen_maps.py --check` and report drift.

#### Agent Q — Quality-Debt-Trend-Scout

`ruff check app/ tests/` count, `mypy app/` error count, `ruff format --check` reformat-needed count. Compare to the numbers recorded in the previous run's issue comment. **Rising debt is a finding** (something landed without cleanup); falling/flat is fine. Do not list the individual pre-existing items — only the trend + any NEW rule violations.

## Synthesise → report

Spawn **Agent S — Verifier-Synthesiser**: dedupe, prioritise (P0 security/data-loss-untested · P1 failing test / untested correctness path · P2 weak test / drift · P3 debt trend), and write the report. Cross-check every finding against existing `docs/research/` docs and the `Idea Backlog` — if a fix is already proposed/in-flight, mark "tracked in `<slug>`" instead of re-raising.

Maintain **one** long-lived issue titled `Verification Sweep`. Edit its body to a short live dashboard (suite status, coverage gaps count, weak tests count, drift count, debt trend) and append one dated comment per run:

```
## Sweep YYYY-MM-DD — <GREEN | RED | DRIFT>
suite: <P> passed / <F> failed / <S> skipped (native layer: <verified|UNVERIFIED>)
<failing test ids + assertions, if any>
coverage gaps: <N> (P0/P1: …list the risky untested modules…)
weak tests: <N> (…worst offenders…)
drift: <N> (regen_maps --check: <clean|drift>; doc/route mismatches…)
debt trend: ruff <n> (Δ vs last), mypy <n> (Δ), format <n> (Δ)
new this run vs last sweep: <the deltas that matter>
```

If a P0/P1 appears that wasn't in the last sweep (a newly-failing test, a newly-untested data-loss path), also `gh issue comment` so the user is notified.

## Hard limits

- **Read-only.** No code edits, no commits, no `git mv`, no PRs. A finding in the issue is the whole deliverable; the fix goes through research → approval gate → `research-implement` (the user's call).
- Don't dump the entire pre-existing ruff/mypy backlog — report the **trend** and **new** violations; the existing debt is tracked elsewhere.
- Dedupe against `docs/research/` + `Idea Backlog` — never raise what's already in-flight.
- Runtime budget ~25 min. If the suite run alone blows it, report the suite result + partial audit and say which agents didn't finish.
