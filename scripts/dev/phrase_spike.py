"""
phrase_spike.py — manual P0 verification for the phrase memory-cue ANLZ write.

Risk R1 (from the plan): does Rekordbox display ANLZ-written MEMORY cues for a
track that is ALREADY in its library, or only on (re-)import / re-analyse?
This script answers it empirically on ONE real track:

  1. resolve the track's live ANLZ dir,
  2. read existing memory-cue count (before),
  3. generate phrase cues from the stored beat grid,
  4. patch them in as memory cues (a timestamped .bak-* is written first),
  5. print before/after so you can refresh Rekordbox and look.

Then: in Rekordbox, reload the track (or "Reload Tags" / re-open the library)
and check whether the new memory cues appear on the waveform. If they do, the
live-library path works; if not, the cues still ride along to USB export / CDJ.

Usage (run from the repo root):
  python scripts/dev/phrase_spike.py --track-id 123
  python scripts/dev/phrase_spike.py --track-id 123 --phrase-length 8
  python scripts/dev/phrase_spike.py --track-id 123 --restore   # roll back newest backup

This touches REAL library ANLZ files (a backup is always made first). It never
writes master.db.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys
from pathlib import Path

# Make `app` importable when run as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.anlz_cue_patch import _walk_tags  # noqa: E402
from app.config import DB_FILENAME  # noqa: E402
from app.phrase_generator import (  # noqa: E402
    commit_phrase_cues,
    extract_beats_from_db,
    generate_phrase_cues,
    resolve_anlz_dir,
)


def _db_path() -> str:
    return str(Path(os.environ.get("APPDATA", "")) / "Pioneer" / "rekordbox" / DB_FILENAME)


def _count_memory_cues(anlz_dir: str, base: str = "ANLZ0000") -> int:
    """Count memory-cue PCOB entries in the .DAT (best-effort, for reporting)."""
    dat = Path(anlz_dir) / f"{base}.DAT"
    if not dat.exists():
        dats = sorted(Path(anlz_dir).glob("*.DAT"))
        if not dats:
            return -1
        dat = dats[0]
    data = dat.read_bytes()
    tags, _ = _walk_tags(data)
    for magic, start, total_len in tags:
        if magic == b"PCOB" and total_len >= 18:
            cue_type = struct.unpack(">I", data[start + 12 : start + 16])[0]
            if cue_type == 0:  # memory list
                return struct.unpack(">H", data[start + 16 : start + 18])[0]
    return 0


def _restore(anlz_dir: str) -> None:
    directory = Path(anlz_dir)
    restored = 0
    for ext in ("DAT", "EXT", "2EX"):
        backups = sorted(directory.glob(f"*.{ext}.bak-*"), reverse=True)
        if not backups:
            continue
        newest = backups[0]
        target = Path(str(newest).rsplit(".bak-", 1)[0])
        shutil.copy2(newest, target)
        print(f"  restored {target.name}  <-  {newest.name}")
        restored += 1
    if not restored:
        print("  no .bak-* files found — nothing to restore")


def main() -> int:
    ap = argparse.ArgumentParser(description="P0 spike: patch phrase memory cues into one track")
    ap.add_argument("--track-id", type=int, required=True, help="Rekordbox integer track ID")
    ap.add_argument("--phrase-length", type=int, default=16, choices=(8, 16, 32))
    ap.add_argument("--restore", action="store_true", help="roll back the newest backup, then exit")
    args = ap.parse_args()

    db_path = _db_path()
    print(f"master.db : {db_path}")
    if not Path(db_path).exists():
        print("ERROR: master.db not found — is Rekordbox installed for this user?")
        return 2

    anlz_dir = resolve_anlz_dir(args.track_id, db_path)
    if not anlz_dir:
        print(f"ERROR: no ANLZ dir for track_id={args.track_id} — is it analysed?")
        return 2
    print(f"ANLZ dir  : {anlz_dir}")

    if args.restore:
        print("Restoring newest backup:")
        _restore(anlz_dir)
        return 0

    before = _count_memory_cues(anlz_dir)
    print(f"memory cues (before): {before}")

    beats = extract_beats_from_db(args.track_id, db_path)
    if not beats:
        print("ERROR: no beat grid for this track — analyse it first")
        return 2
    cues = generate_phrase_cues(beats, phrase_length=args.phrase_length)
    phrase_cues = [c for c in cues if c.get("type") == "phrase_start"]
    print(f"generated  : {len(phrase_cues)} phrase cues (every {args.phrase_length} bars)")

    result = commit_phrase_cues(args.track_id, cues, db_path)
    after = _count_memory_cues(anlz_dir)
    print(f"memory cues (after) : {after}")
    print(f"written    : {result.get('written')}  dat={result.get('dat')} ext={result.get('ext')}")
    print(f"backups    : {len(result.get('backups', []))} file(s)")
    print()
    print("NEXT: in Rekordbox, reload the track (Reload Tags / re-open library) and")
    print("check the waveform for the new memory cues. To undo:")
    print(f"  python scripts/dev/phrase_spike.py --track-id {args.track_id} --restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
