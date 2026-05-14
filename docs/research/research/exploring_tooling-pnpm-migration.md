---
slug: tooling-pnpm-migration
title: von npm auf pnpm 11.x wechseln
owner: tb
created: 2026-05-14
last_updated: 2026-05-14
tags: [tooling, pnpm, package-manager, ci, security]
related: []
---

# von npm auf pnpm 11.x wechseln

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-14 — `research/idea_` — created from template
- 2026-05-14 — `research/exploring_` — repo-wide npm-touchpoint inventory verified against source; Problem/Constraints/Findings/Options written

---

## Problem

The repo manages JS/Node dependencies with **npm**: three `package.json` files (root orchestrator, `frontend/`, `tests/e2e/`) and **two committed `package-lock.json`** (root + `frontend/`; `tests/e2e/` is gitignored). No workspace model — each package installs independently via `npm --prefix`. We want **pnpm 11.x** for its content-addressed store, strict dependency isolation, and a real workspace model. The migration is not a drop-in: it touches CI, the Tauri build hooks, the `.claude` harness, pre-commit, Dependabot, and the `scripts/security-audit.*` scripts — plus two npm-only security controls. Doing it blind silently breaks the build or the security posture — hence this doc.

## Goals / Non-goals

**Goals**
- Replace npm with pnpm 11.x for all Node packages (root, `frontend/`, `tests/e2e/`).
- Preserve exact dependency pinning + a canonical committed lockfile (Schicht-A).
- Keep CI installs reproducible (frozen lockfile, no resolution drift).
- Decide and document the workspace model (workspace vs. independent installs).
- Update every tooling touchpoint (CI, Tauri build commands, `.claude` hooks/settings/commands, pre-commit, Dependabot, `scripts/security-audit.*`) in lockstep so nothing silently breaks.
- Consciously preserve or replace the npm-specific security controls (`npm audit signatures`, lockfile-lint) — no silent loss.

**Non-goals** (deliberately out of scope)
- Bumping any dependency versions — migration ≠ upgrade; versions stay frozen.
- Changing the Python or Rust toolchains.
- The PyInstaller sidecar build (`backend.spec` / `backend_entry.py`) — verified npm-free.
- Adopting pnpm-only features beyond migration needs (catalogs, etc.) — later, if ever.

## Constraints

> External facts that bound the solution space. Every file:line below was read and verified against source on 2026-05-14.

