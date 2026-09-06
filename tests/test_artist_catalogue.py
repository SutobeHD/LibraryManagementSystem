"""Artist-Hub catalogue tests (T-14 — app/artist_store/catalogue.py).

Covers the parts the owner called out and the parts that have burned this feature
before: the three buckets split on the uploader ACCOUNT and never on a name, a foreign
uploader's "(X Remix)" can never reach ``definitely_theirs``, "Original Mix" /
"Extended Mix" survive the mix filter while a 22-minute Boiler Room does not, a
preview/snipped track never enters the missing list, the missing-diff threshold is
pinned in both directions by a seeded corpus, and a second call is served from the
sidecar cache without touching the fetcher.

No network: the fetcher is a local callable that counts its calls. No ``master.db``:
nothing here imports the library. The sidecar is a throwaway file in ``tmp_path``,
monkeypatched the way ``tests/test_artist_store_registry.py`` does it.
"""

from __future__ import annotations

import pytest

from app.artist_store import catalogue as cat
from app.artist_store import schema

ARTIST = "Boys Noize"
ARTIST_URN = "soundcloud:users:1000"
OTHER_URN = "soundcloud:users:2000"


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


def sc_track(
    sc_id: str,
    title: str,
    *,
    uploader_urn: str = ARTIST_URN,
    uploader_name: str = ARTIST,
    duration_ms: int = 5 * 60 * 1000,
    access: str = "playable",
    streamable: bool = True,
    sharing: str = "public",
    downloadable: bool = False,
    genre: str = "Techno",
    tag_list: str = "",
) -> dict:
    """One normalised SC track dict — the contract shape the client hands over."""
    return {
        "sc_id": f"soundcloud:tracks:{sc_id}",
        "title": title,
        "permalink_url": f"https://soundcloud.com/x/{sc_id}",
        "duration_ms": duration_ms,
        "uploader_urn": uploader_urn,
        "uploader_name": uploader_name,
        "genre": genre,
        "tag_list": tag_list,
        "access": access,
        "streamable": streamable,
        "sharing": sharing,
        "downloadable": downloadable,
        "created_at": "2026-01-01T00:00:00Z",
        "artwork_url": "",
    }


def local(track_id: str, title: str, artist: str = ARTIST) -> tuple[str, dict]:
    return track_id, {"id": track_id, "Title": title, "Artist": artist}


def library(*rows: tuple[str, dict]) -> dict[str, dict]:
    return dict(rows)


def titles(bucket: list[dict]) -> list[str]:
    return [t["title"] for t in bucket]


# --------------------------------------------------------------------------- classify


def test_three_buckets_split() -> None:
    result = cat.classify(
        [
            sc_track("1", "Overdrive"),
            sc_track(
                "2", "Mayday (Boys Noize Remix)", uploader_urn=OTHER_URN, uploader_name="Some Label"
            ),
            sc_track("3", "Boiler Room Berlin", duration_ms=22 * 60 * 1000),
        ],
        ARTIST_URN,
        artist_names=[ARTIST],
    )

    assert titles(result.definitely_theirs) == ["Overdrive"]
    assert titles(result.remixes_by_others) == ["Mayday (Boys Noize Remix)"]
    assert titles(result.mixes_and_sets) == ["Boiler Room Berlin"]


def test_definitely_theirs_is_uploader_id_only() -> None:
    """Threat T11: a foreign account naming the artist must never be 'theirs'."""
    result = cat.classify(
        [
            # Same display name, different account — an impostor or a label re-upload.
            sc_track("1", "Overdrive", uploader_urn=OTHER_URN, uploader_name=ARTIST),
            sc_track(
                "2",
                "Kontact Me (Boys Noize Remix)",
                uploader_urn=OTHER_URN,
                uploader_name="Helena Hauff",
            ),
            sc_track("3", "Yeah! (feat. Boys Noize)", uploader_urn=OTHER_URN, uploader_name="Snax"),
        ],
        ARTIST_URN,
        artist_names=[ARTIST],
    )

    assert result.definitely_theirs == []
    assert len(result.remixes_by_others) == 3
    assert all(t["bucket"] == cat.BUCKET_REMIXES for t in result.remixes_by_others)


