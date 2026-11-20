"""Rekordbox format copies: mirror a playlist folder as AIFF / MP3 / FLAC copies.

The copies need no re-analysis in Rekordbox and keep beatgrid, cues, key, rating, MyTags,
artwork and playlist order. Originals are never modified; re-running adds only what is new.

RUNBOOK  (system Python 3.13 has pyrekordbox 0.4.4; the .venv one cannot open master.db)
    python -I -X utf8 scripts/dev/rb_format_copies.py plan   --folder "16.10" --targets aiff,mp3,flac
    python -I -X utf8 scripts/dev/rb_format_copies.py build  --folder "16.10" --targets ...
    python -I -X utf8 scripts/dev/rb_format_copies.py verify --folder "16.10" --targets ...
    (close Rekordbox - apply refuses otherwise; --dry works with Rekordbox open)
    python -I -X utf8 scripts/dev/rb_format_copies.py apply  --folder "16.10" --targets ... [--dry]
    python -I -X utf8 scripts/dev/rb_format_copies.py check  --folder "16.10" --targets ...
    python -I -X utf8 scripts/dev/rb_format_copies.py rollback <backup-dir> [--delete-audio]

    --mp3-mode max     every MP3 at 320 CBR (default)
    --mp3-mode source  lossy sources keep their bitrate (AAC 256 -> MP3 256), lossless -> 320

Copies land in  <music-root>/<folder> <AIFF|MP3|FLAC>/  and in Rekordbox as a sibling
folder "<folder> <SUFFIX>" with playlists "<playlist> <SUFFIX>" in the original order.
State: %APPDATA%/MusicLibraryManager/rb-copies/<folder>/ (plan, probe, manifest, verify, stage).
Backups: %APPDATA%/MusicLibraryManager/copies-<folder>-backups/<ts>/ (master.db trio +
masterPlaylists6.xml + fingerprints + apply report). `check` runs automatically after apply
and must run BEFORE Rekordbox is opened again (its auto-analysis rewrites colour waveforms).

WHAT IS DONE AND WHY (all measured on this library 2026-10-16..22, see memory
reference_beatgrid_transfer_pyrekordbox.md):
  * Timeline: Rekordbox decodes AIFF/WAV/FLAC/AAC like ffmpeg. MP3 with a LAME Info frame
    plays 1152 samples late, ffmpeg-written Info frames keep the full encoder delay, no Info
    frame = ffmpeg. New MP3s are written WITHOUT Info frame; the encoder delay (1105 samples)
    is measured per file by cross-correlation and grid, cues and waveforms are shifted by it.
  * Lossless -> lossless is PCM bit-identical (verified); same extension = byte copy.
  * ANLZ: DAT/EXT/2EX copied from the original with PPTH renamed, PVBR zeroed for PCM/FLAC
    (frames*1152 for MP3), FLAC gets a PVB2 seek table, .3EX embedding gets the copy's own
    content ID + audio md5. Rows get Pioneer FileType codes (AIFF 12, MP3 1, FLAC 5),
    rb_file_id = NTFS file id, ModifiedByRBM/Reserved1 = ''. Without these Rekordbox
    re-analysed everything (first run 2026-10-16).
  * Files already present in the target dir but missing from the DB (e.g. after the user
    merged duplicates) are reused and re-registered, never re-encoded.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import rb_anlz_tags as at  # noqa: E402

APPDATA = Path(os.environ["APPDATA"])
RB_DIR = APPDATA / "Pioneer/rekordbox"
SHARE = RB_DIR / "share"
STATE_ROOT = APPDATA / "MusicLibraryManager/rb-copies"
BACKUP_ROOT = APPDATA / "MusicLibraryManager"
TARGETS = {"aiff": ("AIFF", ".aiff", 12), "mp3": ("MP3", ".mp3", 1), "flac": ("FLAC", ".flac", 5)}
MP3_STD = [128, 160, 192, 224, 256, 320]
LOSSLESS_CODECS = ("pcm_", "flac", "alac")
COPY_FIELDS = [
    "Title", "ArtistID", "AlbumID", "GenreID", "BPM", "Length", "TrackNo", "Commnt", "Rating",
    "ReleaseYear", "RemixerID", "LabelID", "OrgArtistID", "KeyID", "ColorID", "ComposerID",
    "Subtitle", "DiscNo", "ReleaseDate", "Lyricist", "ISRC", "DisableQuantize", "Analysed",
    "AnalysisUpdated", "TrackInfoUpdated", "CueUpdated", "HotCueAutoLoad", "DeliveryControl",
    "DeliveryComment", "Tag", "SamplerTrackInfo", "SamplerPlayOffset", "SamplerGain",
    "VideoAssociate", "LyricStatus", "ServiceID", "ExtInfo", "SearchStr", "FileNameS",
    "OrgFolderPath",
]
CUE_COPY = ["InMpegFrame", "InMpegAbs", "OutMpegFrame", "OutMpegAbs", "Kind", "Color",
            "ColorTableIndex", "ActiveLoop", "Comment", "BeatLoopSize", "CueMicrosec",
            "InPointSeekInfo", "OutPointSeekInfo"]
VOLATILE = {"updated_at", "rb_local_usn", "usn"}
STREAM_TYPES = (19, 25)

_lock = threading.Lock()


def log(*a: object) -> None:
    print(*a, flush=True)


# ── environment ──────────────────────────────────────────────────────────────────────


def resolve_ffmpeg() -> tuple[str, str]:
    if os.environ.get("RB_FFMPEG"):
        ff = os.environ["RB_FFMPEG"]
        return ff, os.environ.get("RB_FFPROBE", str(Path(ff).with_name("ffprobe.exe")))
    try:
        sys.path.insert(0, str(REPO))
        from app import ffmpeg_resolver

        r = ffmpeg_resolver.resolve_for_encoder("libmp3lame")
        if r.available and r.binary:
            return r.binary, ffmpeg_resolver.resolve_ffprobe()
    except Exception as e:
        log("ffmpeg resolver unavailable:", e)
    return "ffmpeg", "ffprobe"


def open_db():
    from pyrekordbox import Rekordbox6Database

    return Rekordbox6Database()


def rekordbox_running() -> bool:
    from pyrekordbox.utils import get_rekordbox_pid

    return bool(get_rekordbox_pid())


def norm(p: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


class Ctx:
    def __init__(self, a: argparse.Namespace):
        self.folder_name: str = a.folder
        self.folder_id: str | None = getattr(a, "folder_id", None)
        self.targets: list[str] = [t.strip() for t in a.targets.split(",") if t.strip()]
        for t in self.targets:
            if t not in TARGETS:
                sys.exit(f"unknown target {t!r}; choose from {list(TARGETS)}")
        self.music_root = Path(a.music_root)
        self.mp3_mode: str = getattr(a, "mp3_mode", "max")
        self.workers: int = getattr(a, "workers", 4)
        self.work = STATE_ROOT / re.sub(r"[^\w.-]+", "_", self.folder_name)
        self.work.mkdir(parents=True, exist_ok=True)
        self.ffmpeg, self.ffprobe = resolve_ffmpeg()

    def dest_dir(self, t: str) -> Path:
        return self.music_root / f"{self.folder_name} {TARGETS[t][0]}"

    def stage_dir(self, t: str, cid: str) -> Path:
        return self.work / "stage" / t / cid

    def load(self, name: str, default=None):
        p = self.work / name
        return json.load(open(p, encoding="utf-8")) if p.exists() else default

    def save(self, name: str, obj) -> None:
        tmp = self.work / (name + ".tmp")
        json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        tmp.replace(self.work / name)


# ── probing ──────────────────────────────────────────────────────────────────────────


def probe_file(ffprobe: str, path: str) -> dict | None:
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-count_packets", "-show_entries",
             "stream=codec_name,codec_type,sample_rate,channels,bits_per_raw_sample,"
             "bits_per_sample,sample_fmt,bit_rate,nb_read_packets:stream_disposition=attached_pic"
             ":format=bit_rate,duration,format_name", "-of", "json", path],
            capture_output=True, text=True, errors="replace", timeout=120,
        )
        j = json.loads(r.stdout or "{}")
        return j if any(s.get("codec_type") == "audio" for s in j.get("streams", [])) else None
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return None


def astream(pr: dict) -> dict:
    return [s for s in pr["streams"] if s["codec_type"] == "audio"][0]


def has_cover(pr: dict) -> bool:
    return any(s["codec_type"] == "video" for s in pr["streams"])


def is_lossless(a: dict) -> bool:
    return a["codec_name"].startswith(LOSSLESS_CODECS)


def source_bits(a: dict) -> int:
    if not is_lossless(a):
        return 16
    if a.get("sample_fmt", "").startswith("flt") or a.get("sample_fmt", "").startswith("dbl"):
        return 24
    bits = int(a.get("bits_per_raw_sample") or a.get("bits_per_sample") or 16)
    return 24 if bits > 16 else 16


def source_view(d: dict) -> tuple[list[str], int, dict | None]:
    """ffmpeg input args + samples to prepend so that ffmpeg reproduces Rekordbox's timeline."""
    if astream(d["probe"])["codec_name"] != "mp3":
        return [], 0, None
    return at.rekordbox_mp3_view(d["path"])


