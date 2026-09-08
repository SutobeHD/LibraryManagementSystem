"""Artist-Hub identity tests (app/artist_store/identity.py + schema v2 track_identity).

Owner decision 2026-09-08: identification is by NAME, remix-aware, with the uploader
URN as the highest-confidence signal rather than the only one. Pinned here:

* every spelled-out remix example lands in the stated role,
* a name that appears ONLY inside ``(X Remix)`` is never ``primary``,
* a foreign uploader with an identical display name and no title credit is at most
  ``medium`` primary — never ``high``,
* aliases from the sidecar resolve like the canonical name,
* ``user_override`` wins over the classifier on every pass and survives an upsert,
* an exact ISRC hit short-circuits the owned/missing diff to owned (score 1.0),
* the v1 -> v2 migration bumps the version and old rows survive,
* ``uncertain`` (and ``featured`` / ``remixed_by_other`` / anything ``low``) is never
  auto-queue-eligible.

No network, no keyring, no ``master.db``: the sidecar is a throwaway SQLite file in
``tmp_path``, monkeypatched the way ``tests/test_artist_store_registry.py`` does it.
"""

from __future__ import annotations

import ast
import sqlite3
import threading
from pathlib import Path

import pytest

from app.artist_store import catalogue as cat
from app.artist_store import identity as idn
from app.artist_store import schema

ARTIST = "Boys Noize"
ARTIST_URN = "soundcloud:users:1000"
FOREIGN_URN = "soundcloud:users:2000"
LABEL = "Some Label"

HIGH, MEDIUM, LOW = idn.CONFIDENCE_HIGH, idn.CONFIDENCE_MEDIUM, idn.CONFIDENCE_LOW


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """Point the sidecar at a throwaway DB and reset its per-process state."""
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


@pytest.fixture
def collection(store) -> str:
    return store.create_collection(ARTIST)


def sc(
    sc_id: str,
    title: str,
    *,
    uploader_urn: str = FOREIGN_URN,
    uploader_name: str = LABEL,
    tag_list: str = "",
    isrc: str = "",
    **extra,
) -> dict:
    return {
        "sc_id": f"soundcloud:tracks:{sc_id}",
        "title": title,
        "uploader_urn": uploader_urn,
        "uploader_name": uploader_name,
        "tag_list": tag_list,
        "isrc": isrc,
        "access": "playable",
        "streamable": True,
        "sharing": "public",
        "duration_ms": 300_000,
        **extra,
    }


def one(track: dict, names=(ARTIST,), urn: str | None = ARTIST_URN, **kw) -> dict:
    rows = idn.classify_roles([track], urn, list(names), **kw)
    assert len(rows) == 1
    return rows[0]


def role_of(track: dict, **kw) -> tuple[str, str]:
    row = one(track, **kw)
    return row["role"], row["confidence"]


# --------------------------------------------------------------------------- the spelled-out examples


