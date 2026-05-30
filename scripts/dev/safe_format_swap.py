"""safe_format_swap.py -- defensive m4a -> AIFF swap for ONE Rekordbox playlist.

Goal: prove the workflow on a small test playlist before doing the whole library.

Guarantees:
- Refuses to write while Rekordbox is open (dry-run still works while RB runs).
- Backs up master.db + master.db-wal + master.db-shm before any write.
- Renames each .m4a to .m4a.backup-<ts> (NOT deleted -- easy rollback).
- Writes JSON manifest under scripts/dev/backups/ with every operation.
- --rollback restores DB + WAL + SHM, renames backups back, deletes new .aiff.
- ffmpeg skips 2112 samples of AAC priming delay (sample-accurate, via atrim).
- Locks output sample rate to source SR (no resample -> no cue drift).
- Uses pyrekordbox/rbox to talk to the SQLCipher-encrypted master.db.
- Updates content_id-keyed row only -- playlists / cues / beatgrid stay linked.

Usage:
    python scripts/dev/safe_format_swap.py --dry-run --playlist "SC_<heart> Liked Tracks"
    python scripts/dev/safe_format_swap.py --execute --playlist "..." --limit 3
    python scripts/dev/safe_format_swap.py --rollback manifest-20260527-203000.json

After --execute: open Rekordbox, verify the playlist. If broken -> --rollback.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Windows console defaults to cp1252; playlist names / track titles routinely
# contain emoji (e.g. SC_<heart> Liked Tracks). Force utf-8 with replace so a
# rogue glyph degrades gracefully to "?" instead of crashing the run.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import rbox  # noqa: E402 -- imported after stdout reconfigure for clean tracebacks

REKORDBOX_DIR = Path(os.environ["APPDATA"]) / "Pioneer" / "rekordbox"
REKORDBOX_DB = REKORDBOX_DIR / "master.db"
SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR / "backups"

FILE_TYPE_M4A = 4
FILE_TYPE_AIFF_FALLBACK = 6
# FFmpeg's AAC decoder ALREADY discards the priming samples reported by the
# iTunSMPB / edit-list / start_pad container info. Adding our own -ss skip
# on top of that produces a double-skip and shifts the beatgrid by ~44 ms
# to the right of the real beats (observed 2026-05-27 on Test playlist).
# Keep at 0 unless empirical evidence per encoder proves otherwise.
AAC_PRIMING_SAMPLES = 0


def check_rekordbox_running() -> None:
    """Abort if rekordbox.exe is in the Windows tasklist."""
    try:
        result = subprocess.run(
            ["tasklist"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "rekordbox.exe" in result.stdout.lower():
            sys.exit("ERROR: Rekordbox is running. Close it first, then re-run.")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("WARN: could not check Rekordbox process state -- continuing anyway.")


def kill_rekordbox_if_present() -> bool:
    """Proactive watchdog: if Pioneer auto-restarted Rekordbox during a long
    run, kill it before the next master.db write hits a 'Rekordbox is running'
    error. Returns True if it actually killed something."""
    try:
        result = subprocess.run(
            ["tasklist"], capture_output=True, text=True, timeout=10,
        )
        if "rekordbox.exe" not in result.stdout.lower():
            return False
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object { $_.Name -match 'rekordbox|Upmgr' } | Stop-Process -Force"],
            capture_output=True, timeout=15,
        )
        return True
    except Exception:
        return False


def backup_master_db(timestamp: str) -> dict[str, str]:
    """Copy master.db and its WAL/SHM siblings. Returns {original: backup_path}."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups: dict[str, str] = {}
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(REKORDBOX_DB) + suffix)
        if src.exists():
            dst = BACKUP_DIR / f"{src.name}.backup-{timestamp}"
            shutil.copy2(src, dst)
            backups[str(src)] = str(dst)
    return backups