def test_remix_by_other_never_auto_queued() -> None:
    payload = cat.classify(
        [
            sc_track(
                "1",
                "Overdrive (Helena Hauff Remix)",
                uploader_urn=OTHER_URN,
                uploader_name="Helena Hauff",
            )
        ],
        ARTIST_URN,
        artist_names=[ARTIST],
    )
    annotated = cat._annotate(payload.remixes_by_others, cat.Diff())

    assert annotated[0]["auto_queue_allowed"] is False


def test_missing_urn_can_never_produce_definitely_theirs() -> None:
    """No bound account means no proof of ownership — including for a blank uploader_urn."""
    result = cat.classify([sc_track("1", "Overdrive", uploader_urn="")], "")

    assert result.definitely_theirs == []
    assert titles(result.remixes_by_others) == ["Overdrive"]


def test_urn_and_numeric_id_are_the_same_account() -> None:
    """Numeric ids are deprecated but still in flight; they must not split identity."""
    result = cat.classify([sc_track("1", "Overdrive", uploader_urn="1000")], ARTIST_URN)

    assert titles(result.definitely_theirs) == ["Overdrive"]


def test_foreign_upload_without_a_credit_is_listed_but_flagged() -> None:
    """Nothing fetched is silently dropped; an unproven credit is ranked, not hidden."""
    result = cat.classify(
        [
            sc_track("1", "Some Other Track", uploader_urn=OTHER_URN, uploader_name="Nobody"),
            sc_track(
                "2",
                "Kontact Me (Boys Noize Remix)",
                uploader_urn=OTHER_URN,
                uploader_name="Helena Hauff",
            ),
        ],
        ARTIST_URN,
        artist_names=[ARTIST],
    )

    assert result.definitely_theirs == []
    assert [t["credited"] for t in result.remixes_by_others] == [False, True]


def test_without_artist_names_foreign_uploads_stay_in_the_remix_bucket() -> None:
    """Unproven credit degrades to the visible-but-never-queued bucket, never to 'theirs'."""
    result = cat.classify(
        [sc_track("1", "Some Other Track", uploader_urn=OTHER_URN, uploader_name="Nobody")],
        ARTIST_URN,
    )

    assert result.definitely_theirs == []
    assert titles(result.remixes_by_others) == ["Some Other Track"]


# --------------------------------------------------------------------------- mix filter


@pytest.mark.parametrize(
    "title",
    [
        "Overdrive (Original Mix)",
        "Overdrive (Extended Mix)",
        "Overdrive (Club Mix)",
        "Overdrive - Extended Mix",
        "Remix Session",
    ],
)
def test_mix_words_that_must_survive(title: str) -> None:
    """A bare \\bmix\\b is NOT in the keyword regex — these are the tracks the user wants."""
    assert cat.mix_exclusion_reason(sc_track("1", title)) is None


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("Boiler Room Berlin", "keyword"),
        ("Essential Mix 2026", "keyword"),
        ("Guest Mix for XLR8R", "keyword"),
        ("Mixtape Vol. 3", "keyword"),
        ("BNR Podcast 041", "keyword"),
        ("Live Set at Berghain", "keyword"),
        ("DJ Set — Awakenings", "keyword"),
        ("Radio Show ep. 12", "keyword"),
        ("Episode 7", "keyword"),
        ("Boys Noize b2b Erol Alkan", "keyword"),
        ("Panorama Bar Takeover", "keyword"),
        ("Tresor Residency", "keyword"),
    ],
)
def test_mix_keywords_excluded(title: str, reason: str) -> None:
    assert cat.mix_exclusion_reason(sc_track("1", title)) == reason


def test_long_form_excluded_even_without_a_keyword() -> None:
    twenty_two_min = sc_track("1", "Untitled Jam", duration_ms=22 * 60 * 1000)

    assert cat.mix_exclusion_reason(twenty_two_min) == "long_form"


def test_boiler_room_loses_to_the_filter_while_extended_mix_survives() -> None:
    result = cat.classify(
        [
            sc_track("1", "Overdrive (Extended Mix)"),
            sc_track("2", "Boiler Room Berlin", duration_ms=22 * 60 * 1000),
        ],
        ARTIST_URN,
    )

    assert titles(result.definitely_theirs) == ["Overdrive (Extended Mix)"]
    assert titles(result.mixes_and_sets) == ["Boiler Room Berlin"]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("access", "preview"), ("access", "blocked"), ("streamable", False), ("sharing", "private")],
)
def test_not_fully_playable_is_excluded(field_name: str, value: object) -> None:
    """A snippet is not the track — a preview must never reach the missing list."""
    track = sc_track("1", "Overdrive")
    track[field_name] = value

    assert cat.mix_exclusion_reason(track) == "unavailable"