class TestRemixCare:
    def test_remix_by_the_artist_of_someone_elses_track_is_remixer(self) -> None:
        assert role_of(sc("1", "Overdrive (Boys Noize Remix)")) == ("remixer", MEDIUM)

    def test_remix_by_the_artist_uploaded_by_linked_account_is_remixer_high(self) -> None:
        track = sc(
            "1", "Bangarang (Boys Noize Remix)", uploader_urn=ARTIST_URN, uploader_name=ARTIST
        )
        assert role_of(track) == ("remixer", HIGH)

    def test_artists_track_remixed_by_someone_else_splits_by_perspective(self) -> None:
        track = sc("1", "Boys Noize - Overdrive (Erol Alkan Remix)")
        assert role_of(track, names=("Boys Noize",)) == ("remixed_by_other", MEDIUM)
        assert role_of(track, names=("Erol Alkan",), urn=None) == ("remixer", MEDIUM)

    def test_extended_mix_is_primary_not_a_remix(self) -> None:
        row = one(sc("1", "Boys Noize - Overdrive (Extended Mix)"))
        assert (row["role"], row["confidence"]) == ("primary", MEDIUM)
        assert row["credit_parse"]["remixer"] is None
        assert row["credit_parse"]["version"] == "Extended"

    @pytest.mark.parametrize(
        "uploader_urn, uploader_name",
        [(FOREIGN_URN, LABEL), (ARTIST_URN, ARTIST), (FOREIGN_URN, ARTIST)],
        ids=["foreign", "linked", "foreign-same-name"],
    )
    def test_a_name_only_inside_a_remix_credit_is_never_primary(
        self, uploader_urn, uploader_name
    ) -> None:
        track = sc(
            "1",
            "Skrillex - Bangarang (Boys Noize Remix)",
            uploader_urn=uploader_urn,
            uploader_name=uploader_name,
        )
        role, _ = role_of(track)
        assert role == "remixer"
        assert role != "primary"

    def test_own_vip_of_own_track_is_primary(self) -> None:
        assert role_of(sc("1", "Boys Noize - Overdrive (Boys Noize VIP)"))[0] == "primary"

    def test_radio_edit_is_a_version_not_a_remixer_called_radio(self) -> None:
        row = one(sc("1", "Overdrive (Radio Edit)", uploader_urn=ARTIST_URN, uploader_name=ARTIST))
        assert row["role"] == "primary"
        assert row["credit_parse"]["remixer"] is None

    def test_label_bracket_after_the_remix_credit_is_peeled(self) -> None:
        row = one(sc("1", "Overdrive (Erol Alkan Remix) [BNR]", uploader_urn=ARTIST_URN))
        assert row["role"] == "remixed_by_other"
        assert row["credit_parse"]["remixer"] == "Erol Alkan"

    def test_dash_separated_remix_credit_counts(self) -> None:
        assert role_of(sc("1", "Skrillex - Bangarang - Boys Noize Remix"))[0] == "remixer"

    def test_unbracketed_suffix_naming_the_artist_counts(self) -> None:
        row = one(sc("1", "Skrillex - Bangarang Boys Noize Remix"))
        assert row["role"] == "remixer"
        assert row["credit_parse"]["remixer"] == ARTIST

    def test_unattributed_edit_from_a_foreign_uploader_is_uncertain(self) -> None:
        # "(Edit)" with no name — someone's edit, no way to say whose.
        assert role_of(sc("1", "Boys Noize - Overdrive (Edit)")) == ("uncertain", LOW)

    def test_co_remixer_credit_counts(self) -> None:
        assert role_of(sc("1", "Skrillex - Title (Erol Alkan & Boys Noize Remix)"))[0] == "remixer"


# --------------------------------------------------------------------------- primary + uploader signals


class TestPrimarySignals:
    def test_linked_uploader_is_primary_high(self) -> None:
        row = one(sc("1", "Overdrive", uploader_urn=ARTIST_URN, uploader_name=ARTIST))
        assert (row["role"], row["confidence"]) == ("primary", HIGH)
        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_UPLOADER_URN

    def test_title_prefix_from_a_label_upload_is_primary_medium(self) -> None:
        row = one(sc("1", "Boys Noize - Overdrive"))
        assert (row["role"], row["confidence"]) == ("primary", MEDIUM)
        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_TITLE_PREFIX
        assert row["credit_parse"]["artist_prefix"] == ARTIST

    def test_same_display_name_on_a_foreign_account_is_at_most_medium(self) -> None:
        row = one(sc("1", "Overdrive", uploader_urn=FOREIGN_URN, uploader_name=ARTIST))
        assert row["role"] == "primary"
        assert row["confidence"] == MEDIUM
        assert row["confidence"] != HIGH
        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_UPLOADER_NAME

    def test_without_a_linked_account_nothing_reaches_high(self) -> None:
        rows = idn.classify_roles(
            [
                sc("1", "Boys Noize - Overdrive", uploader_urn=ARTIST_URN, uploader_name=ARTIST),
                sc("2", "Overdrive", uploader_urn=ARTIST_URN, uploader_name=ARTIST),
            ],
            None,
            [ARTIST],
        )
        assert all(r["confidence"] != HIGH for r in rows)

    def test_co_credited_prefix_counts_for_each_name(self) -> None:
        track = sc("1", "Boys Noize & Skrillex - Title")
        assert role_of(track, names=("Boys Noize",))[0] == "primary"
        assert role_of(track, names=("Skrillex",), urn=None)[0] == "primary"

    def test_promo_prefix_is_stripped(self) -> None:
        assert role_of(sc("1", "PREMIERE: Boys Noize - Overdrive [BNR]"))[0] == "primary"

    def test_linked_account_uploading_someone_elses_track_is_not_primary(self) -> None:
        row = one(sc("1", "Skrillex - Bangarang", uploader_urn=ARTIST_URN, uploader_name=ARTIST))
        assert row["role"] == "uncertain"
        assert "Skrillex" in row["credit_parse"]["reason"]

    def test_the_uploader_urn_alone_does_not_beat_a_foreign_remixer_credit(self) -> None:
        row = one(sc("1", "Overdrive (Erol Alkan Remix)", uploader_urn=ARTIST_URN))
        assert (row["role"], row["confidence"]) == ("remixed_by_other", HIGH)


