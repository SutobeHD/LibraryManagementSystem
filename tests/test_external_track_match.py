"""Tests for ``app/external_track_match.py`` — the shared track-matching module.

Covers the M1 acceptance gates from
``docs/research/implement/accepted_external-track-match-unified-module.md``:
pure-function units (normalise / stem / version-tag), >=95% label-recall on
the 200+ title corpus, fuzzy-match equivalence with the SoundCloud baseline,
adapter-registry mutation, and PATH-detect fingerprint behaviour.

The title corpus lives at ``tests/fixtures/external_track_match/titles_corpus.yaml``.
It is loaded with a tiny stdlib-only parser (``_load_corpus``) — the suite has
no PyYAML dependency and the M1 plan forbids adding one. The corpus uses only
the flat ``key: "value"`` / ``modifiers: [..]`` subset that parser supports.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import app.external_track_match as etm
from app.external_track_match import (
    AdapterNotRegistered,
    Candidate,
    Fingerprint,
    FingerprintUnavailable,
    SourcePlugin,
    VersionTag,
)

# Make tests/fixtures importable so `mock_adapter` resolves regardless of cwd.
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
if str(_FIXTURE_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_FIXTURE_DIR))

from mock_adapter import MockAdapter  # noqa: E402  (path insert must precede import)

_CORPUS_PATH = _FIXTURE_DIR / "external_track_match" / "titles_corpus.yaml"


# ---------------------------------------------------------------------------
# Minimal stdlib YAML loader for the flat title-corpus subset
# ---------------------------------------------------------------------------


def _parse_scalar(raw: str):
    """Parse a single YAML scalar from the corpus subset: quoted str / null / int."""
    raw = raw.strip()
    if raw in ("null", "~", ""):
        return None
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(p) for p in _split_flow_list(inner)]
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def _split_flow_list(inner: str) -> list[str]:
    """Split a flow-list body on commas, respecting quoted segments."""
    parts: list[str] = []
    buf = ""
    quote: str | None = None
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return parts


def _load_corpus(path: Path) -> list[dict]:
    """Load the flat ``cases:`` list from the corpus YAML with no external deps.

    Recognises exactly the structure the corpus uses: a top-level ``cases:``
    key, then ``- key: value`` records where each record is a flat mapping of
    scalars (one optional ``modifiers: [..]`` flow list).
    """
    records: list[dict] = []
    current: dict | None = None
    in_cases = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped == "cases:":
            in_cases = True
            continue
        if not in_cases:
            continue
        if stripped.startswith("- "):
            # Start of a new record; the rest of the line is its first field.
            current = {}
            records.append(current)
            stripped = stripped[2:].strip()
        if current is None:
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = _parse_scalar(value)
    return records


_CORPUS = _load_corpus(_CORPUS_PATH)


# ---------------------------------------------------------------------------
# Pure functions — normalize_title
# ---------------------------------------------------------------------------


def test_normalize_title_lowercases_and_strips_punct() -> None:
    """normalize_title('Strobe!') == 'strobe' — mirrors _normalize_title in soundcloud_api."""
    assert etm.normalize_title("Strobe!") == "strobe"
    assert etm.normalize_title("  Hello, World!!  ") == "hello world"


def test_normalize_title_handles_accents() -> None:
    """normalize_title('Pacífico') == 'pacifico' — NFD accent-fold (new vs stdlib behaviour)."""
    assert etm.normalize_title("Pacífico") == "pacifico"
    assert etm.normalize_title("Café Del Mar") == "cafe del mar"
    assert etm.normalize_title("Tiësto") == "tiesto"


# ---------------------------------------------------------------------------
# Pure functions — extract_title_stem
# ---------------------------------------------------------------------------


def test_extract_title_stem_strips_paren_suffix() -> None:
    """extract_title_stem('Strobe (Radio Edit)') == 'strobe'."""
    assert etm.extract_title_stem("Strobe (Radio Edit)") == "strobe"


def test_extract_title_stem_strips_bracket_suffix() -> None:
    """extract_title_stem('Strobe [Extended Mix]') == 'strobe'."""
    assert etm.extract_title_stem("Strobe [Extended Mix]") == "strobe"


def test_extract_title_stem_strips_trailing_dash_variant() -> None:
    """extract_title_stem('Strobe - Extended Mix') == 'strobe'."""
    assert etm.extract_title_stem("Strobe - Extended Mix") == "strobe"


def test_extract_title_stem_drops_feat_by_default() -> None:
    """extract_title_stem('Song feat. X') drops the feature clause unless disabled."""
    assert etm.extract_title_stem("Song feat. X") == "song"
    assert etm.extract_title_stem("Song feat. X", drop_features=False) == "song feat. x"


def test_extract_title_stem_round_trip_three_shapes() -> None:
    """All four equivalent stems collapse to the same root."""
    a = etm.extract_title_stem("Strobe (Radio Edit)")
    b = etm.extract_title_stem("Strobe - Extended Mix")
    c = etm.extract_title_stem("Strobe (Deadmau5 Club Mix)")
    assert a == b == c == "strobe"


# ---------------------------------------------------------------------------
# Pure functions — parse_version_tag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected_label",
    [(rec["title"], rec.get("label")) for rec in _CORPUS],
    ids=[rec["title"] for rec in _CORPUS],
)
def test_parse_version_tag_label_recall(title: str, expected_label: str | None) -> None:
    """>=95% label recall over the 200+ title corpus per the Goals metric.

    Per-case the assertion is soft (recorded, not hard-failed) so a single
    odd title does not red the whole gate; the aggregate recall is enforced
    by ``test_parse_version_tag_corpus_recall_threshold``.
    """
    tag = etm.parse_version_tag(title)
    actual = tag.label if tag is not None else None
    # Soft per-case check — aggregate gate lives in the threshold test.
    test_parse_version_tag_label_recall._results.append((title, expected_label, actual))  # type: ignore[attr-defined]


test_parse_version_tag_label_recall._results = []  # type: ignore[attr-defined]


def test_parse_version_tag_corpus_recall_threshold() -> None:
    """Aggregate label recall over the whole corpus must be >=95%."""
    results = test_parse_version_tag_label_recall._results  # type: ignore[attr-defined]
    assert results, "label-recall parametrize did not run before the threshold check"
    total = len(results)
    correct = sum(1 for _t, exp, act in results if exp == act)
    recall = correct / total
    misses = [(t, exp, act) for t, exp, act in results if exp != act]
    assert recall >= 0.95, (
        f"label recall {recall:.3f} ({correct}/{total}) below 0.95 — misses: {misses[:15]}"
    )


def test_parse_version_tag_captures_remixer() -> None:
    """parse_version_tag('Strobe (Deadmau5 Remix)').remixer == 'Deadmau5'."""
    tag = etm.parse_version_tag("Strobe (Deadmau5 Remix)")
    assert tag is not None
    assert tag.label == "remix"
    assert tag.remixer == "Deadmau5"


def test_parse_version_tag_captures_year_modifier() -> None:
    """parse_version_tag('Strobe (2024 Edit)').modifiers contains '2024'."""
    tag = etm.parse_version_tag("Strobe (2024 Edit)")
    assert tag is not None
    assert tag.label == "edit"
    assert "2024" in tag.modifiers


def test_parse_version_tag_returns_none_on_no_suffix() -> None:
    """parse_version_tag('Strobe') is None."""
    assert etm.parse_version_tag("Strobe") is None


def test_parse_version_tag_canonical_label_set() -> None:
    """Every parsed label is a member of the canonical 12-member set."""
    for rec in _CORPUS:
        tag = etm.parse_version_tag(rec["title"])
        if tag is not None:
            assert tag.label in etm.VERSION_LABELS


# ---------------------------------------------------------------------------
# Fuzzy match — equivalence with the SoundCloud baseline (regression gate)
# ---------------------------------------------------------------------------


def _sc_baseline_pairs() -> list[tuple[str, str, dict]]:
    """Build (query_title, query_artist, candidates) pairs covering the matcher modes."""
    local = {
        "t1": {"Title": "Strobe", "Artist": "Deadmau5"},
        "t2": {"Title": "Levels", "Artist": "Avicii"},
        "t3": {"Title": "Velvet Shuffle", "Artist": "Some DJ"},
        "t4": {"Title": "Café Del Mar", "Artist": "Energy 52"},
        "t5": {"Title": "Opus", "Artist": "Eric Prydz"},
    }
    return [
        ("Strobe", "Deadmau5", local),
        ("strobe", "deadmau5", local),
        ("Levels", "Avicii", local),
        ("Velvet Shuffles", "Some DJ", local),
        ("Completely Unrelated Banger", "Nobody", local),
        ("Opus", "Eric Prydz", local),
        ("Café Del Mar", "Energy 52", local),
        ("anything", "anyone", {}),
    ]


def test_fuzzy_match_with_score_equivalence_to_sc_baseline() -> None:
    """The module-level matcher returns identical (tid, score) tuples as the SC engine.

    The SC engine method is now a thin delegate to the module function, so this
    check also pins that the delegate rewire preserved behaviour.
    """
    from unittest.mock import MagicMock

    from app.soundcloud_api import SoundCloudSyncEngine

    engine = SoundCloudSyncEngine(MagicMock())
    for title, artist, candidates in _sc_baseline_pairs():
        module_result = etm.fuzzy_match_with_score(title, artist, candidates)
        engine_result = engine._fuzzy_match_with_score(title, artist, candidates)
        assert module_result == engine_result, f"divergence for ({title!r}, {artist!r})"


def test_fuzzy_match_with_score_exact_norm_title_returns_one_point_zero() -> None:
    """Exact normalised-title match short-circuits to (tid, 1.0)."""
    local = {"t1": {"Title": "Song Name", "Artist": "Artist A"}}
    tid, score = etm.fuzzy_match_with_score("Song Name", "Different Artist", local)
    assert tid == "t1"
    assert score == 1.0


def test_fuzzy_match_with_score_threshold_param_default_065() -> None:
    """Default threshold is 0.65; an explicit stricter override is honoured.

    Uses a one-character typo so the match goes through SequenceMatcher rather
    than the exact-normalised-title short-circuit (which ignores the threshold).
    """
    local = {"t1": {"Title": "Velvet Shuffle", "Artist": "Some DJ"}}
    # One-char typo — well above 0.65 but not an exact normalised-title match.
    tid_default, score_default = etm.fuzzy_match_with_score("Velvet Shuffles", "Some DJ", local)
    assert tid_default == "t1"
    assert 0.65 <= score_default < 1.0
    # An impossibly strict threshold rejects the same near-match.
    tid_strict, _ = etm.fuzzy_match_with_score("Velvet Shuffles", "Some DJ", local, threshold=0.999)
    assert tid_strict is None


def test_fuzzy_match_with_score_no_match_returns_none_zero() -> None:
    """Empty candidates dict yields (None, 0.0)."""
    assert etm.fuzzy_match_with_score("anything", "anyone", {}) == (None, 0.0)


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    """Clear ADAPTER_REGISTRY before and after each test so order doesn't leak state."""
    etm.ADAPTER_REGISTRY.clear()
    yield
    etm.ADAPTER_REGISTRY.clear()


