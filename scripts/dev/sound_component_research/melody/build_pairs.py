"""Probe 1 (W8 weak ground truth): original <-> remix / edit pairs from title stems.

Read-only: tmp/library-analysis/tracks.json only. Run with the project venv (imports the title
helpers from app/external_track_match.py). Output: tmp/sc-rework-m/pairs.json (ids + numbers only).

Pair = two local tracks with the same normalised title stem + overlapping artist tokens that are
NOT the same audio (same audio = duration within 3 s AND BPM within 1).
"""

import collections
import itertools
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4 if "scripts" in Path(__file__).parts else 2]
sys.path.insert(0, str(ROOT))
from app.external_track_match import extract_title_stem, normalize_title  # noqa: E402

OUT = ROOT / "tmp" / "sc-rework-m"
SEED = 20261113
N_PAIRS, N_DISTRACT = 40, 60

PITCHED = re.compile(r"sped\s*up|speed\s*up|slowed|nightcore|pitched|reverb", re.I)
SAME_MASTER = re.compile(
    r"\b(original|extended|extd|radio|full|short|long|album|single|club|instrumental|master|"
    r"remaster(ed)?|free\s*(dl|download))\b",
    re.I,
)
REMIXISH = re.compile(
    r"\b(remix|rmx|bootleg|rework|flip|refix|mashup|vip|dub|edit|re-?edit|cover|"
    r"schranz|trance|hardstyle|hardcore|techno|rave)\b",
    re.I,
)
STOP = set(
    "premiere free dl download remix edit bootleg rework records recordings music the and feat ft "
    "schranz trance hard techno official original mix extended version radio vip dj mc x vs with "
    "various artists unknown va hardstyle hardcore rave style id flip".split()
)
LOSSLESS = ("aiff", "aif", "wav", "flac")


def camelot(key):
    """'8A' -> (pitch class of the tonic, mode). Camelot number n, B = major, A = minor."""
    m = re.fullmatch(r"\s*(\d{1,2})([ABab])\s*", key or "")
    if not m:
        return None
    n, mode = int(m.group(1)), m.group(2).upper()
    major_pc = (11 + 7 * (n - 1)) % 12  # 1B = B major
    return (major_pc if mode == "B" else (major_pc + 9) % 12, mode)


def key_shift(ka, kb):
    """Semitones a -> b (-5..6), after mapping minor to its relative major. None if unknown."""
    a, b = camelot(ka), camelot(kb)
    if not a or not b:
        return None
    ra = a[0] if a[1] == "B" else (a[0] + 3) % 12
    rb = b[0] if b[1] == "B" else (b[0] + 3) % 12
    d = (rb - ra) % 12
    return d - 12 if d > 6 else d


def tail_of(title):
    """Everything that extract_title_stem removes: bracket groups + trailing dash part."""
    groups = re.findall(r"[(\[]([^()\[\]]*)[)\]]", title)
    dash = title.rsplit(" - ", 1)[1] if " - " in title else ""
    return " | ".join([*groups, dash]).strip()


def split_title(t):
    """The library holds some titles as 'Artist - Title'; return the real title part."""
    title = t["Title"] or ""
    if " - " in title:
        head, rest = title.split(" - ", 1)
        if artist_tokens(head) and artist_tokens(head) <= artist_tokens(t["Artist"]):
            return rest
    return title


def version_class(t):
    """-> (class, remixer tokens). The version descriptor sits in the title tail or, for many
    files, as a comma part of the Artist field ("X, Extended Mix", "X, Y Remix")."""
    parts = [tail_of(split_title(t)), *(t["Artist"] or "").split(",")[1:]]
    who = set()
    cls = "same"
    for part in parts:
        if PITCHED.search(part):
            return "pitched", frozenset()
        part = re.sub(r"radio\s+edit|extended\s+edit", " ", part, flags=re.I)
        stripped = SAME_MASTER.sub(" ", part)
        if REMIXISH.search(stripped):
            cls = "remix"
            who |= {w for w in normalize_title(REMIXISH.sub(" ", stripped)).split() if w not in STOP}
    return cls, frozenset(who)


def artist_tokens(*fields):
    words = set()
    for f in fields:
        for w in normalize_title(re.sub(r"[/,&|:]", " ", f or "")).split():
            if len(w) >= 3 and w not in STOP and not re.fullmatch(r"[a-z]{0,6}\d{2,}", w):
                words.add(w)
    return words


def same_audio(a, b):
    return abs(a["TotalTime"] - b["TotalTime"]) <= 3 and abs(a["BPM"] - b["BPM"]) <= 1