# --------------------------------------------------------------------------- featured / uncertain


class TestFeaturedAndUncertain:
    @pytest.mark.parametrize(
        "title",
        [
            "Skrillex - Bangarang feat. Boys Noize",
            "Skrillex - Bangarang (feat. Boys Noize)",
            "Skrillex - Bangarang (ft. Boys Noize) (Erol Alkan Remix)",
            "Title (with Boys Noize)",
        ],
    )
    def test_featured_credit_only_is_featured(self, title) -> None:
        row = one(sc("1", title))
        assert row["role"] == "featured"
        assert row["credit_parse"]["featured"] == [ARTIST]
        assert row["auto_queue_allowed"] is False

    def test_with_in_running_text_is_not_a_feature(self) -> None:
        row = one(sc("1", "Dancing with Boys Noize Tonight"))
        assert row["credit_parse"]["featured"] == []
        assert row["role"] == "uncertain"

    def test_name_only_in_tags_is_uncertain(self) -> None:
        row = one(sc("1", "Some Track", tag_list='techno "Boys Noize" berlin'))
        assert (row["role"], row["confidence"]) == ("uncertain", LOW)
        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_TAGS

    def test_near_spelling_is_uncertain_and_named(self) -> None:
        row = one(sc("1", "Overdrive", uploader_name="boysnoize"))
        assert row["role"] == "uncertain"
        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_NEAR_MATCH
        assert row["credit_parse"]["near_match"] == "boysnoize"

    def test_no_credit_at_all_is_uncertain_and_says_so(self) -> None:
        row = one(sc("1", "Nothing Here"))
        assert (row["role"], row["confidence"]) == ("uncertain", LOW)
        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_NONE
        assert row["credit_parse"]["reason"]

    def test_every_track_gets_exactly_one_role(self) -> None:
        rows = idn.classify_roles(
            [sc(str(i), t) for i, t in enumerate(["A - B", "C (D Remix)", "E", "F feat. G"])],
            ARTIST_URN,
            [ARTIST],
        )
        assert len(rows) == 4
        assert all(r["role"] in idn.ROLES and r["confidence"] in idn.CONFIDENCES for r in rows)


# --------------------------------------------------------------------------- aliases


class TestAliases:
    def test_alias_spellings_resolve_like_the_canonical_name(self) -> None:
        names = [ARTIST, "BOYS NOIZE", "Boyz Noize", "Dog Blood"]
        assert role_of(sc("1", "Boyz Noize - Overdrive"), names=names)[0] == "primary"
        assert role_of(sc("2", "Dog Blood - Middle Finger"), names=names)[0] == "primary"
        assert role_of(sc("3", "Title (Dog Blood Remix)"), names=names)[0] == "remixer"

    def test_without_the_alias_the_same_title_is_not_attributed(self) -> None:
        assert role_of(sc("1", "Dog Blood - Middle Finger"))[0] == "uncertain"

    def test_fold_key_variants_of_the_canonical_name_match(self) -> None:
        # fold_key: case, whitespace, ./-/_ separators, apostrophes, & <-> and.
        assert role_of(sc("1", "BOYS  NOIZE - Overdrive"))[0] == "primary"
        assert role_of(sc("2", "Boys-Noize - Overdrive"))[0] == "primary"

    def test_registry_names_feed_classify_for_collection(self, store, collection) -> None:
        store.add_alias(collection, "Boyz Noize", source="merge")
        store.set_link(collection, "soundcloud", ARTIST_URN, "boysnoize", 1.0)
        rows = idn.classify_for_collection(
            collection, [sc("1", "Boyz Noize - Overdrive")], remember=False
        )
        assert rows[0]["role"] == "primary"