def test_register_adapter_idempotent() -> None:
    """Re-registering the same name replaces; no duplicate entry."""
    first = MockAdapter(name="dup")
    second = MockAdapter(name="dup")
    etm.register_adapter("dup", first)
    etm.register_adapter("dup", second)
    assert list(etm.ADAPTER_REGISTRY.keys()).count("dup") == 1
    assert etm.get_adapter("dup") is second


def test_get_adapter_raises_when_missing() -> None:
    """get_adapter on an unknown name raises AdapterNotRegistered."""
    with pytest.raises(AdapterNotRegistered):
        etm.get_adapter("nonexistent")


def test_list_adapters_returns_registered_names() -> None:
    """list_adapters returns every registered name (order-independent)."""
    etm.register_adapter("mock", MockAdapter(name="mock"))
    etm.register_adapter("other", MockAdapter(name="other"))
    assert set(etm.list_adapters()) == {"mock", "other"}


def test_mock_adapter_satisfies_source_plugin_protocol() -> None:
    """The mock adapter is a runtime-checkable SourcePlugin."""
    assert isinstance(MockAdapter(), SourcePlugin)


def test_soundcloud_adapter_satisfies_source_plugin_protocol() -> None:
    """The real SoundCloudAdapter is a runtime-checkable SourcePlugin."""
    assert isinstance(etm.SoundCloudAdapter(), SourcePlugin)


