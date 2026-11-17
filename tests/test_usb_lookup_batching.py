"""Batched master.db lookups in the USB scan / diff / legacy-export paths.

`app/usb_manager.py` used to pay one rbox round-trip per track for artist and
album names, open master.db once per reader, and match the diff with a scan of
every USB track per missing local track. These tests pin the batched shape
with a counting fake `rbox` module (5k tracks, no real master.db):

* one `MasterDb` open per diff / per legacy export,
* one bulk `get_artists()` / `get_albums()` call per batch, zero `*_by_id`,
* `_match_updates` returns exactly what the old nested loop returned.
"""

from __future__ import annotations

import random
import sys
import types
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import usb_manager
from app.usb_manager import UsbSyncEngine, _match_updates, _NameLookup

N_TRACKS = 5000
N_ARTISTS = 40
N_ALBUMS = 25


class FakeMasterDb:
    """Counts every getter call; mirrors the rbox 0.1.7 MasterDb read surface.

    Deliberately has no `get_artist` / `get_album` — rbox doesn't either.
    """

    def __init__(self, contents, artists, albums, playlists=(), playlist_songs=None):
        self.calls: Counter[str] = Counter()
        self._contents = list(contents)
        self._artists = list(artists)
        self._albums = list(albums)
        self._playlists = list(playlists)
        self._playlist_songs = playlist_songs or {}

    def get_contents(self):
        self.calls["get_contents"] += 1
        return list(self._contents)

    def get_artists(self):
        self.calls["get_artists"] += 1
        return list(self._artists)

    def get_albums(self):
        self.calls["get_albums"] += 1
        return list(self._albums)

    def get_artist_by_id(self, ident):
        self.calls["get_artist_by_id"] += 1
        return next((a for a in self._artists if str(a.id) == str(ident)), None)

    def get_album_by_id(self, ident):
        self.calls["get_album_by_id"] += 1
        return next((a for a in self._albums if str(a.id) == str(ident)), None)

    def get_playlists(self):
        self.calls["get_playlists"] += 1
        return list(self._playlists)

    def get_playlist_by_id(self, ident):
        self.calls["get_playlist_by_id"] += 1
        return next((p for p in self._playlists if str(p.id) == str(ident)), None)

    def get_playlist_contents(self, ident):
        self.calls["get_playlist_contents"] += 1
        return list(self._playlist_songs.get(str(ident), []))


def _library(audio_root: Path | None = None, n: int = N_TRACKS):
    artists = [SimpleNamespace(id=str(i), name=f"Artist {i}") for i in range(1, N_ARTISTS + 1)]
    albums = [SimpleNamespace(id=str(i), name=f"Album {i}") for i in range(1, N_ALBUMS + 1)]
    contents = []
    for i in range(1, n + 1):
        folder = str(audio_root / f"t{i}.mp3") if audio_root else f"Z:/does-not-exist/t{i}.mp3"
        contents.append(
            SimpleNamespace(
                id=str(i),
                title=f"Track {i}",
                # Every 7th track has no artist, every 5th no album.
                artist_id=None if i % 7 == 0 else str(i % N_ARTISTS + 1),
                album_id=None if i % 5 == 0 else str(i % N_ALBUMS + 1),
                genre_id="",
                bpm=12800,
                rating=0,
                color_id=0,
                key_id="",
                length=300,
                folder_path=folder,
                file_name_l=f"t{i}.mp3",
            )
        )
    return contents, artists, albums


@pytest.fixture
def fake_rbox(monkeypatch):
    """Install a fake `rbox` module whose `MasterDb(...)` returns `state["db"]`."""
    state: dict = {"opens": 0, "db": None}

    def _open(path):
        state["opens"] += 1
        if state["db"] is None:
            raise RuntimeError("cannot open")
        return state["db"]

    mod = types.ModuleType("rbox")
    mod.MasterDb = _open  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rbox", mod)
    return state


# ---------------------------------------------------------------------------
# _NameLookup
# ---------------------------------------------------------------------------