def test_preview_track_is_kept_out_of_definitely_theirs() -> None:
    result = cat.classify(
        [sc_track("1", "Overdrive", access="preview")], ARTIST_URN, artist_names=[ARTIST]
    )

    assert result.definitely_theirs == []
    assert result.mixes_and_sets[0]["excluded_reason"] == "unavailable"


def test_downloadable_is_never_a_filter() -> None:
    result = cat.classify([sc_track("1", "Overdrive", downloadable=False)], ARTIST_URN)

    assert titles(result.definitely_theirs) == ["Overdrive"]


# --------------------------------------------------------------------------- coercion


def test_hostile_payload_rows_are_dropped_not_invented() -> None:
    rows = cat.coerce_tracks(
        [
            None,
            "not a dict",
            {"title": "no id"},
            {"sc_id": "soundcloud:tracks:9"},  # no title
            {**sc_track("1", "Overdrive"), "duration_ms": "nonsense"},
            sc_track("1", "Overdrive"),  # duplicate sc_id
        ]
    )

    assert [r["sc_id"] for r in rows] == ["soundcloud:tracks:1"]
    assert rows[0]["duration_ms"] == 0


# --------------------------------------------------------------------------- diff corpus

#: (remote title, remote uploader name, local title, local artist)
SHOULD_MATCH = [
    ("Overdrive (Original Mix)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Extended Mix)", ARTIST, "Overdrive", ARTIST),
    ("Transmission [Original Mix]", ARTIST, "Transmission", ARTIST),
    ("Starchild - Extended Mix", ARTIST, "Starchild", ARTIST),
    ("Ich R U", ARTIST, "Ich R. U.", ARTIST),
    ("XTC", ARTIST, "xtc", ARTIST),
    ("  Mvinline  ", ARTIST, "Mvinline", ARTIST),
    ("Cafe Racer", ARTIST, "Café Racer", ARTIST),
    ("Boys Noize - Overdrive", ARTIST, "Overdrive", ARTIST),
    ("Yeah! (feat. Snax)", ARTIST, "Yeah!", ARTIST),
    ("Nott (Original Mix)", ARTIST, "NOTT", "BOYS NOIZE"),
    ("Adonis", ARTIST, "Adonis", "Boys Noize & Erol Alkan"),
    ("Rock & Roll", ARTIST, "Rock and Roll", ARTIST),
    ("Rock the Bells", ARTIST, "Rock Bells", ARTIST),
]

MUST_NOT_MATCH = [
    # a remix vs the original
    ("Overdrive (Helena Hauff Remix)", "Helena Hauff", "Overdrive", ARTIST),
    ("Overdrive (Erol Alkan Bootleg)", "Erol Alkan", "Overdrive", ARTIST),
    # a VIP vs the original
    ("Overdrive (VIP)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (2019 Edit)", ARTIST, "Overdrive", ARTIST),
    # a BARE derivation vs the original — the shape the first corpus never seeded.
    # parse_version_tag returns None for these (no remixer, no known label), so they
    # used to fold onto ("base", "") and read as ALREADY OWNED: a genuinely missing
    # track hidden, which is the gig-night failure this diff exists to prevent.
    ("Overdrive (Remix)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Reprise)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Live)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Acoustic)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Demo)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Rework)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Refix)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Flip)", ARTIST, "Overdrive", ARTIST),
    ("Overdrive (Mashup)", ARTIST, "Overdrive", ARTIST),
    # a different track by the same artist
    ("Ich R U", ARTIST, "Ich Bin Ein Berliner", ARTIST),
    ("Mvinline", ARTIST, "Mayday", ARTIST),
    ("Jerk Off", ARTIST, "Jerk", ARTIST),
    ("Starchild", ARTIST, "Star", ARTIST),
    ("Rock the Bells", ARTIST, "Rock the Bell", ARTIST),
    ("Kill the Beat", ARTIST, "Kill the Beast", ARTIST),
    ("Nott", ARTIST, "Not", ARTIST),
    ("Yeah Yeah", ARTIST, "Yeah", ARTIST),
    ("Rock the Bells Pt. 2", ARTIST, "Rock the Bells", ARTIST),
]