def test_mock_and_real_adapter_register_side_by_side() -> None:
    """A mock and the real SC adapter coexist in the registry, dispatched alike."""
    etm.register_adapter("mock", MockAdapter(name="mock"))
    etm.register_soundcloud_adapter()
    assert set(etm.list_adapters()) == {"mock", "soundcloud"}
    for name in etm.list_adapters():
        adapter = etm.get_adapter(name)
        assert hasattr(adapter, "search")
        assert callable(adapter.search)


def test_mock_adapter_search_returns_candidates() -> None:
    """The mock adapter's async search yields Candidate objects."""
    import asyncio

    adapter = MockAdapter(name="mock")
    results = asyncio.run(adapter.search("Strobe", "Deadmau5"))
    assert results and all(isinstance(c, Candidate) for c in results)
    assert results[0].source == "mock"
    assert results[0].title == "Strobe"


# ---------------------------------------------------------------------------
# Fingerprint — PATH-detect (mock subprocess; no real fpcalc in CI)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_fpcalc_cache():
    """Drop the cached fpcalc PATH-detect so each test sees its own monkeypatch."""
    etm._fpcalc_path.cache_clear()
    yield
    etm._fpcalc_path.cache_clear()


def test_is_fingerprinting_available_true_when_fpcalc_on_path(monkeypatch) -> None:
    """shutil.which('fpcalc') -> a path makes is_fingerprinting_available() True."""
    monkeypatch.setattr(etm.shutil, "which", lambda _b: "/usr/bin/fpcalc")
    assert etm.is_fingerprinting_available() is True


