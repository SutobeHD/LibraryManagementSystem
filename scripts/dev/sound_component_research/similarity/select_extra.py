"""Seeded extra set of 10 lossy (mp3 / m4a) tracks with Rekordbox PQTZ grids, same pool rules as
baseline/select_sample.py, excluding the 40 sample ids. Read-only (master.db via rbox, ANLZ "rb").
Usage: select_extra.py <baseline sample.json> <out extra.json>"""
import json
import os
import random
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "app").is_dir())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
SEED = 20261112
N_EXTRA = 10
DB = Path.home() / "AppData" / "Roaming" / "Pioneer" / "rekordbox" / "master.db"
GENRES = ("Techno", "Raw", "Groove", "Trance", "House", "Uptempo")


def norm_genre(r):
    g = (r.get("Genre") or "").strip()
    if g.lower().replace(" ", "") == "hardtechno":
        return "Hard Techno"
    return g if g in GENRES else None


sample_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
taken = {t["id"] for t in json.load(open(sample_path, encoding="utf-8"))["tracks"]}
tracks = json.load(open(ROOT / "tmp/library-analysis/tracks.json", encoding="utf-8"))
anlz = {}
for line in open(ROOT / "tmp/library-analysis/measure/anlz.jsonl", encoding="utf-8"):
    a = json.loads(line)
    anlz[a["id"]] = a

pool = []
for r in tracks:
    p = str(r.get("path") or "")
    if p.startswith(("soundcloud:", "spotify:")) or str(r["ID"]) in taken:
        continue
    if os.path.splitext(p)[1].lower() not in (".mp3", ".m4a"):
        continue
    if not (180 <= (r.get("TotalTime") or 0) <= 420):
        continue
    g = norm_genre(r)
    if g is None:
        continue
    grid = (anlz.get(str(r["ID"]), {}).get("grid") or {})
    if not grid.get("present") or (grid.get("beats") or 0) < 200 or grid.get("tempo_distinct", 1) != 1:
        continue
    if not os.path.isfile(p):
        continue
    pool.append((g, r))
pool.sort(key=lambda x: str(x[1]["ID"]))
print("lossy pool", len(pool))
chosen = random.Random(SEED).sample(pool, N_EXTRA)

from app.anlz_safe import resolve_anlz_paths  # noqa: E402
from library_measure_anlz import _pqtz_entries, load_anlz  # noqa: E402

paths = resolve_anlz_paths(str(DB), [str(r["ID"]) for _, r in chosen])
out = []
for g, r in chosen:
    tid = str(r["ID"])
    ap = paths.get(tid)
    entries = _pqtz_entries(load_anlz(ap["DAT"])) if ap else []
    out.append({"id": tid, "title": r.get("Title"), "artist": r.get("Artist"), "genre": g,
                "genre_raw": r.get("Genre"), "bpm": r.get("BPM"), "key": r.get("Key"), "path": r["path"],
                "total_time": r.get("TotalTime"), "in_w8": False, "bitrate": r.get("Bitrate"),
                "grid": [[b, bpm, ms] for b, bpm, ms in entries], "extra": True})
    print(tid, g, r.get("BPM"), r.get("Bitrate"), os.path.splitext(r["path"])[1], len(entries))
json.dump({"seed": SEED, "tracks": out}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