def _corpus_score(remote_title: str, uploader: str, local_title: str, local_artist: str) -> float:
    remote = sc_track("1", remote_title, uploader_name=uploader)
    index = cat._LocalIndex(library(local("L1", local_title, local_artist)))
    names = cat._artist_names_for(remote)
    stems = cat.title_stems(remote_title, names)
    return max(
        (cat.match_score(remote, entry) for entry in index.candidates(stems, names)),
        default=0.0,
    )


def test_missing_diff_threshold_corpus() -> None:
    """The threshold is pinned by the corpus, not by taste.

    Both directions must clear :data:`cat.MISSING_MATCH_THRESHOLD`; the assertion on the
    separation window is what fails loudly if someone retunes the constant or the gates.
    """
    should = {row[0]: _corpus_score(*row) for row in SHOULD_MATCH}
    must_not = {(row[0], row[2]): _corpus_score(*row) for row in MUST_NOT_MATCH}

    below = {k: v for k, v in should.items() if v < cat.MISSING_MATCH_THRESHOLD}
    above = {k: v for k, v in must_not.items() if v >= cat.MISSING_MATCH_THRESHOLD}
    assert not below, f"true pairs scored below the threshold: {below}"
    assert not above, f"false pairs scored at or above the threshold: {above}"

    # Recall 14/14 and precision 13/13 on this corpus leave a real window, not a hairline.
    assert min(should.values()) > max(must_not.values())
    assert min(should.values()) - max(must_not.values()) >= 0.04


def test_diff_splits_owned_from_missing() -> None:
    owned = library(local("L1", "Overdrive"), local("L2", "Mvinline"))
    remote = [
        sc_track("1", "Overdrive (Original Mix)"),
        sc_track("2", "Kill the Beat"),
    ]

    result = cat.diff(owned, remote)

    assert result.in_library == ("soundcloud:tracks:1",)
    assert result.missing == ("soundcloud:tracks:2",)
    assert result.matches["soundcloud:tracks:1"].local_track_id == "L1"
    assert result.matches["soundcloud:tracks:2"].matched is False


def test_diff_accepts_a_plain_sequence_of_tracks() -> None:
    result = cat.diff(
        [{"id": "L9", "Title": "Overdrive", "Artist": ARTIST}], [sc_track("1", "Overdrive")]
    )

    assert result.matches["soundcloud:tracks:1"].local_track_id == "L9"


def test_remix_is_reported_missing_even_when_the_original_is_owned() -> None:
    owned = library(local("L1", "Overdrive"))
    remote = [
        sc_track(
            "1",
            "Overdrive (Helena Hauff Remix)",
            uploader_urn=OTHER_URN,
            uploader_name="Helena Hauff",
        )
    ]

    assert cat.diff(owned, remote).missing == ("soundcloud:tracks:1",)


def test_owned_remix_matches_its_own_remote_listing() -> None:
    owned = library(local("L1", "Overdrive (Helena Hauff Remix)"))
    remote = [
        sc_track(
            "1",
            "Overdrive (Helena Hauff Remix)",
            uploader_urn=OTHER_URN,
            uploader_name="Helena Hauff",
        )
    ]

    assert cat.diff(owned, remote).in_library == ("soundcloud:tracks:1",)


def test_empty_library_reports_everything_missing() -> None:
    result = cat.diff({}, [sc_track("1", "Overdrive")])

    assert result.missing == ("soundcloud:tracks:1",)


# --------------------------------------------------------------------------- catalogue


class _Fetcher:
    """Counts calls so 'served from cache' is proven, not assumed."""

    def __init__(self, tracks: list[dict]) -> None:
        self.tracks = tracks
        self.calls = 0
        self.seen_urns: list[str] = []

    def __call__(self, artist_urn: str) -> list[dict]:
        self.calls += 1
        self.seen_urns.append(artist_urn)
        return self.tracks


def _linked_collection() -> str:
    cid = schema.create_collection(ARTIST)
    schema.set_link(
        cid,
        cat.PROVIDER_SOUNDCLOUD,
        remote_id=ARTIST_URN,
        permalink="https://soundcloud.com/boysnoize",
    )
    return cid


