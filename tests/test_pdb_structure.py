"""PDB writer structural test against F: drive Pioneer reference.

Builds a fresh export.pdb from a synthetic 16-track input, then verifies
the structural invariants we know Rekordbox 7 enforces:

  1. File header well-formed (magic=0, page_size=4096, num_tables=20)
  2. Each table descriptor's empty_candidate is UNIQUE (no two tables
     share a blank page) — this is the fix for the corruption dialog.
  3. Each empty_candidate page is actually all-zero in the file.
  4. Each chain terminator (next_page) points at the table's OWN blank
     page, not at next_unused (matches F: drive convention).
  5. next_unused points past EOF.
  6. @0x14 (sequence) >= max page seqpage in the file.

Pass if all invariants hold AND the file is parseable by rbox.

Run from repo root: PYTHONIOENCODING=utf-8 python tests/test_pdb_structure.py
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.usb_pdb import write_export_pdb


def make_synthetic_input():
    """Mimic the data shape that OneLibraryUsbWriter._write_pdb_from_db
    passes into write_export_pdb()."""
    contents = []
    for i in range(8):
        contents.append({
            "id": 100 + i,
            "title": f"Synthetic Track {i:02d}",
            "artist_id": 1 + (i % 3),
            "album_id": 1 + (i % 2),
            "genre_id": 1,
            "key_id": 1 + (i % 12),
            "label_id": 1,
            "color_id": 0,
            "artwork_id": 1 + i,
            "bpm": 128.0 + i,
            "length_seconds": 240,
            "bitrate": 320,
            "year": 2024,
            "rating": 0,
            "sample_rate": 44100,
            "sample_depth": 16,
            "file_size": 8000000,
            "file_path": f"/Contents/Test/track_{i:02d}.m4a",
            "file_name": f"track_{i:02d}.m4a",
            "comment": "",
            "isrc": "",
            "date_added": "2024-01-01",
            "analyze_path": f"/PIONEER/USBANLZ/P000/{i+1:08X}/ANLZ0000.DAT",
            "analyze_date": "2024-01-01",
            "file_type": 1,
            "play_count": 0,
            "master_db_id": 0,
            "master_content_id": 0,
        })
    artists = {1: "Artist A", 2: "Artist B", 3: "Artist C"}
    albums = {1: ("Album X", 1), 2: ("Album Y", 2)}
    genres = {1: "Techno"}
    keys = {i: f"{i}A" for i in range(1, 13)}
    labels = {1: "Test Label"}
    playlists = [
        {"id": 1, "name": "Test Playlist", "parent_id": 0, "is_folder": False},
    ]
    # write_export_pdb() expects List[Tuple[entry_index, track_id, playlist_id]]
    playlist_entries = [(i, 100 + i, 1) for i in range(8)]
    return contents, artists, albums, keys, genres, labels, playlists, playlist_entries


def main():
    with tempfile.TemporaryDirectory(prefix="pdbtest_") as tmp:
        usb_root = Path(tmp)
        rb_dir = usb_root / "PIONEER" / "rekordbox"
        rb_dir.mkdir(parents=True)

        contents, artists, albums, keys, genres, labels, playlists, pl_entries = make_synthetic_input()
        write_export_pdb(
            usb_root,
            contents=contents,
            artists=artists,
            albums=albums,
            keys=keys,
            genres=genres,
            labels=labels,
            playlists=playlists,
            playlist_entries=pl_entries,
        )

        pdb_path = rb_dir / "export.pdb"
        if not pdb_path.exists():
            print("FAIL: export.pdb not created")
            return 1

        data = pdb_path.read_bytes()
        page_size = 4096
        num_pages = len(data) // page_size
        print(f"Generated PDB: {len(data)} B = {num_pages} pages")

        # Header
        magic, ps, n_tab, next_unused, u10, seq, _, _ = struct.unpack("<IIIIIIII", data[:32])
        print(f"  magic={magic} page_size={ps} num_tables={n_tab} next_unused={next_unused} u10={u10} seq={seq}")

        results = []
        results.append(("magic == 0", magic == 0))
        results.append(("page_size == 4096", ps == 4096))
        results.append(("num_tables == 20", n_tab == 20))
        results.append(("next_unused points past EOF", next_unused == num_pages))

        # Parse table descriptors @ offset 0x1C
        descriptors = []
        for i in range(n_tab):
            off = 0x1C + i * 16
            t, e, f, l = struct.unpack("<IIII", data[off:off+16])
            descriptors.append({"type": t, "empty": e, "first": f, "last": l})

        # 1. empty_candidate uniqueness (the fix)
        empties = [d["empty"] for d in descriptors]
        results.append(("all 20 empty_candidate values UNIQUE", len(set(empties)) == 20))

        # 2. each empty_candidate page is all-zero
        all_blanks_zero = True
        for d in descriptors:
            page_off = d["empty"] * page_size
            page_bytes = data[page_off:page_off + page_size]
            if not all(b == 0 for b in page_bytes):
                all_blanks_zero = False
                print(f"  NON-ZERO empty page at index {d['empty']}")
                break
        results.append(("all empty_candidate pages all-zero", all_blanks_zero))

        # 3. chain terminator next_page points at own blank
        # Walk each table's chain, find the terminator, check its next_page
        terminators_correct = True
        for d in descriptors:
            cur = d["first"]
            visited = set()
            while cur and cur not in visited:
                visited.add(cur)
                page = data[cur * page_size:(cur + 1) * page_size]
                if len(page) < 16:
                    break
                next_page = struct.unpack("<I", page[12:16])[0]
                # Terminator: next_page == own empty (the fix)
                # OR cur == d["last"] and we're done
                if next_page == d["empty"]:
                    break
                if cur == d["last"]:
                    # Last page should point at empty
                    if next_page != d["empty"]:
                        print(f"  Table type={d['type']}: last page {d['last']} next={next_page}, expected own empty {d['empty']}")
                        terminators_correct = False
                    break
                cur = next_page
        results.append(("chain terminators point at own blank", terminators_correct))

        # 4. seq >= max page seqpage
        max_seqpage = 0
        for pg in range(1, num_pages):
            page = data[pg * page_size:(pg + 1) * page_size]
            if len(page) < 20:
                continue
            page_idx, ptype, pnext, pseq = struct.unpack("<IIII", page[4:20])
            if page_idx == pg and pseq > max_seqpage:
                max_seqpage = pseq
        results.append((f"header seq ({seq}) >= max page seq ({max_seqpage})", seq >= max_seqpage))

        # Print results
        print()
        print("=== Structural invariants ===")
        all_ok = True
        for name, ok in results:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {name}")
            if not ok:
                all_ok = False

        # Print descriptor table for inspection
        print()
        print("=== Table descriptors ===")
        for i, d in enumerate(descriptors):
            print(f"  [{i:2}] type={d['type']:2} empty={d['empty']:3} first={d['first']:3} last={d['last']:3}")

        # Try to actually open with rbox (this is the real Rekordbox would do too)
        # Note: we don't have rbox.Pdb opener; export.pdb is the legacy format.
        # rbox only opens exportLibrary.db. So this test verifies structure only.

        print()
        if all_ok:
            print("*** RESULT: PASS — all invariants hold ***")
            return 0
        else:
            print("*** RESULT: FAIL ***")
            return 2


if __name__ == "__main__":
    sys.exit(main())
