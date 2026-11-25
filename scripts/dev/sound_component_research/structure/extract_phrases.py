"""Read-only: per-phrase PSSI entries for every track -> tmp/sc-struct/phrases.jsonl.
ANLZ opened 'rb' via scripts/library_measure_anlz._read_anlz; nothing is written outside tmp/sc-struct."""
import json, sys, time, logging
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
import library_measure_anlz as L
from app.anlz_safe import resolve_anlz_paths

tracks = json.load(open(ROOT / "tmp/library-analysis/tracks.json", encoding="utf-8"))
paths = resolve_anlz_paths(str(L.DEFAULT_DB), None)
out = open(ROOT / "tmp/sc-struct/phrases.jsonl", "w", encoding="utf-8")
t0 = time.monotonic(); n = 0; nop = 0
for t in tracks:
    tid = str(t["ID"]); row = {"id": tid}
    p = paths.get(tid)
    ext = p and p.get("EXT")
    if not ext or not Path(ext).is_file():
        row["pssi"] = None; nop += 1
    else:
        try:
            anlz, masked, _plain, _err = L._read_anlz(ext)
            tags = anlz.getall_tags("PSSI")
            if not tags:
                row["pssi"] = None; nop += 1
            else:
                c = tags[0].content
                row["pssi"] = {
                    "masked": masked,
                    "mood": int.from_bytes(bytes(c.mood), "big"),
                    "end_beat": int.from_bytes(bytes(c.end_beat), "big"),
                    "bank": int.from_bytes(bytes(c.bank), "big"),
                    # beat, kind, k1, k2, k3, fill, beat_fill, b, beat_2, beat_3, beat_4
                    "e": [[int(e.beat), int(e.kind), int(e.k1), int(e.k2), int(e.k3), int(e.fill),
                           int(e.beat_fill), int(e.b), int(e.beat_2), int(e.beat_3), int(e.beat_4)]
                          for e in c.entries],
                }
            # grid: beat_in_bar of beat #1 so phrase starts can be checked against downbeats
            dat = p.get("DAT")
            if dat and Path(dat).is_file():
                a2 = L.load_anlz(dat)
                ents = L._pqtz_entries(a2)
                if ents:
                    row["grid"] = {"beats": len(ents), "bib0": ents[0][0],
                                   "bpm_min": min(b for _, b, _ in ents), "bpm_max": max(b for _, b, _ in ents),
                                   "last_ms": ents[-1][2], "first_ms": ents[0][2]}
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[:200]; row["pssi"] = None; nop += 1
    out.write(json.dumps(row) + "\n"); n += 1
out.close()
print(f"rows {n} no_pssi {nop} wall {time.monotonic()-t0:.1f}s")