class TestNameLookup:
    def test_one_bulk_call_for_many_lookups(self) -> None:
        contents, artists, albums = _library()
        db = FakeMasterDb(contents, artists, albums)
        lookup = _NameLookup(db, "get_artists", "get_artist_by_id")
        names = [lookup(c.artist_id) for c in contents]
        assert db.calls["get_artists"] == 1
        assert db.calls["get_artist_by_id"] == 0
        assert names[0] == "Artist 2"
        assert names[6] == ""  # track 7: no artist

    def test_unknown_and_falsy_ids_are_empty(self) -> None:
        db = FakeMasterDb([], [SimpleNamespace(id="1", name=None)], [])
        lookup = _NameLookup(db, "get_artists", "get_artist_by_id")
        assert lookup(None) == ""
        assert lookup("") == ""
        assert lookup(0) == ""
        assert lookup("999") == ""
        assert lookup("1") == ""  # name None → "" like `getattr(...) or ""`
        assert db.calls["get_artist_by_id"] == 0

    def test_int_and_str_ids_hit_the_same_entry(self) -> None:
        db = FakeMasterDb([], [SimpleNamespace(id=12, name="Twelve")], [])
        lookup = _NameLookup(db, "get_artists", "get_artist_by_id")
        assert lookup("12") == "Twelve"
        assert lookup(12) == "Twelve"

    def test_bulk_failure_falls_back_to_memoised_by_id(self) -> None:
        contents, artists, albums = _library()
        db = FakeMasterDb(contents, artists, albums)

        def _boom():
            db.calls["get_artists"] += 1
            raise RuntimeError("bad row")

        db.get_artists = _boom  # type: ignore[method-assign]
        lookup = _NameLookup(db, "get_artists", "get_artist_by_id")
        names = [lookup(c.artist_id) for c in contents]
        assert names[0] == "Artist 2"
        # One by-id call per DISTINCT artist, not per track.
        assert db.calls["get_artist_by_id"] == N_ARTISTS

    def test_by_id_failure_in_fallback_is_empty_and_memoised(self) -> None:
        db = FakeMasterDb([], [], [])
        db.get_artists = lambda: (_ for _ in ()).throw(RuntimeError("x"))  # type: ignore[method-assign]

        def _raise(ident):
            db.calls["get_artist_by_id"] += 1
            raise RuntimeError("row gone")

        db.get_artist_by_id = _raise  # type: ignore[method-assign]
        lookup = _NameLookup(db, "get_artists", "get_artist_by_id")
        assert lookup("5") == ""
        assert lookup("5") == ""
        assert db.calls["get_artist_by_id"] == 1


# ---------------------------------------------------------------------------
# calculate_diff — one open, bulk artist names
# ---------------------------------------------------------------------------


class TestCalculateDiffBatching:
    def test_one_open_and_constant_getter_calls(self, tmp_path: Path, fake_rbox) -> None:
        contents, artists, albums = _library()
        db = FakeMasterDb(contents, artists, albums, playlists=[SimpleNamespace(id="p1", name="A")])
        fake_rbox["db"] = db
        engine = UsbSyncEngine(str(tmp_path / "master.db"), str(tmp_path / "usb"))

        diff = engine.calculate_diff()

        assert fake_rbox["opens"] == 1  # was 2 (tracks reader + playlists reader)
        assert db.calls["get_artists"] == 1
        assert db.calls["get_artist_by_id"] == 0
        assert db.calls["get_contents"] == 1
        assert db.calls["get_playlists"] == 1
        assert diff["total_local"] == N_TRACKS
        assert diff["tracks"]["to_add"] == N_TRACKS  # empty stick
        assert diff["playlists"]["local_total"] == 1

    def test_local_tracks_carry_real_artist_names(self, tmp_path: Path, fake_rbox) -> None:
        contents, artists, albums = _library(n=14)
        fake_rbox["db"] = FakeMasterDb(contents, artists, albums)
        engine = UsbSyncEngine(str(tmp_path / "master.db"), str(tmp_path / "usb"))
        tracks = engine._read_local_tracks()
        assert tracks["1"]["ArtistName"] == "Artist 2"
        assert tracks["7"]["ArtistName"] == ""
        assert tracks["7"]["ArtistID"] == ""

    def test_open_failure_returns_empty_without_second_open(
        self, tmp_path: Path, fake_rbox
    ) -> None:
        fake_rbox["db"] = None
        engine = UsbSyncEngine(str(tmp_path / "master.db"), str(tmp_path / "usb"))
        diff = engine.calculate_diff()
        assert fake_rbox["opens"] == 1
        assert diff["total_local"] == 0
        assert diff["playlists"]["local_total"] == 0


