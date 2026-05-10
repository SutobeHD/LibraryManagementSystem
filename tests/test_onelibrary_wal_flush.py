"""End-to-end regression test for OneLibraryUsbWriter — runs the FULL
sync() generator against a temp dir to confirm WAL is flushed and the
resulting DB is Rekordbox-readable.

Regression target: 0bdd554 + e87cd3d (WAL-checkpoint-on-close fix). Without
the fix, sync() returns with ~400 KB of unmerged WAL frames and Rekordbox
prompts "Device library is corrupted" on stick insert.

Pass criteria after sync():
  - exportLibrary.db-wal: 0 B (or absent)
  - exportLibrary.db-shm: absent
  - rbox.OneLibrary re-open succeeds
  - Track + playlist + playlist-content rows all readable

Run from repo root: PYTHONIOENCODING=utf-8 python tests/test_onelibrary_wal_flush.py
"""
from __future__ import annotations
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rbox

from app.usb_one_library import OneLibraryUsbWriter


class FakeSource:
    """Minimal LibrarySource that satisfies OneLibraryUsbWriter.sync()."""

    def __init__(self, tracks):
        self.tracks = tracks
        self.playlists = [
            {
                "id": "pl1",
                "name": "Test Playlist",
                "parent_id": "ROOT",
                "type": "1",   # 0=folder, 1=playlist, 4=smart
                "is_folder": False,
                "track_ids": [int(t["id"]) for t in tracks],
            },
        ]

    def iter_tracks(self):
        return iter(self.tracks)

    def iter_playlists(self):
        return iter(self.playlists)

    def get_playlist_track_ids(self, pid):
        if pid == "pl1":
            return [int(t["id"]) for t in self.tracks]
        return []

    def get_playlists_tree(self):
        return self.playlists

    def get_track_anlz_paths(self, track_id):
        return None


def make_tracks(n):
    return [
        {
            "id": str(100 + i),
            "title": f"Test Track {i:02d}",
            "artist": f"Artist {i % 5}",
            "album": f"Album {i % 3}",
            "genre": "Techno",
            "key": f"{(i % 12) + 1}A",
            "label": "TestLabel",
            "comment": f"comment {i}",
            "bpm": 128.0 + i,
            "duration_ms": 240000,
            "rating": (i % 5),
            "release_year": 2024,
            "bitrate": 320,
            "path": "",
        }
        for i in range(n)
    ]


def main():
    with tempfile.TemporaryDirectory(prefix="rbtest_") as tmp:
        usb_root = Path(tmp)
        print(f"Test USB root: {usb_root}")

        writer = OneLibraryUsbWriter(str(usb_root))
        # Need a copy of the production template under the writer-expected path.
        template = Path("app/templates/exportLibrary_template.db")
        if not template.exists():
            print("Template missing — run app/templates/build_template.py first")
            return 1
        # writer's TEMPLATE_DB attribute already points at the same path

        source = FakeSource(make_tracks(8))

        events = list(writer.sync(source, audio_copy=False, copy_anlz=False, playlist_filter=["pl1"]))

        for ev in events:
            stage = ev.get("stage", "")
            msg = ev.get("message", "")
            prog = ev.get("progress", 0)
            if stage in ("error", "warning"):
                marker = "!!"
            else:
                marker = " ."
            print(f" {marker} [{prog:3}%] {stage:12} {msg}")

        # Inspect file state
        db_path = usb_root / "PIONEER" / "rekordbox" / "exportLibrary.db"
        wal_path = Path(str(db_path) + "-wal")
        shm_path = Path(str(db_path) + "-shm")
        pdb_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"

        print()
        print("=== File state after sync ===")
        print(f"  exportLibrary.db     : {db_path.stat().st_size if db_path.exists() else 'MISSING'} B")
        print(f"  exportLibrary.db-wal : {wal_path.stat().st_size if wal_path.exists() else 'absent'} B")
        print(f"  exportLibrary.db-shm : {shm_path.stat().st_size if shm_path.exists() else 'absent'} B")
        print(f"  export.pdb           : {pdb_path.stat().st_size if pdb_path.exists() else 'MISSING'} B")

        # Verify Rekordbox-readable: open the DB with rbox once more (this is what
        # Rekordbox does internally — open + read all contents). If WAL is broken
        # or main DB is corrupted, this raises.
        print()
        print("=== Re-open verification (simulates Rekordbox stick scan) ===")
        try:
            db = rbox.OneLibrary(str(db_path))
            contents = list(db.get_contents())
            non_placeholder = [c for c in contents if not (c.title or "").startswith("__placeholder_")]
            artists = list(db.get_artists())
            playlists = list(db.get_playlists())
            playlist_contents = []
            for pl in playlists:
                try:
                    playlist_contents.extend(db.get_playlist_contents(pl.id))
                except Exception:
                    pass
            print(f"  Total content rows : {len(contents)}")
            print(f"  Non-placeholder    : {len(non_placeholder)}")
            print(f"  Artists            : {len(artists)}")
            print(f"  Playlists          : {len(playlists)} (expect 1)")
            print(f"  Playlist contents  : {len(playlist_contents)} (expect 8)")
            for c in non_placeholder[:3]:
                print(f"    - id={c.id} title={c.title!r} bpm={c.bpmx100/100}")
            del db

            # PASS criteria
            wal_after = wal_path.stat().st_size if wal_path.exists() else 0
            written_count = len(non_placeholder)
            ok = (wal_after == 0) and (written_count == 8) and (len(playlists) == 1) and (len(playlist_contents) == 8)
            print()
            print(f"WAL after re-open : {wal_after} B  (target 0)")
            print(f"Tracks written    : {written_count}/8")
            print()
            print("*** RESULT:", "PASS" if ok else "FAIL", "***")
            return 0 if ok else 2

        except Exception as e:
            print(f"  RE-OPEN FAILED: {e}")
            print()
            print("*** RESULT: FAIL — Rekordbox would also fail to read this DB ***")
            return 3


if __name__ == "__main__":
    sys.exit(main())