def test_is_fingerprinting_available_false_when_fpcalc_missing(monkeypatch) -> None:
    """shutil.which('fpcalc') -> None makes is_fingerprinting_available() False."""
    monkeypatch.setattr(etm.shutil, "which", lambda _b: None)
    assert etm.is_fingerprinting_available() is False


def test_fingerprint_returns_unavailable_when_fpcalc_missing(monkeypatch) -> None:
    """fingerprint() degrades to the BINARY_MISSING sentinel when fpcalc is absent."""
    monkeypatch.setattr(etm.shutil, "which", lambda _b: None)
    result = etm.fingerprint("anything.mp3")
    assert result is FingerprintUnavailable.BINARY_MISSING
    assert isinstance(result, FingerprintUnavailable._Reason)


def test_fingerprint_validates_audio_path_sandbox(monkeypatch, tmp_path) -> None:
    """A path outside ALLOWED_AUDIO_ROOTS raises ValueError before any subprocess."""
    # Pretend fpcalc exists so the guard, not the PATH-detect, is what fires.
    monkeypatch.setattr(etm.shutil, "which", lambda _b: "/usr/bin/fpcalc")
    # Force a non-empty allow-list that the temp path is NOT inside.
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside = tmp_path / "outside" / "track.mp3"

    def _fake_guard(p: Path) -> None:
        resolved = p.resolve()
        if not resolved.is_relative_to(allowed_root):
            raise ValueError(f"{resolved} outside allowed roots")

    monkeypatch.setattr(etm, "_resolve_audio_root_guard", _fake_guard)
    # Subprocess must never be reached.
    monkeypatch.setattr(
        etm.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("subprocess.run reached despite sandbox violation"),
    )
    with pytest.raises(ValueError, match="outside allowed roots"):
        etm.fingerprint(outside)