# ---------------------------------------------------------------------------
# _match_updates — identical to the old nested loop
# ---------------------------------------------------------------------------


def _old_match_updates(local_tracks, local_hashes, usb_tracks, usb_hashes):
    """Verbatim copy of the pre-batching loop from `calculate_diff`."""
    to_update = []
    for h, local_id in local_hashes.items():
        if h not in usb_hashes:
            lt = local_tracks[local_id]
            for _uid, ut in usb_tracks.items():
                if (
                    lt.get("Title", "").lower() == ut.get("Title", "").lower()
                    and lt.get("ArtistName", "").lower() == ut.get("ArtistName", "").lower()
                ):
                    to_update.append({"local": lt, "usb": ut})
                    break
    return to_update


def _track(tid, title, artist, duration, bpm):
    t = {"ID": tid, "Title": title, "ArtistName": artist, "Duration": duration, "BPM": bpm}
    t["_hash"] = f"{title}|{artist}|{duration}|{bpm}"
    return t


def _random_side(rng: random.Random, prefix: str, n: int) -> dict[str, dict]:
    titles = ["Intro", "intro", "INTRO", "Drift", "Bloom", "Night Run", "ÄÖÜ", ""]
    artists = ["DJ A", "dj a", "B", "", "Ünder", "C c"]
    return {
        f"{prefix}{i}": _track(
            f"{prefix}{i}",
            rng.choice(titles),
            rng.choice(artists),
            rng.choice([300, 301]),
            rng.choice([12800, 12900]),
        )
        for i in range(n)
    }


def _pairs(updates):
    return [(id(u["local"]), id(u["usb"])) for u in updates]


class TestMatchUpdatesEquivalence:
    @pytest.mark.parametrize("seed", range(25))
    def test_randomised_fixture_matches_old_loop(self, seed: int) -> None:
        rng = random.Random(seed)
        local = _random_side(rng, "L", rng.randint(0, 60))
        usb = _random_side(rng, "U", rng.randint(0, 60))
        local_hashes = {t["_hash"]: tid for tid, t in local.items()}
        usb_hashes = {t["_hash"]: tid for tid, t in usb.items()}

        old = _old_match_updates(local, local_hashes, usb, usb_hashes)
        new = _match_updates(local, local_hashes, usb, usb_hashes)

        assert _pairs(new) == _pairs(old)

    def test_first_usb_match_in_stick_order_wins(self) -> None:
        local = {"L1": _track("L1", "Drift", "A", 300, 1)}
        usb = {
            "U1": _track("U1", "drift", "a", 999, 1),
            "U2": _track("U2", "DRIFT", "A", 998, 1),
        }
        lh = {t["_hash"]: k for k, t in local.items()}
        uh = {t["_hash"]: k for k, t in usb.items()}
        new = _match_updates(local, lh, usb, uh)
        assert [u["usb"]["ID"] for u in new] == ["U1"]
        assert _pairs(new) == _pairs(_old_match_updates(local, lh, usb, uh))

    def test_none_artist_on_stick_no_longer_crashes(self) -> None:
        # USB `LEFT JOIN djmdArtist` miss → ArtistName None. The old loop
        # raised AttributeError on `.lower()`; now None counts as "".
        local = {"L1": _track("L1", "Drift", "", 300, 1)}
        usb = {"U1": {"ID": "U1", "Title": "Drift", "ArtistName": None, "_hash": "x"}}
        lh = {t["_hash"]: k for k, t in local.items()}
        uh = {"x": "U1"}
        with pytest.raises(AttributeError):
            _old_match_updates(local, lh, usb, uh)
        assert [u["usb"]["ID"] for u in _match_updates(local, lh, usb, uh)] == ["U1"]

    def test_key_computed_once_per_track(self, monkeypatch) -> None:
        """O(local + usb) — not O(to_add x usb)."""
        local = {f"L{i}": _track(f"L{i}", f"T{i}", "A", 1, 1) for i in range(N_TRACKS)}
        usb = {f"U{i}": _track(f"U{i}", f"T{i}", "B", 2, 2) for i in range(N_TRACKS)}
        lh = {t["_hash"]: k for k, t in local.items()}
        uh = {t["_hash"]: k for k, t in usb.items()}
        real = usb_manager._diff_name_key
        calls = {"n": 0}

        def counting(track):
            calls["n"] += 1
            return real(track)

        monkeypatch.setattr(usb_manager, "_diff_name_key", counting)
        assert _match_updates(local, lh, usb, uh) == []
        assert calls["n"] == 2 * N_TRACKS


