"""Seeded stratified held-out sample: 60 local tracks with Rekordbox PQTZ grid + PSSI phrases,
none of the 50 selection tracks (baseline sample + similarity extra). Read-only: master.db via
rbox (path lookup), ANLZ opened "rb". Writes <out>/fresh_ids.json (ids only) and the working
file <out>/fresh_sample.json (run_sim.py input format + PSSI).
Usage: select_fresh.py <out dir> <selection json> [<selection json> ...]"""
import json
import logging
import os
import random
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "app").is_dir())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
SEED = 20261113
# (genre, total, of which lossy mp3 / m4a) -- old 40-sample quota x 1.5; House has no lossy file
# in the pool, Uptempo only lossy ones
QUOTA = [("Hard Techno", 14, 4), ("Raw", 10, 3), ("Techno", 10, 4), ("Groove", 6, 3),
         ("Trance", 9, 4), ("House", 8, 0), ("Uptempo", 3, 3)]
MIN_S, MAX_S = 180, 480
GENRES = {g for g, _n, _l in QUOTA}
LOSSY = (".mp3", ".m4a")


def norm_genre(r):
    g = (r.get("Genre") or "").strip()
    if g.lower().replace(" ", "") == "hardtechno":
        return "Hard Techno"
    return g if g in GENRES else None


def main():
    out_dir = Path(sys.argv[1])
    taken = set()
    for p in sys.argv[2:]:
        taken |= {str(t["id"]) for t in json.load(open(p, encoding="utf-8"))["tracks"]}
    tracks = json.load(open(ROOT / "tmp/library-analysis/tracks.json", encoding="utf-8"))
    anlz, phr = {}, {}
    for line in open(ROOT / "tmp/library-analysis/measure/anlz.jsonl", encoding="utf-8"):
        a = json.loads(line)
        anlz[a["id"]] = a
    for line in open(ROOT / "tmp/sc-struct/phrases.jsonl", encoding="utf-8"):
        a = json.loads(line)
        phr[a["id"]] = a
    pool: dict = {}
    for r in tracks:
        tid, p = str(r["ID"]), str(r.get("path") or "")
        if p.startswith(("soundcloud:", "spotify:")) or tid in taken:
            continue
        if not (MIN_S <= (r.get("TotalTime") or 0) <= MAX_S):
            continue
        g = norm_genre(r)
        if g is None:
            continue
        grid = anlz.get(tid, {}).get("grid") or {}
        if not grid.get("present") or (grid.get("beats") or 0) < 200:
            continue
        ps = (phr.get(tid) or {}).get("pssi")
        if not ps or not ps.get("e"):
            continue
        if not os.path.isfile(p):
            continue
        pool.setdefault((g, os.path.splitext(p)[1].lower() in LOSSY), []).append(r)
    rng = random.Random(SEED)
    chosen = []
    for g, n, n_lossy in QUOTA:
        for lossy, k in ((True, n_lossy), (False, n - n_lossy)):
            cand = sorted(pool.get((g, lossy), []), key=lambda r: str(r["ID"]))
            print(f"{g:12s} lossy={lossy!s:5s} pool={len(cand):4d} take={k}")
            chosen += [(g, r) for r in rng.sample(cand, k)]

    import library_measure_anlz as L

    from app.anlz_safe import resolve_anlz_paths

    paths = resolve_anlz_paths(str(L.DEFAULT_DB), [str(r["ID"]) for _, r in chosen])
    out = []
    for g, r in chosen:
        tid = str(r["ID"])
        ap = paths[tid]
        entries = L._pqtz_entries(L.load_anlz(ap["DAT"]))
        a_ext, masked, _plain, _err = L._read_anlz(ap["EXT"])
        c = a_ext.getall_tags("PSSI")[0].content
        pssi = {"mood": int.from_bytes(bytes(c.mood), "big"), "end_beat": int.from_bytes(bytes(c.end_beat), "big"),
                "masked": masked, "e": [[int(e.beat), int(e.kind)] for e in c.entries]}
        out.append({"id": tid, "title": r.get("Title"), "artist": r.get("Artist"), "genre": g, "bpm": r.get("BPM"),
                    "key": r.get("Key"), "path": r["path"], "total_time": r.get("TotalTime"), "bitrate": r.get("Bitrate"),
                    "grid": [[b, bpm, ms] for b, bpm, ms in entries], "pssi": pssi})
    out_dir.mkdir(parents=True, exist_ok=True)
    json.dump({"seed": SEED, "ids": [o["id"] for o in out]}, open(out_dir / "fresh_ids.json", "w", encoding="utf-8"))
    json.dump({"seed": SEED, "quota": QUOTA, "tracks": out}, open(out_dir / "fresh_sample.json", "w", encoding="utf-8"), ensure_ascii=False)
    n_lossy = sum(os.path.splitext(o["path"])[1].lower() in LOSSY for o in out)
    print("n", len(out), "lossy", n_lossy, "with grid", sum(bool(o["grid"]) for o in out), "moods", sorted({o["pssi"]["mood"] for o in out}))


if __name__ == "__main__":
    main()