# ── plan ─────────────────────────────────────────────────────────────────────────────


def find_folder(db, ctx: Ctx):
    if ctx.folder_id:
        f = db.get_playlist(ID=str(ctx.folder_id))
        if f is None or f.Attribute != 1:
            sys.exit(f"folder id {ctx.folder_id} not found / not a folder")
        return f
    hits = [p for p in db.get_playlist(Name=ctx.folder_name).all() if p.Attribute == 1]
    if len(hits) != 1:
        sys.exit(f"folder {ctx.folder_name!r}: {len(hits)} matches - pass --folder-id")
    return hits[0]


_SUFFIX_RE = re.compile(r"^(.*) \(\d+\)$")


def base_stem(name: str) -> str:
    m = _SUFFIX_RE.match(Path(name).stem)
    return (m.group(1) if m else Path(name).stem).casefold()


def reconcile_copy_map(db, ctx: Ctx, t: str, originals: dict, state: dict) -> tuple[dict, list]:
    """orig_cid -> copy_cid for target t, from state.json + rows found under the dest dir."""
    dest = norm(ctx.dest_dir(t))
    by_stem: dict[str, list] = defaultdict(list)
    for cid, c in originals.items():
        if c.FolderPath:
            by_stem[Path(c.FolderPath).stem.casefold()].append(cid)
    cmap: dict[str, str] = {}
    for ocid, ccid in state.get("copies", {}).get(t, {}).items():
        if ocid in originals and db.get_content(ID=str(ccid)) is not None:
            cmap[ocid] = str(ccid)
    unmatched = []
    for c in db.get_content().all():
        if not c.FolderPath or c.rb_local_deleted or norm(Path(c.FolderPath).parent) != dest:
            continue
        if str(c.ID) in cmap.values():
            continue
        cands = by_stem.get(base_stem(c.FolderPath), [])
        if len(cands) > 1:
            cands = [k for k in cands if originals[k].Title == c.Title and originals[k].BPM == c.BPM]
        if len(cands) == 1 and cands[0] not in cmap:
            cmap[cands[0]] = str(c.ID)
        else:
            unmatched.append(str(c.FolderPath))
    return cmap, unmatched


