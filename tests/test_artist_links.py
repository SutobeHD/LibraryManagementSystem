"""Social-link tests (T-22 / T-23, Threats T13 T15 — app/artist_store/links.py).

Owner refinement 2026-09-26: find where an artist lives online. What is pinned here:

* ``classify_url`` is the only gate from an untrusted string to a stored link — the
  table below is the contract: services, handles, canonical https, and every hostile
  shape refused (script schemes, credentials, IPs, odd ports, lookalike hosts).
* Precedence manual > SoundCloud profile > MusicBrainz > bio, a hidden link stays
  hidden across refreshes, and a source that failed keeps what it gave before.
* MusicBrainz only binds through the linked SoundCloud URL or the user's pick; a name
  match is a candidate, never a binding.

No network: SoundCloud and MusicBrainz are fakes; the store is a throwaway SQLite file.
"""

from __future__ import annotations

import pytest

from app import musicbrainz_client as mb_client
from app.artist_store import links, schema

MBID = "d2f4a968-1f6e-4a4a-9376-ee2b2a50c87a"
OTHER_MBID = "a1f4a968-1f6e-4a4a-9376-ee2b2a50c87b"


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


@pytest.fixture
def cid() -> str:
    return schema.create_collection("Boys Noize")


# --------------------------------------------------------------------------- classify


@pytest.mark.parametrize(
    ("raw", "service", "url", "handle"),
    [
        (
            "https://www.instagram.com/boysnoize/",
            "instagram",
            "https://www.instagram.com/boysnoize",
            "@boysnoize",
        ),
        (
            "instagram.com/BoysNoize?igshid=abc",
            "instagram",
            "https://www.instagram.com/BoysNoize",
            "@BoysNoize",
        ),
        ("https://twitter.com/boysnoize", "x", "https://x.com/boysnoize", "@boysnoize"),
        (
            "https://www.tiktok.com/@boysnoize",
            "tiktok",
            "https://www.tiktok.com/@boysnoize",
            "@boysnoize",
        ),
        (
            "https://m.facebook.com/boysnoize",
            "facebook",
            "https://www.facebook.com/boysnoize",
            "boysnoize",
        ),
        (
            "https://www.facebook.com/profile.php?id=123",
            "facebook",
            "https://www.facebook.com/profile.php?id=123",
            None,
        ),
        (
            "https://www.youtube.com/@boysnoize",
            "youtube",
            "https://www.youtube.com/@boysnoize",
            "@boysnoize",
        ),
        (
            "https://www.youtube.com/channel/UC1eE",
            "youtube",
            "https://www.youtube.com/channel/UC1eE",
            None,
        ),
        (
            "https://open.spotify.com/intl-de/artist/62k5LK?si=x",
            "spotify",
            "https://open.spotify.com/artist/62k5LK",
            None,
        ),
        (
            "https://itunes.apple.com/us/artist/id60393190",
            "apple_music",
            "https://music.apple.com/us/artist/60393190",
            None,
        ),
        ("https://www.deezer.com/de/artist/27", "deezer", "https://www.deezer.com/artist/27", None),
        (
            "https://boysnoize.bandcamp.com/album/x",
            "bandcamp",
            "https://boysnoize.bandcamp.com/",
            "boysnoize",
        ),
        (
            "https://www.beatport.com/artist/boys-noize/5139",
            "beatport",
            "https://www.beatport.com/artist/boys-noize/5139",
            "boys-noize",
        ),
        (
            "https://www.residentadvisor.net/dj/BoysNoize",
            "resident_advisor",
            "https://ra.co/dj/boysnoize",
            "BoysNoize",
        ),
        (
            "https://www.discogs.com/de/artist/243374-Boys-Noize",
            "discogs",
            "https://www.discogs.com/artist/243374-Boys-Noize",
            None,
        ),
        (
            "https://soundcloud.com/boysnoize",
            "soundcloud",
            "https://soundcloud.com/boysnoize",
            "boysnoize",
        ),
        ("https://linktr.ee/boysnoize", "linktree", "https://linktr.ee/boysnoize", "boysnoize"),
        (
            "https://www.boysnoize.com/tour/",
            "website",
            "https://www.boysnoize.com/tour",
            "boysnoize.com",
        ),
    ],
)
def test_classify_known_shapes(raw, service, url, handle) -> None:
    found = links.classify_url(raw, allow_website=True)

    assert found is not None
    assert (found.service, found.url, found.handle) == (service, url, handle)


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html,<b>x</b>",
        "file:///C:/Windows/System32/calc.exe",
        "\\\\server\\share\\x.exe",
        "https://user:pw@www.instagram.com/x",
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://localhost/x",
        "https://example.com:8443/x",
        "https://exa mple.com/x",
        "https://example.com/\x00",
        "https://" + "a" * 2100 + ".com",
        "ftp://example.com/x",
        "boysnoize",
        "",
        None,
    ],
)
def test_hostile_or_useless_input_is_refused(raw) -> None:
    assert links.classify_url(raw, allow_website=True) is None


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.instagram.com/p/Cx123/",
        "https://x.com/boysnoize/status/1",
        "https://soundcloud.com/boysnoize/overdrive",
        "https://www.youtube.com/watch?v=abc",
        "https://www.facebook.com/sharer.php?u=x",
        "https://ra.co/clubs/1",
        "https://open.spotify.com/track/1",
    ],
)
def test_posts_tracks_and_share_dialogs_are_not_profiles(raw) -> None:
    assert links.classify_url(raw, allow_website=True) is None


