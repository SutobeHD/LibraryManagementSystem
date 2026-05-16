---
slug: security-pydantic-extra-allow-blob-write
title: Pydantic SetReq extra:allow as unauth blob-write primitive
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [security, follow-up, auth-audit-adjacent]
related: [security-api-auth-hardening]
---

# Pydantic SetReq extra:allow as unauth blob-write primitive

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded from auth-audit adjacent findings
- 2026-05-15 — `research/idea_` — section fill from thin scaffold
- 2026-05-15 — `research/idea_` — rework pass (quality-bar review pre-`exploring_`)
- 2026-05-15 — research/exploring_ — promoted; quality-bar met (concrete caps 8KB/64/256/256KB; decoupled-from-Phase-1; agent caught + superseded own token-leak overclaim)
- 2026-05-15 — research/exploring_ — perfect-quality rework loop (deep self-review pass)

---

## Problem

`app/main.py:319`: `class SetReq(BaseModel): model_config = {"extra": "allow"}` for settings POST. Currently pre-auth → arbitrary key dump into `settings.json` by anyone. After Phase-1 auth lands: caller authenticated, but schema still unconstrained — buggy / compromised / LLM-injected client can dump unbounded payloads. Stored-blob write primitive persists across restarts. Need declared-field allowlist + per-value size cap + per-key type validation. Cost of inaction: settings.json grows unbounded → disk-fill + UI hang via `GET /api/settings` echoing huge JSON on every mount. Stored-XSS surface today is zero (verified — see Findings 2026-05-15 supersede); threat is integrity + DoS + namespace-pollution.

## Goals / Non-goals

**Goals**
- Constrain `POST /api/settings` declared fields to safe types + value ranges; constrain unknown extras with size/count caps (not key-name allowlist).
- Cap total payload size + per-value size + per-dict-key-count + per-list-length so a single POST cannot bloat `settings.json` unbounded.
- Preserve forward-compat for legitimate future setting additions without backend redeploy (extras still flow through under caps).
- Surface schema violations clearly to frontend (`422` with field path + reason, not a 500).
- Keep load-path tolerant: an old `settings.json` with now-rejected values must not brick startup; only Save round-trips re-validate.

**Non-goals**
- Redesign the entire settings system (no schema-versioning migration framework).
- Move shortcut-binding storage out of `settings.json` (separate concern).
- Centralise all frontend setting writes through a single facade (refactor scope creep).

## Constraints

External facts bounding solution. Re-verified 2026-05-15.

- `SetReq` at `app/main.py:319-339` declares `model_config = {"extra": "allow"}` (L323) deliberately — comment L320-322 explains frontend writes arbitrary preference keys (shortcuts, waveform colors, scan_folders).
- POST handler `save_s` at `app/main.py:1874-1892` merges `s.model_dump()` (L1877) + `getattr(s, "model_extra", None) or {}` (L1878-1879) then calls `SettingsManager.save(payload)` (L1880). Zero key filtering, zero size cap, zero auth.
- Persistence path: `SettingsManager.save` at `app/services.py:671-692` writes `Path("settings.json")` atomically (`tmp` + `os.replace`); no input validation, no length check. `load` at `app/services.py:660-669` merges file over `DEFAULT` dict (L664), swallows `OSError` / `JSONDecodeError` → falls back to `DEFAULT` silently with `logger.warning` only (L665-668).
- Frontend writes 6 keys NOT in `SetReq` (allowed only via `extra: "allow"`): `shortcuts` (object, `frontend/src/components/settings/SettingsShortcuts.jsx:47`; 14 actions defined L9-24), `waveform_color_low/mid/high` (hex strings, `SettingsAppearance.jsx:31-33`), `locale` (`SettingsAppearance.jsx:65`). Plus 3 declared in `services.py:DEFAULT` (L655-657) but absent from `SetReq`: `sc_sync_folder_id`, `sc_download_format`, `legacy_pdb_stub`.
- `POST /api/settings` at `app/main.py:1874` has NO auth gate today — `require_session` does not exist anywhere in `app/main.py` (verified: `Grep require_session|X-Session-Token` returns 0 matches). Phase-1 auth-hardening (`docs/research/implement/draftplan_security-api-auth-hardening.md`) introduces it.
- Wholesale strict-allowlist would 422 the live frontend the moment it adds a new key before backend re-ship.
- `SettingsManager` has NO size-guarding today — `Grep len\\(` near settings ops finds 0 hits in `app/services.py` settings region (matches are all in XML / FFmpeg / waveform code, not in `SettingsManager`).
- No rate limit on POST. No `MAX_BODY_SIZE` middleware in `app/main.py` (`Grep MAX_BODY_SIZE|max_request_size|content_length|body_size` in `app/` returns 0 matches). FastAPI/Starlette default request body limit is effectively unbounded for JSON in this app.
- Pydantic version: `requirements.txt:16` pins `pydantic==2.5.3` → `model_validator(mode="after")` API available (added Pydantic v2.0). Spec: `@model_validator(mode="after")` decorates a method on the model that takes `self` and returns `self` (or raises). Runs after field validation + extras parsing, so `self.model_extra` is populated and inspectable.
- `soundcloud_auth_token` is vestigial in `SetReq`. Real token stored in OS keyring via `set_soundcloud_auth_token` (`app/main.py:3048-3084`, `keyring.set_password` L3076); SC API calls read from `keyring.get_password` (verified L2812, 2885, 3141, 3201, 3232, 3278, 3322, 3366). `settings.json` value only echoed back via `GET /api/settings` and read by `SoundCloudView.jsx:23-24` for legacy UI display. Overwriting cannot redirect SC API auth.