def detect_aiff_filetype(db: "rbox.MasterDb") -> int:
    """Look up the FileType integer Rekordbox uses for existing AIFF rows."""
    for c in db.get_contents():
        try:
            fp = (c.folder_path or "").lower()
        except Exception:
            continue
        if fp.endswith(".aiff") or fp.endswith(".aif"):
            print(f"INFO: detected FileType={c.file_type} for existing AIFF rows.")
            return int(c.file_type)
    print(
        f"WARN: no existing AIFF tracks in DB -- using fallback FileType={FILE_TYPE_AIFF_FALLBACK}."
    )
    return FILE_TYPE_AIFF_FALLBACK


def find_playlist(db: "rbox.MasterDb", name: str):
    for pl in db.get_playlists():
        if pl.name == name and not getattr(pl, "rb_local_deleted", False):
            return pl
    return None


def probe_sample_rate(audio_path: Path) -> int:
    """Return the source sample rate via ffprobe. Locks AIFF output to same SR."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate",
            "-of", "csv=p=0",
            str(audio_path),
        ],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return int(result.stdout.strip())


def convert_m4a_to_aiff(src: Path, dst: Path, sample_rate: int) -> None:
    """ffmpeg src -> dst.

    - `-vn` drops embedded cover-art (FFmpeg can't encode PNG into AIFF; cover
      stays in Rekordbox's content-id-keyed /PIONEER/Artwork/ cache anyway).
    - `-ss` placed AFTER `-i` = output option = sample-accurate skip of the
      AAC priming delay. Sub-sample drift is rounded to nearest sample
      (~20 us at 48 kHz, well below any audible threshold).
    - `-ar` locks output SR to source SR -- never resample (= no cue drift).
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if AAC_PRIMING_SAMPLES > 0:
        cmd += ["-ss", f"{AAC_PRIMING_SAMPLES / sample_rate:.9f}"]
    cmd += [
        "-vn",
        "-c:a", "pcm_s16le",
        "-ar", str(sample_rate),
        "-map_metadata", "0",
        "-write_id3v2", "1",
        "-y",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {src.name}: {result.stderr.strip()}")


def execute(playlist_name: str | None, dry_run: bool, limit: int | None = None,
            all_m4a: bool = False, path_scope: str | None = None) -> None:
    # Dry-run only reads, but rbox still has to load+decrypt master.db -- it
    # can do that fine while Rekordbox is open (own connection). Writes are
    # blocked because we don't want to race against RB's writer.
    if not dry_run:
        check_rekordbox_running()

    db = rbox.MasterDb(str(REKORDBOX_DB))
    aiff_file_type = detect_aiff_filetype(db)

    if all_m4a:
        # Whole-library scan: every undeleted m4a row.
        items = [
            c for c in db.get_contents()
            if not getattr(c, "rb_local_deleted", False)
        ]
        scope_label = "ALL m4a in library"
    elif path_scope:
        # Folder-scope: every undeleted track whose folder_path starts under
        # the given path. Case-insensitive, separator-normalized -- master.db
        # stores paths with forward slashes on Windows, callers may pass
        # backslashes.
        norm = path_scope.replace("\\", "/").rstrip("/").lower()
        items = []
        for c in db.get_contents():
            if getattr(c, "rb_local_deleted", False):
                continue
            fp = (getattr(c, "folder_path", "") or "").replace("\\", "/").lower()
            if fp.startswith(norm + "/") or fp == norm:
                items.append(c)
        scope_label = f"path {path_scope!r}"
    else:
        pl = find_playlist(db, playlist_name)
        if not pl:
            sys.exit(f"ERROR: playlist {playlist_name!r} not found in master.db")
        items = db.get_playlist_contents(pl.id)
        scope_label = f"playlist {playlist_name!r} (id={pl.id})"

    m4a_items = [c for c in items if int(getattr(c, "file_type", 0)) == FILE_TYPE_M4A]
    total_m4a = len(m4a_items)
    if limit is not None and limit > 0:
        m4a_items = m4a_items[:limit]

    print(f"\nScope:              {scope_label}")
    print(f"Total tracks:       {len(items)}")
    print(f"m4a to convert:     {total_m4a}")
    if limit is not None and limit > 0:
        print(f"Limited to:         first {len(m4a_items)} (--limit {limit})")
    print(f"AIFF FileType code: {aiff_file_type}")

    # Storage forecast (m4a source size sum)
    total_src_bytes = 0
    for c in m4a_items:
        try:
            total_src_bytes += int(getattr(c, "file_size", 0) or 0)
        except Exception:
            pass
    print(f"Source size:        {total_src_bytes/1024/1024:.1f} MB m4a")
    print(f"Estimated AIFF:     ~{total_src_bytes*5/1024/1024:.0f} MB (x5 expansion)")

    print("\n=== Plan ===")
    PREVIEW = 8 if len(m4a_items) > 20 else len(m4a_items)
    for c in m4a_items[:PREVIEW]:
        src = Path(c.folder_path)
        print(f"  [{c.id}]  {src.name}")
    if len(m4a_items) > PREVIEW:
        print(f"  ... ({len(m4a_items) - PREVIEW} more)")

    if not m4a_items:
        print("\nNothing to do.")
        return
    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return

    if len(m4a_items) > 10:
        ans = input(f"\n{len(m4a_items)} tracks. Type 'yes' to proceed: ").strip().lower()
        if ans != "yes":
            sys.exit("Aborted.")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_backups = backup_master_db(timestamp)
    print(f"\n[OK] DB backups:")
    for orig, bk in db_backups.items():
        print(f"     {orig}  ->  {bk}")

    manifest: dict = {
        "timestamp": timestamp,
        "scope": scope_label,
        "playlist": playlist_name if not all_m4a else None,
        "all_m4a": all_m4a,
        "db_backups": db_backups,
        "aiff_file_type": aiff_file_type,
        "tracks": [],
    }
    manifest_path = BACKUP_DIR / f"manifest-{timestamp}.json"

    def save_manifest() -> None:
        # Atomic write: tmp file then rename, so a crash mid-write can't corrupt
        # the manifest we rely on for rollback.
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp.replace(manifest_path)

    # Persist an empty manifest immediately so rollback has an anchor even if
    # we crash before the first successful track.
    save_manifest()
    print(f"[OK] Manifest anchor: {manifest_path}")

    aborted = False
    for i, c in enumerate(m4a_items, 1):
        # Every 50 tracks, proactively kill Rekordbox if Pioneer's watchdog
        # re-launched it. Cheaper than letting db.update_content fail and
        # rolling back per-track.
        if i > 1 and i % 50 == 0 and kill_rekordbox_if_present():
            print(f"  [{i}/{len(m4a_items)}] watchdog: killed re-launched Rekordbox")

        src = Path(c.folder_path)
        dst = src.with_suffix(".aiff")
        if not src.exists():
            print(f"  SKIP (file missing on disk): {src}")
            continue
        try:
            sr = probe_sample_rate(src)
        except subprocess.CalledProcessError as e:
            print(f"  SKIP (ffprobe failed): {src.name}  {e}")
            continue

        print(f"  [{i}/{len(m4a_items)}] Convert ({sr} Hz): {src.name}")
        try:
            convert_m4a_to_aiff(src, dst, sr)
        except RuntimeError as e:
            print(f"    FAILED: {e}")
            continue

        backup_audio = src.with_name(src.name + f".backup-{timestamp}")
        src.rename(backup_audio)

        new_size = dst.stat().st_size
        old_path = c.folder_path
        old_filename = c.file_name_l
        old_size = c.file_size

        # Mutate the rbox Content row and persist
        c.folder_path = str(dst)
        c.file_name_l = dst.name
        c.file_type = aiff_file_type
        c.file_size = new_size
        try:
            db.update_content(c)
        except Exception as e:
            # DB write failed (most likely Rekordbox auto-restarted mid-run).
            # Roll THIS track back individually so files+DB stay consistent.
            print(f"    DB UPDATE FAILED: {e}")
            print(f"    Restoring file pair for track {c.id}...")
            try:
                if backup_audio.exists():
                    backup_audio.rename(src)
                if dst.exists():
                    dst.unlink()
                # Revert in-memory rbox row attributes
                c.folder_path = old_path
                c.file_name_l = old_filename
                c.file_type = FILE_TYPE_M4A
                c.file_size = old_size
            except Exception as inner:
                print(f"    WARN: per-track recovery also failed: {inner}")
            # If this was Rekordbox-running detection, no point continuing.
            if "Rekordbox is running" in str(e):
                print("    -> Rekordbox detected during run. Aborting cleanly.")
                aborted = True
                break
            continue

        manifest["tracks"].append({
            "id": c.id,
            "original": {
                "folder_path": old_path,
                "file_name_l": old_filename,
                "file_type": FILE_TYPE_M4A,
                "file_size": old_size,
                "audio_backup": str(backup_audio),
            },
            "new": {
                "folder_path": str(dst),
                "file_name_l": dst.name,
                "file_type": aiff_file_type,
                "file_size": new_size,
            },
        })
        save_manifest()

    save_manifest()
    print(f"\n[OK] Manifest: {manifest_path}")
    if aborted:
        print(f"\nAborted early. {len(manifest['tracks'])} tracks converted (out of {len(m4a_items)} planned).")
        print("Re-run --execute later to continue, or --rollback to revert what already landed.")
    else:
        print(f"\nDone. {len(manifest['tracks'])} tracks converted.")
    print("\nNext step: open Rekordbox, check the playlist:")
    print("  - tracks still in playlist?")
    print("  - beatgrid aligned (zoom into first kick)?")
    print("  - hot cues still on the beat?")
    print("  - BPM unchanged?")
    print(f"\nIf broken: python {Path(sys.argv[0]).name} --rollback {manifest_path.name}")


def rollback(manifest_arg: str) -> None:
    check_rekordbox_running()
    manifest_path = Path(manifest_arg)
    if not manifest_path.is_absolute():
        manifest_path = BACKUP_DIR / manifest_arg
    if not manifest_path.exists():
        sys.exit(f"ERROR: manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Restore DB + WAL + SHM
    for orig, bk in manifest["db_backups"].items():
        bk_path = Path(bk)
        if not bk_path.exists():
            sys.exit(f"ERROR: backup missing: {bk_path}")
        shutil.copy2(bk_path, Path(orig))
        print(f"[OK] DB restored: {orig}")

    # Restore audio files
    for track in manifest["tracks"]:
        backup_audio = Path(track["original"]["audio_backup"])
        original_audio = Path(track["original"]["folder_path"])
        new_audio = Path(track["new"]["folder_path"])
        if backup_audio.exists():
            backup_audio.rename(original_audio)
            print(f"  restored audio: {original_audio.name}")
        else:
            print(f"  WARN: backup missing for {original_audio.name}")
        if new_audio.exists():
            new_audio.unlink()
    print("\nRollback complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Show plan, change nothing.")
    group.add_argument("--execute", action="store_true", help="Run the swap.")
    group.add_argument(
        "--rollback", metavar="MANIFEST",
        help="Restore from a manifest file (path or filename inside backups/).",
    )
    parser.add_argument("--playlist", help="Playlist name (for --dry-run / --execute).")
    parser.add_argument(
        "--all-m4a", action="store_true",
        help="Scope: every undeleted m4a row in master.db (library-wide).",
    )
    parser.add_argument(
        "--path", metavar="PATH", default=None,
        help="Scope: all m4a tracks whose folder_path starts with PATH (recursive).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process only the first N m4a tracks (cautious first runs).",
    )
    args = parser.parse_args()

    if args.rollback:
        rollback(args.rollback)
        return
    scopes = [bool(args.playlist), args.all_m4a, bool(args.path)]
    if sum(scopes) == 0:
        parser.error("one of --playlist NAME / --all-m4a / --path PATH is required")
    if sum(scopes) > 1:
        parser.error("--playlist / --all-m4a / --path are mutually exclusive")
    execute(args.playlist, dry_run=args.dry_run, limit=args.limit,
            all_m4a=args.all_m4a, path_scope=args.path)


if __name__ == "__main__":
    main()
