"""Artist-Hub Tier-2 discovery tests (T-16 — app/artist_store/discovery.py).

Pins the guardrails the owner set and the failure modes this feature has shipped before:
exactly ONE related hop per favourite and never one on a result, an empty or 404 related
list degrading to the zero-call local fallback instead of raising, a spent budget being
reported as "skipped" rather than as "nothing found", and every suggestion being an
artist the user does not already have.

No network: the related fetcher is a local stub that counts its calls, and the one test
that exercises the real client path monkeypatches ``requests.get``. No keyring, no
credentials — ``discover`` takes the token as an argument. The sidecar is a throwaway
file in ``tmp_path``, monkeypatched the way ``tests/test_artist_catalogue.py`` does it.
"""

from __future__ import annotations

import pytest

from app import soundcloud_api as sc_api
from app.artist_store import discovery, schema

FAV_A = "Boys Noize"
FAV_B = "Gesaffelstein"
URN_A = "soundcloud:users:1000"
URN_B = "soundcloud:users:2000"


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


def favourite(name: str, urn: str = "") -> str:
    """Create a favourited collection, optionally bound to a SoundCloud account."""
    cid = schema.create_collection(name)
    schema.add_favourite(cid)
    if urn:
        schema.set_link(
            cid, discovery.PROVIDER_SOUNDCLOUD, urn, f"https://soundcloud.com/{urn}", 1.0
        )
    return cid


def sc_user(urn: str, username: str, *, track_count: int = 10, followers: int = 100) -> dict:
    """One normalised SC user dict — what ``normalize_artist`` hands back."""
    return {
        "urn": urn,
        "username": username,
        "permalink_url": f"https://soundcloud.com/{username}",
        "track_count": track_count,
        "followers_count": followers,
        "avatar_url": "",
    }


def cached_catalogue(cid: str, artist_urn: str, uploads: list[tuple[str, str]]) -> None:
    """Seed the sidecar catalogue cache with ``(uploader_urn, uploader_name)`` tracks."""
    tracks = [
        {
            "sc_id": f"soundcloud:tracks:{i}",
            "title": f"Track {i}",
            "uploader_urn": urn,
            "uploader_name": name,
        }
        for i, (urn, name) in enumerate(uploads)
    ]
    schema.set_catalogue_cache(
        cid, {"artist_urn": artist_urn, "fetched_at": "2026-09-09T00:00:00+00:00", "tracks": tracks}
    )


class FakeRelated:
    """Stand-in for ``sc_api.get_related_artists``: counts calls, spends the budget.

    Spending is what the real client does inside ``_sc_paginate``, so the budget
    assertions here mean the same thing they do in production.
    """

    def __init__(self, by_urn: dict[str, object], *, raises: dict[str, Exception] | None = None):
        self.by_urn = by_urn
        self.raises = raises or {}
        self.calls: list[str] = []

    def __call__(self, user_urn_or_id, auth_token, *, budget=None):
        self.calls.append(str(user_urn_or_id))
        if budget is not None:
            budget.try_spend()
        if user_urn_or_id in self.raises:
            raise self.raises[str(user_urn_or_id)]
        return self.by_urn.get(str(user_urn_or_id), sc_api.SCResultList([]))


# ── Tier 1: one hop, never transitive ─────────────────────────────────────────


def test_related_is_called_once_per_favourite_and_never_on_a_result():
    """ONE hop. The candidates that come back are never themselves queried."""
    favourite(FAV_A, URN_A)
    favourite(FAV_B, URN_B)
    candidate = sc_user("soundcloud:users:3000", "Vitalic")
    fake = FakeRelated(
        {
            URN_A: sc_api.SCResultList([candidate]),
            URN_B: sc_api.SCResultList([sc_user("soundcloud:users:4000", "Zombie Nation")]),
        }
    )

    result = discovery.discover(token="tok", related_fetch=fake)

    assert fake.calls == [URN_A, URN_B]
    assert "soundcloud:users:3000" not in fake.calls
    assert result["sources"]["related"] == discovery.STATE_OK
    assert {s["name"] for s in result["suggestions"]} == {"Vitalic", "Zombie Nation"}
    assert result["calls_used"] == 2


