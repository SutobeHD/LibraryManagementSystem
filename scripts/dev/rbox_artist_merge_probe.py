#!/usr/bin/env python3
"""Probe rbox's artist/playlist write semantics against a COPY of a master.db.

Evidence behind `docs/research/research/exploring_library-artist-hub.md`
Findings wave 5. Re-run it after an rbox upgrade — every claim the artist-hub
merge design rests on is checked here.

The probe WRITES. It refuses to run against the real library and refuses to
run while Rekordbox is open. Prepare a copy first (Rekordbox closed):

    cp "$APPDATA/Pioneer/rekordbox/master.db"            /tmp/rbtest/
    cp "$APPDATA/Pioneer/rekordbox/master.db-wal"        /tmp/rbtest/
    cp "$APPDATA/Pioneer/rekordbox/master.db-shm"        /tmp/rbtest/
    cp "$APPDATA/Pioneer/rekordbox/masterPlaylists6.xml" /tmp/rbtest/
    python scripts/dev/rbox_artist_merge_probe.py --db /tmp/rbtest/master.db

masterPlaylists6.xml must sit beside the copy: without it rbox sets
plxml_path=None and silently skips the XML update on every playlist create.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TAG = "__LMS_PROBE__"


def _real_db() -> Path | None:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Pioneer" / "rekordbox" / "master.db" if appdata else None


def _guard(db: Path) -> None:
    real = _real_db()
    if real and db.resolve() == real.resolve():
        sys.exit(f"refusing to write to the real library: {db}")
    if not db.exists():
        sys.exit(f"no such file: {db}")
    if not (db.parent / "masterPlaylists6.xml").exists():
        sys.exit(f"copy masterPlaylists6.xml next to {db.name} first — see the module docstring")


def _show(label: str, value: object) -> None:
    print(f"  {label:<42} {value}")


def _section(name: str) -> None:
    print(f"\n{'=' * 72}\n{name}\n{'=' * 72}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, type=Path, help="path to a COPY of master.db")
    args = ap.parse_args()
    _guard(args.db)

    import rbox

    if rbox.is_rekordbox_running():
        sys.exit("Rekordbox is running — close it first")

    db = rbox.MasterDb(str(args.db))
    xml = args.db.parent / "masterPlaylists6.xml"
    xml_size_before = xml.stat().st_size

    _section("SETUP")
    _show("db", args.db)
    _show("playlist_xml_path()", db.playlist_xml_path())
    _show("get_local_usn()", db.get_local_usn())

    _section("delete_playlist_song arity")
    try:
        db.delete_playlist_song("1", "2")
        _show("two-arg call", "ACCEPTED — app/live_database.py:1342 would be correct")
    except TypeError as exc:
        _show("two-arg call raises", exc)

    _section("USN on create + playlist identity")
    u0 = db.get_local_usn()
    folder = db.create_playlist_folder(f"{TAG}Artists", None)
    u1 = db.get_local_usn()
    pl = db.create_playlist(f"{TAG}Child", folder.id, None, None, None)
    u2 = db.get_local_usn()
    content = db.get_contents()[0]
    song = db.create_playlist_song(pl.id, content.id, None)
    u3 = db.get_local_usn()
    _show("folder / playlist / song usn delta", f"+{u1 - u0} / +{u2 - u1} / +{u3 - u2}")
    _show(
        "rb_local_usn written on new rows",
        f"{folder.rb_local_usn} / {pl.rb_local_usn} / {song.rb_local_usn}",
    )
    _show("folder id -> hex (as in the xml)", f"{folder.id} -> {format(int(folder.id), 'X')}")

    dupe = db.create_playlist_folder(f"{TAG}Artists", None)
    same_name = [p for p in db.get_playlists() if p.name == f"{TAG}Artists"]
    _show("duplicate folder name accepted", f"{len(same_name)} siblings ({folder.id}, {dupe.id})")
    picked = db.get_playlist_by_path([f"{TAG}Artists"])
    _show("get_playlist_by_path picks", f"{picked.id if picked else None} (silently, no error)")

    _section("removal — the correct one-arg form")
    rows = db.get_playlist_songs(pl.id)
    u4 = db.get_local_usn()
    db.delete_playlist_song(rows[0].id)
    _show(
        "delete_playlist_song(row.id)",
        f"ok, usn +{db.get_local_usn() - u4}, {len(db.get_playlist_songs(pl.id))} left",
    )

    _section("artist writers — the load-bearing check")
    target = next(c for c in db.get_contents() if c.artist_id)
    _show("content usn BEFORE", target.rb_local_usn)
    _show("search_str / src_artist_name", f"{target.search_str!r} / {target.src_artist_name!r}")

    db.update_content_artist(target.id, f"{TAG}Artist A")
    via_helper = db.get_content_by_id(target.id)
    _show("update_content_artist -> content usn", f"{via_helper.rb_local_usn} (unchanged = STALE)")
    _show("  created the artist on demand?", db.get_artist_by_name(f"{TAG}Artist A") is not None)

    artist_b = db.get_artist_by_name(f"{TAG}Artist B") or db.create_artist(f"{TAG}Artist B")
    via_helper.artist_id = artist_b.id
    db.update_content(via_helper)
    via_model = db.get_content_by_id(target.id)
    _show("update_content(item) -> content usn", f"{via_model.rb_local_usn} (bumped)")
    _show("  updated_at", via_model.updated_at)

    _section("delete_artist side effects")
    db.update_content_remixer(target.id, f"{TAG}Artist B")
    db.update_content_composer(target.id, f"{TAG}Artist B")
    db.delete_artist(artist_b.id)
    after = db.get_content_by_id(target.id)
    _show(
        "artist / remixer / composer",
        f"{after.artist_id} / {after.remixer_id} / {after.composer_id}",
    )
    _show("artist row deleted", db.get_artist_by_id(artist_b.id) is None)
    _show("content usn after detach", f"{after.rb_local_usn} (stale — the detach does not bump)")

    _section("masterPlaylists6.xml")
    _show("size before -> after", f"{xml_size_before} -> {xml.stat().st_size}")
    _show(
        "folder node present (hex id)",
        format(int(folder.id), "X") in xml.read_text(encoding="utf-8", errors="replace"),
    )

    print("\nDone. Discard the copy — it now contains probe rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