def main():
    data = json.loads((ROOT / "tmp/library-analysis/tracks.json").read_text(encoding="utf-8"))
    local = [
        t
        for t in data
        if not str(t.get("path", "")).startswith(("soundcloud:", "spotify:"))
        and t.get("TotalTime", 0) >= 100
        and t.get("BPM", 0) > 60
        and Path(t["path"]).is_file()
    ]
    groups = collections.defaultdict(list)
    for t in local:
        stem = normalize_title(extract_title_stem(split_title(t)))
        if len(stem) >= 3 and set(stem.split()) - STOP:
            groups[stem].append(t)

    pairs, n_copy_pairs, n_no_artist = [], 0, 0
    for stem, members in groups.items():
        if len(members) < 2:
            continue
        # collapse same-audio copies to one representative (lossless first)
        members = sorted(members, key=lambda t: (t["path"].rsplit(".", 1)[-1].lower() not in LOSSLESS, t["ID"]))
        reps = []
        for t in members:
            if any(same_audio(t, r) for r in reps):
                n_copy_pairs += 1
            else:
                reps.append(t)
        for a, b in itertools.combinations(reps, 2):
            ta, tb = artist_tokens(a["Artist"], a["Remixer"]), artist_tokens(b["Artist"], b["Remixer"])
            ca, cb = version_class(a), version_class(b)
            overlap = bool(ta & tb)
            if not overlap:
                # remixer of one side named as the artist of the other, or an empty artist field
                # on a same-master cut with identical tempo
                weak = (not ta or not tb) and ca[0] == cb[0] == "same" and abs(a["BPM"] - b["BPM"]) <= 1
                if not weak:
                    n_no_artist += 1
                    continue
            if "pitched" in (ca[0], cb[0]):
                sub = "pitched"
            elif ca[0] == cb[0] == "same":
                sub = "ext"
            elif ca[0] == cb[0] == "remix":
                sub = "ext" if ca[1] and cb[1] and (ca[1] <= cb[1] or cb[1] <= ca[1]) else "remix_remix"
            else:
                sub = "orig_remix"
            pairs.append(
                {
                    "a": a["ID"],
                    "b": b["ID"],
                    "group": stem,
                    "sub": sub,
                    "artist_overlap": overlap,
                    "dbpm": round(abs(a["BPM"] - b["BPM"]), 2),
                    "bpm_ratio": round(max(a["BPM"], b["BPM"]) / min(a["BPM"], b["BPM"]), 3),
                    "ddur": round(abs(a["TotalTime"] - b["TotalTime"]), 1),
                    "key_shift": key_shift(a["Key"], b["Key"]),
                    "mode_change": (camelot(a["Key"]) or (0, "?"))[1] != (camelot(b["Key"]) or (0, "?"))[1],
                }
            )

    n_groups = len({p["group"] for p in pairs})
    by_sub = collections.Counter(p["sub"] for p in pairs)
    shifts = collections.Counter(p["key_shift"] for p in pairs)
    summary = {
        "local_tracks": len(local),
        "stem_groups_multi": sum(1 for v in groups.values() if len(v) > 1),
        "same_audio_copies_collapsed": n_copy_pairs,
        "pairs_dropped_no_artist_overlap": n_no_artist,
        "pairs": len(pairs),
        "groups": n_groups,
        "by_sub": dict(by_sub),
        "key_shift_semitones": {str(k): v for k, v in sorted(shifts.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))},
        "key_same_share": round(shifts[0] / max(1, len(pairs)), 3),
        "bpm_same_le1": sum(p["dbpm"] <= 1 for p in pairs),
        "bpm_diff_1_10": sum(1 < p["dbpm"] <= 10 for p in pairs),
        "bpm_diff_gt10": sum(p["dbpm"] > 10 for p in pairs),
    }
    for sub in by_sub:
        ps = [p for p in pairs if p["sub"] == sub]
        summary[f"sub_{sub}"] = {
            "n": len(ps),
            "key_same": sum(p["key_shift"] == 0 for p in ps),
            "key_shifted": sum(p["key_shift"] not in (0, None) for p in ps),
            "bpm_median_abs_diff": sorted(p["dbpm"] for p in ps)[len(ps) // 2],
        }

    # selection: one pair per title group, every track used once; same-master cuts first
    rng = random.Random(SEED)
    order = {"pitched": 0, "ext": 1, "orig_remix": 2, "remix_remix": 3}
    pool = sorted(pairs, key=lambda p: (not p["artist_overlap"], p["group"], p["a"], p["b"]))
    rng.shuffle(pool)
    pool.sort(key=lambda p: order[p["sub"]])
    quota = {"pitched": 40, "ext": 14, "orig_remix": 13, "remix_remix": 13}
    chosen, used_groups, used_ids, n_sub = [], set(), set(), collections.Counter()
    for strict in (True, False):
        for p in pool:
            if len(chosen) >= N_PAIRS or p["group"] in used_groups or {p["a"], p["b"]} & used_ids:
                continue
            if strict and (n_sub[p["sub"]] >= quota[p["sub"]] or not p["artist_overlap"]):
                continue
            chosen.append(p)
            used_groups.add(p["group"])
            used_ids |= {p["a"], p["b"]}
            n_sub[p["sub"]] += 1
    # distractors: random local tracks outside every multi-version title group
    grouped_ids = {t["ID"] for v in groups.values() if len(v) > 1 for t in v}
    cand = sorted(t["ID"] for t in local if t["ID"] not in grouped_ids)
    distract = rng.sample(cand, N_DISTRACT + 20)  # spare ids for unreadable files / missing grids
    (OUT / "pairs.json").write_text(
        json.dumps({"summary": summary, "all_pairs": pairs, "chosen": chosen, "distractors": distract}, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=1))
    print("chosen", len(chosen), dict(n_sub))


if __name__ == "__main__":
    main()