def test_fingerprint_respects_timeout_param(monkeypatch) -> None:
    """The subprocess invocation forwards the timeout kwarg (default 10.0)."""
    monkeypatch.setattr(etm.shutil, "which", lambda _b: "/usr/bin/fpcalc")
    monkeypatch.setattr(etm, "_resolve_audio_root_guard", lambda _p: None)
    captured: dict = {}

    def _fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            cmd, 0, stdout="DURATION=200\nFINGERPRINT=AQAAxyz\n", stderr=""
        )

    monkeypatch.setattr(etm.subprocess, "run", _fake_run)
    etm.fingerprint("track.mp3")
    assert captured.get("timeout") == 10.0
    etm.fingerprint("track.mp3", timeout=3.5)
    assert captured.get("timeout") == 3.5


def test_fingerprint_returns_fingerprint_dataclass_on_success(monkeypatch) -> None:
    """A well-formed fpcalc stdout yields a Fingerprint dataclass."""
    monkeypatch.setattr(etm.shutil, "which", lambda _b: "/usr/bin/fpcalc")
    monkeypatch.setattr(etm, "_resolve_audio_root_guard", lambda _p: None)

    def _fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="DURATION=247\nFINGERPRINT=AQADtMmS_recognisable\n", stderr=""
        )

    monkeypatch.setattr(etm.subprocess, "run", _fake_run)
    result = etm.fingerprint("track.mp3")
    assert isinstance(result, Fingerprint)
    assert result.fpcalc_hash == "AQADtMmS_recognisable"
    assert result.duration_s == 247.0


def test_fingerprint_returns_timeout_sentinel_on_subprocess_timeout(monkeypatch) -> None:
    """A subprocess timeout degrades to the TIMEOUT sentinel, never raises."""
    monkeypatch.setattr(etm.shutil, "which", lambda _b: "/usr/bin/fpcalc")
    monkeypatch.setattr(etm, "_resolve_audio_root_guard", lambda _p: None)

    def _fake_run(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd, 10.0)

    monkeypatch.setattr(etm.subprocess, "run", _fake_run)
    assert etm.fingerprint("track.mp3") is FingerprintUnavailable.TIMEOUT


def test_fingerprint_returns_decode_error_on_nonzero_exit(monkeypatch) -> None:
    """A non-zero fpcalc exit degrades to the DECODE_ERROR sentinel."""
    monkeypatch.setattr(etm.shutil, "which", lambda _b: "/usr/bin/fpcalc")
    monkeypatch.setattr(etm, "_resolve_audio_root_guard", lambda _p: None)

    def _fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="ERROR: bad file")

    monkeypatch.setattr(etm.subprocess, "run", _fake_run)
    assert etm.fingerprint("track.mp3") is FingerprintUnavailable.DECODE_ERROR


# ---------------------------------------------------------------------------
# Module-purity gate — read-only invariant
# ---------------------------------------------------------------------------


def test_module_has_no_db_writer_imports() -> None:
    """The module source contains no master.db writer / rbox coupling."""
    source = Path(etm.__file__).read_text(encoding="utf-8")
    # Strip comment + docstring lines so prose mentions don't trip the gate.
    code_lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    for forbidden in ("_db_write_lock", "pyrekordbox", "import rbox", "from rbox"):
        assert forbidden not in code, f"forbidden DB-writer reference {forbidden!r} in module"


def test_dataclasses_are_frozen_and_hashable() -> None:
    """VersionTag / Candidate / Fingerprint are frozen and hashable where expected."""
    tag = VersionTag(label="remix", remixer="Deadmau5", modifiers=("Extended", "Remix"))
    assert hash(tag) == hash(VersionTag("remix", "Deadmau5", ("Extended", "Remix")))
    with pytest.raises((AttributeError, TypeError)):
        tag.label = "edit"  # type: ignore[misc]
    fp = Fingerprint(fpcalc_hash="abc", duration_s=1.0)
    assert hash(fp) == hash(Fingerprint("abc", 1.0))


def test_corpus_has_at_least_200_cases() -> None:
    """The title corpus must carry >=200 records per the Goals metric."""
    assert len(_CORPUS) >= 200, f"corpus has only {len(_CORPUS)} cases"
