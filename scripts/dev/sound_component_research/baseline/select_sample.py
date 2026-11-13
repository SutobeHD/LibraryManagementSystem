"""Seeded stratified sample of 40 local tracks + Rekordbox PQTZ beat grids. Read-only."""
import json, os, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
SEED = 20261110
OUT = ROOT / "tmp" / "sc-baseline"
DB = Path.home() / "AppData" / "Roaming" / "Pioneer" / "rekordbox" / "master.db"

QUOTA = [("Hard Techno", 9), ("Techno", 6), ("Raw", 7), ("Groove", 4), ("Trance", 6),
         ("House", 5), ("Uptempo", 2), ("Hip-Hop*", 1)]


def norm_genre(r):
    g = (r.get("Genre") or "").strip()
    gl = g.lower().replace(" ", "")
    if gl == "hardtechno":
        return "Hard Techno"
    if g in ("Techno", "Raw", "Groove", "Trance", "House", "Uptempo"):
        return g
    if not g and "pashanim" in (r.get("Artist") or "").lower():
        return "Hip-Hop*"   # untagged; assigned by artist (only local hip-hop of 3-7 min)
    return None


tracks = json.load(open(ROOT / "tmp/library-analysis/tracks.json", encoding="utf-8"))
anlz = {}
for line in open(ROOT / "tmp/library-analysis/measure/anlz.jsonl", encoding="utf-8"):
    a = json.loads(line)
    anlz[a["id"]] = a
w8 = {json.loads(l)["id"] for l in open(ROOT / "tmp/library-analysis/measure/audio_w8.jsonl", encoding="utf-8")}

pool = {}
for r in tracks:
    p = str(r.get("path") or "")
    if p.startswith(("soundcloud:", "spotify:")):
        continue
    tt = r.get("TotalTime") or 0
    if not (180 <= tt <= 420):
        continue
    g = norm_genre(r)
    if g is None:
        continue
    a = anlz.get(str(r["ID"]), {})
    grid = a.get("grid") or {}
    if not grid.get("present") or (grid.get("beats") or 0) < 200:
        continue
    if not os.path.isfile(p):
        continue
    pool.setdefault(g, []).append(r)

rng = random.Random(SEED)
chosen = []
for g, n in QUOTA:
    cand = sorted(pool.get(g, []), key=lambda r: str(r["ID"]))
    print(f"{g:12s} pool={len(cand):4d} take={n}")
    chosen += [(g, r) for r in rng.sample(cand, min(n, len(cand)))]

from app.anlz_safe import resolve_anlz_paths  # noqa: E402
from library_measure_anlz import load_anlz, _pqtz_entries  # noqa: E402

ids = [str(r["ID"]) for _, r in chosen]
paths = resolve_anlz_paths(str(DB), ids)
out = []
for g, r in chosen:
    tid = str(r["ID"])
    ap = paths.get(tid)
    entries = _pqtz_entries(load_anlz(ap["DAT"])) if ap else []
    out.append({
        "id": tid, "title": r.get("Title"), "artist": r.get("Artist"), "genre": g,
        "genre_raw": r.get("Genre"), "bpm": r.get("BPM"), "key": r.get("Key"),
        "path": r["path"], "total_time": r.get("TotalTime"), "in_w8": tid in w8,
        "anlz_dat": ap["DAT"] if ap else None,
        "grid": [[b, bpm, ms] for b, bpm, ms in entries],
    })
    print(tid, g, r.get("BPM"), r.get("TotalTime"), len(entries), os.path.splitext(r["path"])[1], "|", r.get("Artist"), "-", r.get("Title"))
json.dump({"seed": SEED, "quota": QUOTA, "tracks": out}, open(OUT / "sample.json", "w", encoding="utf-8"), ensure_ascii=False)
print("n", len(out), "with grid", sum(1 for o in out if o["grid"]))