def cmd_plan(ctx: Ctx) -> None:
    db = open_db()
    folder = find_folder(db, ctx)
    children = sorted(db.get_playlist(ParentID=folder.ID).all(), key=lambda p: p.Seq)
    playlists = [p for p in children if p.Attribute == 0]
    for p in children:
        if p.Attribute != 0:
            log(f"  skip non-playlist child {p.Name!r} (attribute {p.Attribute})")
    originals: dict = {}
    pl_entries = []
    for p in playlists:
        songs = sorted(db.get_playlist_songs(PlaylistID=p.ID).all(), key=lambda s: s.TrackNo)
        cids = [str(s.ContentID) for s in songs]
        pl_entries.append({"pl_id": str(p.ID), "name": p.Name, "seq": p.Seq, "cids": cids})
        for s in songs:
            originals.setdefault(str(s.ContentID), s.Content)
    state = ctx.load("state.json", {"copies": {}})
    probe = ctx.load("probe.json", {})
    plan = {"folder": {"id": str(folder.ID), "name": folder.Name, "seq": folder.Seq,
                       "parent": str(folder.ParentID)},
            "playlists": pl_entries, "targets": {}, "skipped": [], "mp3_mode": ctx.mp3_mode}
    skipped = {}
    for cid, c in originals.items():
        if c.FileType in STREAM_TYPES or not c.FolderPath or not Path(c.FolderPath).exists():
            skipped[cid] = {"title": c.Title, "path": c.FolderPath,
                            "reason": "stream" if c.FileType in STREAM_TYPES else "file missing"}
    plan["skipped"] = list(skipped.values())
    need_probe = set()
    for t in ctx.targets:
        suffix = TARGETS[t][0]
        cmap, unmatched = reconcile_copy_map(db, ctx, t, originals, state)
        cf = [p for p in db.get_playlist(ParentID=folder.ParentID).all()
              if p.Attribute == 1 and p.Name == f"{folder.Name} {suffix}"]
        copy_pls = {}
        if cf:
            for k in db.get_playlist(ParentID=cf[0].ID).all():
                copy_pls[k.Name] = [str(s.ContentID) for s in sorted(
                    db.get_playlist_songs(PlaylistID=k.ID).all(), key=lambda s: s.TrackNo)]
        to_convert = [cid for cid in originals if cid not in cmap and cid not in skipped]
        need_probe |= set(to_convert)
        pls = []
        for pe in pl_entries:
            name = f"{pe['name']} {suffix}"
            have = copy_pls.get(name)
            if have is None:
                pls.append({"name": name, "new": True, "add": len([c for c in pe["cids"] if c not in skipped])})
                continue
            back = {v: k for k, v in cmap.items()}
            have_orig = [back.get(x, "?") for x in have]
            missing = [c for c in pe["cids"] if c not in skipped and cmap.get(c) not in have]
            common_ok = [c for c in pe["cids"] if c in have_orig] == [c for c in have_orig if c in pe["cids"]]
            pls.append({"name": name, "new": False, "add": len(missing), "order_ok": common_ok,
                        "foreign": have_orig.count("?")})
        orphans = []
        dd = ctx.dest_dir(t)
        if dd.exists():
            registered = {norm(c.FolderPath) for c in db.get_content().all() if c.FolderPath}
            orphans = [f.name for f in dd.iterdir()
                       if f.suffix.lower() == TARGETS[t][1] and norm(f) not in registered]
        plan["targets"][t] = {"copy_folder_id": str(cf[0].ID) if cf else None, "dest_dir": str(dd),
                              "copy_map": cmap, "unmatched_rows": unmatched, "to_convert": to_convert,
                              "playlists": pls, "orphan_files": orphans}
        log(f"[{t}] copies known {len(cmap)}, to convert {len(to_convert)}, "
            f"orphan files in dest {len(orphans)}, unmatched copy rows {len(unmatched)}")
        for p in pls:
            log(f"    {p['name']!r}: {'NEW, ' if p['new'] else ''}add {p['add']}"
                + ("" if p["new"] else f", order_ok={p['order_ok']}, foreign={p['foreign']}"))
    for cid in sorted(need_probe):
        if cid in probe and probe[cid].get("path") == originals[cid].FolderPath:
            continue
        c = originals[cid]
        probe[cid] = {"cid": cid, "title": c.Title, "path": c.FolderPath, "ft": c.FileType,
                      "rb_sr": c.SampleRate, "anlz": c.AnalysisDataPath,
                      "probe": probe_file(ctx.ffprobe, c.FolderPath)}
        if probe[cid]["probe"] is None:
            log(f"  WARN unreadable source {c.FolderPath}")
    ctx.save("probe.json", probe)
    ctx.save("plan.json", plan)
    log(f"playlists {len(pl_entries)}, unique tracks {len(originals)}, skipped {len(skipped)} "
        f"({Counter(s['reason'] for s in skipped.values())})")
    log("plan written to", ctx.work / "plan.json")


# ── build (convert + stage ANLZ) ─────────────────────────────────────────────────────


def run(cmd: list[str], timeout: int = 900) -> bytes:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"rc={r.returncode} {r.stderr.decode('utf-8', 'replace')[-400:]}")
    return r.stdout


def decode(ctx: Ctx, path: str, sr: int, in_args=(), pad: int = 0, fmt: str = "f32le", seconds=None):
    import numpy as np

    cmd = [ctx.ffmpeg, "-v", "error", "-nostdin", *in_args, "-i", path, "-map", "0:a:0"]
    if pad:
        cmd += ["-af", f"adelay={pad}S:all=1"]
    if seconds:
        cmd += ["-t", str(seconds)]
    codec = {"f32le": "pcm_f32le", "s32le": "pcm_s32le"}[fmt]
    cmd += ["-ac", "2", "-ar", str(sr), "-f", fmt, "-c:a", codec, "-"]
    raw = run(cmd)
    return np.frombuffer(raw, dtype=np.float32 if fmt == "f32le" else np.int32).reshape(-1, 2)


def lag_of(new, ref, max_lag: int = 6000) -> tuple[int, float]:
    """Samples by which `new` is delayed vs `ref` (positive = later) + normalised correlation."""
    import numpy as np
    from scipy.signal import correlate

    n = min(len(new), len(ref), 44100 * 90)
    x = new[:n].mean(axis=1).astype(np.float64)
    y = ref[:n].mean(axis=1).astype(np.float64)
    c = correlate(x, y, mode="full", method="fft")
    mid = n - 1
    win = c[mid - max_lag : mid + max_lag + 1]
    k = int(np.argmax(win)) - max_lag
    a, b = (x[k:], y[: n - k]) if k >= 0 else (x[: n + k], y[-k:])
    r = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    return k, r


def mp3_bitrate(a: dict, mode: str) -> int:
    if mode == "max" or is_lossless(a):
        return 320
    kb = int(a.get("bit_rate") or 0) / 1000
    return min(MP3_STD, key=lambda s: abs(s - kb)) if kb else 320


def build_cmd(ctx: Ctx, d: dict, dst: Path, t: str, in_args, pad: int, cover: bool) -> tuple[list[str], dict]:
    a = astream(d["probe"])
    sr = int(a["sample_rate"])
    bits = source_bits(a)
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", *in_args, "-i", d["path"], "-map", "0:a:0"]
    if cover:
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
        if t == "mp3":
            cmd += ["-disposition:v:0", "attached_pic"]
    cmd += ["-map_metadata", "0"]
    if pad:
        cmd += ["-af", f"adelay={pad}S:all=1"]
    cmd += ["-ar", str(sr)]
    info = {"sr": sr, "bits": bits, "lossless_src": is_lossless(a)}
    if t == "aiff":
        cmd += ["-c:a", f"pcm_s{bits}be", "-write_id3v2", "1"]
    elif t == "flac":
        cmd += ["-c:a", "flac", "-sample_fmt", "s16" if bits == 16 else "s32"]
    else:
        br = mp3_bitrate(a, ctx.mp3_mode)
        info["mp3_kbps"] = br
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{br}k", "-write_xing", "0", "-id3v2_version", "3"]
    cmd += ["-y", str(dst)]
    return cmd, info


def stage_anlz(ctx: Ctx, src_dat: Path, out_dir: Path, filename: str, t: str, audio: Path,
               shift_ms: int = 0, shift_k: int = 0, pvbr_last: int = 0) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for ext in (".DAT", ".EXT", ".2EX"):
        head, tags = at.read_tags(src_dat.with_suffix(ext))
        new = []
        for name, th, raw in tags:
            if name == "PPTH":
                raw = at.ppth_tag(filename)
            elif name == "PVBR":
                raw = at.pvbr_tag(raw, pvbr_last if t == "mp3" else 0)
            elif name == "PVB2":
                continue
            elif t == "mp3" and (shift_ms or shift_k):
                if name == "PQTZ":
                    raw = at.shift_pqtz(raw, shift_ms)
                elif name == "PQT2":
                    raw = at.shift_pqt2(raw, shift_ms)
                elif name in ("PWV3", "PWV5", "PWV7"):
                    raw = at.shift_wave(raw, shift_k)
            new.append((name, th, raw))
            if ext == ".EXT" and name == "PWV4" and t == "flac":
                new.append(("PVB2", 32, at.build_pvb2(audio, ctx.ffprobe)))
        if ext == ".EXT" and t == "flac" and not any(n == "PVB2" for n, _, _ in new):
            raise RuntimeError("PVB2 not inserted (no PWV4 in EXT?)")
        at.write_tags(out_dir / ("ANLZ0000" + ext), head, new)
    x3 = src_dat.with_suffix(".3EX")
    if x3.exists():
        shutil.copy2(x3, out_dir / "ANLZ0000.3EX")


