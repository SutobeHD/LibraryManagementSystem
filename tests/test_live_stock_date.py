"""StockDate in live track dicts: a missing date must not become the string "None" (B17)."""

from types import SimpleNamespace

from app.live_database import LiveRekordboxDB


def _row(rid: int, stock_date):
    return SimpleNamespace(
        id=rid,
        artist_id=None,
        album_id=None,
        genre_id=None,
        label_id=None,
        key_id=None,
        title=f"t{rid}",
        stock_date=stock_date,
    )


def test_stock_date_passes_through_and_null_is_empty():
    db = LiveRekordboxDB("does-not-exist.db")
    db._local.conn = SimpleNamespace(get_contents=lambda: [_row(1, "2024-05-01"), _row(2, None)])
    db.artist_map = db.album_map = db.genre_map = db.label_map = db.key_map = {}
    db.remixer_map = db.lyricist_map = db.composer_map = {}
    db.track_to_tags = {}
    db.track_to_tag_ids = {}

    db._load_tracks()

    assert db.tracks["1"]["StockDate"] == "2024-05-01"
    assert db.tracks["2"]["StockDate"] == ""