def test_catalogue_ties_buckets_and_diff_together() -> None:
    cid = _linked_collection()
    fetch = _Fetcher(
        [
            sc_track("1", "Overdrive (Original Mix)"),
            sc_track("2", "Kill the Beat"),
            sc_track(
                "3", "Mayday (Boys Noize Remix)", uploader_urn=OTHER_URN, uploader_name="Some Label"
            ),
            sc_track("4", "Boiler Room Berlin", duration_ms=22 * 60 * 1000),
        ]
    )

    payload = cat.catalogue(
        cid,
        local_tracks=library(local("L1", "Overdrive")),
        artist_names=[ARTIST],
        fetch=fetch,
    )

    assert set(payload) == {
        cat.BUCKET_THEIRS,
        cat.BUCKET_REMIXES,
        cat.BUCKET_MIXES,
        "in_library",
        "fetched_at",
        "from_cache",
        "truncated",
    }
    assert titles(payload[cat.BUCKET_THEIRS]) == ["Overdrive (Original Mix)", "Kill the Beat"]
    assert titles(payload[cat.BUCKET_REMIXES]) == ["Mayday (Boys Noize Remix)"]
    assert titles(payload[cat.BUCKET_MIXES]) == ["Boiler Room Berlin"]
    assert payload["in_library"] == ["soundcloud:tracks:1"]
    assert payload["from_cache"] is False
    assert payload["truncated"] is False
    owned, missing = payload[cat.BUCKET_THEIRS]
    assert owned["in_library"] is True and owned["auto_queue_allowed"] is False
    assert missing["in_library"] is False and missing["auto_queue_allowed"] is True
    # Mixes are excluded from the diff, so their ownership is unknown, not "no".
    mix = payload[cat.BUCKET_MIXES][0]
    assert mix["in_library"] is None and mix["match_score"] is None
    assert mix["auto_queue_allowed"] is False


def test_second_call_is_served_from_cache_without_refetching() -> None:
    cid = _linked_collection()
    fetch = _Fetcher([sc_track("1", "Overdrive")])

    first = cat.catalogue(cid, local_tracks={}, fetch=fetch)
    second = cat.catalogue(cid, local_tracks={}, fetch=fetch)

    assert fetch.calls == 1
    assert first["from_cache"] is False
    assert second["from_cache"] is True
    assert second["fetched_at"] == first["fetched_at"]
    assert titles(second[cat.BUCKET_THEIRS]) == ["Overdrive"]


def test_cache_holds_the_catalogue_not_the_diff() -> None:
    """The local side moves whenever the library does, so the cached hit must re-diff."""
    cid = _linked_collection()
    fetch = _Fetcher([sc_track("1", "Overdrive")])

    cat.catalogue(cid, local_tracks={}, fetch=fetch)
    after_download = cat.catalogue(cid, local_tracks=library(local("L1", "Overdrive")), fetch=fetch)

    assert fetch.calls == 1
    assert after_download["from_cache"] is True
    assert after_download["in_library"] == ["soundcloud:tracks:1"]


def test_expired_cache_refetches() -> None:
    cid = _linked_collection()
    fetch = _Fetcher([sc_track("1", "Overdrive")])

    cat.catalogue(cid, local_tracks={}, fetch=fetch)
    cat.catalogue(cid, local_tracks={}, fetch=fetch, max_age_s=-1)

    assert fetch.calls == 2


def test_force_refresh_bypasses_the_cache() -> None:
    cid = _linked_collection()
    fetch = _Fetcher([sc_track("1", "Overdrive")])

    cat.catalogue(cid, local_tracks={}, fetch=fetch)
    payload = cat.catalogue(cid, local_tracks={}, fetch=fetch, force_refresh=True)

    assert fetch.calls == 2
    assert payload["from_cache"] is False


def test_cache_is_ignored_after_rebinding_to_another_account() -> None:
    cid = _linked_collection()
    fetch = _Fetcher([sc_track("1", "Overdrive")])
    cat.catalogue(cid, local_tracks={}, fetch=fetch)

    schema.set_link(cid, cat.PROVIDER_SOUNDCLOUD, remote_id=OTHER_URN)
    cat.catalogue(cid, local_tracks={}, fetch=fetch)

    assert fetch.calls == 2
    assert fetch.seen_urns == [ARTIST_URN, OTHER_URN]


def test_catalogue_uses_the_bound_urn_when_none_is_passed() -> None:
    cid = _linked_collection()
    fetch = _Fetcher([])

    cat.catalogue(cid, local_tracks={}, fetch=fetch)

    assert fetch.seen_urns == [ARTIST_URN]