def test_lookalike_hosts_are_never_the_service() -> None:
    for raw in (
        "https://instagram.com.evil.io/boysnoize",
        "https://notinstagram.com/boysnoize",
        "https://\u0456nstagram.com/boysnoize",  # Cyrillic i
    ):
        assert links.classify_url(raw) is None
        found = links.classify_url(raw, allow_website=True)
        assert found is not None and found.service == "website"
    idn = links.classify_url("https://\u0456nstagram.com/boysnoize", allow_website=True)
    assert idn is not None and idn.url.startswith("https://xn--")


def test_one_key_per_profile_however_it_is_spelled() -> None:
    spellings = [
        "https://www.instagram.com/boysnoize/",
        "http://instagram.com/BoysNoize",
        "instagram.com/boysnoize?utm_source=x#top",
    ]
    assert {links.classify_url(s).url_key for s in spellings} == {"instagram:boysnoize"}


# --------------------------------------------------------------------------- bio


def test_bio_yields_known_services_and_labelled_handles_only() -> None:
    bio = (
        "Booking: agent@agency.com | IG: @boysnoize | TikTok @boysnoize\n"
        "twitter - @boysnoize. Stream: https://open.spotify.com/artist/62k5LK.\n"
        "Label: https://boysnoizerecords.com (not me) · boysnoize.bandcamp.com/music"
    )

    found = {c.service: c for c in links.extract_bio_links(bio)}

    assert set(found) == {"instagram", "tiktok", "x", "spotify", "bandcamp"}
    assert found["spotify"].url == "https://open.spotify.com/artist/62k5LK"
    assert "website" not in found


def test_an_email_is_not_a_handle() -> None:
    assert links.extract_bio_links("contact: bookings@boysnoize.com") == []


# --------------------------------------------------------------------------- manual + hide


def test_manual_link_is_stored_and_listed(cid) -> None:
    row = links.add_manual_link(cid, "https://www.instagram.com/boysnoize/")

    assert row["source"] == "manual"
    listed = links.list_links(cid)["links"]
    assert [(link["service"], link["url"]) for link in listed] == [
        ("instagram", "https://www.instagram.com/boysnoize")
    ]


def test_manual_link_refuses_a_script_url(cid) -> None:
    with pytest.raises(ValueError):
        links.add_manual_link(cid, "javascript:alert(document.cookie)")
    assert links.list_links(cid)["links"] == []


def test_removing_a_manual_link_deletes_it(cid) -> None:
    links.add_manual_link(cid, "https://ra.co/dj/boysnoize")

    assert links.remove_link(cid, "resident_advisor:boysnoize") == "deleted"
    assert links.list_links(cid)["hidden_count"] == 0
    assert links.remove_link(cid, "resident_advisor:boysnoize") is None


# --------------------------------------------------------------------------- refresh


class _FakeMB:
    def __init__(self, *, anchored=None, relations=None, search=None, fail=False) -> None:
        self.anchored = anchored or []
        self.relations = relations or []
        self.search = search or []
        self.fail = fail
        self.calls: list[str] = []

    def artists_for_url(self, url):
        self.calls.append(f"url:{url}")
        if self.fail:
            raise mb_client.MusicBrainzUnavailable("down")
        return self.anchored

    def artist_with_urls(self, mbid):
        self.calls.append(f"artist:{mbid}")
        if self.fail:
            raise mb_client.MusicBrainzUnavailable("down")
        return {"mbid": mbid, "name": "Boys Noize", "relations": self.relations}

    def search_artists(self, name, limit=5):
        self.calls.append(f"search:{name}")
        if self.fail:
            raise mb_client.MusicBrainzUnavailable("down")
        return self.search


PROFILE = {
    "urn": "soundcloud:users:1",
    "username": "Boys Noize",
    "permalink_url": "https://soundcloud.com/boysnoize",
    "website": "https://www.boysnoize.com",
    "website_title": "Official",
    "description": "IG: @boysnoize",
}
WEB_PROFILES = [
    {"service": "instagram", "url": "https://instagram.com/boysnoize", "title": "Instagram"},
    {"service": "bandcamp", "url": "https://boysnoize.bandcamp.com/", "title": ""},
]