# --------------------------------------------------------------------------- auto-queue rule


class TestAutoQueueRule:
    @pytest.mark.parametrize("confidence", sorted(idn.CONFIDENCES))
    def test_uncertain_is_never_eligible(self, confidence) -> None:
        assert idn.auto_queue_eligible("uncertain", confidence) is False

    @pytest.mark.parametrize("role", ["featured", "remixed_by_other"])
    @pytest.mark.parametrize("confidence", sorted(idn.CONFIDENCES))
    def test_review_only_roles_are_never_eligible(self, role, confidence) -> None:
        assert idn.auto_queue_eligible(role, confidence) is False

    @pytest.mark.parametrize("role", ["primary", "remixer"])
    def test_primary_and_remixer_need_high_or_medium(self, role) -> None:
        assert idn.auto_queue_eligible(role, HIGH) is True
        assert idn.auto_queue_eligible(role, MEDIUM) is True
        assert idn.auto_queue_eligible(role, LOW) is False

    def test_classified_flag_uses_the_same_rule(self) -> None:
        rows = idn.classify_roles(
            [
                sc("1", "Boys Noize - Overdrive"),
                sc("2", "Overdrive (Boys Noize Remix)"),
                sc("3", "Boys Noize - Overdrive (Erol Alkan Remix)"),
                sc("4", "Nothing Here"),
            ],
            ARTIST_URN,
            [ARTIST],
        )
        flags = {r["sc_id"].rsplit(":", 1)[1]: r["auto_queue_allowed"] for r in rows}
        assert flags == {"1": True, "2": True, "3": False, "4": False}
        for r in rows:
            assert r["auto_queue_allowed"] == idn.auto_queue_eligible(r["role"], r["confidence"])

    def test_an_owned_track_is_never_queued_whatever_its_role(self) -> None:
        owned = {**sc("1", "Boys Noize - Overdrive"), "in_library": True}
        missing = {**sc("2", "Boys Noize - Overdrive"), "in_library": False}
        rows = idn.classify_roles([owned, missing], ARTIST_URN, [ARTIST])
        assert [r["auto_queue_allowed"] for r in rows] == [False, True]
        assert rows[0]["in_library"] is True, "extra keys on the input survive"


# --------------------------------------------------------------------------- user override


class TestUserOverride:
    def test_override_wins_over_the_classifier(self) -> None:
        track = sc("1", "Nothing Here")
        row = one(track, overrides={track["sc_id"]: "primary"})
        assert (row["role"], row["confidence"]) == ("primary", HIGH)
        assert row["identity_source"] == idn.SOURCE_USER_OVERRIDE
        assert row["classifier_role"] == "uncertain"
        assert row["auto_queue_allowed"] is True

    def test_override_can_demote_too(self) -> None:
        track = sc("1", "Boys Noize - Overdrive")
        row = one(track, overrides={track["sc_id"]: "uncertain"})
        assert row["role"] == "uncertain"
        assert row["auto_queue_allowed"] is False

    def test_unknown_override_role_is_refused(self) -> None:
        track = sc("1", "Boys Noize - Overdrive")
        with pytest.raises(ValueError, match="override"):
            one(track, overrides={track["sc_id"]: "owner"})

    def test_stored_override_wins_on_every_subsequent_pass(self, store, collection) -> None:
        store.set_link(collection, "soundcloud", ARTIST_URN, "boysnoize", 1.0)
        track = sc("1", "Nothing Here")

        first = idn.classify_for_collection(collection, [track])
        assert first[0]["role"] == "uncertain"
        assert idn.set_override(collection, track["sc_id"], "primary") is True

        for _ in range(2):
            again = idn.classify_for_collection(collection, [track])
            assert again[0]["role"] == "primary"
            assert again[0]["identity_source"] == idn.SOURCE_USER_OVERRIDE

        stored = store.get_track_identity(collection, track["sc_id"])
        assert stored["user_override"] == "primary"
        assert stored["role"] == "uncertain", "the classifier verdict is kept beside the pin"

    def test_override_on_an_unseen_track_is_refused_not_invented(self, store, collection) -> None:
        assert idn.set_override(collection, "soundcloud:tracks:404", "primary") is False
        assert store.get_track_identity(collection, "soundcloud:tracks:404") is None

    def test_unpin_restores_the_classifier(self, store, collection) -> None:
        track = sc("1", "Nothing Here")
        idn.classify_for_collection(collection, [track], artist_urn=ARTIST_URN, names=[ARTIST])
        idn.set_override(collection, track["sc_id"], "primary")
        idn.set_override(collection, track["sc_id"], None)
        rows = idn.classify_for_collection(
            collection, [track], artist_urn=ARTIST_URN, names=[ARTIST]
        )
        assert rows[0]["role"] == "uncertain"
        assert rows[0]["identity_source"] == idn.SOURCE_CLASSIFIER


