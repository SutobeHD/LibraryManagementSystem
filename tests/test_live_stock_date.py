"""StockDate in live track dicts: a missing date must not become the string "None" (B17),
and a NULL stock_date falls back to the day the row was created."""

from datetime import date, datetime
from types import SimpleNamespace

from app.live_database import LiveRekordboxDB


def _row(rid: int, stock_date, created_at=None):
    return SimpleNamespace(
        id=rid,
        artist_id=None,
        album_id=None,
        genre_id=None,
        label_id=None,
        key_id=None,
        title=f"t{rid}",
        stock_date=stock_date,
        created_at=created_at,
    )


def _load(rows) -> dict:
    db = LiveRekordboxDB("does-not-exist.db")
    db._local.conn = SimpleNamespace(get_contents=lambda: rows)
    db.artist_map = db.album_map = db.genre_map = db.label_map = db.key_map = {}
    db.remixer_map = db.lyricist_map = db.composer_map = {}
    db.track_to_tags = {}
    db.track_to_tag_ids = {}
    db._load_tracks()
    return db.tracks


def test_stock_date_passes_through_and_null_is_empty():
    tracks = _load([_row(1, "2024-05-01"), _row(2, None)])

    assert tracks["1"]["StockDate"] == "2024-05-01"
    assert tracks["2"]["StockDate"] == ""


def test_missing_stock_date_falls_back_to_created_at_day():
    tracks = _load(
        [
            _row(1, None, datetime(2023, 3, 9, 21, 4, 5, 123000)),
            _row(2, "", "2022-11-30 08:15:00.000 +00:00"),
            _row(3, "  ", date(2021, 1, 2)),
            _row(4, None, "not a date"),
        ]
    )

    assert tracks["1"]["StockDate"] == "2023-03-09"
    assert tracks["2"]["StockDate"] == "2022-11-30"
    assert tracks["3"]["StockDate"] == "2021-01-02"
    assert tracks["4"]["StockDate"] == ""


def test_stock_date_wins_over_created_at():
    tracks = _load([_row(1, "2024-05-01", datetime(2020, 1, 1, 12, 0))])

    assert tracks["1"]["StockDate"] == "2024-05-01"