def test_unlinked_artist_raises_instead_of_looking_empty() -> None:
    cid = schema.create_collection("Unbound Artist")

    with pytest.raises(cat.ArtistNotLinked):
        cat.catalogue(cid, local_tracks={}, fetch=_Fetcher([]))


def test_no_fetcher_and_no_cache_raises_instead_of_faking_a_sync() -> None:
    cid = _linked_collection()

    with pytest.raises(cat.CatalogueUnavailable):
        cat.catalogue(cid, local_tracks={})


def test_cached_catalogue_still_serves_without_a_fetcher() -> None:
    cid = _linked_collection()
    cat.catalogue(cid, local_tracks={}, fetch=_Fetcher([sc_track("1", "Overdrive")]))

    payload = cat.catalogue(cid, local_tracks={})

    assert payload["from_cache"] is True
    assert titles(payload[cat.BUCKET_THEIRS]) == ["Overdrive"]


def test_track_cap_truncates_and_reports_it() -> None:
    cid = _linked_collection()
    fetch = _Fetcher([sc_track(str(i), f"Track {i}") for i in range(12)])

    payload = cat.catalogue(cid, local_tracks={}, fetch=fetch, max_tracks=10)

    assert payload["truncated"] is True
    assert len(payload[cat.BUCKET_THEIRS]) == 10


def test_fetcher_reported_truncation_is_carried_through() -> None:
    """A fetch cut short by the client's call budget must not read as a complete catalogue."""

    class _PartialResult(list):
        truncated = True
        stop_reason = "call_budget_exhausted"

    cid = _linked_collection()

    def fetch(_urn: str) -> _PartialResult:
        return _PartialResult([sc_track("1", "Overdrive")])

    payload = cat.catalogue(cid, local_tracks={}, fetch=fetch)

    assert payload["truncated"] is True
    assert len(payload[cat.BUCKET_THEIRS]) == 1


def test_catalogue_logs_no_credentials(caplog) -> None:
    """The module never receives the OAuth token; nothing about it may reach the log."""
    cid = _linked_collection()
    with caplog.at_level("DEBUG", logger="ARTIST_STORE"):
        cat.catalogue(cid, local_tracks={}, fetch=_Fetcher([sc_track("1", "Overdrive")]))

    text = caplog.text.casefold()
    assert "op=artist_catalogue" in text
    assert "token" not in text
    assert "oauth" not in text


class TestBareDerivationsAreNotOwned:
    """Regression: a parenthetical with no remixer used to collapse onto the original.

    ``parse_version_tag`` only recognises a parenthetical naming a remixer or carrying a
    label it knows, so "(Remix)" / "(Live)" / "(Flip)" fell through to ``("base", "")``
    — the same key as the plain title — and ``extract_title_stem`` strips the
    parenthetical, so the stems matched exactly and the fuzzy scorer short-circuited to
    1.0. The remote track was then reported as already in the library.
    """

    @pytest.mark.parametrize(
        "suffix",
        ["Remix", "Reprise", "Live", "Acoustic", "Demo", "Rework", "Refix", "Flip", "Mashup"],
    )
    def test_bare_derivation_gets_its_own_key(self, suffix) -> None:
        assert cat.derivation_key(f"Overdrive ({suffix})") != cat.derivation_key("Overdrive")

    @pytest.mark.parametrize(
        "suffix", ["Original Mix", "Extended Mix", "Club Mix", "Radio Mix", "Dub Mix"]
    )
    def test_base_labels_still_fold_onto_the_original(self, suffix) -> None:
        assert cat.derivation_key(f"Overdrive ({suffix})") == cat.derivation_key("Overdrive")

    def test_a_bare_derivation_reads_as_missing_not_owned(self) -> None:
        lib = library(local("L1", "Overdrive", ARTIST))
        remote = [
            sc_track("1", "Overdrive (Remix)"),
            sc_track("2", "Overdrive (Live)"),
            sc_track("3", "Overdrive"),
        ]

        result = cat.diff(lib, remote)

        assert set(result.missing) == {"soundcloud:tracks:1", "soundcloud:tracks:2"}, (
            "a bare derivation collapsed onto the original — a missing track would be "
            "reported as already owned"
        )
        assert set(result.in_library) == {"soundcloud:tracks:3"}