# --------------------------------------------------------------------------- remember_identities


class TestRememberIdentities:
    def test_upsert_count_and_round_trip(self, store, collection) -> None:
        rows = idn.classify_roles(
            [
                sc("1", "Boys Noize - Overdrive", isrc="US-RC1-17-07839"),
                sc("2", "Overdrive (Boys Noize Remix)"),
            ],
            ARTIST_URN,
            [ARTIST],
        )
        assert idn.remember_identities(collection, rows) == 2

        stored = {r["sc_urn"]: r for r in store.list_track_identities(collection)}
        assert set(stored) == {"soundcloud:tracks:1", "soundcloud:tracks:2"}
        assert stored["soundcloud:tracks:1"]["isrc"] == "USRC11707839"
        assert stored["soundcloud:tracks:1"]["role"] == "primary"
        assert stored["soundcloud:tracks:2"]["role"] == "remixer"
        assert stored["soundcloud:tracks:2"]["isrc"] is None
        assert stored["soundcloud:tracks:1"]["uploader_urn"] == FOREIGN_URN
        assert store.find_track_identities_by_isrc("USRC11707839")[0]["collection_id"] == collection

    def test_upsert_keeps_first_seen_refreshes_last_seen_and_keeps_the_pin(
        self, store, collection, monkeypatch
    ) -> None:
        track = sc("1", "Nothing Here")
        rows = idn.classify_roles([track], ARTIST_URN, [ARTIST])

        monkeypatch.setattr(store, "_now_iso", lambda: "2026-09-08T10:00:00+00:00")
        idn.remember_identities(collection, rows)
        store.set_identity_override(collection, track["sc_id"], "remixer")

        monkeypatch.setattr(store, "_now_iso", lambda: "2026-09-09T10:00:00+00:00")
        renamed = idn.classify_roles(
            [{**track, "title": "Boys Noize - Now Credited"}], ARTIST_URN, [ARTIST]
        )
        assert idn.remember_identities(collection, renamed) == 1

        row = store.get_track_identity(collection, track["sc_id"])
        assert row["first_seen"] == "2026-09-08T10:00:00+00:00"
        assert row["last_seen"] == "2026-09-09T10:00:00+00:00"
        assert row["role"] == "primary", "classifier verdict is refreshed"
        assert row["user_override"] == "remixer", "the pin is never touched by an upsert"
        assert row["title"] == "Boys Noize - Now Credited"

    def test_one_track_can_hold_a_different_role_per_artist(self, store) -> None:
        # The composite key exists for exactly this: remixer for one, remixed_by_other
        # for the other. A per-track primary key could keep only one of them.
        boys = store.create_collection("Boys Noize")
        skrillex = store.create_collection("Skrillex")
        track = sc("1", "Skrillex - Bangarang (Boys Noize Remix)")
        idn.remember_identities(boys, idn.classify_roles([track], None, ["Boys Noize"]))
        idn.remember_identities(skrillex, idn.classify_roles([track], None, ["Skrillex"]))
        assert store.get_track_identity(boys, track["sc_id"])["role"] == "remixer"
        assert store.get_track_identity(skrillex, track["sc_id"])["role"] == "remixed_by_other"

    def test_rows_without_an_id_are_skipped_not_invented(self, store, collection) -> None:
        assert idn.remember_identities(collection, [{"title": "x", "role": "primary"}]) == 0
        assert store.list_track_identities(collection) == []

    def test_unknown_collection_is_an_integrity_error(self, store) -> None:
        rows = idn.classify_roles([sc("1", "Boys Noize - Overdrive")], None, [ARTIST])
        with pytest.raises(sqlite3.IntegrityError):
            idn.remember_identities("a_deadbeef0000", rows)

    def test_garbage_role_is_refused_by_the_store(self, store, collection) -> None:
        with pytest.raises(ValueError, match="unknown role"):
            store.upsert_track_identity(
                collection, "soundcloud:tracks:1", role="owner", confidence="high"
            )

    def test_cascade_on_collection_delete(self, store, collection) -> None:
        idn.remember_identities(
            collection, idn.classify_roles([sc("1", "Boys Noize - Overdrive")], None, [ARTIST])
        )
        store.delete_collection(collection)
        assert store.find_track_identities_by_isrc("") == []
        conn = store._connect()
        n = conn.execute("SELECT COUNT(*) AS n FROM track_identity").fetchone()["n"]
        assert n == 0

    def test_role_counts_only_count_what_was_classified(self) -> None:
        rows = idn.classify_roles(
            [sc("1", "Boys Noize - Overdrive"), sc("2", "Nothing Here")], None, [ARTIST]
        )
        counts = idn.role_counts(rows)
        assert counts["primary"] == 1 and counts["uncertain"] == 1
        assert sum(counts.values()) == 2