def test_unlinked_favourite_is_reported_not_queried():
    """An artist with no bound account was never looked up — say so, do not call."""
    favourite(FAV_A)
    fake = FakeRelated({})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert fake.calls == []
    assert result["sources"]["related"] == discovery.STATE_NOT_QUERIED
    assert result["sources_detail"]["related"]["reason"] == "no_linked_accounts"
    assert result["sources_detail"]["related"]["not_linked"] == [FAV_A]


def test_missing_token_never_queries_and_says_so():
    favourite(FAV_A, URN_A)
    fake = FakeRelated({URN_A: sc_api.SCResultList([sc_user("soundcloud:users:3000", "Vitalic")])})

    result = discovery.discover(token="", related_fetch=fake)

    assert fake.calls == []
    assert result["sources"]["related"] == discovery.STATE_NOT_QUERIED
    assert result["sources_detail"]["related"]["reason"] == "not_signed_in"
    assert result["calls_used"] == 0


# ── Tier 2: zero-call fallback ────────────────────────────────────────────────


def test_empty_related_falls_back_to_co_occurrence_with_zero_further_calls():
    cid = favourite(FAV_A, URN_A)
    cached_catalogue(
        cid,
        URN_A,
        [
            (URN_A, FAV_A),
            ("soundcloud:users:5000", "Turbo Recordings"),
            ("soundcloud:users:5000", "Turbo Recordings"),
        ],
    )
    fake = FakeRelated({URN_A: sc_api.SCResultList([])})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert len(fake.calls) == 1
    assert result["calls_used"] == 1  # the one related call; the fallback added none
    assert result["sources"]["co_occurrence"] == discovery.STATE_OK
    assert [s["name"] for s in result["suggestions"]] == ["Turbo Recordings"]
    row = result["suggestions"][0]
    assert row["sources"] == [discovery.SOURCE_CO_OCCURRENCE]
    assert row["co_occurrence_tracks"] == 2
    # Co-occurrence never measured a catalogue size — it must not print one.
    assert row["track_count"] is None


def test_404_degrades_to_the_fallback_and_never_raises():
    cid = favourite(FAV_A, URN_A)
    cached_catalogue(cid, URN_A, [("soundcloud:users:5000", "Turbo Recordings")])
    fake = FakeRelated({}, raises={URN_A: sc_api.NotFoundError("gone")})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert result["sources"]["related"] == discovery.STATE_FAILED
    assert result["sources_detail"]["related"]["failed"] == [
        {"artist": FAV_A, "reason": "not_found"}
    ]
    assert [s["name"] for s in result["suggestions"]] == ["Turbo Recordings"]


def test_client_swallowed_404_is_still_reported_as_failed():
    """The client turns a 404 into an empty list with ``stop_reason='not_found'``.

    Reading that as an answer would print "nothing found" for an account that is gone.
    """
    favourite(FAV_A, URN_A)
    fake = FakeRelated({URN_A: sc_api.SCResultList([], stop_reason="not_found")})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert result["suggestions"] == []
    assert result["sources"]["related"] == discovery.STATE_FAILED
    assert result["sources"]["co_occurrence"] == discovery.STATE_NO_DATA


def test_auth_failure_stops_the_run_and_is_reported_not_raised():
    favourite(FAV_A, URN_A)
    favourite(FAV_B, URN_B)
    fake = FakeRelated({}, raises={URN_A: sc_api.AuthExpiredError("expired")})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert fake.calls == [URN_A]  # no point hammering the rest with a dead token
    assert result["sources"]["related"] == discovery.STATE_FAILED
    assert result["sources_detail"]["related"]["reason"] == "auth_expired"
    assert result["sources_detail"]["related"]["skipped"] == [FAV_B]
    assert result["suggestions"] == []