## Open Questions

Numbered. RESOLVED inline, PARKED with reason, or deferred to `draftplan_`.

1. **Strict whitelist vs extended deny-list?** RESOLVED — neither pure. Option B = typed-known allowlist (15 declared `SetReq` fields stay strict) + capped-extras passthrough (everything else size-bounded, no key-name blocklist). Pure deny-list rejected: new attack key bypasses until blocklist updated.
2. **Per-value byte cap.** RESOLVED — 8 KB serialized per value. Largest realistic value today is `shortcuts` dict (14 actions × ~12-char combo + JSON overhead ≈ 400 bytes); 8 KB = 20× headroom. A 16 KB color-palette blob would force a constant bump — acceptable explicit trigger.
3. **Total payload byte cap.** RESOLVED — 256 KB on the POST body (re-serialized at validator time). Measured baseline = 619 bytes (sample populated `settings.json`); 256 KB = ~423× headroom. Stops megabyte DoS; legitimate growth has 2+ orders of magnitude before brushing the cap.
4. **Recursive nested-dict validation.** RESOLVED — yes, one level of nesting is enough today (`shortcuts.{action}: str` = the deepest legitimate case). Walker checks: dict key count ≤ 64, key length ≤ 64 chars, leaf-value serialized size ≤ 8 KB. Depth counter starts at 1 for the top-level dict, increments on entering an inner dict; depth > 2 rejected (no current legitimate consumer of `outer.inner.deeper`).
5. **Load-path migration for now-rejected stored keys.** RESOLVED — DO NOT change `SettingsManager.load`. It stays raw `json.load` + DEFAULT merge (`app/services.py:660-669`); no Pydantic validation on load. Rationale: enforcement happens at write boundary (POST validator); legacy `settings.json` keeps working in-place until user explicitly Saves, at which point frontend re-POSTs the now-validated subset. No "strip-silent-on-load" code (avoids hidden mutation); no "fail-loud" (would brick legacy installs).
6. **422 with per-field reasons vs generic 400.** RESOLVED — 422 with field path + reason. Information disclosure cost negligible: this is a local desktop sidecar, not an internet service; frontend needs the field path to surface "Setting X invalid" to the user. Body content NEVER echoed in error (avoids reflecting attacker payload).
7. **Type-coerce vs strict-mode.** RESOLVED — strict mode on the 15 typed fields via `model_config = {"extra": "allow", "strict": True}`. Stops `"true"` → `True` boolean spoofing. Frontend already sends correct types via axios JSON serialization, so zero break risk.
8. **List-entry cap for `scan_folders`.** RESOLVED — 256 entries max, 1024 chars per path. Power-user scan_folders is 5-20 paths today; 256 = ~12× headroom. Path-length 1024 covers Windows MAX_PATH workarounds (`\\?\` prefix expands to ~32 K but no DJ-library legitimately uses that).
9. **Combine ship with `require_session` auth gate?** RESOLVED — decoupled. Auth-hardening already in `implement/draftplan_security-api-auth-hardening.md`; this work lands separately on top of it (additive). Sequencing: auth lands first preferred, but neither blocks the other — payload-shape hardening is valuable even without auth (catches frontend bugs, LLM-injection bloating settings.json from compromised app context).
10. **Audit-log content + level for rejected payloads.** RESOLVED — `logger.warning("[settings] POST rejected: keys=%d bytes=%d offending=%s reason=%s")`. WARNING level (input-validation rejections are security-relevant per industry convention). Log `keys_total`, `offending_key` (name only), `reason`, `payload_bytes`. NEVER log values. NEVER log full body. Matches the existing `[SC] /api/soundcloud/auth-token rejected: <reason>` pattern at `app/main.py:3071-3072` (also WARNING).
11. **PARKED — final cap numbers signed off by user?** 8 KB / 64 dict-keys / 256 list-entries / 256 KB total are defensible from measured 619-byte baseline + 14-shortcut max, but user may want different headroom (e.g. tighten 256 KB → 64 KB if "no legitimate user ever needs 64 KB"). Decision needed at `draftplan_` sign-off; default-values in code are easy to change pre-release. Parked because: requires product-owner judgment, not engineering data.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- **Declared `SetReq` fields** (`app/main.py:325-339`): `default_export_format`, `default_export_dir`, `theme`, `auto_snap`, `db_path`, `artist_view_threshold`, `waveform_visual_mode`, `hide_streaming`, `remember_lib_mode`, `last_lib_mode`, `ranking_filter_mode`, `insights_playcount_threshold`, `insights_bitrate_threshold`, `soundcloud_auth_token`, `scan_folders` — 15 typed fields.
- **Frontend-only / extras (allowed by `extra: "allow"`):** `shortcuts: {action → combo}` (DAW key bindings, `SettingsShortcuts.jsx:47`), `waveform_color_low/mid/high` (hex strings, `SettingsAppearance.jsx:31-33`), `locale` (`SettingsAppearance.jsx:65`), `sc_sync_folder_id`, `sc_download_format`, `legacy_pdb_stub` (declared in `services.py:DEFAULT` 655-657 but NOT in `SetReq`). Net: 6 named unanticipated keys; an unauth client can add unlimited more.
- **Risk after Phase-1 auth lands:** unauth blob-write closed; remaining threat = authed-bug, LLM-injection, or compromised desktop process bloating `settings.json`. Severity ↓ from critical → moderate, urgency ↓ but not zero.
- **Pre-auth concrete blob attack today:** `curl -X POST http://127.0.0.1:8000/api/settings -d '{"x": "<100MB garbage>"}'` → `SettingsManager.save` writes 100 MB JSON → next startup `SettingsManager.load` returns `{**DEFAULT, **<huge>}` (no streaming) + `GET /api/settings` serializes it on every UI mount → 100 MB allocation + multi-second hang per request. Persists across restarts; recovery requires manual `settings.json` delete.
- **Stored-XSS-on-read amplifier:** values are echoed back verbatim by GET `/api/settings`; any frontend that renders a setting without escaping (e.g. `waveform_visual_mode` injected into a `<style>` block) becomes an XSS sink. React's JSX auto-escapes textContent, so the realistic sink is anything passed to `dangerouslySetInnerHTML`, inline `style={}` strings, or `<style>` blocks driven by setting values.

### 2026-05-15 — supersede: token-leak amplifier was wrong
- Earlier claim that overwriting `soundcloud_auth_token` via `SetReq` "swaps the user's auth identity silently" is INCORRECT. Verified: real token is stored in OS keyring via `set_soundcloud_auth_token` (`app/main.py:3049-3084`); every SC API call reads from `keyring.get_password(KEYRING_SERVICE, KEYRING_SC_TOKEN)` (verified at lines 2812, 2885, 3141, 3201, 3232, 3278, 3322, 3366). The `settings.json` field is vestigial; only consumer is `SoundCloudView.jsx:23-24` for legacy UI display. Overwriting it spoofs the displayed value but cannot redirect SC API calls. Removing the field from `SetReq` + `DEFAULT` is a separate cleanup, not a token-security gate.

### 2026-05-15 — supersede: stored-XSS sink claim too broad
- Prior finding implied `waveform_color_*` injected into `<style>` is an XSS sink. Re-verified: app uses `style={{ background: settings.waveform_color_X || '#default' }}` at `SettingsAppearance.jsx:51-53` (React inline-style object, NOT `<style>` block, NOT `dangerouslySetInnerHTML`). React inline-style values pass through `CSSPropertyOperations` which serializes the JS object back to CSS — does NOT execute string-as-CSS, does NOT enable `expression()` / `url(javascript:)` injection in modern React. `Grep dangerouslySetInnerHTML` in `frontend/src` returns 0 matches. Stored-XSS surface today is effectively zero. Hardening is still warranted on integrity + DoS grounds, not XSS.

### 2026-05-15 — measured baseline + cap derivation
- **Measured `settings.json` size on populated worktree:** 619 bytes (`.claude/worktrees/gallant-lumiere-cff8ae/settings.json`, 20 keys, scan_folders empty, shortcuts empty). Real-world populated install with 14 shortcuts + 10 scan_folders + 3 hex colors ≈ 2.5 KB upper estimate.
- **Cap derivation:** total 256 KB = 423× measured baseline, 100× projected populated. Per-value 8 KB = ~20× largest realistic value (shortcuts dict ~400 B serialized for 14 actions). Dict-keys 64 = 4.5× current 14. List-entries 256 = ~12× power-user 20 scan_folders. Path 1024 chars covers Windows MAX_PATH (260) plus `\\?\` UNC prefix (~32 K rejected — no legit DJ usage).
- **Pydantic v2.5.3 model_validator spec:** `@model_validator(mode="after")` decorates instance method `def _check(self) -> "SetReq"`. Runs AFTER field validation; `self.model_extra` populated dict of extras. Raise `ValueError` → 422 with field path. Available since v2.0 — confirmed v2.5.3 from `requirements.txt:16`.

## Options Considered

Required by `evaluated_`. Comparison table first, then per-option detail.

| Option | Behavior diff | Effort (hrs) | Maintenance debt | Concrete failure mode |
|---|---|---|---|---|
| A — Strict whitelist | 422 on any key not declared in `SetReq` | M (~6-8) | High — every frontend pref add needs backend PR | Frontend adds `waveform_opacity`, ships, user Save → 422, settings unsaveable until backend redeploy |
| B — Hybrid (typed+capped-extras) | 422 only on cap-violation; unknowns flow through | S-M (~3-5) | Low — caps stable, no per-key tracking | 16+ KB legitimate value (future color palette) hits per-value cap, requires constant bump |
| C — Schema versioning + `_extras` envelope | New unknowns must be written under `_extras.foo`; old POSTs work via shim | L (~12-16) | Medium — explicit migration hook per version | Frontend forgets `_extras.` prefix, key silently lost on save (developer-side trap, not user-side) |
| D — Total-byte-cap only (minimum) | 413 on body > N bytes; no per-key, no type tightening | S (~1-2) | Very low | Per-value `theme = "<5 KB garbage>"` still accepted; doesn't address type-confusion vector |

### Option A — Strict whitelist
- Sketch: Flip `extra: "allow"` → `extra: "forbid"`. Declare every legitimate key in `SetReq` (known 15 + currently-untyped 6: `shortcuts`, `waveform_color_low/mid/high`, `locale`, `sc_sync_folder_id`, `sc_download_format`, `legacy_pdb_stub`). Tight per-field types + bounded length/regex.
- Pros: smallest attack surface; schema is the contract; rejected unknowns are loud + traceable.
- Cons: every new frontend setting requires backend update + redeploy; load-path also needs strip-or-422 logic for legacy keys; couples frontend-backend release cadence.
- Risk: high regression surface — first frontend feature adding a new key without backend coordination breaks Save UX.

### Option B — Hybrid (typed-known + size-capped-extras) — RECOMMENDED
- Sketch: Keep `extra: "allow"`. Add `model_validator(mode="after")` on `SetReq` enforcing: per-value ≤ 8 KB serialized, per-dict ≤ 64 keys (key length ≤ 64 chars), list ≤ 256 entries (path ≤ 1024 chars for `scan_folders`), total serialized payload ≤ 256 KB. Add `"strict": True` to stop type-coercion on declared fields. Tighten declared-field types: `theme: Literal["dark","light"]`, `waveform_visual_mode: Literal["blue","3band","custom"]`, `waveform_color_*: constr(pattern=r"^#[0-9a-fA-F]{6}$")` (added as declared `Optional[str]` fields, not extras), non-negative `int` thresholds via `conint(ge=0)`.
- Pros: keeps forward-compat the frontend already relies on; closes blob-write quantitatively; one validator + one constants block; load-path untouched (silent-strip on next save round-trip).
- Cons: doesn't catch typo-keys (`wavefrom_color_low` persists); re-serializing payload at validation time = small perf hit (negligible at < 10 KB typical).
- Risk: low — caps are pure additions; the one foreseeable break is a future legitimate value > 8 KB needing a constant bump (visible failure with clear error).

### Option C — Schema-versioning + frontend-managed-extension
- Sketch: Add `schema_version: int` field; route unknown keys into a single `_extras: dict[str, Any]` blob with the same per-value + total caps as Option B. Frontend writes through `_extras` for experimental prefs until promoted to typed field. Backend gains explicit migration hook per version bump.
- Pros: clean separation known-vs-experimental; future-proof for real migrations; explicit audit trail of unknown keys; supports gradual promotion.
- Cons: requires coordinated frontend refactor (every existing extra-write site changes); more files touched; over-engineered for the present threat; doesn't ship faster than B.
- Risk: scope creep — solves a problem not yet faced at the cost of delaying the one currently exposed.

### Option D — Total-byte-cap only (minimum-viable)
- Sketch: Single Starlette middleware checks `Content-Length` header for `POST /api/settings`, rejects 413 if > 256 KB. No Pydantic changes, no per-key caps, no type tightening.
- Pros: tiny patch (~10 LOC); closes the megabyte-DoS vector immediately; zero risk to existing flows.
- Cons: doesn't constrain individual key values; doesn't fix type-coercion (`"true"` → `True`); doesn't reject lists of 1 million tiny strings; misses the namespace-pollution vector (attacker creates 100 K distinct 1-byte keys).
- Risk: very low — pure additive — but leaves most of the vulnerability surface uncovered, so likely a stepping-stone, not a destination.

## Recommendation

**Option B (Hybrid).** Single `model_validator(mode="after")` on `SetReq`, six module-level cap constants, `Literal` + bounded-string tightening on declared fields, `strict: True` to stop coercion. Decoupled from auth-hardening (additive).

Validator shape (prose pseudocode, NOT real code):

1. Define `MAX_VALUE_BYTES = 8 * 1024`, `MAX_DICT_KEYS = 64`, `MAX_KEY_LEN = 64`, `MAX_LIST_ITEMS = 256`, `MAX_PATH_LEN = 1024`, `MAX_TOTAL_BYTES = 256 * 1024`.
2. Inside `@model_validator(mode="after") def _enforce_caps(self) -> "SetReq":` — first call `json.dumps(self.model_dump(), separators=(",",":"))` and assert total length ≤ `MAX_TOTAL_BYTES`, else `raise ValueError("payload exceeds 256 KB")`.
3. Walk `self.model_extra or {}`: reject if dict has > `MAX_DICT_KEYS`; per key, reject if `len(key) > MAX_KEY_LEN`; per value, dispatch on type — dict ≤ `MAX_DICT_KEYS` keys (max nesting depth = 2: top-level extras dict + one inner dict like `shortcuts.{action}`), list ≤ `MAX_LIST_ITEMS`, leaf serialized ≤ `MAX_VALUE_BYTES`.
4. Walk declared list/path fields (`scan_folders`, declared `shortcuts` dict): reject if len > `MAX_LIST_ITEMS` / `MAX_DICT_KEYS` or any entry > `MAX_PATH_LEN` / `MAX_VALUE_BYTES`. (Declared-field-level constraints like `Field(max_length=...)` catch the simple cases; validator handles the cross-cutting "value-too-big-when-serialized" check that field-level can't express.)
5. On rejection, raise `ValueError(f"key={offending_key} reason={reason}")` — Pydantic turns this into 422 with field path; handler at `app/main.py:1874` returns the structured error to frontend; add `logger.warning("[settings] POST rejected: keys=%d bytes=%d offending=%s reason=%s")` from the validator before the raise (so the line fires whether or not the exception handler bubbles up cleanly).

**Gates before `draftplan_`:** Q11 (user signs off on cap numbers — engineering data supports defaults, product owner picks final). All other Open Questions RESOLVED above.

**Sequencing:** auth-hardening lands first (preferred — closes the unauth window). This work lands on top, additive. Either order works — payload-shape hardening is valuable even pre-auth (catches frontend bugs, LLM-injection, compromised-app-context bloat).

---

## Implementation Plan

Seeded at `exploring_`. Refine at `draftplan_`.

### Scope
- **In:** `SetReq` validator + caps constants; tighten declared-field types (`Literal`, `Annotated[str, StringConstraints(...)]`, `Field(ge=0)`); promote 6 extras to declared (Step 3); add extras recursive walker; structured 422 error path; one-line `logger.warning` audit log on rejection; pytest coverage for each cap boundary in `tests/test_services.py`; back-compat smoke test using sample populated `settings.json`.
- **Out:** auth gating (`require_session` — separate Phase-1 ship); removing vestigial `soundcloud_auth_token` from `SetReq` (separate cleanup, see Constraints L57); schema-versioning framework (Option C, deferred); body-size middleware (declared-field caps + validator catch the threat; middleware is belt-and-suspenders that can land later if a true bypass surfaces); frontend `saveSettings` error-handling improvements (separate UX work — see Risk 2 mitigation A).

### Step-by-step
1. Add module-level constants in `app/main.py` near `SetReq` (L319) — `MAX_VALUE_BYTES`, `MAX_DICT_KEYS`, `MAX_KEY_LEN`, `MAX_LIST_ITEMS`, `MAX_PATH_LEN`, `MAX_TOTAL_BYTES`.
2. Tighten existing 15 `SetReq` declared fields (the ones already in `app/main.py:325-339`). Verified-from-source: `waveform_visual_mode: Literal["blue","3band","custom"]` (`SettingsAppearance.jsx:24-26`), `ranking_filter_mode: Literal["all","unrated","untagged"]` (comment `app/services.py:648`). Audit-needed-pre-merge (do NOT guess Literals; if exhaustive value set unclear, leave as `str` + length cap): `theme` (verify "dark"/"light" exhaustive), `last_lib_mode` ("xml"/"db" likely from `main.jsx:406-411` branching but confirm in callers), `default_export_format` (no frontend reference; trace producers in `app/services.py` export pipeline). Booleans (`auto_snap`, `hide_streaming`, `remember_lib_mode`) get `bool` (no change). `artist_view_threshold`, `insights_playcount_threshold`, `insights_bitrate_threshold`: `int = Field(ge=0)`. Strings without enum (`default_export_dir`, `db_path`, `soundcloud_auth_token`): `Annotated[str, StringConstraints(max_length=MAX_PATH_LEN)]`. `scan_folders: list[Annotated[str, StringConstraints(max_length=MAX_PATH_LEN)]] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)`. Add `"strict": True` to `model_config`.
3. Promote 6 currently-extra-only keys to declared optional fields (so they get typed + cap-checked instead of relying on the extras walker): `shortcuts: Optional[dict[str, str]]` (with bounded key + value lengths via `Annotated`); `waveform_color_low/mid/high: Optional[Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]]`; `locale: Optional[Literal["de","en"]]` (per `SettingsAppearance.jsx:60-61`); `sc_sync_folder_id: Optional[str]`; `sc_download_format: Optional[Literal["auto","aiff"]]` (documented at `services.py:656`); `legacy_pdb_stub: Optional[bool]`. After promotion, declared catalog = 21 keys (15 original + 6 promoted). `extra: "allow"` STAYS — rationale: final safety net for unanticipated keys the frontend may add mid-cycle; caps validator constrains them. Flipping to `extra: "forbid"` is an explicit follow-up decision, not part of this ship.
4. Add `@model_validator(mode="after")` `_enforce_caps` method per Recommendation prose. Reuse a single `_walk(value, depth)` helper for dict/list traversal; cap recursion `depth ≤ 2` (defensive).
5. `save_s` handler (`app/main.py:1874-1892`) needs NO change — FastAPI's automatic `RequestValidationError` → 422 path covers the response. The `logger.warning` line lives inside `_enforce_caps` itself, fired immediately before `raise ValueError`, so it logs regardless of how the framework formats the response.
6. Add tests in `tests/test_services.py` (extend existing `SettingsManager` test class or add `class TestSetReqValidation`): happy path (sample populated `settings.json` from repo at `.claude/worktrees/gallant-lumiere-cff8ae/settings.json` — 619 bytes, 20 keys — POSTs 200); each cap boundary (just-under accepts, just-over 422s) for `MAX_VALUE_BYTES` / `MAX_DICT_KEYS` / `MAX_KEY_LEN` / `MAX_LIST_ITEMS` / `MAX_PATH_LEN` / `MAX_TOTAL_BYTES`; type-strict rejection (`{"auto_snap": "true"}` → 422 under `strict: True`); nested dict overflow (`{"shortcuts": {"x": "<9 KB>"}}` → 422); recursion depth > 2 (`{"a":{"b":{"c":"x"}}}` → 422); back-compat (load existing `settings.json` with extras → `SettingsManager.load` returns dict without raising).
7. Update `docs/backend-index.md` row for `POST /api/settings` (add note: "size-capped, strict types").
8. Re-measure typical `settings.json` after manual smoke (start dev, save various settings, check file size) — confirm < 5 KB in realistic use.

### Files touched
- `app/main.py` (caps constants, `SetReq` tightening, validator method, handler logging) — ~80-120 LOC net.
- `tests/test_services.py` (extend with `TestSetReqValidation` class) — ~150 LOC net.
- `docs/backend-index.md` (annotate `POST /api/settings` row: "strict types, size caps").
- `CHANGELOG.md` (`Security` section entry on next release cut).

### Testing
- `pytest tests/test_services.py -v -k Settings` — boundary coverage per cap (test class extension per Step 6).
- `pytest tests/` — full suite green (ensures no regression on settings consumers like `folder_watcher.reconcile` at `app/main.py:1885-1890`).
- Manual: start `npm run dev:full`, exercise every settings tab (Appearance, Shortcuts, Folders, SoundCloud, Insights), confirm Save round-trips without 422.
- Manual blob-attack repro: `curl -X POST http://127.0.0.1:8000/api/settings -H "Content-Type: application/json" -d '{"x":"<300 KB string>"}'` → expect 422 (was: silent multi-MB write that bricks GET `/api/settings` thereafter).