# --------------------------------------------------------------------------- ISRC fast path


class TestIsrcFastPath:
    def test_isrc_match_short_circuits_to_owned(self) -> None:
        local = {
            "7": {
                "id": "7",
                "Title": "Completely Different Title",
                "Artist": "Nobody",
                "ISRC": "US-RC1-17-07839",
            }
        }
        remote = [sc("1", "Overdrive", isrc="USRC11707839")]
        result = cat.diff(local, remote, artist_names=[ARTIST])
        verdict = result.matches["soundcloud:tracks:1"]
        assert result.in_library == ("soundcloud:tracks:1",)
        assert verdict.local_track_id == "7"
        assert verdict.score == 1.0
        assert verdict.method == cat.MATCH_ISRC

    def test_isrc_fast_path_beats_the_derivation_gate(self) -> None:
        # Same recording, retitled as a remix on SoundCloud: the title path would say
        # missing (remix != original); identical ISRC says owned.
        local = [{"id": "7", "Title": "Overdrive", "Artist": ARTIST, "ISRC": "USRC11707839"}]
        remote = [sc("1", "Overdrive (Erol Alkan Remix)", isrc="USRC11707839")]
        assert cat.diff(local, remote).in_library == ("soundcloud:tracks:1",)

    def test_title_path_runs_when_either_side_lacks_an_isrc(self) -> None:
        local = [{"id": "7", "Title": "Overdrive", "Artist": ARTIST, "ISRC": ""}]
        remote = [sc("1", "Boys Noize - Overdrive", isrc="USRC11707839")]
        result = cat.diff(local, remote, artist_names=[ARTIST])
        assert result.matches["soundcloud:tracks:1"].method == cat.MATCH_TITLE
        assert result.in_library == ("soundcloud:tracks:1",)

    def test_different_isrcs_do_not_prevent_a_title_match(self) -> None:
        local = [{"id": "7", "Title": "Overdrive", "Artist": ARTIST, "ISRC": "USRC11700001"}]
        remote = [sc("1", "Boys Noize - Overdrive", isrc="USRC11700002")]
        assert cat.diff(local, remote, artist_names=[ARTIST]).in_library == ("soundcloud:tracks:1",)

    @pytest.mark.parametrize("junk", ["", "0", "unknown", "N/A", "USRC117", "12345678901234"])
    def test_junk_isrcs_never_compare_equal(self, junk) -> None:
        local = [{"id": "7", "Title": "Totally Other", "Artist": "Nobody", "ISRC": junk}]
        remote = [sc("1", "Overdrive", isrc=junk)]
        result = cat.diff(local, remote)
        assert result.missing == ("soundcloud:tracks:1",)
        assert result.matches["soundcloud:tracks:1"].method == cat.MATCH_NONE

    def test_normalize_isrc_shapes(self) -> None:
        assert cat.normalize_isrc("us-rc1-17-07839") == "USRC11707839"
        assert cat.normalize_isrc(" USRC1 1707839 ") == "USRC11707839"
        assert cat.normalize_isrc("USRC11707839") == "USRC11707839"
        assert cat.normalize_isrc(None) == ""
        assert cat.normalize_isrc("GB-ABC-99-1234") == ""

    def test_annotated_catalogue_exposes_the_match_method(self, store) -> None:
        cid = store.create_collection(ARTIST)
        local = {"7": {"id": "7", "Title": "Retitled", "Artist": "Nobody", "ISRC": "USRC11707839"}}
        remote = [
            sc(
                "1", "Overdrive", uploader_urn=ARTIST_URN, uploader_name=ARTIST, isrc="USRC11707839"
            ),
            sc("2", "Rocket Boy", uploader_urn=ARTIST_URN, uploader_name=ARTIST),
        ]
        view = cat.catalogue(
            cid,
            local_tracks=local,
            artist_urn=ARTIST_URN,
            artist_names=[ARTIST],
            fetch=lambda _u: remote,
        )
        by_id = {t["sc_id"]: t for t in view[cat.BUCKET_THEIR_TRACKS]}
        assert by_id["soundcloud:tracks:1"]["match_method"] == cat.MATCH_ISRC
        assert by_id["soundcloud:tracks:1"]["in_library"] is True
        assert by_id["soundcloud:tracks:2"]["match_method"] == cat.MATCH_NONE
        assert by_id["soundcloud:tracks:2"]["in_library"] is False
        assert by_id["soundcloud:tracks:1"]["isrc"] == "USRC11707839"