def _sc(profile=PROFILE, web=WEB_PROFILES, error=None):
    def user_fetch(urn, token, budget=None):
        if error is not None:
            raise error
        return profile

    def profiles_fetch(urn, token, budget=None):
        return web

    return {"sc_user_fetch": user_fetch, "sc_profiles_fetch": profiles_fetch}


def _refresh(cid, *, mb, linked=True, **sc):
    return links.refresh(
        cid,
        names=("Boys Noize",),
        sc_urn="soundcloud:users:1" if linked else "",
        sc_permalink="https://soundcloud.com/boysnoize" if linked else None,
        token="tok" if linked else "",
        mb=mb,
        **(sc or _sc()),
    )


def test_refresh_merges_soundcloud_and_anchored_musicbrainz(cid) -> None:
    mb = _FakeMB(
        anchored=[{"mbid": MBID, "name": "Boys Noize"}],
        relations=[
            {"type": "social network", "url": "https://www.instagram.com/boysnoize/"},
            {"type": "other databases", "url": "https://ra.co/dj/boysnoize"},
            {"type": "other databases", "url": "http://viaf.org/viaf/329751"},
            {"type": "official homepage", "url": "https://www.boysnoize.com/"},
            {"type": "social network", "url": "https://twitter.com/old", "ended": True},
        ],
    )

    result = _refresh(cid, mb=mb)

    assert result["sources"] == {"soundcloud": "ok", "musicbrainz": "ok"}
    by_service = {link["service"]: link for link in result["links"]}
    assert set(by_service) == {"soundcloud", "instagram", "bandcamp", "resident_advisor", "website"}
    # The artist's own SoundCloud profile outranks MusicBrainz for the same profile.
    assert by_service["instagram"]["source"] == "soundcloud_profile"
    assert by_service["resident_advisor"]["source"] == "musicbrainz"
    assert result["musicbrainz"] == {
        "mbid": MBID,
        "url": f"https://musicbrainz.org/artist/{MBID}",
        "anchored": True,
    }
    assert "url:https://soundcloud.com/boysnoize" in mb.calls


def test_bio_links_are_low_and_lose_to_the_profile(cid) -> None:
    sc = _sc(web=[], profile={**PROFILE, "description": "IG: @boysnoize · TikTok @bn"})

    result = _refresh(cid, mb=_FakeMB(), **sc)

    by_service = {link["service"]: link for link in result["links"]}
    assert by_service["instagram"]["source"] == "soundcloud_bio"
    assert by_service["instagram"]["confidence"] == "low"


def test_a_hidden_link_stays_hidden_after_a_refresh(cid) -> None:
    _refresh(cid, mb=_FakeMB())
    assert links.remove_link(cid, "instagram:boysnoize") == "hidden"

    result = _refresh(cid, mb=_FakeMB())

    assert "instagram" not in {link["service"] for link in result["links"]}
    assert result["hidden_count"] == 1
    assert links.restore_hidden(cid) == 1
    assert "instagram" in {link["service"] for link in links.list_links(cid)["links"]}


def test_manual_link_is_never_overwritten_by_a_fetch(cid) -> None:
    links.add_manual_link(cid, "https://www.instagram.com/boysnoize")

    result = _refresh(cid, mb=_FakeMB())

    instagram = next(link for link in result["links"] if link["service"] == "instagram")
    assert instagram["source"] == "manual"


def test_a_failed_source_keeps_what_it_gave_before(cid) -> None:
    mb_ok = _FakeMB(
        anchored=[{"mbid": MBID}],
        relations=[{"type": "other databases", "url": "https://ra.co/dj/boysnoize"}],
    )
    _refresh(cid, mb=mb_ok)

    result = _refresh(cid, mb=_FakeMB(fail=True), **_sc(error=ValueError("bad json")))

    assert result["sources"] == {"soundcloud": "failed", "musicbrainz": "failed"}
    services = {link["service"] for link in result["links"]}
    assert {"resident_advisor", "instagram", "bandcamp"} <= services


def test_a_link_the_source_dropped_goes_when_that_source_answers(cid) -> None:
    _refresh(cid, mb=_FakeMB())

    result = _refresh(cid, mb=_FakeMB(), **_sc(web=[]))

    assert "bandcamp" not in {link["service"] for link in result["links"]}


