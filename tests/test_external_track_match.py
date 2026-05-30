"""external_track_match unit tests (external-track-match-unified-module T-3..T-9).

Covers the standalone module: pure title functions, version-tag parser (per the
remix-detector regex catalogue), verbatim fuzzy-match port, fingerprint PATH-detect
shell, adapter registry, and the no-DB-writer-imports invariant.

The ≥200-row labelled-corpus recall test (T8/T12) is owner-labelling work and is
NOT included here — these cases gate function correctness, not the recall metric.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import external_track_match as etm


@pytest.fixture(autouse=True)
def _reset_registry():
    """Module-global ADAPTER_REGISTRY must not leak across tests."""
    saved = dict(etm.ADAPTER_REGISTRY)
    etm.ADAPTER_REGISTRY.clear()
    yield
    etm.ADAPTER_REGISTRY.clear()
    etm.ADAPTER_REGISTRY.update(saved)


# ── normalize_title ──────────────────────────────────────────────────────────


def test_normalize_title_lowercases_and_strips_punct():
    assert etm.normalize_title("Strobe!") == "strobe"


def test_normalize_title_handles_accents():
    assert etm.normalize_title("Pacífico") == "pacifico"


def test_normalize_title_nfd_fold_off_keeps_accent():
    # nfd_fold=False mirrors the old stdlib-only matcher (accent survives as \w).
    assert etm.normalize_title("Pacífico", nfd_fold=False) == "pacífico"


# ── extract_title_stem ──────────────────────────────────────────────────────


def test_extract_title_stem_strips_paren_suffix():
    assert etm.extract_title_stem("Strobe (Radio Edit)") == "strobe"


def test_extract_title_stem_strips_bracket_suffix():
    assert etm.extract_title_stem("Strobe [Extended Mix]") == "strobe"


def test_extract_title_stem_strips_trailing_dash_variant():
    assert etm.extract_title_stem("Strobe - Extended Mix") == "strobe"


def test_extract_title_stem_drops_feat_by_default():
    assert etm.extract_title_stem("Song feat. X") == "song"
    assert etm.extract_title_stem("Song feat. X", drop_features=False) == "song feat. x"


def test_extract_title_stem_round_trip_shapes_collapse():
    root = "strobe"
    assert (
        etm.extract_title_stem("Strobe (Radio Edit)")
        == etm.extract_title_stem("Strobe - Extended Mix")
        == etm.extract_title_stem("Strobe (Deadmau5 Club Mix)")
        == root
    )


# ── parse_version_tag ────────────────────────────────────────────────────────


def test_parse_version_tag_returns_none_on_no_suffix():
    assert etm.parse_version_tag("Strobe") is None


def test_parse_version_tag_pure_variant():
    tag = etm.parse_version_tag("Strobe (Extended Mix)")
    assert tag is not None
    assert tag.label == "extended"
    assert tag.remixer is None
    assert tag.modifiers == ("Extended",)


def test_parse_version_tag_captures_remixer():
    tag = etm.parse_version_tag("Strobe (Deadmau5 Remix)")
    assert tag.label == "remix"
    assert tag.remixer == "Deadmau5"


def test_parse_version_tag_bootleg_synonyms_map_to_bootleg():
    for kind in ("Bootleg", "Flip", "Refix", "Rework"):
        tag = etm.parse_version_tag(f"Track (SomeDJ {kind})")
        assert tag.label == "bootleg", kind
        assert tag.remixer == "SomeDJ"


def test_parse_version_tag_captures_year_modifier():
    tag = etm.parse_version_tag("Strobe (2024 Edit)")
    assert tag.label == "edit"
    assert tag.modifiers == ("2024",)


def test_parse_version_tag_compound_extended_remix():
    tag = etm.parse_version_tag("Strobe (Deadmau5 Extended Remix)")
    assert tag.label == "remix"
    assert tag.remixer == "Deadmau5"
    assert "Extended" in tag.modifiers


def test_parse_version_tag_trailing_dash():
    tag = etm.parse_version_tag("Strobe - Club Mix")
    assert tag.label == "club"


def test_parse_version_tag_all_labels_canonical():
    samples = [
        "A (Extended Mix)",
        "A (Radio Edit)",
        "A (Club Mix)",
        "A (Dub)",
        "A (Instrumental)",
        "A (Acapella)",
        "A (VIP)",
        "A (X Remix)",
        "A (X Bootleg)",
        "A (2020 Edit)",
        "A (X Mashup)",
        "A (Original Mix)",
    ]
    for s in samples:
        tag = etm.parse_version_tag(s)
        assert tag is not None and tag.label in etm.VERSION_LABELS, s


# ── fuzzy_match_with_score (verbatim port) ───────────────────────────────────


def test_fuzzy_match_exact_normalised_title_short_circuits():
    cands = {"t1": {"Title": "Strobe", "Artist": "Deadmau5"}}
    tid, score = etm.fuzzy_match_with_score("strobe!", "deadmau5", cands)
    assert tid == "t1"
    assert score == 1.0


def test_fuzzy_match_below_threshold_returns_none():
    cands = {"t1": {"Title": "Totally Different", "Artist": "Other"}}
    tid, score = etm.fuzzy_match_with_score("Strobe", "Deadmau5", cands)
    assert tid is None
    assert score == 0.0


def test_fuzzy_match_picks_best_above_threshold():
    cands = {
        "t1": {"Title": "Strobe (Radio Edit)", "Artist": "Deadmau5"},
        "t2": {"Title": "Ghosts n Stuff", "Artist": "Deadmau5"},
    }
    tid, score = etm.fuzzy_match_with_score("Strobe Radio Edit", "Deadmau5", cands)
    assert tid == "t1"
    assert 0.65 <= score <= 1.0


# ── adapter registry ─────────────────────────────────────────────────────────


class _StubPlugin:
    name = "stub"

    async def search(self, title, artist, duration_s=None, *, max_results=20):
        return []

    def parse_version(self, raw):
        return None

    def quota_remaining(self):
        return None


def test_register_get_list_adapter():
    p = _StubPlugin()
    etm.register_adapter("stub", p)
    assert etm.get_adapter("stub") is p
    assert "stub" in etm.list_adapters()


def test_register_adapter_idempotent_replace():
    a, b = _StubPlugin(), _StubPlugin()
    etm.register_adapter("stub", a)
    etm.register_adapter("stub", b)
    assert etm.get_adapter("stub") is b
    assert etm.list_adapters().count("stub") == 1


def test_get_adapter_unknown_raises():
    with pytest.raises(etm.AdapterNotRegistered):
        etm.get_adapter("nope")


def test_stub_plugin_satisfies_protocol():
    assert isinstance(_StubPlugin(), etm.SourcePlugin)


# ── fingerprint ──────────────────────────────────────────────────────────────


def test_fingerprint_unavailable_when_binary_missing(monkeypatch):
    etm.is_fingerprinting_available.cache_clear()
    monkeypatch.setattr(etm.shutil, "which", lambda _name: None)
    result = etm.fingerprint("/music/x.mp3", allowed_roots=[Path("/music")])
    assert isinstance(result, etm.BinaryMissing)
    etm.is_fingerprinting_available.cache_clear()


def test_fingerprint_rejects_path_outside_roots(monkeypatch):
    etm.is_fingerprinting_available.cache_clear()
    monkeypatch.setattr(etm.shutil, "which", lambda _name: "/usr/bin/fpcalc")
    result = etm.fingerprint("/etc/passwd", allowed_roots=[Path("/music")])
    assert isinstance(result, etm.DecodeError)
    etm.is_fingerprinting_available.cache_clear()


# ── no-DB-writer-imports invariant (T-9) ─────────────────────────────────────


def test_module_has_no_db_writer_imports():
    src = Path(etm.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {"rbox", "pyrekordbox", "app.database", "app.live_database"}
    assert not (imported & forbidden), f"forbidden imports: {imported & forbidden}"
