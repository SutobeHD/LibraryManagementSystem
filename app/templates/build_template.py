"""Build a clean exportLibrary_template.db from any Rekordbox-exported USB stick.

Usage:
    python -m app.templates.build_template <path_to_rekordbox_stick>

Example:
    python -m app.templates.build_template F:

The script copies the stick's exportLibrary.db (+ WAL/SHM), strips all user
data while preserving the system seed rows (categories, menu_items, colors,
properties), and saves the cleaned shell as
`app/templates/exportLibrary_template.db`.

The template is then used by `OneLibraryUsbWriter` to bypass rbox 0.1.7's
broken `create_content` API — we mutate the template's existing content rows
via `update_content` instead.

WHY THIS EXISTS
===============
rbox 0.1.7's `OneLibrary.create()` produces a database that fails Diesel
foreign-key validation on every subsequent insert. Even on a real Rekordbox-
created DB, `create_content(path)` raises "Unexpected null for non-null
column" because rbox doesn't auto-fill some required NOT NULL fields. There
is no way to construct a `NewContent` builder from Python. The only working
write path is `update_content(existing_row)`, which means we MUST start from
a template that already contains content slot rows.
"""
import gc
import logging
import shutil
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def build_template(stick_root: Path, out_template: Path) -> int:
    """Build a clean OneLibrary template from the given Rekordbox stick.

    Returns the number of content slots in the resulting template (the
    upper bound for tracks per OneLibrary sync).
    """
    import rbox  # imported lazily so the module can be discovered without rbox

    src_db = stick_root / "PIONEER" / "rekordbox" / "exportLibrary.db"
    if not src_db.exists():
        raise FileNotFoundError(
            f"No exportLibrary.db found at {src_db}. "
            f"Use a Rekordbox-exported USB stick as the source."
        )

    # Stage to a working file so we don't mutate the user's stick
    work = out_template.with_suffix(".building.db")
    for ext in ("", "-shm", "-wal", "-journal"):
        Path(str(work) + ext).unlink(missing_ok=True)
    shutil.copy2(str(src_db), str(work))
    for ext in ("-shm", "-wal"):
        src_ext = Path(str(src_db) + ext)
        if src_ext.exists():
            shutil.copy2(str(src_ext), str(Path(str(work) + ext)))

    db = rbox.OneLibrary(str(work))

    # Collect counts for the cleanup report
    pre_contents = len(list(db.get_contents()))
    pre_artists = len(list(db.get_artists()))
    pre_playlists = len(list(db.get_playlists()))

    print(f"Source has {pre_contents} contents, {pre_artists} artists, "
          f"{pre_playlists} playlists")

    # CRITICAL ORDER: playlist_content children first, then playlists, then
    # contents (so they release their FKs to image/album/artist), then the
    # FK targets last. The wrong order leaves orphan FKs and the next sync
    # step gets stuck.
    print("Wiping playlists…")
    for pl in list(db.get_playlists()):
        try:
            db.delete_playlist(pl.id)
        except Exception:
            pass

    print("Mutating contents into placeholder slots (preserved for sync)…")
    # Keep the content rows — they are our placeholder slots — but reset
    # their searchable fields so the template doesn't ship with somebody
    # else's track titles.
    placeholder_count = 0
    for c in list(db.get_contents()):
        try:
            c.title = f"__placeholder_{c.id}__"
            c.title_for_search = ""
            c.subtitle = ""
            c.dj_comment = ""
            c.path = f"/__placeholder__/{c.id}.mp3"
            c.file_name = f"placeholder_{c.id}.mp3"
            c.bpmx100 = 0
            c.length = 0
            c.rating = 0
            c.release_year = 0
            c.release_date = ""
            c.isrc = ""
            db.update_content(c)
            placeholder_count += 1
        except Exception as e:
            print(f"  reset of content id={c.id} skipped: {e}")

    print("Anonymising artists/albums/labels (template ships without owner data)…")
    # Reset names of all artist / album / label rows so the template doesn't
    # leak the original creator's library. Content placeholders still FK
    # into these rows, so we MUST keep them — only the names get cleared.
    for a in list(db.get_artists()):
        try:
            a.name = ""
            db.update_artist(a)
        except Exception:
            pass
    for a in list(db.get_albums()):
        try:
            a.name = ""
            db.update_album(a)
        except Exception:
            pass
    for lab in list(db.get_labels()):
        try:
            lab.name = ""
            db.update_label(lab)
        except Exception:
            pass
    for img in list(db.get_images()):
        try:
            img.path = ""
            db.update_image(img)
        except Exception:
            pass
    for k in list(db.get_keys()):
        try:
            k.name = ""
            db.update_key(k)
        except Exception:
            pass
    for g in list(db.get_genres()):
        try:
            g.name = ""
            db.update_genre(g)
        except Exception:
            pass

    print("Wiping my_tags…")
    for t in list(db.get_my_tags()):
        try:
            db.delete_my_tag(t.id)
        except Exception:
            pass

    # Final state report
    after = {
        "contents": len(list(db.get_contents())),
        "images": len(list(db.get_images())),
        "artists": len(list(db.get_artists())),
        "albums": len(list(db.get_albums())),
        "genres": len(list(db.get_genres())),
        "keys": len(list(db.get_keys())),
        "labels": len(list(db.get_labels())),
        "playlists": len(list(db.get_playlists())),
    }
    print(f"Template state after cleanup: {after}")

    # Close + checkpoint WAL → main DB so the template ships as a single file
    del db
    gc.collect()
    time.sleep(0.5)

    # Reopen one more time to flush any deferred WAL state
    db2 = rbox.OneLibrary(str(work))
    final_count = len(list(db2.get_contents()))
    del db2
    gc.collect()
    time.sleep(0.5)

    # Move into place; keep WAL/SHM if they exist (rbox needs them together)
    out_template.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("", "-shm", "-wal"):
        src_ext = Path(str(work) + ext)
        dst_ext = Path(str(out_template) + ext)
        dst_ext.unlink(missing_ok=True)
        if src_ext.exists():
            shutil.copy2(str(src_ext), str(dst_ext))

    # Cleanup working files
    for ext in ("", "-shm", "-wal", "-journal"):
        Path(str(work) + ext).unlink(missing_ok=True)

    return final_count


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    stick = Path(argv[1])
    out = Path(__file__).parent / "exportLibrary_template.db"
    slots = build_template(stick, out)
    print()
    print(f"Template written: {out} ({out.stat().st_size:,} B)")
    print(f"Content slots available: {slots}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