def test_a_name_match_is_a_candidate_never_a_binding(cid) -> None:
    mb = _FakeMB(
        search=[
            {"mbid": MBID, "name": "Boys Noize", "score": 100, "aliases": []},
            {"mbid": OTHER_MBID, "name": "Boys Noise Band", "score": 95, "aliases": []},
        ]
    )

    result = _refresh(cid, mb=mb, linked=False)

    assert result["sources"] == {"soundcloud": "not_linked", "musicbrainz": "needs_confirmation"}
    assert [c["mbid"] for c in result["musicbrainz_candidates"]] == [MBID]
    assert result["musicbrainz"] is None
    assert result["links"] == []

    binding = links.confirm_musicbrainz(cid, MBID)
    assert binding == {
        "mbid": MBID,
        "url": f"https://musicbrainz.org/artist/{MBID}",
        "anchored": False,
    }


def test_a_low_score_or_other_name_is_not_even_a_candidate(cid) -> None:
    mb = _FakeMB(search=[{"mbid": MBID, "name": "Boys Noize", "score": 60}])

    result = _refresh(cid, mb=mb, linked=False)

    assert result["sources"]["musicbrainz"] == "no_match"
    assert result["musicbrainz_candidates"] == []


def test_an_ambiguous_anchor_binds_nothing(cid) -> None:
    mb = _FakeMB(anchored=[{"mbid": MBID}, {"mbid": OTHER_MBID}])

    result = _refresh(cid, mb=mb)

    assert result["sources"]["musicbrainz"] == "ambiguous"
    assert result["musicbrainz"] is None


def test_a_confirmed_binding_is_never_second_guessed(cid) -> None:
    links.confirm_musicbrainz(cid, OTHER_MBID)
    mb = _FakeMB(anchored=[{"mbid": MBID}])

    result = _refresh(cid, mb=mb)

    assert result["musicbrainz"]["mbid"] == OTHER_MBID
    assert not any(call.startswith("url:") for call in mb.calls)


def test_an_anchored_binding_goes_when_the_anchor_does(cid) -> None:
    mb = _FakeMB(
        anchored=[{"mbid": MBID}],
        relations=[{"type": "other databases", "url": "https://ra.co/dj/boysnoize"}],
    )
    _refresh(cid, mb=mb)

    relinked = _FakeMB(anchored=[])
    result = _refresh(cid, mb=relinked)

    assert result["musicbrainz"] is None
    assert "resident_advisor" not in {link["service"] for link in result["links"]}


def test_dropping_musicbrainz_takes_its_links_now(cid) -> None:
    mb = _FakeMB(
        anchored=[{"mbid": MBID}],
        relations=[{"type": "other databases", "url": "https://ra.co/dj/boysnoize"}],
    )
    _refresh(cid, mb=mb)

    assert links.drop_musicbrainz(cid) is True
    listed = links.list_links(cid)
    assert listed["musicbrainz"] is None
    assert "resident_advisor" not in {link["service"] for link in listed["links"]}


def test_unlinking_the_account_takes_its_links_but_not_yours(cid) -> None:
    _refresh(cid, mb=_FakeMB())
    links.add_manual_link(cid, "https://ra.co/dj/boysnoize")
    assert links.remove_link(cid, "bandcamp:boysnoize") == "hidden"

    result = _refresh(cid, mb=_FakeMB(), linked=False)

    assert result["sources"]["soundcloud"] == "not_linked"
    assert {link["service"] for link in result["links"]} == {"resident_advisor"}
    assert result["hidden_count"] == 1


def test_not_connected_is_reported_without_touching_soundcloud(cid) -> None:
    def boom(*_a, **_k):
        raise AssertionError("SoundCloud must not be called without a token")

    result = links.refresh(
        cid,
        names=("Boys Noize",),
        sc_urn="soundcloud:users:1",
        token="",
        use_musicbrainz=False,
        sc_user_fetch=boom,
        sc_profiles_fetch=boom,
    )

    assert result["sources"] == {"soundcloud": "not_connected", "musicbrainz": "not_queried"}
    assert schema.get_link_fetch(cid)["sources"] == result["sources"]


def test_confirm_refuses_a_malformed_mbid(cid) -> None:
    with pytest.raises(ValueError):
        links.confirm_musicbrainz(cid, "../../x")


# --------------------------------------------------------------------------- account picker


def test_account_ranking_puts_exact_names_first_then_followers() -> None:
    users = [
        {"urn": "u:1", "username": "boys noize fan", "followers_count": 900_000},
        {"urn": "u:2", "username": "BoysNoize", "followers_count": 10},
        {"urn": "u:3", "username": "Boys Noize", "followers_count": 5},
        {"urn": "u:4", "username": "Boys Noize", "followers_count": 1_000_000},
    ]

    ranked = links.rank_soundcloud_accounts(users, ("Boys Noize",))

    assert [(r["urn"], r["match"]) for r in ranked] == [
        ("u:4", "exact"),
        ("u:3", "exact"),
        ("u:2", "close"),
        ("u:1", "weak"),
    ]