- **Dependency pinning is a hard repo rule** (Schicht-A — `.claude/rules/coding-rules.md`, `docs/SECURITY.md`). Exact versions, lockfile canonical, reproducible CI installs. pnpm equivalent: `pnpm install --frozen-lockfile`; `save-exact=true` in `.npmrc` is honored by pnpm.
- **lockfile-lint has no `pnpm-lock.yaml` support** (verified 2026-05-14 — `lirantal/lockfile-lint#48` open, not implemented). `.lockfile-lintrc.json` hardcodes `path: frontend/package-lock.json` + `type: npm`. It is invoked from `package.json:13` (`lint:lockfile`), `scripts/security-audit.sh:41`, and `scripts/security-audit.ps1:43`; the `audit` + `full-check` slash commands call it. The control breaks entirely unless replaced.
- **`npm audit signatures` has no pnpm *command* equivalent — but the control is not simply lost.** It is invoked in `scripts/security-audit.sh:33` + `scripts/security-audit.ps1:34` (Schicht-A defense against "maintainer account compromise", `docs/SECURITY.md:84`). pnpm has no `audit signatures` subcommand (`pnpm/pnpm#7909` open), **but** pnpm verifies ECDSA registry signatures automatically *at install time* (npm only does so on-demand) and adds `trustPolicy: no-downgrade`, for which npm has no equivalent. What is genuinely lost is the manual *Sigstore provenance-attestation* check — a trade, not a pure loss. (Related: the repo stages Sigstore *release signing* for "Schicht B" — `release.yml:27-28` carries `id-token` / `attestations` permissions.)
- **The Tauri build pipeline calls npm in two places.** `src-tauri/tauri.conf.json:7-8` (`beforeDevCommand: "npm run dev:full"`, `beforeBuildCommand: "npm run build"`), and hardcoded in `src-tauri/src/main.rs` (Vite dev-server spawn — `L141` Windows `cmd.exe /c npm run dev`, `L145` Unix `npm run dev`). The `main.rs` spawn is `#[cfg(debug_assertions)]`-only — release builds use the PyInstaller sidecar, no npm. The Windows `cmd.exe /c` wrapper stays: pnpm is also a `.cmd` shim on Windows.
- **CI** — `ci.yml`: one Node job (`frontend-lint`); `actions/setup-node@v6` (L99), `cache: npm` + `cache-dependency-path: frontend/package-lock.json` (L102-103), `npm ci --prefix frontend` (L106), `npm run lint/format:check/build` (L109/112/115). `release.yml`: `cache: npm` (L134-135), `npm ci` root (L176) + frontend (L180), `tauri-apps/tauri-action@v0` (L219, auto-detects the package manager from the lockfile present).
- **Dependabot** — `.github/dependabot.yml` has two `package-ecosystem: "npm"` blocks (`/frontend` L13, `/` L37). Dependabot's `"npm"` ecosystem also covers pnpm, so the ecosystem string can stay — but the `directory` entries depend on the chosen workspace model.
- **The `.claude` harness depends on npm.** `settings.json`: npm/npx allow-list L5-14, `npm publish*` deny L115, `npm install --save*` / `--save-dev*` ask L157-158. `hooks/format-on-edit.py`: `npx --no-install prettier` L119, `eslint` L122. `launch.json`: frontend MCP server `command: "npm"` L19. Plus 5 slash commands + 2 agent docs. Until updated, pnpm is not allow-listed → a permission prompt on every command.
- **pre-commit** (`.pre-commit-config.yaml:74,79`) calls `npx --no-install prettier/eslint`. pnpm has no `--no-install`; `pnpm exec` is the local-only equivalent.
- **`scripts/security-audit.{sh,ps1}` + `scripts/local-release.ps1` run npm directly.** The security scripts run `npm audit` ×2, `npm audit signatures`, `npx lockfile-lint`; `local-release.ps1` runs `npm run build` + `npm run tauri build`.
- **`tests/e2e/package-lock.json` is gitignored** (`tests/e2e/.gitignore:2`) — that package has *no* pinning today.
- **No Node version is pinned** — no `.nvmrc` / `.node-version`, no `engines` field; CI hardcodes Node 20. Both `.npmrc` files set `engine-strict=true`, which is currently inert (nothing to enforce).
- **Two `.npmrc` files** (root + `frontend/`, byte-identical 7 keys). pnpm honors `ignore-scripts`, `save-exact`, `prefer-offline`, `engine-strict`, `fund`; it silently ignores the npm-only `audit-level` and `update-notifier`.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. **Workspace model** — `pnpm-workspace.yaml` (lists `frontend` + `tests/e2e`; idiomatic; replaces `npm --prefix` with `pnpm --filter`; one root lockfile; bigger diff) **vs.** three independent `pnpm install` calls (smaller, mechanical diff; three lockfiles)?
2. **`node-linker`** — does the Vite 7 / esbuild / `@vitejs/plugin-react` 4.7 stack build under pnpm's default symlinked `node_modules`, or is `node-linker=hoisted` / `shamefully-hoist=true` needed? Resolvable only by an actual `pnpm install` + `pnpm run build`.
3. **lockfile-lint replacement** — drop the control, or replace it (`pnpm audit`, `pnpm dedupe --check`, pnpm's built-in lockfile integrity)? Affects `.lockfile-lintrc.json`, `package.json:13`, and both `security-audit` scripts.
4. **`npm audit signatures` (Sigstore)** — accept the loss, or wire an external Sigstore verification step? The repo already has `id-token` / `attestations` CI permissions staged for "Schicht B" release signing — could the replacement fold into that effort?
5. **`tests/e2e`** — join the workspace (gains a committed `pnpm-lock.yaml` + pinning, a security *improvement*) or stay loose / gitignored?
6. **Toolchain pinning** — add `packageManager: pnpm@11.x` + `engines.node` to the root `package.json` during the migration (would finally make `engine-strict=true` do something), or keep out of scope?
7. **CI cache ordering** — `cache: pnpm` in `actions/setup-node` requires `pnpm/action-setup` to run first; accept the workflow reordering in both `ci.yml` and `release.yml`?
8. **Guard rail** — add a pre-commit `forbid-package-lock` hook post-migration so a stray `package-lock.json` can't reappear?

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-14 — repo-wide npm-touchpoint inventory (verified against source)

> Every file:line below was read and confirmed. An initial automated inventory missed four files — `.github/dependabot.yml`, `scripts/security-audit.sh`, `scripts/security-audit.ps1`, `scripts/local-release.ps1` — and miscounted the lockfiles (two committed, not three). Both corrected here.

**Packages & lockfiles** — 3 `package.json`: root (`scripts` L6-18; devDeps `@tauri-apps/cli` 2.11.1, `concurrently` 9.2.1; dep `@tauri-apps/api` 2.11.0), `frontend/` (`scripts` L6-14; `vite` 7.3.3, `wavesurfer.js` 7.12.6, `@vitejs/plugin-react` 4.7.0 — **no npm/npx in any script**), `tests/e2e/` (`scripts` L7-10; `mocha` 10.7.3, `selenium-webdriver` 4.25.0 — **no npm/npx in any script**). **2 committed `package-lock.json`** (root, `frontend/`); `tests/e2e/package-lock.json` is gitignored (`tests/e2e/.gitignore:2`) and not currently present on disk. No `engines` / `packageManager` / `workspaces` field anywhere; no `pnpm-lock.yaml` / `pnpm-workspace.yaml`; no `.nvmrc` / `.node-version` / `npm-shrinkwrap.json`.

**Root `package.json` scripts** — cross-package calls use `npm run … --prefix frontend` and `npm … --prefix tests/e2e`; `audit` (L12) runs `npm audit --audit-level=high && npm audit signatures`; `lint:lockfile` (L13) runs `npx --yes lockfile-lint`; `e2e:test` (L15) / `e2e:install` (L16) target `tests/e2e`.

**CI** — `ci.yml`: a single Node job (`frontend-lint`); `actions/setup-node@v6` (L99), `cache: npm` + `cache-dependency-path: frontend/package-lock.json` (L102-103), `npm ci --prefix frontend` (L106), `npm run lint/format:check/build` (L109/112/115). `release.yml`: `cache: npm` (L134-135), `npm ci` root (L176) + frontend (L180), `tauri-apps/tauri-action@v0` (L219). The `build-backend` stage (PyInstaller) is npm-free — only `build-tauri` touches npm.

**Dependabot** — `.github/dependabot.yml`: `package-ecosystem: "npm"` for `/frontend` (L13) and `/` (L37); also `pip`, `cargo`, `github-actions` blocks.

**`.claude` harness** — `settings.json`: npm/npx allow L5-14, `npm publish*` deny L115, `npm install --save*` / `--save-dev*` ask L157-158. `hooks/format-on-edit.py`: `npx --no-install prettier` L119, `npx --no-install eslint` L122. `hooks/auto-push-after-commit.py`: npm-free. `launch.json`: frontend server `command: "npm"` L19. Slash commands: `dev-full` (L9,13), `full-check` (L19,22,23), `audit` (L2,9,10), `tauri-build` (L9), `tauri-dev` (L9). Agent docs: `e2e-tester` (L47-49,52 — 4×), `test-runner` (L54,57,120 — 3×).

**Tauri / Rust** — `tauri.conf.json:7-8` (`beforeDevCommand: "npm run dev:full"`, `beforeBuildCommand: "npm run build"`); `main.rs` Vite spawn, `#[cfg(debug_assertions)]`-only: log L137, Windows `cmd.exe /c npm run dev` L141, Unix `npm run dev` L145. `backend.spec` / `backend_entry.py`: verified npm-free (grep, zero matches).

**Scripts** — `scripts/security-audit.sh`: `npm audit` L17+L25, `npm audit signatures` L33, `npx --yes lockfile-lint` L41. `scripts/security-audit.ps1`: `npm audit` L15+L25, `npm audit signatures` L34, `npx --yes lockfile-lint` L43. `scripts/local-release.ps1`: `npm run build` L48, `npm run tauri build` L53.

**Config** — root `.npmrc` + `frontend/.npmrc` (byte-identical: `ignore-scripts`, `save-exact`, `audit-level`, `fund`, `update-notifier`, `prefer-offline`, `engine-strict`); `.lockfile-lintrc.json` (`path: frontend/package-lock.json`, `type: npm`); `.pre-commit-config.yaml:74,79` (`npx --no-install`).

**Docs** — ~75 `npm` mentions across ~23 files (top: `docs/SECURITY.md`, `CLAUDE.md`, `docs/NAMING_MAP.md` 7, `docs/e2e-testing.md` 6, `.claude/rules/tooling.md`, `docs/FILE_MAP.md` 4). Mostly prose, but `docs/SECURITY.md` and `.claude/rules/{coding-rules,agentic-mode,tooling}.md` encode *normative* npm rules ("NEVER use `npm install`", "`npm ci` in CI") that need rewording, not blind find-replace.

**Blast radius (ranked):**
- *Must change (build / CI / security checks break otherwise):* root `package.json` scripts; both committed `package-lock.json` → `pnpm-lock.yaml`; `ci.yml`; `release.yml`; `.github/dependabot.yml` (`directory` entries); `src-tauri/tauri.conf.json`; `src-tauri/src/main.rs`; `.claude/launch.json`; `.claude/hooks/format-on-edit.py`; `.pre-commit-config.yaml`; `.lockfile-lintrc.json` (references a dead lockfile); `scripts/security-audit.sh`; `scripts/security-audit.ps1`; `scripts/local-release.ps1`.
- *Should change (works but degraded / inconsistent):* `.claude/settings.json` allow-list; both `.npmrc`; `tests/e2e/.gitignore`; new `pnpm-workspace.yaml` (if workspace chosen); 5 slash commands + 2 agent docs.
- *Docs-only:* `CLAUDE.md`, `.claude/rules/*.md`, `docs/SECURITY.md`, `docs/NAMING_MAP.md`, `docs/e2e-testing.md`, `docs/HANDOVER.md`, `docs/architecture.md`, `docs/FILE_MAP.md`, `docs/{frontend,rust}-index.md`, `docs/research/_INDEX.md`, `README.md`, `CHANGELOG.md`.

### 2026-05-14 — Open-Questions analysis

Working through the 8 Open Questions. Two external facts were verified by web research (sources at the end of this entry).

**Q1 (workspace model)** — Recommend **Option A** (`pnpm-workspace.yaml`): one lockfile to lint/cache, shared store, fixes the `--prefix` pattern. Still a user-owned architecture call — recorded as a recommendation, not a decision.

**Q2 (`node-linker`)** — Cannot be closed without a real `pnpm install` + `pnpm run build`. Assessment: Vite 7 / esbuild / `@vitejs/plugin-react` 4.7 generally build under pnpm's default `isolated` linker — esbuild's platform-specific optional deps are handled correctly by pnpm. Plan: try default `isolated` first, fall back to `node-linker=hoisted` only if the build breaks. Risk: low-to-medium; not a blocker for *planning*, but a hard gate before *shipping*.

**Q3 (lockfile-lint replacement)** — **Verified: lockfile-lint has no pnpm support** (`lirantal/lockfile-lint#48`, open). What it currently enforces: every resolved URL comes from the npm registry (no git/local/mirror URLs). pnpm replacements: (a) pnpm verifies ECDSA registry signatures at install time (see Q4) — covers part of the intent; (b) `pnpm install --frozen-lockfile` enforces lockfile/manifest consistency; (c) a small custom check over `pnpm-lock.yaml` `resolution` entries could re-implement the registry-only assertion. Recommend (a)+(b) as the baseline, add (c) only if the explicit registry-only gate is deemed load-bearing.

**Q4 (`npm audit signatures` / Sigstore)** — **Verified, and the picture changed.** pnpm has no `audit signatures` subcommand (`pnpm/pnpm#7909`, open), **but** pnpm verifies ECDSA registry signatures *automatically at install time* (npm only does this on-demand via the command), and adds `trustPolicy: no-downgrade`, for which npm has no equivalent. What is genuinely lost is the manual *Sigstore provenance-attestation* check. Conclusion: this is a **trade, not a pure loss** — arguably a net improvement for the "maintainer account compromise" threat, minus the provenance layer. Recommend: accept the trade; fold a dedicated Sigstore provenance check into the already-planned "Schicht B" work if still wanted.

**Q5 (`tests/e2e`)** — Tied to Q1. If Option A: fold `tests/e2e` into the workspace — it gains a committed `pnpm-lock.yaml`, a pinning *improvement* over today's gitignored state. If Option B: leave it independent.

**Q6 (toolchain pinning)** — Recommend **yes**: add `packageManager: "pnpm@11.x"` + `engines.node` to the root `package.json`. This makes the currently-inert `engine-strict=true` actually enforce something, and `packageManager` gives Corepack-based pnpm version pinning — directly in the spirit of Schicht-A pinning.

**Q7 (CI cache ordering)** — **Answered (factual).** `actions/setup-node` with `cache: pnpm` requires the `pnpm` binary already on PATH to resolve the store path, so `pnpm/action-setup` must run *before* `setup-node`. The reordering in `ci.yml` + `release.yml` is unavoidable but mechanical. No open decision here.

**Q8 (guard rail)** — Recommend **yes**: add a pre-commit `forbid-package-lock` hook, mirroring the existing `forbid-env-files` / `forbid-master-db` hooks (`.pre-commit-config.yaml:84-95`). Cheap, prevents a stray `package-lock.json` regression.

**Net effect on Open Questions:** Q7 closed (factual). Q3 + Q4 factually verified — Q4's framing shifted from "loss" to "trade". Q1, Q6, Q8 have firm recommendations pending user sign-off. Q2 needs an actual build test. Q5 follows from Q1.

Sources:
- [Pnpm support · Issue #48 · lirantal/lockfile-lint](https://github.com/lirantal/lockfile-lint/issues/48)
- [Support pnpm audit signatures · Issue #7909 · pnpm/pnpm](https://github.com/pnpm/pnpm/issues/7909)
- [pnpm audit | pnpm](https://pnpm.io/cli/audit)
- [npm Supply Chain Security in 2026 — Mondoo](https://mondoo.com/blog/npm-supply-chain-security-package-manager-defenses-2026)

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — pnpm + `pnpm-workspace.yaml` (workspace model)
- Sketch: One `pnpm-workspace.yaml` at root listing `frontend` and `tests/e2e`. Root stays the orchestrator; cross-package calls use `pnpm --filter` instead of `npm --prefix`. A single `pnpm-lock.yaml` at root covers all three packages.
- Pros: Idiomatic pnpm; one lockfile to lint/audit/cache; shared store dedups `@tauri-apps/*`; fixes the `--prefix` pattern; `tests/e2e` gains real pinning.
- Cons: Largest diff; changes dependency resolution + `node_modules` topology most aggressively; depends on Q2 (`node-linker`); CI cache strategy changes; Dependabot `directory` entries need rework.
- Effort: M
- Risk: Medium — workspace hoisting could surface a Vite/esbuild build issue.

### Option B — pnpm, three independent installs (no workspace)
- Sketch: Swap `npm` → `pnpm` command-for-command; keep three separate installs (`pnpm -C frontend …`, `pnpm -C tests/e2e …`). Three `pnpm-lock.yaml` files.
- Pros: Smallest, most mechanical diff; per-package isolation unchanged; easy to reason about and to revert.
- Cons: Non-idiomatic pnpm; no cross-package store dedup; still three lockfiles to lint/cache; doesn't fix the `--prefix` pattern.
- Effort: S
- Risk: Low.

### Option C — stay on npm (do-nothing baseline)
- Sketch: No migration.
- Pros: Zero risk, zero work; `npm audit signatures` + lockfile-lint stay intact.
- Cons: Forgoes the store/speed/isolation benefits; the two npm-only controls become accidental lock-in rather than a deliberate choice.
- Effort: —
- Risk: —

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

Leaning **Option A** (workspace) for the cleaner end state. After the 2026-05-14 Open-Questions analysis, the remaining gates before this can move to `evaluated_` / `implement/draftplan_` are narrower:

1. **Q2 (hard gate)** — an actual `pnpm install` + `pnpm run build` of `frontend/` must prove the Vite 7 / esbuild stack builds under pnpm's default `isolated` `node_modules` (or pin down the needed `node-linker` value). This is the one item that cannot be closed on paper.
2. **User sign-off on the recommendations** — Q1 (workspace model), Q6 (toolchain pinning), Q8 (guard-rail hook) have firm recommendations. Q3 / Q4 have a recommended security-control replacement strategy: pnpm's install-time ECDSA verification + `--frozen-lockfile` as the lockfile-lint replacement; accept the `audit signatures` trade and defer Sigstore provenance to "Schicht B". These need an explicit yes/no.
3. Q5 follows mechanically from Q1; Q7 is already resolved (factual — workflow reordering only).

Option B is the fallback if the workspace model causes build friction in step 1.

---

## Implementation Plan

> Required from `implement/draftplan_` onward. Concrete enough that someone else could execute it without re-deriving the design.

### Scope
- **In:** …
- **Out (deliberately):** …

### Step-by-step
1. …
2. …

### Files touched (expected)
- …

### Testing approach
- …

### Risks & rollback
- …

## Review

> Filled by reviewer at `review_`. If any box is unchecked or rework reasons are listed, the doc moves to `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or explicitly deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons** (only if applicable):
- …

## Implementation Log

> Filled during `inprogress_`. What got built, what surprised us, what changed from the plan. Dated entries.

### YYYY-MM-DD
- …

---

## Decision / Outcome

> Required by `archived/*`. Final state of the topic.

**Result**: `implemented` | `superseded` | `abandoned`
**Why**: …
**Rejected alternatives** (one line each):
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_` graduation):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code: <file:line or PR>
- External docs: <url>
- Related research: <slugs>
