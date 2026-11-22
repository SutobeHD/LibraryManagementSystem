"""Joint copy agreement of intro AND outro bars (mix-partner filter), same code path as derive_features.py.

Copy pairs from tmp/sc-derived-struct/copy_pairs_ids.json (rework D, 92 title-matched pairs);
bin = round(bars / 8). Writes tmp/sc-derived-struct/mix_partner_joint.txt. Ids only."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
sys.path.insert(0, str(HERE.parents[1] / "structure"))
import common  # noqa: E402

common.ROOT = ROOT
common.SC = ROOT / "tmp" / "sc-struct"
OUT = ROOT / "tmp" / "sc-derived-struct"

tracks, _meta, _anlz = common.load()
io = {str(t["id"]): (t["feat"]["intro"], t["feat"]["outro"]) for t in tracks}
pairs = json.loads((OUT / "copy_pairs_ids.json").read_text(encoding="utf-8"))["pairs"]
n = eq = pm1 = sbin = 0
for a, b in pairs:
    if a not in io or b not in io:
        continue
    (ia, oa), (ib, ob) = io[a], io[b]
    n += 1
    eq += ia == ib and oa == ob
    pm1 += abs(ia - ib) <= 1 and abs(oa - ob) <= 1
    sbin += round(ia / 8) == round(ib / 8) and round(oa / 8) == round(ob / 8)
lines = [
    f"copy pairs with intro + outro: {n} of {len(pairs)}",
    f"intro AND outro: both exact {eq / n:.2f} | both within +-1 bar {pm1 / n:.2f} | both in the same round(bars / 8) bin {sbin / n:.2f}",
]
(OUT / "mix_partner_joint.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