# --------------------------------------------------------------------------- migration


class TestMigrationV2:
    def test_v1_file_walks_to_v2_and_keeps_its_rows(self, tmp_path, monkeypatch) -> None:
        db_file = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.executescript(schema._DDL_V1)
        conn.execute(
            "INSERT INTO collections (id, kind, canonical_name, sort_key, created_at, updated_at) "
            "VALUES ('a_1', 'artist', 'Boys Noize', 'boys noize', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO favourites (collection_id, added_at) VALUES ('a_1', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO aliases (collection_id, alias, source) VALUES ('a_1', 'BOYS NOIZE', 'merge')"
        )
        schema._set_schema_version(conn, 1)
        conn.commit()
        tables_before = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "track_identity" not in tables_before

        assert schema.migrate(conn) == 2
        assert schema._schema_version(conn) == 2
        tables = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "track_identity" in tables
        assert {"ix_track_identity_collection", "ix_track_identity_isrc"} <= indexes
        assert (
            conn.execute("SELECT canonical_name FROM collections WHERE id='a_1'").fetchone()[0]
            == "Boys Noize"
        )
        assert conn.execute("SELECT COUNT(*) FROM favourites").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0] == 1

        # A second run is a no-op, not a second walk.
        assert schema.migrate(conn) == 2
        conn.close()

    def test_fresh_db_also_gets_the_v2_table(self, store) -> None:
        conn = store._connect()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(track_identity)")}
        assert cols == {
            "sc_urn",
            "collection_id",
            "isrc",
            "title",
            "uploader_urn",
            "role",
            "confidence",
            "first_seen",
            "last_seen",
            "user_override",
        }
        assert store._schema_version(conn) == store.SCHEMA_VERSION == 2

    def test_step_is_registered_for_v1(self) -> None:
        assert 1 in schema._MIGRATIONS
        assert schema._MIGRATIONS[1] is schema._migrate_v1_to_v2


# --------------------------------------------------------------------------- hygiene


class _RecordingLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquisitions = 0

    def __enter__(self):
        self._lock.acquire()
        self.acquisitions += 1
        return self

    def __exit__(self, *exc_info) -> bool:
        self._lock.release()
        return False