### Risks & rollback
- **Risk 1:** a `Literal[...]` constraint on a declared field (e.g. `theme`) misses a real frontend option → user's existing value rejected on next Save. Mitigation: pre-merge audit of every frontend producer site for each field that gains a `Literal`; if exhaustive value set cannot be confirmed cheaply, downgrade to `str` + length cap for that field (still safe, just less restrictive). Acceptance test: load production-snapshot `settings.json` files (collect a few from real users / dev installs) and POST each → all must 200.
- **Risk 2:** existing user's `settings.json` contains a now-invalid value (e.g. `theme: "custom"` from old experiment). Load-path stays tolerant — `SettingsManager.load` (`app/services.py:660-669`) does raw `json.load` + dict-merge, no Pydantic validation; legacy file continues to work. Save-path: when user next opens Settings and clicks Save, frontend POSTs the current full settings (read via `GET /api/settings` at mount, `SettingsView.jsx:115-121`); the now-invalid value reaches `SetReq`, 422s. Mitigation A (preferred): frontend `saveSettings` catches 422, surfaces toast "Setting X invalid: {reason}", scrolls to offending field. Mitigation B (defense-in-depth): on POST 422 for a declared-field value, log the key + reason in the backend audit line (Step 5) so support can diagnose.
- **Rollback:** revert single commit. `SetReq` returns to `extra: "allow"` + no validator; no DB migration needed; `settings.json` schema unchanged so on-disk format compatible both directions.

## Review

Filled at `review_`. Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Implementation Log

Filled during `inprogress_`. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD
- …

---

## Decision / Outcome

Required by `archived/*`.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_`):
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