# ---------------------------------------------------------------------------
# Legacy XML export — bulk names, one open, same output
# ---------------------------------------------------------------------------


def _run_legacy(engine: UsbSyncEngine, playlist_ids=None) -> list[dict]:
    return list(engine._sync_library_legacy({"drive": str(engine.usb_root)}, playlist_ids))


@pytest.fixture
def legacy_engine(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(usb_manager.time, "sleep", lambda s: None)
    usb = tmp_path / "usb"
    (usb / "PIONEER").mkdir(parents=True)
    return UsbSyncEngine(str(tmp_path / "master.db"), str(usb))


class TestLegacyExportBatching:
    def test_constant_lookups_for_5k_tracks(self, legacy_engine, fake_rbox) -> None:
        contents, artists, albums = _library()
        db = FakeMasterDb(contents, artists, albums)
        fake_rbox["db"] = db

        events = _run_legacy(legacy_engine)

        assert events[-1]["stage"] == "complete", events[-1]
        assert events[-1]["skipped_missing"] == N_TRACKS
        assert fake_rbox["opens"] == 1
        assert db.calls["get_artists"] == 1
        assert db.calls["get_albums"] == 1
        # Was 2 per track (artist + album by id) = ~8.6k calls here.
        assert db.calls["get_artist_by_id"] == 0
        assert db.calls["get_album_by_id"] == 0

        xml = ET.parse(legacy_engine.usb_pioneer / "rekordbox.xml").getroot()
        rows = {t.get("TrackID"): t for t in xml.iter("TRACK")}
        assert len(rows) == N_TRACKS
        assert rows["1"].get("Artist") == "Artist 2"
        assert rows["1"].get("Album") == "Album 2"
        assert rows["7"].get("Artist") == ""
        assert rows["5"].get("Album") == ""

    def test_copied_files_land_under_the_artist_folder(
        self, tmp_path: Path, legacy_engine, fake_rbox
    ) -> None:
        audio = tmp_path / "audio"
        audio.mkdir()
        contents, artists, albums = _library(audio_root=audio, n=8)
        for c in contents:
            Path(c.folder_path).write_bytes(b"ID3" + c.id.encode())
        db = FakeMasterDb(contents, artists, albums)
        fake_rbox["db"] = db

        events = _run_legacy(legacy_engine)

        assert events[-1]["stage"] == "complete", events[-1]
        assert events[-1]["copied"] == 8
        contents_dir = legacy_engine.usb_root / "Contents"
        assert (contents_dir / "Artist 2" / "Track 1" / "t1.mp3").read_bytes() == b"ID31"
        # `_clean_filename("")` yields "Unknown" (pre-existing), not "UnknownArtist".
        assert (contents_dir / "Unknown" / "Track 7" / "t7.mp3").is_file()
        # Relocation pre-pass + copy loop share the one bulk fetch.
        assert db.calls["get_artists"] == 1
        assert db.calls["get_artist_by_id"] == 0

    def test_playlist_filter_still_resolves(self, legacy_engine, fake_rbox) -> None:
        contents, artists, albums = _library(n=20)
        db = FakeMasterDb(
            contents,
            artists,
            albums,
            playlists=[SimpleNamespace(id="p1", name="Set")],
            playlist_songs={"p1": [contents[0], contents[3]]},
        )
        fake_rbox["db"] = db

        events = _run_legacy(legacy_engine, ["p1"])

        assert events[-1]["stage"] == "complete", events[-1]
        xml = ET.parse(legacy_engine.usb_pioneer / "rekordbox.xml").getroot()
        collection = xml.find("COLLECTION")
        assert collection is not None
        assert sorted(t.get("TrackID") for t in collection.iter("TRACK")) == ["1", "4"]
        assert fake_rbox["opens"] == 1


# ---------------------------------------------------------------------------
# Golden output — rekordbox.xml + copied files byte-pinned
# ---------------------------------------------------------------------------

_GOLDEN_ROWS = [
    # (id, title, artist_id, album_id, kind, file_name_l)
    ("1", "Intro", "1", "1", "file", "intro.mp3"),
    ("2", "Tit\x13le", "2", None, "file", "title.mp3"),
    ("3", "No Artist", None, "2", "file", "noartist.mp3"),
    ("4", "Ghost", "3", "1", "missing", "ghost.mp3"),
    ("5", "Stream", "1", None, "stream", ""),
    ("6", "Unknown Id", "999", "999", "file", "unknown.mp3"),
    ("7", "CON", "1", "2", "file", ""),
]


def _golden_db(audio: Path) -> FakeMasterDb:
    artists = [
        SimpleNamespace(id="1", name="Ärtist/One"),
        SimpleNamespace(id="2", name="  dots.. "),
        SimpleNamespace(id="3", name=None),
    ]
    albums = [SimpleNamespace(id="1", name="Alb<1>"), SimpleNamespace(id="2", name="B & C")]
    contents = []
    for tid, title, aid, alid, kind, fname in _GOLDEN_ROWS:
        if kind == "stream":
            folder = f"soundcloud:tracks:{tid}"
        else:
            folder = str(audio / f"src{tid}.mp3")
            if kind == "file":
                Path(folder).write_bytes(f"audio-{tid}".encode())
        contents.append(
            SimpleNamespace(
                id=tid,
                title=title,
                artist_id=aid,
                album_id=alid,
                length=int(tid) * 61,
                bpm=12000 + int(tid),
                key_id="",
                rating=int(tid) % 5,
                folder_path=folder,
                file_name_l=fname,
            )
        )
    return FakeMasterDb(contents, artists, albums)


def _golden_snapshot(engine: UsbSyncEngine, audio: Path) -> tuple[str, list[tuple[str, bytes]]]:
    """rekordbox.xml with the tmp roots replaced, plus every file on the stick."""
    import urllib.parse

    def _url(p: str) -> str:
        return urllib.parse.quote(f"file://localhost/{p}".replace("\\", "/"), safe=":/./-_~")

    xml = (engine.usb_pioneer / "rekordbox.xml").read_text(encoding="utf-8")
    xml = xml.replace(_url(str(engine.usb_root.resolve())), "<USB>")
    xml = xml.replace(_url(str(audio)), "<AUDIO>")
    files = sorted(
        (p.relative_to(engine.usb_root).as_posix(), p.read_bytes())
        for p in (engine.usb_root / "Contents").rglob("*")
        if p.is_file()
    )
    return xml, files


# Produced by the pre-batching implementation (HEAD 3dcd5bc) on _golden_db.
_GOLDEN_XML = '<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n<DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="7"><TRACK TrackID="1" Name="Intro" Artist="\xc4rtist/One" Album="Alb&lt;1&gt;" TotalTime="61" AverageBpm="12001.00" Tonality="" Rating="1" Location="<USB>/Contents/%C3%84rtist_One/Intro/intro.mp3" /><TRACK TrackID="2" Name="Title" Artist="  dots.. " Album="" TotalTime="122" AverageBpm="12002.00" Tonality="" Rating="2" Location="<USB>/Contents/dots/Title/title.mp3" /><TRACK TrackID="3" Name="No Artist" Artist="" Album="B &amp; C" TotalTime="183" AverageBpm="12003.00" Tonality="" Rating="3" Location="<USB>/Contents/Unknown/No%20Artist/noartist.mp3" /><TRACK TrackID="4" Name="Ghost" Artist="" Album="Alb&lt;1&gt;" TotalTime="244" AverageBpm="12004.00" Tonality="" Rating="4" Location="<AUDIO>/src4.mp3" /><TRACK TrackID="6" Name="Unknown Id" Artist="" Album="" TotalTime="366" AverageBpm="12006.00" Tonality="" Rating="1" Location="<USB>/Contents/Unknown/Unknown%20Id/unknown.mp3" /><TRACK TrackID="7" Name="CON" Artist="\xc4rtist/One" Album="B &amp; C" TotalTime="427" AverageBpm="12007.00" Tonality="" Rating="2" Location="<USB>/Contents/%C3%84rtist_One/_CON/src7.mp3" /></COLLECTION></DJ_PLAYLISTS>'
_GOLDEN_FILES = [
    ("Contents/Unknown/No Artist/noartist.mp3", b"audio-3"),
    ("Contents/Unknown/Unknown Id/unknown.mp3", b"audio-6"),
    ("Contents/dots/Title/title.mp3", b"audio-2"),
    ("Contents/\xc4rtist_One/Intro/intro.mp3", b"audio-1"),
    ("Contents/\xc4rtist_One/_CON/src7.mp3", b"audio-7"),
]


class TestLegacyExportGolden:
    def test_output_matches_pre_batching_export(
        self, tmp_path: Path, legacy_engine, fake_rbox
    ) -> None:
        audio = tmp_path / "audio"
        audio.mkdir()
        fake_rbox["db"] = _golden_db(audio)

        events = _run_legacy(legacy_engine)

        assert events[-1]["stage"] == "complete", events[-1]
        xml, files = _golden_snapshot(legacy_engine, audio)
        assert xml == _GOLDEN_XML
        assert files == _GOLDEN_FILES


# ---------------------------------------------------------------------------
# calculate_diff end-to-end — real artist names make hashes line up
# ---------------------------------------------------------------------------


def _write_plain_stick_db(path: Path, rows: list[tuple[str, str, str | None, int, int]]) -> None:
    """Unencrypted stand-in for exportLibrary.db with the columns `_read_usb_tracks` reads."""
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE djmdContent (ID TEXT, Title TEXT, ArtistID TEXT, AlbumID TEXT, "
        "GenreID TEXT, BPM INTEGER, Rating INTEGER, ColorID INTEGER, Key TEXT, "
        "Duration INTEGER, FolderPath TEXT, FileNameL TEXT)"
    )
    conn.execute("CREATE TABLE djmdArtist (ID TEXT, Name TEXT)")
    for tid, title, artist, duration, bpm in rows:
        aid = f"a{tid}" if artist is not None else None
        conn.execute(
            "INSERT INTO djmdContent (ID, Title, ArtistID, BPM, Duration) VALUES (?, ?, ?, ?, ?)",
            (tid, title, aid, bpm, duration),
        )
        if aid:
            conn.execute("INSERT INTO djmdArtist VALUES (?, ?)", (aid, artist))
    conn.commit()
    conn.close()


class TestCalculateDiffEndToEnd:
    def test_same_artist_on_both_sides_is_unchanged(self, tmp_path: Path, fake_rbox) -> None:
        artists = [SimpleNamespace(id="1", name="Artist A"), SimpleNamespace(id="2", name="B")]
        contents = [
            SimpleNamespace(id="1", title="Drift", artist_id="1", length=300, bpm=12800),
            SimpleNamespace(id="2", title="Bloom", artist_id="2", length=200, bpm=12000),
            SimpleNamespace(id="3", title="New One", artist_id="1", length=100, bpm=12500),
        ]
        fake_rbox["db"] = FakeMasterDb(contents, artists, [])
        engine = UsbSyncEngine(str(tmp_path / "master.db"), str(tmp_path / "usb"))
        _write_plain_stick_db(
            engine.usb_db_path,
            [
                ("10", "Drift", "Artist A", 300, 12800),  # identical → hash match
                ("11", "bloom", "b", 999, 12000),  # same name, other length → update
                ("12", "Gone", "X", 1, 1),  # not local → remove
            ],
        )

        diff = engine.calculate_diff()

        # Before the fix every local ArtistName was "", so "Drift" never
        # hash-matched and to_add was 3. `unchanged` = local - to_add - to_update
        # subtracts "Bloom" twice (to_update is a subset of to_add) — pre-existing.
        assert diff["tracks"] == {"to_add": 2, "to_remove": 2, "to_update": 1, "unchanged": 0}