def choose_name(ctx: Ctx, t: str, src_path: str, registered: set[str], taken: set[str]) -> tuple[Path, bool]:
    """Returns (dest path, reuse_existing_file)."""
    dd = ctx.dest_dir(t)
    stem, ext = Path(src_path).stem, TARGETS[t][1]
    cand = dd / (stem + ext)
    i = 2
    while True:
        key = norm(cand)
        if key not in registered and key not in taken:
            return cand, cand.exists()
        cand = dd / f"{stem} ({i}){ext}"
        i += 1


def build_one(ctx: Ctx, cid: str, d: dict, targets: list[str], registered: set[str], taken: set[str],
              manifest: dict) -> None:
    a = astream(d["probe"])
    sr = int(a["sample_rate"])
    src_ext = Path(d["path"]).suffix.lower()
    in_args, pad, hdr = source_view(d)
    src_dat = SHARE / d["anlz"].lstrip("/\\")
    ref = None
    entry = manifest.get(cid, {})
    entry.update({"title": d["title"], "src": d["path"], "src_codec": a["codec_name"],
                  "src_view": {"in_args": in_args, "pad": pad, "mp3hdr": hdr}})
    for t in targets:
        if entry.get(t, {}).get("ok"):
            continue
        with _lock:
            dst, reuse = choose_name(ctx, t, d["path"], registered, taken)
            taken.add(norm(dst))
        res: dict = {"path": str(dst)}
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if reuse:
                res["mode"] = "reuse"
            elif src_ext == TARGETS[t][1] or (src_ext == ".aif" and t == "aiff"):
                shutil.copy2(d["path"], dst)
                if at.md5_file(dst) != at.md5_file(d["path"]):
                    raise RuntimeError("byte copy mismatch")
                res["mode"] = "copy"
            else:
                cover = has_cover(d["probe"])
                cmd, info = build_cmd(ctx, d, dst, t, in_args, pad, cover)
                try:
                    run(cmd)
                except RuntimeError:
                    if not cover:
                        raise
                    cmd, info = build_cmd(ctx, d, dst, t, in_args, pad, False)
                    run(cmd)
                    info["cover_dropped"] = True
                res.update(info)
                res["mode"] = "convert"
            out_pr = probe_file(ctx.ffprobe, str(dst))
            if out_pr is None:
                raise RuntimeError("output not probeable")
            oa = astream(out_pr)
            # alignment of the new file's Rekordbox timeline vs the original's
            if res["mode"] == "copy":
                lag, corr = 0, 1.0
            else:
                if ref is None:
                    ref = decode(ctx, d["path"], sr, in_args, pad)
                n_args, n_pad = ([], 0)
                if oa["codec_name"] == "mp3":
                    n_args, n_pad, _ = at.rekordbox_mp3_view(dst)
                lag, corr = lag_of(decode(ctx, str(dst), sr, n_args, n_pad), ref)
            res.update(lag=lag, corr=round(corr, 5))
            if t == "mp3" and res["mode"] != "copy":
                if not (500 < lag < 3000 and corr > 0.98):
                    raise RuntimeError(f"unexpected mp3 alignment lag={lag} corr={corr:.3f}")
                shift_ms = round(lag * 1000 / sr)
                shift_k = round(lag * 150 / sr)
                frames = int(oa["nb_read_packets"])
                res.update(shift_samples=lag, shift_ms=shift_ms, shift_wave_entries=shift_k, mp3_frames=frames)
                stage_anlz(ctx, src_dat, ctx.stage_dir(t, cid), dst.name, t, dst, shift_ms, shift_k, frames * 1152)
            else:
                if not (lag == 0 and corr > 0.999):
                    raise RuntimeError(f"unexpected alignment lag={lag} corr={corr:.4f}")
                if res["mode"] == "convert" and res.get("lossless_src"):
                    import numpy as np

                    x = decode(ctx, d["path"], sr, in_args, pad, fmt="s32le")
                    y = decode(ctx, str(dst), sr, fmt="s32le")
                    if x.shape != y.shape or not np.array_equal(x, y):
                        raise RuntimeError("lossless output not bit-identical to source")
                    res["verify"] = "PCM bit-identical"
                res.update(shift_samples=0, shift_ms=0)
                stage_anlz(ctx, src_dat, ctx.stage_dir(t, cid), dst.name, t, dst)
            res["out"] = {k: oa.get(k) for k in ("codec_name", "sample_rate", "bits_per_raw_sample",
                                                 "bits_per_sample", "bit_rate")}
            res["out"]["duration"] = float(out_pr["format"]["duration"])
            res["out"]["cover"] = has_cover(out_pr)
            res["size"] = dst.stat().st_size
            res["ok"] = True
        except Exception as e:
            res["ok"] = False
            res["error"] = repr(e)[:500]
        entry[t] = res
        log(f"{cid:>10} {t:4} {res.get('mode', '?'):7} ok={res['ok']} lag={res.get('lag')} "
            f"shift_ms={res.get('shift_ms')} {res.get('error', '')[:100]} | {dst.name[:60]}")
    with _lock:
        manifest[cid] = entry
        ctx.save("manifest.json", manifest)


def cmd_build(ctx: Ctx) -> None:
    plan = ctx.load("plan.json")
    probe = ctx.load("probe.json", {})
    if not plan:
        sys.exit("run plan first")
    manifest = ctx.load("manifest.json", {})
    db = open_db()
    registered = {norm(c.FolderPath) for c in db.get_content().all() if c.FolderPath}
    jobs: dict[str, list[str]] = defaultdict(list)
    for t in ctx.targets:
        for cid in plan["targets"][t]["to_convert"]:
            if probe.get(cid, {}).get("probe"):
                jobs[cid].append(t)
    taken: set[str] = set()
    log(f"building {len(jobs)} tracks x {ctx.targets} with {ctx.workers} workers "
        f"(mp3 mode {ctx.mp3_mode})")
    with ThreadPoolExecutor(ctx.workers) as ex:
        list(ex.map(lambda cid: build_one(ctx, cid, probe[cid], jobs[cid], registered, taken, manifest), jobs))
    ok = sum(1 for cid in jobs for t in jobs[cid] if manifest.get(cid, {}).get(t, {}).get("ok"))
    bad = [(cid, t, manifest[cid][t].get("error")) for cid in jobs for t in jobs[cid]
           if not manifest.get(cid, {}).get(t, {}).get("ok")]
    log(f"build done: {ok} ok, {len(bad)} failed")
    for b in bad[:20]:
        log("  FAIL", b)


# ── verify (audio vs original waveform) ──────────────────────────────────────────────