def test_no_cached_catalogue_is_no_data_not_nothing_found():
    favourite(FAV_A, URN_A)
    fake = FakeRelated({}, raises={URN_A: sc_api.NotFoundError("gone")})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert result["suggestions"] == []
    assert result["sources"] == {
        discovery.SOURCE_RELATED: discovery.STATE_FAILED,
        discovery.SOURCE_CO_OCCURRENCE: discovery.STATE_NO_DATA,
    }
    assert result["sources_detail"]["co_occurrence"]["no_cache"] == [FAV_A]


# ── Exclusion ─────────────────────────────────────────────────────────────────


def test_already_favourited_and_already_local_candidates_are_excluded():
    favourite(FAV_A, URN_A)
    favourite(FAV_B, URN_B)
    # In the library but not favourited: an alias spelling, plus a differently-cased one.
    local = schema.create_collection("Vitalic")
    schema.add_alias(local, "VITALIC", source="library")
    fake = FakeRelated(
        {
            URN_A: sc_api.SCResultList(
                [
                    sc_user(URN_B, FAV_B),  # already favourited (by URN)
                    sc_user("soundcloud:users:9000", "boys noize"),  # favourited (by fold)
                    sc_user("soundcloud:users:3000", "vitalic"),  # already in the library
                    sc_user("soundcloud:users:4000", "Zombie Nation"),  # genuinely new
                ]
            ),
            URN_B: sc_api.SCResultList([]),
        }
    )

    result = discovery.discover(token="tok", related_fetch=fake)

    assert [s["name"] for s in result["suggestions"]] == ["Zombie Nation"]
    assert result["excluded"] == 3
    # The exclusion claim is only as good as the set it was checked against: 3 known
    # local artists (2 favourites + Vitalic), 2 of them bound to an account.
    assert result["excluded_against"] == {"local_names": 3, "linked_accounts": 2}


def test_co_occurrence_never_suggests_the_seed_itself():
    cid = favourite(FAV_A, URN_A)
    schema.add_alias(cid, "BOYS NOIZE", source="library")
    cached_catalogue(
        cid,
        URN_A,
        [("", "BOYS NOIZE"), (URN_A, FAV_A), ("soundcloud:users:5000", "Turbo Recordings")],
    )

    result = discovery.discover(token="", related_fetch=FakeRelated({}))

    assert [s["name"] for s in result["suggestions"]] == ["Turbo Recordings"]


# ── Ranking (pure — no DB, no network) ────────────────────────────────────────


def test_two_favourites_beat_one_bigger_catalogue():
    """Co-signal first: an artist two favourites point at outranks a bigger single hit."""
    shared = discovery.Candidate(name="Vitalic", urn="u:3", track_count=10, seeds=(FAV_A,))
    shared_again = discovery.Candidate(name="Vitalic", urn="u:3", track_count=10, seeds=(FAV_B,))
    big = discovery.Candidate(name="Zombie Nation", urn="u:4", track_count=5000, seeds=(FAV_A,))

    ranked = discovery.rank_candidates([big, shared, shared_again])

    assert [c.name for c in ranked.suggestions] == ["Vitalic", "Zombie Nation"]
    assert ranked.suggestions[0].co_signal == 2
    assert ranked.suggestions[0].seeds == (FAV_A, FAV_B)


def test_rank_falls_back_to_track_count_then_followers():
    small = discovery.Candidate(
        name="A", urn="u:1", track_count=10, followers_count=99, seeds=("x",)
    )
    big = discovery.Candidate(name="B", urn="u:2", track_count=90, followers_count=1, seeds=("x",))
    unknown = discovery.Candidate(name="C", urn="u:3", seeds=("x",))

    ranked = discovery.rank_candidates([unknown, small, big])

    assert [c.name for c in ranked.suggestions] == ["B", "A", "C"]