class TestHygiene:
    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(
                lambda s, cid: s.upsert_track_identity(
                    cid, "soundcloud:tracks:1", role="primary", confidence="high"
                ),
                id="upsert_track_identity",
            ),
            pytest.param(
                lambda s, cid: s.set_identity_override(cid, "soundcloud:tracks:1", "remixer"),
                id="set_identity_override",
            ),
            pytest.param(
                lambda s, cid: s.delete_track_identity(cid, "soundcloud:tracks:1"),
                id="delete_track_identity",
            ),
        ],
    )
    def test_identity_writers_hold_the_module_lock(
        self, store, collection, monkeypatch, call
    ) -> None:
        recorder = _RecordingLock()
        monkeypatch.setattr(store, "_write_lock", recorder)
        call(store, collection)
        assert recorder.acquisitions >= 1

    def test_identity_reads_do_not_take_the_lock(self, store, collection, monkeypatch) -> None:
        recorder = _RecordingLock()
        monkeypatch.setattr(store, "_write_lock", recorder)
        store.get_track_identity(collection, "soundcloud:tracks:1")
        store.list_track_identities(collection)
        store.get_identity_overrides(collection)
        store.find_track_identities_by_isrc("USRC11707839")
        assert recorder.acquisitions == 0

    def test_identity_module_touches_no_library_writer_and_no_network(self) -> None:
        tree = ast.parse(Path(idn.__file__).read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not imported & {"app.database", "app.live_database", "rbox", "httpx", "requests"}
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not used & {
            "_db_write_lock",
            "db_lock",
            "auth_token",
            "access_token",
            "refresh_token",
        }

    def test_classify_is_pure_no_sidecar_write(self, store, collection) -> None:
        idn.classify_roles([sc("1", "Boys Noize - Overdrive")], ARTIST_URN, [ARTIST])
        assert store.list_track_identities(collection) == []


class TestDisplayNameAloneNeverAutoQueues:
    """A bare display-name match must not spend the user's bandwidth unattended.

    SoundCloud display names are not unique. A tribute page, an impostor or a
    genuinely different act of the same name lands at ``primary``/``medium`` — right,
    because the name really is the artist's — but MEDIUM is otherwise auto-queue
    eligible, so without this gate a pure name collision would download itself.
    The track stays visible and one click from downloading; it just never goes
    unattended. Any corroborating signal clears the gate.
    """

    def test_uploader_name_only_is_primary_but_not_queueable(self) -> None:
        row = one(sc("1", "Some Track", uploader_urn=FOREIGN_URN, uploader_name=ARTIST))

        assert (row["role"], row["confidence"]) == (idn.ROLE_PRIMARY, idn.CONFIDENCE_MEDIUM)
        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_UPLOADER_NAME
        assert row["auto_queue_allowed"] is False, (
            "a foreign account merely NAMED like the artist would auto-download on a "
            "pure name collision"
        )

    def test_a_title_credit_clears_the_gate(self) -> None:
        row = one(sc("2", f"{ARTIST} - Some Track", uploader_urn=FOREIGN_URN, uploader_name=LABEL))

        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_TITLE_PREFIX
        assert row["auto_queue_allowed"] is True

    def test_the_linked_account_clears_the_gate(self) -> None:
        row = one(sc("3", "Some Track", uploader_urn=ARTIST_URN, uploader_name=ARTIST))

        assert row["credit_parse"]["matched_on"] == idn.SIGNAL_UPLOADER_URN
        assert row["auto_queue_allowed"] is True

    def test_the_rule_is_pure_and_signal_aware(self) -> None:
        assert idn.auto_queue_eligible(idn.ROLE_PRIMARY, idn.CONFIDENCE_MEDIUM) is True
        assert (
            idn.auto_queue_eligible(
                idn.ROLE_PRIMARY, idn.CONFIDENCE_MEDIUM, idn.SIGNAL_UPLOADER_NAME
            )
            is False
        )
        assert (
            idn.auto_queue_eligible(idn.ROLE_PRIMARY, idn.CONFIDENCE_HIGH, idn.SIGNAL_UPLOADER_NAME)
            is False
        ), "even HIGH must not rescue a name-only match — HIGH comes from the URN, not the name"