def _env(a, s: int, w: int, n: int):
    import numpy as np

    seg = a[s : s + n * w] if s >= 0 else np.concatenate([np.zeros(-s, np.float32), a[: n * w + s]])
    if len(seg) < n * w:
        seg = np.concatenate([seg, np.zeros(n * w - len(seg), np.float32)])
    return seg.reshape(n, w).max(axis=1)


def best_shift(a, h, w: int) -> tuple[int, float]:
    """Sample offset of audio `a` against Rekordbox's stored PWV3 heights `h` (150/s)."""
    import numpy as np

    n = len(h)
    hz = (h - h.mean()) / (h.std() + 1e-9)

    def score(s: int) -> float:
        e = _env(a, s, w, n)
        e = (e - e.mean()) / (e.std() + 1e-9)
        return float((e * hz).mean())

    coarse = list(range(-4000, 4001, 16))
    s0 = coarse[int(np.argmax([score(s) for s in coarse]))]
    fine = list(range(s0 - 24, s0 + 25))
    sc = [score(s) for s in fine]
    return fine[int(np.argmax(sc))], max(sc)


def cmd_verify(ctx: Ctx) -> None:
    import numpy as np

    manifest = ctx.load("manifest.json", {})
    probe = ctx.load("probe.json", {})
    out = ctx.load("verify.json", {})
    items = [(cid, t) for cid in manifest for t in ctx.targets
             if manifest[cid].get(t, {}).get("ok") and not out.get(cid, {}).get(t, {}).get("ok")]
    log(f"verifying {len(items)} files")

    def one(item):
        cid, t = item
        d = probe[cid]
        m = manifest[cid][t]
        sr = int(d["rb_sr"] or astream(d["probe"])["sample_rate"])
        orig = SHARE / d["anlz"].lstrip("/\\")
        src_grid = at.pqtz_entries([r for n, _, r in at.read_tags(orig.with_suffix(".DAT"))[1] if n == "PQTZ"][0])
        stg = at.pqtz_entries([r for n, _, r in at.read_tags(ctx.stage_dir(t, cid) / "ANLZ0000.DAT")[1]
                               if n == "PQTZ"][0])
        shift = int(m.get("shift_ms") or 0)
        diffs = sorted({n[2] - s[2] for n, s in zip(stg, src_grid)})
        res = {"grid_shift_ms": shift, "grid_diffs": diffs, "beats": (len(stg), len(src_grid))}
        if m["mode"] == "copy":
            res.update(ok=diffs == [0] and len(stg) == len(src_grid), detail="byte copy")
        else:
            h = at.pwv3_heights([r for n, _, r in at.read_tags(orig.with_suffix(".EXT"))[1] if n == "PWV3"][0])
            n_args, n_pad = [], 0
            if m["out"]["codec_name"] == "mp3":
                n_args, n_pad, _ = at.rekordbox_mp3_view(m["path"])
            # first 90 s are enough to pin the start offset; full-track alignment is ~20x slower
            audio = np.abs(decode(ctx, m["path"], sr, n_args, n_pad, seconds=95)).mean(axis=1)
            s0, corr = best_shift(audio, h[: 90 * 150].astype(np.float64), sr // 150)
            audio_ms = s0 * 1000 / sr  # +s0 = new audio starts s0 samples later than the original
            res.update(audio_offset_ms=round(audio_ms, 2), corr=round(corr, 3),
                       ok=abs(audio_ms - shift) <= 1.0 and diffs == [shift] and len(stg) == len(src_grid),
                       detail=f"audio {audio_ms:+.2f} ms vs grid {shift} ms")
        log(f"{cid:>10} {t:4} {'OK  ' if res['ok'] else 'FAIL'} {res['detail']} beats={res['beats']}")
        return cid, t, res

    with ThreadPoolExecutor(ctx.workers) as ex:
        for cid, t, res in ex.map(one, items):
            out.setdefault(cid, {})[t] = res
    ctx.save("verify.json", out)
    bad = [(c, t) for c in out for t in out[c] if not out[c][t]["ok"]]
    log(f"verify: {sum(len(v) for v in out.values()) - len(bad)} ok, {len(bad)} FAIL {bad[:10]}")


# ── fingerprints (originals + existing copies must not change) ───────────────────────


def fingerprint_contents(db, cids: list[str], audio_md5: bool) -> dict:
    from sqlalchemy import text

    q = lambda s, **p: [dict(r) for r in db.session.execute(text(s), p).mappings().all()]  # noqa: E731
    snap = {}
    for cid in cids:
        rows = q("SELECT * FROM djmdContent WHERE ID=:c", c=cid)
        if not rows:
            snap[cid] = None
            continue
        row = rows[0]
        e = {"row": {k: str(v) for k, v in row.items() if k not in VOLATILE}}
        for tbl in ("djmdCue", "contentCue", "contentFile", "djmdSongMyTag", "djmdMixerParam"):
            e[tbl] = sorted(json.dumps({k: str(v) for k, v in r.items() if k not in VOLATILE}, sort_keys=True)
                            for r in q(f"SELECT * FROM {tbl} WHERE ContentID=:c", c=cid))
        if row.get("AnalysisDataPath"):
            d = (SHARE / row["AnalysisDataPath"].lstrip("/\\")).parent
            e["anlz_md5"] = {x.name: at.md5_file(x) for x in sorted(d.iterdir())} if d.exists() else {}
        if audio_md5 and row.get("FolderPath") and Path(row["FolderPath"]).exists():
            e["audio_md5"] = at.md5_file(row["FolderPath"])
        snap[cid] = e
    return snap


def fingerprint_playlists(db, pl_ids: list[str]) -> dict:
    return {pid: [(str(s.ContentID), s.TrackNo) for s in sorted(
        db.get_playlist_songs(PlaylistID=pid).all(), key=lambda s: s.TrackNo)] for pid in pl_ids}


# ── apply (DB write) ─────────────────────────────────────────────────────────────────


def split_dir(u: str) -> str:
    return f"{u[:3]}/{u[3:]}"


def iso_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat(timespec="milliseconds")


def make_copy(db, ctx: Ctx, cid: str, t: str, m: dict, share_w: Path, created_dirs: list, now):
    from pyrekordbox.db6 import tables

    src = db.get_content(ID=cid)
    out = m["out"]
    c = db.add_content(m["path"])
    for f in COPY_FIELDS:
        setattr(c, f, getattr(src, f))
    c.FileType = TARGETS[t][2]
    sr = int(out["sample_rate"])
    if t == "mp3":
        c.BitRate, c.BitDepth = int(out["bit_rate"]) // 1000, 16
    elif t == "flac":
        c.BitRate, c.BitDepth = 0, int(out.get("bits_per_raw_sample") or out.get("bits_per_sample"))
    else:
        c.BitDepth = int(out.get("bits_per_raw_sample") or out.get("bits_per_sample"))
        c.BitRate = sr * c.BitDepth * 2 // 1000
    c.SampleRate = sr
    c.DJPlayCount = 0
    c.ModifiedByRBM = ""
    c.Reserved1 = ""
    c.rb_file_id = str(os.stat(m["path"]).st_ino)
    u = c.UUID
    anlz_dir = share_w / "PIONEER/USBANLZ" / split_dir(u)
    if anlz_dir.exists():
        raise RuntimeError(f"ANLZ dir exists {anlz_dir}")
    shutil.copytree(ctx.stage_dir(t, cid), anlz_dir)
    created_dirs.append(anlz_dir)
    if (anlz_dir / "ANLZ0000.3EX").exists():
        at.patch_3ex(anlz_dir / "ANLZ0000.3EX", str(c.ID), at.md5_file(m["path"]))
    c.AnalysisDataPath = f"/PIONEER/USBANLZ/{split_dir(u)}/ANLZ0000.DAT"
    path_map = {}
    if src.ImagePath:
        s_art = SHARE / src.ImagePath.lstrip("/\\")
        d_art = share_w / "PIONEER/Artwork" / split_dir(u)
        if s_art.parent.exists() and not d_art.exists():
            shutil.copytree(s_art.parent, d_art)
            created_dirs.append(d_art)
            c.ImagePath = f"/PIONEER/Artwork/{split_dir(u)}/{s_art.name}"
            path_map[src.ImagePath] = c.ImagePath
        else:
            c.ImagePath = None
    old_anlz = str(Path(src.AnalysisDataPath).parent).replace("\\", "/")
    for ext in ("DAT", "EXT", "2EX", "3EX"):
        path_map[f"{old_anlz}/ANLZ0000.{ext}"] = f"/PIONEER/USBANLZ/{split_dir(u)}/ANLZ0000.{ext}"
    for row in db.session.query(tables.ContentFile).filter_by(ContentID=cid).all():
        np_ = path_map.get(row.Path)
        if np_ is None:
            continue
        lp = share_w / np_.lstrip("/")
        if not lp.exists():
            continue
        db.add(tables.ContentFile.create(
            ID=f"{u}_{urllib.parse.quote(np_, safe='')}", ContentID=c.ID, Path=np_,
            Hash=at.md5_file(lp), Size=lp.stat().st_size, rb_local_path=str(SHARE / np_.lstrip("/")),
            rb_insync_hash=None, rb_insync_local_usn=None, rb_file_hash_dirty=0,
            rb_local_file_status=0, rb_in_progress=0, rb_process_type=0, rb_temp_path=None,
            rb_priority=row.rb_priority, rb_file_size_dirty=0, UUID=str(uuid.uuid4()),
            created_at=now, updated_at=now))
    shift = int(m.get("shift_ms") or 0)
    cc = db.session.query(tables.ContentCue).filter_by(ContentID=cid).one_or_none()
    old_json = {str(x["ID"]): x for x in json.loads(cc.Cues)} if cc is not None and cc.Cues else {}
    new_json = []
    for q in db.get_cue(ContentID=cid).all():
        in_ms = q.InMsec + shift
        out_ms = q.OutMsec + shift if q.OutMsec not in (None, -1) else q.OutMsec
        nq = tables.DjmdCue.create(
            ID=str(db.generate_unused_id(tables.DjmdCue, is_28_bit=False)), ContentID=c.ID,
            ContentUUID=u, UUID=str(uuid.uuid4()), InMsec=in_ms, InFrame=in_ms * 150 // 1000,
            OutMsec=out_ms, OutFrame=(out_ms * 150 // 1000) if out_ms not in (None, -1) else q.OutFrame,
            created_at=now, updated_at=now, **{k: getattr(q, k) for k in CUE_COPY})
        db.add(nq)
        j = dict(old_json.get(str(q.ID), {}))
        if j:
            j.update(ID=nq.ID, ContentID=c.ID, ContentUUID=u, InMsec=nq.InMsec, InFrame=nq.InFrame,
                     OutMsec=nq.OutMsec, OutFrame=nq.OutFrame, UUID=nq.UUID,
                     created_at=iso_utc(now), updated_at=iso_utc(now))
            new_json.append(j)
    if cc is not None:
        db.add(tables.ContentCue.create(
            ID=u, ContentID=c.ID, Cues=json.dumps(new_json, separators=(",", ":")),
            rb_cue_count=len(new_json), UUID=str(uuid.uuid4()), created_at=now, updated_at=now))
    for mp in db.session.query(tables.DjmdMixerParam).filter_by(ContentID=cid).all():
        db.add(tables.DjmdMixerParam.create(
            ID=str(uuid.uuid4()), ContentID=c.ID, GainHigh=mp.GainHigh, GainLow=mp.GainLow,
            PeakHigh=mp.PeakHigh, PeakLow=mp.PeakLow, UUID=str(uuid.uuid4()),
            created_at=now, updated_at=now))
    for st in db.session.query(tables.DjmdSongMyTag).filter_by(ContentID=cid).all():
        db.add(tables.DjmdSongMyTag.create(
            ID=str(uuid.uuid4()), MyTagID=st.MyTagID, ContentID=c.ID, TrackNo=st.TrackNo,
            UUID=str(uuid.uuid4()), created_at=now, updated_at=now))
    return c


def cmd_apply(ctx: Ctx, dry: bool) -> None:
    plan = ctx.load("plan.json")
    manifest = ctx.load("manifest.json", {})
    verify = ctx.load("verify.json", {})
    state = ctx.load("state.json", {"copies": {}, "runs": []})
    if not plan:
        sys.exit("run plan first")
    if rekordbox_running() and not dry:
        sys.exit("ABORT: Rekordbox is running - close it first.")
    new_tracks: dict[str, list[str]] = {}
    for t in ctx.targets:
        ids = []
        for cid in plan["targets"][t]["to_convert"]:
            m = manifest.get(cid, {}).get(t)
            if not m:
                continue
            if not (m.get("ok") and verify.get(cid, {}).get(t, {}).get("ok")):
                sys.exit(f"ABORT: {cid} {t} not built+verified ok - run build/verify")
            if not Path(m["path"]).exists() or not (ctx.stage_dir(t, cid) / "ANLZ0000.DAT").exists():
                sys.exit(f"ABORT: missing file/stage for {cid} {t}")
            ids.append(cid)
        new_tracks[t] = ids
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = BACKUP_ROOT / f"copies-{ctx.work.name}-backups" / ts
    share_w = ctx.work / "dryshare" if dry else SHARE
    if dry and share_w.exists():
        shutil.rmtree(share_w)
    if not dry:
        bdir.mkdir(parents=True)
        for name in ("master.db", "master.db-wal", "master.db-shm", "masterPlaylists6.xml"):
            if (RB_DIR / name).exists():
                shutil.copy2(RB_DIR / name, bdir / name)
                if at.md5_file(RB_DIR / name) != at.md5_file(bdir / name):
                    sys.exit(f"backup copy mismatch {name}")
        log("backup:", bdir)
    db = open_db()
    folder = db.get_playlist(ID=plan["folder"]["id"])
    src_pls = sorted(db.get_playlist(ParentID=folder.ID).all(), key=lambda p: p.Seq)
    src_pls = [p for p in src_pls if p.Attribute == 0]
    orig_cids = list({c for pe in plan["playlists"] for c in pe["cids"]})
    for t in ctx.targets:
        for cid in new_tracks[t]:
            p = str(Path(manifest[cid][t]["path"]))
            if db.get_content(FolderPath=p).count():
                sys.exit(f"ABORT: already in DB: {p}")
    # fingerprints before
    existing = {t: dict(plan["targets"][t]["copy_map"]) for t in ctx.targets}
    copy_pl_ids = {}
    for t in ctx.targets:
        cf = plan["targets"][t]["copy_folder_id"]
        if cf:
            copy_pl_ids[t] = [str(k.ID) for k in db.get_playlist(ParentID=cf).all()]
    before = {
        "originals": fingerprint_contents(db, orig_cids, audio_md5=not dry),
        "copies": fingerprint_contents(db, [v for t in existing for v in existing[t].values()], audio_md5=False),
        "orig_playlists": fingerprint_playlists(db, [pe["pl_id"] for pe in plan["playlists"]]),
        "copy_playlists": fingerprint_playlists(db, [p for t in copy_pl_ids for p in copy_pl_ids[t]]),
    }
    if not dry:
        json.dump(before, open(bdir / "fingerprint_before.json", "w", encoding="utf-8"), default=str)
    created_dirs: list[Path] = []
    report = {"backup": str(bdir), "folder": plan["folder"], "targets": {}, "dry": dry}
    now = datetime.datetime.now()
    try:
        for idx, t in enumerate(ctx.targets):
            suffix = TARGETS[t][0]
            cf_id = plan["targets"][t]["copy_folder_id"]
            created_folder = False
            if cf_id is None:
                cf = db.create_playlist_folder(f"{folder.Name} {suffix}", parent=str(folder.ParentID),
                                               seq=min(folder.Seq + 1 + idx,
                                                       db.get_playlist(ParentID=folder.ParentID).count() + 1))
                cf_id = str(cf.ID)
                created_folder = True
            cmap = dict(existing[t])
            new_ids = {}
            for cid in new_tracks[t]:
                c = make_copy(db, ctx, cid, t, manifest[cid][t], share_w, created_dirs, now)
                cmap[cid] = str(c.ID)
                new_ids[cid] = str(c.ID)
            back = {v: k for k, v in cmap.items()}
            pl_rep = []
            for sp in src_pls:
                songs = [str(s.ContentID) for s in sorted(db.get_playlist_songs(PlaylistID=sp.ID).all(),
                                                          key=lambda s: s.TrackNo)]
                kids = sorted(db.get_playlist(ParentID=cf_id).all(), key=lambda p: p.Seq)
                hit = [k for k in kids if k.Name == f"{sp.Name} {suffix}"]
                if hit:
                    pl = hit[0]
                    have = [back.get(str(s.ContentID)) for s in sorted(
                        db.get_playlist_songs(PlaylistID=pl.ID).all(), key=lambda s: s.TrackNo)]
                    add = [c for c in songs if c not in have]
                    created = False
                else:
                    seq = 1
                    for pp in reversed([p for p in src_pls if p.Seq < sp.Seq]):
                        h = [k for k in kids if k.Name == f"{pp.Name} {suffix}"]
                        if h:
                            seq = h[0].Seq + 1
                            break
                    pl = db.create_playlist(f"{sp.Name} {suffix}", parent=cf_id, seq=seq)
                    add, created = songs, True
                n, skip = 0, []
                for k in add:
                    if k not in cmap:
                        skip.append(db.get_content(ID=k).Title)
                        continue
                    db.add_to_playlist(pl, db.get_content(ID=cmap[k]))
                    n += 1
                if created or n or skip:
                    pl_rep.append({"name": pl.Name, "created": created, "added": n, "skipped": skip})
            report["targets"][t] = {"copy_folder_id": cf_id, "folder_created": created_folder,
                                    "new_content_ids": new_ids, "playlists": pl_rep}
            state["copies"].setdefault(t, {}).update(cmap)
        if dry:
            log(json.dumps(report["targets"], indent=1, ensure_ascii=False)[:4000])
            raise RuntimeError("dry run - rolling back")
        db.commit()
    except BaseException:
        db.rollback()
        for d in created_dirs:
            shutil.rmtree(d, ignore_errors=True)
        if dry:
            log("dry run ok - nothing written")
            return
        raise
    report["created_dirs"] = [str(d) for d in created_dirs]
    json.dump(report, open(bdir / "apply_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    state["runs"].append({"ts": ts, "backup": str(bdir), "new": {t: len(v) for t, v in new_tracks.items()}})
    ctx.save("state.json", state)
    ctx.save("last_report.json", report)
    log("COMMITTED. report:", bdir / "apply_report.json")
    cmd_check(ctx, report, before)


# ── check (after apply, before Rekordbox is reopened) ────────────────────────────────


def cmd_check(ctx: Ctx, report: dict | None = None, before: dict | None = None) -> None:
    from pyrekordbox.db6 import tables

    report = report or ctx.load("last_report.json")
    plan = ctx.load("plan.json")
    manifest = ctx.load("manifest.json", {})
    if not report or not plan:
        sys.exit("nothing to check (no report/plan)")
    if before is None and report.get("backup"):
        p = Path(report["backup"]) / "fingerprint_before.json"
        before = json.load(open(p, encoding="utf-8")) if p.exists() else None
    db = open_db()
    errs: list[str] = []
    src_names = [pe["name"] for pe in plan["playlists"]]
    for t, info in report["targets"].items():
        suffix = TARGETS[t][0]
        kids = sorted(db.get_playlist(ParentID=info["copy_folder_id"]).all(), key=lambda p: p.Seq)
        names = [k.Name for k in kids]
        if names != [f"{n} {suffix}" for n in src_names]:
            errs.append(f"{t}: playlist order/names {names}")
        cmap = {**plan["targets"][t]["copy_map"], **info["new_content_ids"]}
        back = {v: k for k, v in cmap.items()}
        for pe in plan["playlists"]:
            kp = [k for k in kids if k.Name == f"{pe['name']} {suffix}"]
            if not kp:
                errs.append(f"{t}: missing playlist {pe['name']}")
                continue
            got = [back.get(str(s.ContentID), "?") for s in sorted(
                db.get_playlist_songs(PlaylistID=kp[0].ID).all(), key=lambda s: s.TrackNo)]
            want = [c for c in pe["cids"] if c in cmap]
            if got != want:
                errs.append(f"{t} {pe['name']}: order/content mismatch")
            log(f"  {t} {kp[0].Name}: {len(got)}/{len(pe['cids'])} {'OK' if got == want else 'MISMATCH'}")
        for cid, nid in info["new_content_ids"].items():
            c, src, m = db.get_content(ID=str(nid)), db.get_content(ID=cid), manifest[cid][t]
            shift = int(m.get("shift_ms") or 0)
            p = Path(c.FolderPath)
            if c.FileType != TARGETS[t][2]:
                errs.append(f"{nid} FileType {c.FileType}")
            if str(os.stat(p).st_ino) != str(c.rb_file_id):
                errs.append(f"{nid} rb_file_id")
            dat = SHARE / c.AnalysisDataPath.lstrip("/\\")
            g_new = at.pqtz_entries([r for n, _, r in at.read_tags(dat)[1] if n == "PQTZ"][0])
            g_src = at.pqtz_entries([r for n, _, r in at.read_tags(SHARE / src.AnalysisDataPath.lstrip("/\\"))[1]
                                     if n == "PQTZ"][0])
            if [(b, tp, tm - shift) for b, tp, tm in g_new] != g_src:
                errs.append(f"{nid} grid")
            ppth = [r for n, _, r in at.read_tags(dat)[1] if n == "PPTH"][0]
            if ppth[16:].decode("utf-16-be").rstrip("\x00") != "?/" + p.name:
                errs.append(f"{nid} PPTH")
            ext_tags = [n for n, _, _ in at.read_tags(dat.with_suffix(".EXT"))[1]]
            if (t == "flac") != ("PVB2" in ext_tags):
                errs.append(f"{nid} PVB2")
            x3 = dat.with_suffix(".3EX")
            if x3.exists():
                import msgpack

                e = msgpack.unpackb(x3.read_bytes(), raw=False, strict_map_key=False)["embedding"]
                if e["d2"] != str(c.ID) or e["d3"] != at.md5_file(p):
                    errs.append(f"{nid} 3EX")
            cs = sorted((q.Kind, q.InMsec, q.OutMsec) for q in db.get_cue(ContentID=cid).all())
            cn = sorted((q.Kind, q.InMsec - shift, q.OutMsec - shift if q.OutMsec not in (None, -1) else q.OutMsec)
                        for q in db.get_cue(ContentID=str(nid)).all())
            if cs != cn:
                errs.append(f"{nid} cues")
            for cf in db.session.query(tables.ContentFile).filter_by(ContentID=str(nid)).all():
                if at.md5_file(cf.rb_local_path) != cf.Hash:
                    errs.append(f"{nid} contentFile {cf.Path}")
            for f in ("Title", "ArtistID", "BPM", "KeyID", "Rating", "ColorID", "Commnt"):
                if getattr(c, f) != getattr(src, f):
                    errs.append(f"{nid} field {f}")
    n_new = sum(len(i["new_content_ids"]) for i in report["targets"].values())
    if before:
        after_o = fingerprint_contents(db, list(before["originals"]), audio_md5="audio_md5" in next(
            (v for v in before["originals"].values() if v), {}))
        d_o = [k for k in before["originals"] if before["originals"][k] != after_o.get(k)]
        after_c = fingerprint_contents(db, list(before["copies"]), audio_md5=False)
        d_c = [k for k in before["copies"] if before["copies"][k] != after_c.get(k)]
        after_op = fingerprint_playlists(db, list(before["orig_playlists"]))
        d_op = [k for k in before["orig_playlists"] if [tuple(x) for x in before["orig_playlists"][k]] != after_op[k]]
        after_cp = fingerprint_playlists(db, list(before["copy_playlists"]))
        d_cp = [k for k in before["copy_playlists"]
                if after_cp[k][: len(before["copy_playlists"][k])] != [tuple(x) for x in before["copy_playlists"][k]]]
        log(f"originals changed: {len(d_o)} {d_o[:5]} | existing copies changed: {len(d_c)} {d_c[:5]} | "
            f"original playlists changed: {len(d_op)} | existing copy playlists (prefix) changed: {len(d_cp)}")
        errs += [f"original changed {k}" for k in d_o] + [f"existing copy changed {k}" for k in d_c]
        errs += [f"orig playlist changed {k}" for k in d_op] + [f"copy playlist prefix changed {k}" for k in d_cp]
    log(f"check: {n_new} new copies, ERRORS {len(errs)}")
    for e in errs[:40]:
        log("   ", e)


# ── rollback ─────────────────────────────────────────────────────────────────────────


def cmd_rollback(bdir: Path, delete_audio: bool) -> None:
    if rekordbox_running():
        sys.exit("ABORT: close Rekordbox first")
    rep = json.load(open(bdir / "apply_report.json", encoding="utf-8"))
    for name in ("master.db", "master.db-wal", "master.db-shm", "masterPlaylists6.xml"):
        src = bdir / name
        if src.exists():
            shutil.copy2(src, RB_DIR / name)
        elif (RB_DIR / name).exists() and name.startswith("master.db-"):
            (RB_DIR / name).unlink()
    for d in rep.get("created_dirs", []):
        shutil.rmtree(d, ignore_errors=True)
    if delete_audio:
        work = STATE_ROOT / re.sub(r"[^\w.-]+", "_", rep["folder"]["name"])
        mp = work / "manifest.json"
        manifest = json.load(open(mp, encoding="utf-8")) if mp.exists() else {}
        n = 0
        for t, info in rep["targets"].items():
            for cid in info["new_content_ids"]:
                p = manifest.get(cid, {}).get(t, {}).get("path")
                if p and Path(p).exists() and manifest[cid][t].get("mode") != "reuse":
                    Path(p).unlink()
                    n += 1
        log(f"deleted {n} copied audio files (reused pre-existing files were kept)")
    log("restored from", bdir, "- re-run `plan` to resync state.json")


# ── main ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--folder", required=True, help="Rekordbox folder name, e.g. '16.10'")
        p.add_argument("--folder-id", help="disambiguate when several folders share the name")
        p.add_argument("--targets", default="aiff,mp3,flac")
        p.add_argument("--music-root", default=str(Path.home() / "Music"))
        p.add_argument("--mp3-mode", choices=("max", "source"), default="max")
        p.add_argument("--workers", type=int, default=4)

    for name in ("plan", "build", "verify", "check"):
        common(sub.add_parser(name))
    pa = sub.add_parser("apply")
    common(pa)
    pa.add_argument("--dry", action="store_true")
    pr = sub.add_parser("rollback")
    pr.add_argument("backup_dir")
    pr.add_argument("--delete-audio", action="store_true")
    a = ap.parse_args()
    if a.cmd == "rollback":
        cmd_rollback(Path(a.backup_dir), a.delete_audio)
        return
    ctx = Ctx(a)
    log(f"work dir {ctx.work} | ffmpeg {ctx.ffmpeg}")
    {"plan": cmd_plan, "build": cmd_build, "verify": cmd_verify,
     "apply": lambda c: cmd_apply(c, a.dry), "check": cmd_check}[a.cmd](ctx)


if __name__ == "__main__":
    main()