def test_rank_excludes_by_fold_and_by_urn_and_counts_them():
    ranked = discovery.rank_candidates(
        [
            discovery.Candidate(name="BOYS NOIZE", urn="u:1", seeds=("x",)),
            discovery.Candidate(name="Vitalic", urn="u:2", seeds=("x",)),
            discovery.Candidate(name="Zombie Nation", urn="u:3", seeds=("x",)),
        ],
        excluded_folds=["Boys Noize"],
        excluded_urns=["u:2"],
    )

    assert [c.name for c in ranked.suggestions] == ["Zombie Nation"]
    assert ranked.excluded == 2


def test_rank_limit_reports_truncation():
    candidates = [
        discovery.Candidate(name=f"A{i}", urn=f"u:{i}", track_count=i, seeds=("x",))
        for i in range(5)
    ]

    ranked = discovery.rank_candidates(candidates, limit=2)

    assert len(ranked.suggestions) == 2
    assert ranked.truncated is True


def test_rank_merges_the_two_sources_into_one_row():
    from_related = discovery.Candidate(
        name="Vitalic",
        urn="u:3",
        track_count=42,
        seeds=(FAV_A,),
        sources=(discovery.SOURCE_RELATED,),
    )
    from_local = discovery.Candidate(
        name="Vitalic",
        urn="u:3",
        seeds=(FAV_B,),
        sources=(discovery.SOURCE_CO_OCCURRENCE,),
        co_occurrence_tracks=3,
    )

    ranked = discovery.rank_candidates([from_related, from_local])

    assert len(ranked.suggestions) == 1
    row = ranked.suggestions[0].as_dict()
    assert row["sources"] == [discovery.SOURCE_RELATED, discovery.SOURCE_CO_OCCURRENCE]
    assert row["co_signal"] == 2
    assert row["track_count"] == 42
    assert row["co_occurrence_tracks"] == 3


# ── Budget ────────────────────────────────────────────────────────────────────


def test_budget_truncates_the_run_and_is_reported():
    favourite(FAV_A, URN_A)
    favourite(FAV_B, URN_B)
    favourite("Vitalic", "soundcloud:users:3000")
    fake = FakeRelated(
        {
            URN_A: sc_api.SCResultList([sc_user("soundcloud:users:8000", "Zombie Nation")]),
            URN_B: sc_api.SCResultList([]),
        }
    )
    budget = sc_api.CallBudget(limit=2, label="test")

    result = discovery.discover(token="tok", budget=budget, related_fetch=fake)

    assert len(fake.calls) == 2
    assert result["calls_used"] == 2
    assert result["call_budget"] == {"limit": 2, "used": 2, "remaining": 0}
    assert result["truncated"] is True
    assert result["sources_detail"]["related"]["skipped"] == ["Vitalic"]
    assert result["sources_detail"]["related"]["queried"] == [FAV_A, FAV_B]


def test_exhausted_budget_reports_skipped_budget_not_empty():
    favourite(FAV_A, URN_A)
    fake = FakeRelated({URN_A: sc_api.SCResultList([sc_user("soundcloud:users:3000", "Vitalic")])})
    budget = sc_api.CallBudget(limit=1, used=1, label="test")

    result = discovery.discover(token="tok", budget=budget, related_fetch=fake)

    assert fake.calls == []
    assert result["suggestions"] == []
    assert result["sources"]["related"] == discovery.STATE_SKIPPED_BUDGET
    assert result["truncated"] is True


def test_client_reported_budget_stop_is_a_skip_not_an_answer():
    favourite(FAV_A, URN_A)
    fake = FakeRelated({URN_A: sc_api.SCResultList([], truncated=True, stop_reason="budget")})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert result["sources"]["related"] == discovery.STATE_SKIPPED_BUDGET
    assert result["sources_detail"]["related"]["queried"] == []


def test_discover_runs_under_a_cap_even_without_a_caller_budget():
    favourite(FAV_A, URN_A)
    fake = FakeRelated({URN_A: sc_api.SCResultList([])})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert result["call_budget"]["limit"] == discovery.DEFAULT_DISCOVERY_BUDGET


