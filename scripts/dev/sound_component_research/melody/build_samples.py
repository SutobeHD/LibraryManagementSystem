"""Sample sets + Rekordbox beat grids + analysis windows for the melody probes.

Run with the project venv (pyrekordbox). Read-only: tracks.json, tmp/sc-struct/phrases.jsonl,
ANLZ files opened 'rb' through scripts/library_measure_anlz, master.db only through
app.anlz_safe.resolve_anlz_paths. Output: tmp/sc-rework-m/samples.json (ids, numbers, beat times).
"""

import collections
import json
import logging
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4 if "scripts" in Path(__file__).parts else 2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
import library_measure_anlz as L  # noqa: E402

from app.anlz_safe import resolve_anlz_paths  # noqa: E402

OUT = ROOT / "tmp" / "sc-rework-m"
SEED = 20261113
WIN_S, N_WIN = 30.0, 4
N_NEG, N_GENRE, N_FOLDER = 120, 40, 50
FOLDER_WORDS = ("acid",)
QUALITY_TAGS = {"BadFormat", "Bad Quality"}
# PSSI kind -> label per mood (see structure/common.py): C = chorus / main part
CHORUS = {1: {5}, 2: {9}, 3: {9}}
BODY = {1: {2, 5}, 2: {2, 3, 4, 5, 6, 7, 8, 9}, 3: {2, 3, 4, 5, 6, 7, 8, 9}}


def user_tags(t):
    return {x.strip() for x in (t.get("MyTag") or "").split(",") if x.strip()}


def pick_windows(beats, bib0, dur, pssi):
    """4 window starts (s), each on a downbeat. Chorus phrases first, then other body phrases,
    else evenly spaced between 15 % and 85 % of the track."""
    times = [b / 1000.0 for b in beats]
    if len(times) < 64:
        return None, "nogrid"
    down = [i for i in range(len(times)) if (bib0 - 1 + i) % 4 == 0]
    lo, hi = 0.15 * dur, 0.85 * dur - WIN_S

    def snap(t):
        i = min(down, key=lambda k: abs(times[k] - t))
        return times[i]

    starts, src = [], "even"
    if pssi and pssi.get("e"):
        mood = pssi["mood"]
        ents = sorted(pssi["e"], key=lambda e: e[0])
        spans = []
        for j, e in enumerate(ents):
            b0 = e[0] - 1
            b1 = (ents[j + 1][0] if j + 1 < len(ents) else pssi["end_beat"]) - 1
            if 0 <= b0 < len(times) and b1 > b0:
                spans.append((e[1], times[b0], times[min(b1, len(times) - 1)]))
        for kinds, name in ((CHORUS.get(mood, set()), "pssi_chorus"), (BODY.get(mood, set()), "pssi_body")):
            cand = []
            for kind, t0, t1 in spans:
                if kind in kinds:
                    t = t0
                    while t + WIN_S <= t1 + 8.0 and t + WIN_S <= dur - 2:  # may run 8 s into the next phrase
                        cand.append(t)
                        t += WIN_S
            if len(cand) >= N_WIN:
                idx = [round(k * (len(cand) - 1) / (N_WIN - 1)) for k in range(N_WIN)]
                starts, src = [snap(cand[i]) for i in idx], name
                break
    if len(set(starts)) < N_WIN:
        if hi <= lo:
            return None, "short"
        starts = [snap(lo + k * (hi - lo) / (N_WIN - 1)) for k in range(N_WIN)]
        src = "even"
    starts = sorted(set(round(s, 3) for s in starts))
    if len(starts) < N_WIN or starts[-1] + WIN_S > dur:
        return None, "short"
    return starts, src


