"""Download recognizer tests (T-28 — app/artist_store/recognizer.py, rows T39 + T40).

Owner refinement 2026-09-26 (2): at download time, recognise whether the artist is
known, and give the file the right names. Pins Threat T18 — only a HIGH-confidence
correction is applied; a split nothing vouches for stays a suggestion — and the
lookup's tolerance ladder (exact -> case -> fold, ambiguous = unknown).

Same fixture shape as ``test_artist_attribution.py``: a ``LiveRekordboxDB`` with
``.tracks`` filled by hand and the real splitter; the store is a throwaway SQLite file.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.artist_store import recognizer, registry, schema
from app.live_database import LiveRekordboxDB

BOYS = "Boys Noize"


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(autouse=True)
def _neutral_library_config(monkeypatch):
    import app.services as services

    monkeypatch.setattr(services.SettingsManager, "load", staticmethod(lambda: {}))
    monkeypatch.setattr(
        services.MetadataManager,
        "get_mapped_name",
        classmethod(lambda cls, category, name: name),
    )


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


def _library(*artists: str) -> LiveRekordboxDB:
    """One track per given Artist string."""
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {}
    for i, artist in enumerate(artists, start=1):
        db.tracks[str(i)] = {"ID": str(i), "Title": f"Track {i}", "Artist": artist, "Remixer": ""}
    db._finalize_ui_metadata()
    return db


def _sc(
    title: str,
    username: str = "",
    *,
    label_artist: str = "",
    user_id: int | None = None,
) -> dict[str, Any]:
    user: dict[str, Any] = {"username": username} if username else {}
    if user_id is not None:
        user["id"] = user_id
    pub = {"artist": label_artist} if label_artist else {}
    return {"title": title, "user": user, "publisher_metadata": pub}


def _credits(rec: recognizer.Recognition) -> dict[str, tuple[str, bool]]:
    return {c.name: (c.role, c.known) for c in rec.credits}


# --------------------------------------------------------------------------- T39 — names


def test_a_label_upload_naming_a_known_artist_is_split() -> None:
    rec = recognizer.recognize(_sc("Boys Noize - Starter", "Boysnoize Records"), _library(BOYS))

    assert (rec.artist, rec.title) == (BOYS, "Starter")
    assert rec.corrections == (recognizer.CORRECTION_KNOWN_ARTIST_PREFIX,)
    assert rec.suggestion is None
    assert rec.changed is True
    assert _credits(rec) == {BOYS: ("primary", True)}


def test_an_unknown_prefix_is_only_a_suggestion() -> None:
    rec = recognizer.recognize(_sc("New Act - Song", "Some Label"), _library(BOYS))

    assert (rec.artist, rec.title) == ("Some Label", "New Act - Song")
    assert rec.changed is False
    assert rec.suggestion == recognizer.Suggestion(
        "New Act", "Song", recognizer.SUGGESTION_UNKNOWN_ARTIST_PREFIX
    )
    # "Is the artist known?" is asked about the likeliest reading, not the label.
    assert _credits(rec) == {"New Act": ("primary", False)}


@pytest.mark.parametrize(
    "title",
    [
        "Overdrive - Extended Mix",
        "Overdrive - Original Mix",
        "Overdrive - VIP",
        "Intro - Overdrive",
    ],
)
def test_a_version_phrase_is_never_a_credit(title: str) -> None:
    rec = recognizer.recognize(_sc(title, "Some Label"), _library(BOYS, "Overdrive"))

    assert (rec.artist, rec.title) == ("Some Label", title)
    assert rec.suggestion is None
    assert rec.corrections == ()


def test_the_uploader_repeating_their_name_is_stripped() -> None:
    rec = recognizer.recognize(_sc("Boys Noize - Starter", BOYS), None)

    assert (rec.artist, rec.title) == (BOYS, "Starter")
    assert rec.corrections == (recognizer.CORRECTION_TITLE_REPEATS_ARTIST,)


def test_a_handle_repeated_as_a_spelled_name_takes_the_spelling() -> None:
    rec = recognizer.recognize(_sc("Boys Noize - Starter", "boysnoize"), None)

    assert (rec.artist, rec.title) == (BOYS, "Starter")


def test_label_metadata_wins_over_uploader_and_prefix() -> None:
    plain = recognizer.recognize(_sc("Starter", "Boysnoize Records", label_artist=BOYS), None)
    repeated = recognizer.recognize(
        _sc("Boys Noize - Starter", "Boysnoize Records", label_artist=BOYS), None
    )
    someone_else = recognizer.recognize(
        _sc("Other Act - Song", "Boysnoize Records", label_artist=BOYS), _library("Other Act")
    )

    assert (plain.artist, plain.title) == (BOYS, "Starter")
    assert (repeated.artist, repeated.title) == (BOYS, "Starter")
    assert (someone_else.artist, someone_else.title) == (BOYS, "Other Act - Song")
    assert someone_else.suggestion is None


def test_no_name_at_all_stays_unknown_and_is_never_a_known_artist() -> None:
    rec = recognizer.recognize({"title": "Starter"}, _library("Unknown Artist", "Unknown Artist"))

    assert rec.artist == recognizer.UNKNOWN_ARTIST
    assert rec.credits == ()
    assert rec.corrections == ()


def test_without_a_library_the_store_still_vouches() -> None:
    registry.favourite_artist_by_name(BOYS)

    rec = recognizer.recognize(_sc("Boys Noize - Starter", "Boysnoize Records"), None)

    assert (rec.artist, rec.title) == (BOYS, "Starter")
    assert rec.credits[0].favourite is True


# --------------------------------------------------------------------------- T40 — known


def test_a_known_spelling_is_taken() -> None:
    rec = recognizer.recognize(_sc("Starter", "BOYS NOIZE"), _library(BOYS, BOYS))

    assert rec.artist == BOYS
    assert rec.corrections == (recognizer.CORRECTION_KNOWN_SPELLING,)
    assert rec.credits[0].library_tracks == 2


def test_a_merged_alias_resolves_to_its_artist() -> None:
    cid = schema.create_collection(BOYS)
    schema.add_alias(cid, "Boysnoize", source="merge")

    rec = recognizer.recognize(_sc("Starter", "Boysnoize"), None)

    assert rec.artist == BOYS
    assert rec.credits[0].collection_id == cid


def test_the_bound_account_names_the_artist() -> None:
    cid = schema.create_collection(BOYS)
    schema.set_link(cid, "soundcloud", remote_id="soundcloud:users:42")

    rec = recognizer.recognize(_sc("Starter", "BN Official", user_id=42), None)

    assert rec.artist == BOYS
    assert rec.corrections == (recognizer.CORRECTION_BOUND_ACCOUNT,)


def test_a_foreign_account_with_the_same_title_is_not_bound() -> None:
    cid = schema.create_collection(BOYS)
    schema.set_link(cid, "soundcloud", remote_id="soundcloud:users:42")

    rec = recognizer.recognize(_sc("Starter", "BN Official", user_id=43), None)

    assert rec.artist == "BN Official"
    assert rec.credits[0].known is False


def test_an_ambiguous_fold_is_left_alone() -> None:
    rec = recognizer.recognize(_sc("Starter", "BOYS.NOIZE"), _library("Boys-Noize", BOYS))

    assert rec.artist == "BOYS.NOIZE"
    assert rec.corrections == ()
    assert rec.credits[0].known is False


def test_credits_carry_known_favourite_and_the_role_on_their_page() -> None:
    registry.favourite_artist_by_name(BOYS)
    db = _library("Charli XCX", BOYS)

    rec = recognizer.recognize(_sc("Sirens (Boys Noize Remix)", "Charli XCX"), db)

    by_name = {c.name: c for c in rec.credits}
    assert by_name["Charli XCX"].role == "remixed_by_other"
    assert by_name["Charli XCX"].favourite is False
    assert (by_name[BOYS].role, by_name[BOYS].known, by_name[BOYS].favourite) == (
        "remixer",
        True,
        True,
    )


def test_a_new_artist_and_a_guest_are_reported_new() -> None:
    rec = recognizer.recognize(_sc("Song feat. Guest", "New Act"), _library(BOYS))

    assert _credits(rec) == {"New Act": ("primary", False), "Guest": ("featured", False)}


def test_version_words_are_peeled_off_a_remixer() -> None:
    rec = recognizer.recognize(_sc("Overdrive (Boys Noize VIP Remix)", "Somebody"), _library(BOYS))

    assert _credits(rec)[BOYS] == ("remixer", True)


def test_their_own_remix_of_their_own_track_stays_primary() -> None:
    rec = recognizer.recognize(_sc("Overdrive (Boys Noize Remix)", BOYS), _library(BOYS))

    assert _credits(rec) == {BOYS: ("primary", True)}


def test_as_dict_is_the_task_payload() -> None:
    rec = recognizer.recognize(_sc("Boys Noize - Starter", "Boysnoize Records"), _library(BOYS))

    payload = rec.as_dict()

    assert payload["changed"] is True
    assert payload["raw_artist"] == "Boysnoize Records"
    assert payload["corrections"] == ["known_artist_prefix"]
    assert payload["credits"][0]["name"] == BOYS
    assert payload["suggestion"] is None


def test_control_characters_never_reach_the_names() -> None:
    """A tag (and the undo pair the card sends back) never carries a control character."""
    rec = recognizer.recognize(_sc("Boys\x7fNoize -\tStarter", "Label\x00Name"), None)

    assert rec.raw_artist == "Label Name"
    assert rec.raw_title == "Boys Noize - Starter"
    assert all(ch.isprintable() for ch in rec.artist + rec.title)