# ── Report shape + the real client path ───────────────────────────────────────


def test_report_names_the_seeds_and_both_sources():
    cid = favourite(FAV_A, URN_A)
    cached_catalogue(cid, URN_A, [("soundcloud:users:5000", "Turbo Recordings")])
    fake = FakeRelated({URN_A: sc_api.SCResultList([sc_user("soundcloud:users:3000", "Vitalic")])})

    result = discovery.discover(token="tok", related_fetch=fake)

    assert result["seeded_from"] == [FAV_A]
    assert result["favourites"] == 1
    assert set(result["sources"]) == {discovery.SOURCE_RELATED, discovery.SOURCE_CO_OCCURRENCE}
    assert result["sources"] == {
        discovery.SOURCE_RELATED: discovery.STATE_OK,
        discovery.SOURCE_CO_OCCURRENCE: discovery.STATE_OK,
    }
    assert {s["name"] for s in result["suggestions"]} == {"Vitalic", "Turbo Recordings"}


def test_default_path_uses_the_real_client_over_a_mocked_http_layer(monkeypatch):
    """No fetcher injected: the module must reach ``sc_api.get_related_artists``."""
    favourite(FAV_A, URN_A)
    seen: list[str] = []

    class Resp:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {
                "collection": [
                    {
                        "urn": "soundcloud:users:3000",
                        "username": "Vitalic",
                        "permalink_url": "https://soundcloud.com/vitalic",
                        "track_count": 61,
                        "followers_count": 5,
                    }
                ],
                "next_href": None,
            }

    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        seen.append(url)
        return Resp()

    monkeypatch.setattr(sc_api.requests, "get", fake_get)

    result = discovery.discover(token="tok")

    assert len(seen) == 1 and seen[0].endswith(f"/users/{URN_A}/related")
    assert [s["name"] for s in result["suggestions"]] == ["Vitalic"]
    assert result["suggestions"][0]["track_count"] == 61
    assert result["calls_used"] == 1


class TestAPartialWalkIsNotOk:
    """An abort after one seed answered must not read as "both sources answered".

    The state branch used to test `queried` first, so a run that asked one favourite
    and was then rate-limited reported STATE_OK. The UI's `allSourcesAnswered` then
    printed "Both sources answered and turned up nobody you do not already have" for
    favourites that were never asked — fabricated absence, the exact class this
    module's per-source contract exists to prevent.
    """

    def _three_linked(self):
        ids = []
        for name in ("Aaa", "Bbb", "Ccc"):
            cid = schema.create_collection(name)
            schema.add_favourite(cid)
            schema.set_link(
                cid, discovery.PROVIDER_SOUNDCLOUD, f"soundcloud:users:{len(ids) + 1}", "", 1.0
            )
            ids.append(cid)
        return ids

    def test_rate_limited_after_one_seed_is_not_ok(self) -> None:
        self._three_linked()
        seen: list[str] = []

        def _fetch(urn, _token, **_kw):
            seen.append(urn)
            if len(seen) == 1:
                return sc_api.SCResultList([])
            raise sc_api.RateLimitError("429")

        out = discovery.discover(token="t", related_fetch=_fetch)

        assert (
            out["sources"]["related"] != discovery.STATE_OK
        ), "a walk that never asked two of three favourites reported itself as ok"
        assert out["sources"]["related"] == discovery.STATE_FAILED
        assert out["sources_detail"]["related"]["reason"] == "rate_limited"

    def test_a_clean_full_walk_is_still_ok(self) -> None:
        self._three_linked()

        out = discovery.discover(
            token="t", related_fetch=lambda _urn, _tok, **_kw: sc_api.SCResultList([])
        )

        assert out["sources"]["related"] == discovery.STATE_OK
        assert len(out["sources_detail"]["related"]["queried"]) == 3