def main():
    rng = random.Random(SEED)
    data = json.loads((ROOT / "tmp/library-analysis/tracks.json").read_text(encoding="utf-8"))
    local = {
        t["ID"]: t
        for t in data
        if not str(t.get("path", "")).startswith(("soundcloud:", "spotify:")) and t.get("TotalTime", 0) >= 100
    }
    pairs = json.loads((OUT / "pairs.json").read_text(encoding="utf-8"))
    sets = collections.defaultdict(list)
    for p in pairs["chosen"]:
        sets["pair"] += [p["a"], p["b"]]
    sets["distract"] = list(pairs["distractors"])
    tagged = {i: user_tags(t) for i, t in local.items()}
    reviewed = {i for i, tg in tagged.items() if tg - QUALITY_TAGS}
    for tag in ("Melodic", "Synth", "Hard", "Vocal", "Acid", "Dark"):
        sets["tag_" + tag] = sorted(i for i, tg in tagged.items() if tag in tg)
    # negatives for Melodic: user-tagged tracks (so the chip row was used on them) without the
    # tag, same Genre-field distribution as the positives
    by_genre = collections.Counter(local[i]["Genre"] for i in sets["tag_Melodic"])
    neg = []
    pos_all = set(sets["tag_Melodic"])
    for genre, n in sorted(by_genre.items()):
        pool = sorted(i for i in reviewed if i not in pos_all and local[i]["Genre"] == genre)
        k = min(len(pool), round(n * N_NEG / len(pos_all)))
        neg += rng.sample(pool, k)
    sets["neg_Melodic"] = neg
    used = set().union(*[set(v) for v in sets.values()])
    for genre in ("Trance", "Hard Techno", "Raw", "Groove"):
        pool = sorted(i for i, t in local.items() if t["Genre"] == genre and i not in used)
        sets["genre_" + genre] = rng.sample(pool, min(N_GENRE, len(pool)))

    # weak label from the user's own crate folders: a folder name that contains the word
    used = set().union(*[set(v) for v in sets.values()])
    for word in FOLDER_WORDS:
        pool = sorted(i for i, t in local.items() if re.search(word, str(Path(t["path"]).parent), re.I) and i not in used)
        sets["folder_" + word] = rng.sample(pool, min(N_FOLDER, len(pool)))

    phr = {}
    with open(ROOT / "tmp/sc-struct/phrases.jsonl", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            phr[r["id"]] = r.get("pssi")
    anlz_paths = resolve_anlz_paths(str(L.DEFAULT_DB), None)
    want = sorted(set().union(*[set(v) for v in sets.values()]))
    tracks, skipped = {}, collections.Counter()
    for tid in want:
        t = local.get(tid)
        p = anlz_paths.get(tid) or {}
        dat = p.get("DAT")
        if not t or not dat or not Path(dat).is_file() or not Path(t["path"]).is_file():
            skipped["missing"] += 1
            continue
        try:
            ents = L._pqtz_entries(L.load_anlz(dat))
        except Exception as exc:  # unreadable ANLZ: skip the track, keep the run alive
            skipped[type(exc).__name__] += 1
            continue
        if not ents:
            skipped["nogrid"] += 1
            continue
        beats = [e[2] for e in ents]
        wins, src = pick_windows(beats, ents[0][0], float(t["TotalTime"]), phr.get(tid))
        if wins is None:
            skipped[src] += 1
            continue
        tracks[tid] = {
            "bpm": t["BPM"],
            "dur": t["TotalTime"],
            "genre": t["Genre"],
            "key": t["Key"],
            "ext": t["path"].rsplit(".", 1)[-1].lower(),
            "bib0": ents[0][0],
            "beats_ms": beats,
            "wins": wins,
            "win_src": src,
            "tags": sorted(tagged.get(tid, set()) - QUALITY_TAGS),
        }
    out = {"sets": {k: [i for i in v if i in tracks] for k, v in sets.items()}, "tracks": tracks}
    (OUT / "samples.json").write_text(json.dumps(out), encoding="utf-8")
    print("tracks", len(tracks), "skipped", dict(skipped))
    print({k: len(v) for k, v in out["sets"].items()})
    print("win_src", collections.Counter(t["win_src"] for t in tracks.values()))
    print("ext", collections.Counter(t["ext"] for t in tracks.values()))
    print("melodic genres", dict(by_genre))


if __name__ == "__main__":
    main()
