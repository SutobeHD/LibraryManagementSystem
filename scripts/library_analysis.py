"""Whole-library analysis: which track fields are filled, how the Genre field is used, and how
well the genre atlas covers the library.

Reads the track list read-only from a running backend (GET /api/library/tracks) or from a saved
JSON dump, runs every track through app.genre_atlas, and writes into --out:

  report.md    human-readable summary (tables)
  report.json  the same numbers, machine-readable (for diffs between runs)
  tracks.csv   one row per track with the top atlas candidates, sortable in a spreadsheet

Nothing is written to the library. "Agreement" compares the atlas with the user's own Genre
labels (leave-the-genre-field-out); it measures consistency with those labels, not truth.

Usage:
  python scripts/library_analysis.py                          # backend at http://127.0.0.1:8000
  python scripts/library_analysis.py --input tracks.json      # saved dump of /api/library/tracks
  python scripts/library_analysis.py --save-input tracks.json --out tmp/library-analysis
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.genre_atlas import GenreAtlas, normalize_key, soundcloud_permalink  # noqa: E402

logger = logging.getLogger("library_analysis")

DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_OUT = ROOT / "tmp" / "library-analysis"
FETCH_TIMEOUT_S = 180

# Rekordbox stores "unknown" as 0 in these numeric columns.
ZERO_IS_EMPTY = {"BPM", "ReleaseYear", "Bitrate", "SampleRate", "TotalTime", "Rating", "ColorID"}
NUMERIC_SUMMARY = ("BPM", "Bitrate", "SampleRate", "TotalTime", "ReleaseYear", "PlayCount")
NO_DISTINCT = {"beatGrid", "TagIDs", "ID", "path", "Artwork"}
CONFIDENCE_BUCKETS = ((0.6, ">= 60 %"), (0.4, "40-59 %"), (0.2, "20-39 %"), (0.0, "< 20 %"))


# --------------------------------------------------------------------------- input


def fetch_tracks(api: str) -> list[dict[str, Any]]:
    url = api.rstrip("/") + "/api/library/tracks"
    start = time.monotonic()
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    logger.info("fetched %d tracks from %s in %.1fs", len(data), url, time.monotonic() - start)
    if not isinstance(data, list):
        raise ValueError(f"{url} did not return a list")
    return data


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _bpm(track: dict[str, Any]) -> float | None:
    try:
        bpm = float(track.get("BPM") or 0)
    except (TypeError, ValueError):
        return None
    return bpm if 0 < bpm < 400 else None


def mytags(track: dict[str, Any]) -> list[str]:
    """MyTag names of a track, de-duplicated, order kept ("Melodic, Raw, Raw" -> 2 tags)."""
    seen: dict[str, None] = {}
    for part in str(track.get("MyTag") or "").split(","):
        name = part.strip()
        if name:
            seen.setdefault(name, None)
    return list(seen)


def source_of(track: dict[str, Any]) -> str:
    path = str(track.get("path") or "")
    if ":" in path and not (len(path) > 1 and path[1] == ":"):
        return path.split(":", 1)[0].lower()  # soundcloud:tracks:..., spotify:track:...
    return "local" if path else "none"


def format_of(track: dict[str, Any]) -> str:
    if source_of(track) != "local":
        return "-"
    return PurePath(str(track.get("path"))).suffix.lower().lstrip(".") or "?"


def derived(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source_of(track),
        "format": format_of(track),
        "mytags": mytags(track),
        "soundcloud_uploader": soundcloud_permalink(_text(track.get("Comment"))),
    }


# --------------------------------------------------------------------------- fields


def is_filled(field: str, value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, (int, float)) and field in ZERO_IS_EMPTY:
        return value != 0
    return True


def field_report(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(tracks) or 1
    fields: list[str] = []
    for t in tracks:
        for k in t:
            if k not in fields:
                fields.append(k)
    rows = []
    for f in fields:
        values = [t.get(f) for t in tracks]
        filled = [v for v in values if is_filled(f, v)]
        row: dict[str, Any] = {
            "field": f,
            "filled": len(filled),
            "pct": round(100 * len(filled) / n, 1),
        }
        if f not in NO_DISTINCT:
            row["distinct"] = len({str(v) for v in filled})
        if f in NUMERIC_SUMMARY:
            nums = [float(v) for v in filled if isinstance(v, (int, float))]
            if nums:
                row["min"] = min(nums)
                row["median"] = statistics.median(nums)
                row["max"] = max(nums)
        rows.append(row)
    return rows


def derived_report(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    d = [derived(t) for t in tracks]
    tag_counts: Counter[str] = Counter()
    for x in d:
        tag_counts.update(x["mytags"])
    return {
        "source": Counter(x["source"] for x in d).most_common(),
        "format": Counter(x["format"] for x in d).most_common(),
        "tracks_with_mytags": sum(1 for x in d if x["mytags"]),
        "mytags": tag_counts.most_common(),
        "tracks_with_soundcloud_url": sum(1 for x in d if x["soundcloud_uploader"]),
        "soundcloud_uploaders": len({x["soundcloud_uploader"] for x in d} - {None}),
    }


# --------------------------------------------------------------------------- atlas helpers


def suggest_for(
    atlas: GenreAtlas,
    track: dict[str, Any],
    *,
    use_genre: bool = True,
    use_comment: bool = True,
    limit: int = 5,
) -> dict[str, Any]:
    return atlas.suggest(
        title=_text(track.get("Title")),
        artist=_text(track.get("Artist")),
        genre=_text(track.get("Genre")) if use_genre else None,
        comment=_text(track.get("Comment")) if use_comment else None,
        label=_text(track.get("Label")),
        bpm=_bpm(track),
        limit=limit,
    )


def resolve_label(atlas: GenreAtlas, value: str) -> list[str]:
    """Atlas genre ids a Genre-field value stands for (via tag or genre name), best first."""
    res = atlas.suggest(genre=value, limit=10)
    return [
        c["id"]
        for c in res["candidates"]
        if any(r["field"] == "genre" and r["source"] in ("tag", "genre") for r in c["reasons"])
    ]


def ancestors(atlas: GenreAtlas, gid: str) -> list[str]:
    out = []
    seen = {gid}
    cur = (atlas.genres.get(gid) or {}).get("parent")
    while cur and cur in atlas.genres and cur not in seen:
        out.append(cur)
        seen.add(cur)
        cur = atlas.genres[cur].get("parent")
    return out


def level1(atlas: GenreAtlas, gid: str) -> str:
    """The level-1 genre above gid (e.g. hard-bounce -> techno), or gid itself."""
    chain = [gid, *ancestors(atlas, gid)]
    for g in chain:
        if (atlas.genres.get(g) or {}).get("level") == 1:
            return g
    return chain[-1]


def same_branch(atlas: GenreAtlas, a: str, b: str) -> bool:
    return a == b or a in ancestors(atlas, b) or b in ancestors(atlas, a)


def evidence_sources(result: dict[str, Any]) -> set[str]:
    return {r["source"] for c in result["candidates"] for r in c["reasons"]} - {"bpm"}


# --------------------------------------------------------------------------- genre field


def genre_vocabulary(tracks: list[dict[str, Any]], atlas: GenreAtlas) -> dict[str, Any]:
    by_value: dict[str, list[float]] = defaultdict(list)
    empty = 0
    for t in tracks:
        v = _text(t.get("Genre"))
        if not v:
            empty += 1
            continue
        by_value[v].append(_bpm(t) or 0.0)
    values = []
    for v, bpms in sorted(by_value.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        real = [b for b in bpms if b]
        values.append(
            {
                "value": v,
                "tracks": len(bpms),
                "bpm_median": round(statistics.median(real), 1) if real else None,
                "resolves_to": resolve_label(atlas, v),
            }
        )
    clusters: dict[str, list[str]] = defaultdict(list)
    for v in by_value:
        clusters[normalize_key(v)].append(v)
    variants: list[dict[str, Any]] = [
        {"key": k, "spellings": sorted(vs), "tracks": sum(len(by_value[x]) for x in vs)}
        for k, vs in clusters.items()
        if len(vs) > 1
    ]
    variants.sort(key=lambda x: -x["tracks"])
    return {
        "tracks_without_genre": empty,
        "distinct_values": len(by_value),
        "values": values,
        "spelling_variants": variants,
        "unresolved_values": [x for x in values if not x["resolves_to"]],
    }


# --------------------------------------------------------------------------- coverage


def coverage(
    tracks: list[dict[str, Any]], atlas: GenreAtlas
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results = [suggest_for(atlas, t) for t in tracks]
    n = len(tracks) or 1
    kinds: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    top1: Counter[str] = Counter()
    top1_l1: Counter[str] = Counter()
    top1_family: Counter[str] = Counter()
    anywhere: Counter[str] = Counter()
    conf: Counter[str] = Counter()
    for res in results:
        cands = res["candidates"]
        if not cands:
            kinds["none"] += 1
            continue
        kinds["bpm_only" if res["bpm_only"] else "metadata"] += 1
        for s in evidence_sources(res):
            sources[s] += 1
        g0 = cands[0]
        top1[g0["id"]] += 1
        top1_l1[level1(atlas, g0["id"])] += 1
        top1_family[g0.get("family") or "?"] += 1
        for c in cands:
            anywhere[c["id"]] += 1
        for floor, label in CONFIDENCE_BUCKETS:
            if g0["confidence"] >= floor:
                conf[label] += 1
                break

    electronic = sorted(gid for gid, g in atlas.genres.items() if g.get("family") == "electronic")
    tree = [
        {
            "id": gid,
            "name": atlas.genres[gid].get("name"),
            "level1": level1(atlas, gid),
            "top1": top1.get(gid, 0),
            "anywhere": anywhere.get(gid, 0),
        }
        for gid in electronic
    ]
    report = {
        "tracks": len(tracks),
        "kinds": {k: {"tracks": v, "pct": round(100 * v / n, 1)} for k, v in kinds.items()},
        "evidence_sources": dict(sources.most_common()),
        "top1": top1.most_common(),
        "top1_level1": top1_l1.most_common(),
        "top1_family": top1_family.most_common(),
        "top1_confidence": [(label, conf.get(label, 0)) for _f, label in CONFIDENCE_BUCKETS],
        "electronic_tree": tree,
        "electronic_never_suggested": [x["id"] for x in tree if x["anywhere"] == 0],
    }
    return report, results


# --------------------------------------------------------------------------- agreement


def agreement(tracks: list[dict[str, Any]], atlas: GenreAtlas) -> dict[str, Any]:
    """Leave-the-genre-field-out: can the other evidence reproduce the user's Genre label?

    Reference = atlas ids the track's Genre value resolves to. Variant A predicts from title,
    artist, comment, label and BPM; variant B also drops the comment (MyTag blocks in comments
    repeat the user's labels, so A is not fully independent).
    """
    ref_cache: dict[str, list[str]] = {}
    totals: dict[str, Counter[str]] = {v: Counter() for v in ("A", "B")}
    per_value: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: {"A": Counter(), "B": Counter()}
    )
    for t in tracks:
        value = _text(t.get("Genre"))
        if not value:
            continue
        if value not in ref_cache:
            ref_cache[value] = resolve_label(atlas, value)
        ref = ref_cache[value]
        if not ref:
            continue
        for variant, use_comment in (("A", True), ("B", False)):
            res = suggest_for(atlas, t, use_genre=False, use_comment=use_comment, limit=3)
            cands = [c["id"] for c in res["candidates"]]
            c = totals[variant]
            pv = per_value[value][variant]
            for counter in (c, pv):
                counter["labelled"] += 1
                if not cands:
                    counter["no_prediction"] += 1
                    continue
                counter["predicted"] += 1
                if res["bpm_only"]:
                    counter["bpm_only"] += 1
                if cands[0] in ref:
                    counter["hit1"] += 1
                if any(x in ref for x in cands[:3]):
                    counter["hit3"] += 1
                if any(same_branch(atlas, cands[0], r) for r in ref):
                    counter["branch1"] += 1

    def rates(c: Counter[str]) -> dict[str, Any]:
        p = c["predicted"] or 1
        return {
            "labelled": c["labelled"],
            "predicted": c["predicted"],
            "bpm_only": c["bpm_only"],
            "hit1_pct": round(100 * c["hit1"] / p, 1),
            "hit3_pct": round(100 * c["hit3"] / p, 1),
            "same_branch1_pct": round(100 * c["branch1"] / p, 1),
        }

    values = sorted(per_value.items(), key=lambda kv: -kv[1]["A"]["labelled"])
    return {
        "A_without_genre": rates(totals["A"]),
        "B_without_genre_and_comment": rates(totals["B"]),
        "per_value": [
            {
                "value": v,
                "resolves_to": ref_cache[v][:3],
                "A": rates(d["A"]),
                "B": rates(d["B"]),
            }
            for v, d in values
        ],
    }


# --------------------------------------------------------------------------- gaps


def gaps(
    tracks: list[dict[str, Any]], atlas: GenreAtlas, results: list[dict[str, Any]], top: int
) -> dict[str, Any]:
    none_reasons: Counter[str] = Counter()
    uploaders: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    for t, res in zip(tracks, results, strict=True):
        if not res["candidates"]:
            has_text = any(_text(t.get(k)) for k in ("Genre", "Comment", "Label"))
            none_reasons["no BPM" if not _bpm(t) else "BPM outside all level-1 windows"] += 1
            if not has_text:
                none_reasons["no genre/comment/label text"] += 1
        scene_hit = bool(res["matched"]["scenes"])
        up = soundcloud_permalink(_text(t.get("Comment")))
        if up and not scene_hit:
            uploaders[up] += 1
        label = _text(t.get("Label"))
        if label and not scene_hit:
            labels[label] += 1
    return {
        "no_candidate_reasons": dict(none_reasons.most_common()),
        "unmatched_soundcloud_uploaders": uploaders.most_common(top),
        "unmatched_soundcloud_uploaders_total": len(uploaders),
        "unmatched_labels": labels.most_common(top),
        "unmatched_labels_total": len(labels),
    }


# --------------------------------------------------------------------------- output


def write_csv(
    path: Path, tracks: list[dict[str, Any]], results: list[dict[str, Any]], atlas: GenreAtlas
) -> None:
    cols = [
        "ID",
        "Artist",
        "Title",
        "Genre",
        "MyTags",
        "BPM",
        "Key",
        "Rating",
        "Label",
        "Source",
        "Format",
        "Bitrate",
        "Atlas1",
        "Atlas1Conf",
        "Atlas1Level1",
        "Atlas2",
        "Atlas3",
        "Evidence",
        "SoundCloudUploader",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:  # BOM: Excel opens UTF-8
        w = csv.writer(fh, delimiter=";")
        w.writerow(cols)
        for t, res in zip(tracks, results, strict=True):
            d = derived(t)
            c = res["candidates"]
            w.writerow(
                [
                    t.get("ID"),
                    t.get("Artist"),
                    t.get("Title"),
                    t.get("Genre"),
                    ", ".join(d["mytags"]),
                    _bpm(t) or "",
                    t.get("Key"),
                    t.get("Rating"),
                    t.get("Label"),
                    d["source"],
                    d["format"],
                    t.get("Bitrate"),
                    c[0]["name"] if c else "",
                    c[0]["confidence"] if c else "",
                    (atlas.genres.get(level1(atlas, c[0]["id"])) or {}).get("name") if c else "",
                    c[1]["name"] if len(c) > 1 else "",
                    c[2]["name"] if len(c) > 2 else "",
                    "bpm-only" if res["bpm_only"] else ",".join(sorted(evidence_sources(res))),
                    d["soundcloud_uploader"] or "",
                ]
            )


def _table(headers: list[str], rows: Iterable[Iterable[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join("" if x is None else str(x) for x in r) + " |")
    return out


def render_md(rep: dict[str, Any], atlas: GenreAtlas, top: int) -> str:
    name: dict[str, str] = {gid: str(g.get("name") or gid) for gid, g in atlas.genres.items()}
    cov, gv, ag, gp, dv = (
        rep["coverage"],
        rep["genre_field"],
        rep["agreement"],
        rep["gaps"],
        rep["derived"],
    )
    L: list[str] = [
        "# Library analysis",
        "",
        f"{rep['tracks']} tracks. Atlas {rep['atlas']['counts']} "
        f"(commit {(rep['atlas']['source'] or {}).get('commit', '?')[:10]}). "
        f"Generated {rep['generated']}.",
        "",
        "## 1. Fields",
        "",
    ]
    L += _table(
        ["Field", "Filled", "%", "Distinct", "Min", "Median", "Max"],
        (
            [
                f["field"],
                f["filled"],
                f["pct"],
                f.get("distinct", ""),
                f.get("min", ""),
                f.get("median", ""),
                f.get("max", ""),
            ]
            for f in rep["fields"]
        ),
    )
    L += ["", "Derived from path and MyTag:", ""]
    L += _table(["Source", "Tracks"], dv["source"])
    L += [""]
    L += _table(["Format", "Tracks"], dv["format"])
    L += [
        "",
        f"MyTags: {dv['tracks_with_mytags']} tracks tagged, {len(dv['mytags'])} distinct tags. "
        f"SoundCloud URL in comment: {dv['tracks_with_soundcloud_url']} tracks from "
        f"{dv['soundcloud_uploaders']} uploaders.",
        "",
    ]
    L += _table(["MyTag", "Tracks"], dv["mytags"][:top])

    L += [
        "",
        "## 2. Genre field",
        "",
        f"{gv['distinct_values']} distinct values; {gv['tracks_without_genre']} tracks without "
        "a genre.",
        "",
    ]
    L += _table(
        ["Value", "Tracks", "BPM median", "Atlas reads it as"],
        (
            [
                v["value"],
                v["tracks"],
                v["bpm_median"],
                ", ".join(name.get(x, x) for x in v["resolves_to"][:4]) or "**nothing**",
            ]
            for v in gv["values"][:top]
        ),
    )
    if gv["spelling_variants"]:
        L += ["", "Same genre, different spellings:", ""]
        L += _table(
            ["Spellings", "Tracks"],
            ([" / ".join(x["spellings"]), x["tracks"]] for x in gv["spelling_variants"]),
        )

    k = cov["kinds"]
    L += [
        "",
        "## 3. Atlas coverage",
        "",
    ]
    L += _table(
        ["Result", "Tracks", "%"],
        (
            [label, k.get(key, {}).get("tracks", 0), k.get(key, {}).get("pct", 0.0)]
            for key, label in (
                ("metadata", "Candidate from metadata"),
                ("bpm_only", "Candidate from tempo only"),
                ("none", "No candidate"),
            )
        ),
    )
    L += ["", "Evidence used (tracks):", ""]
    L += _table(["Source", "Tracks"], cov["evidence_sources"].items())
    L += ["", "Top candidate by main genre:", ""]
    L += _table(["Main genre", "Tracks"], ([name.get(g, g), n] for g, n in cov["top1_level1"]))
    L += ["", "Top candidate, most frequent genres:", ""]
    L += _table(["Genre", "Tracks"], ([name.get(g, g), n] for g, n in cov["top1"][:top]))
    L += ["", "Confidence of the top candidate:", ""]
    L += _table(["Confidence", "Tracks"], cov["top1_confidence"])
    techno = [x for x in cov["electronic_tree"] if x["level1"] == "techno"]
    L += ["", "Techno tree (top candidate / in top 5):", ""]
    L += _table(
        ["Genre", "Top 1", "In top 5"],
        (
            [x["name"], x["top1"], x["anywhere"]]
            for x in sorted(techno, key=lambda x: (-x["top1"], -x["anywhere"], x["id"]))
        ),
    )
    never = [name.get(g, g) for g in cov["electronic_never_suggested"]]
    L += [
        "",
        f"Electronic atlas genres never suggested ({len(never)}): {', '.join(never)}.",
        "",
        "## 4. Agreement with your Genre labels",
        "",
        "Hide the Genre field, predict from the rest, check whether the prediction is one of the "
        "genres your label stands for. A = title, artist, comment, label, BPM. B = without the "
        "comment too. Same branch = top candidate is the labelled genre, its parent or a child.",
        "",
    ]
    L += _table(
        ["Variant", "Labelled", "Predicted", "Tempo only", "Hit@1 %", "Hit@3 %", "Same branch %"],
        (
            [
                label,
                r["labelled"],
                r["predicted"],
                r["bpm_only"],
                r["hit1_pct"],
                r["hit3_pct"],
                r["same_branch1_pct"],
            ]
            for label, r in (
                ("A", ag["A_without_genre"]),
                ("B", ag["B_without_genre_and_comment"]),
            )
        ),
    )
    L += ["", "Per Genre value (variant A):", ""]
    L += _table(
        ["Value", "Atlas reads it as", "Tracks", "Hit@1 %", "Hit@3 %", "Same branch %"],
        (
            [
                v["value"],
                ", ".join(name.get(x, x) for x in v["resolves_to"]),
                v["A"]["labelled"],
                v["A"]["hit1_pct"],
                v["A"]["hit3_pct"],
                v["A"]["same_branch1_pct"],
            ]
            for v in ag["per_value"][:top]
        ),
    )
    L += [
        "",
        "## 5. Gaps",
        "",
    ]
    L += _table(["Why no candidate", "Tracks"], gp["no_candidate_reasons"].items())
    L += [
        "",
        f"SoundCloud uploaders without a scene note: {gp['unmatched_soundcloud_uploaders_total']}"
        " (most tracks first):",
        "",
    ]
    L += _table(["Uploader", "Tracks"], gp["unmatched_soundcloud_uploaders"])
    L += ["", f"Labels without a scene note: {gp['unmatched_labels_total']}:", ""]
    L += _table(["Label", "Tracks"], gp["unmatched_labels"])

    ac = rep.get("analysis_cache")
    if ac:
        L += [
            "",
            "## 6. LMS analysis features",
            "",
            f"LMS-only features (loudness, mood, brightness, phrases, stereo, confidences) live in "
            f"the analysis cache `{ac['cache_dir']}`, keyed by file path. "
            f"{ac['with_valid_entry']} of {ac['local_tracks']} local tracks have a valid entry "
            f"({ac['pct']} %); the cache holds {ac['cache_entries']} entries in total.",
        ]
        if ac["with_valid_entry"]:
            L += ["", "Mood of the covered tracks:", ""]
            L += _table(["Mood", "Tracks"], ac["mood"])
            L += [
                "",
                f"LUFS median {ac['lufs_median']}, key confidence median "
                f"{ac['key_confidence_median']}.",
            ]
    return "\n".join(L) + "\n"


def analysis_cache_report(
    tracks: list[dict[str, Any]], cache_dir: Path | None = None
) -> dict[str, Any] | None:
    """Read-only look at the LMS analysis cache: which library files already have features."""
    from app.analysis_cache import AnalysisCache

    cache_dir = cache_dir or Path.home() / ".cache" / "rb_editor_pro" / "analysis_cache"
    if not (cache_dir / "index.json").is_file():
        return None
    cache = AnalysisCache(str(cache_dir))  # get() only stats files and reads gz entries
    local = [t for t in tracks if source_of(t) == "local"]
    moods: Counter[str] = Counter()
    lufs: list[float] = []
    key_conf: list[float] = []
    hits = 0
    for t in local:
        res = cache.get(str(t.get("path")))
        if not res:
            continue
        hits += 1
        moods[str((res.get("mood") or {}).get("mood") or "?")] += 1
        if isinstance(res.get("lufs"), (int, float)):
            lufs.append(float(res["lufs"]))
        if isinstance(res.get("key_confidence"), (int, float)):
            key_conf.append(float(res["key_confidence"]))
    return {
        "cache_dir": str(cache_dir),
        "cache_entries": len(cache._index),
        "local_tracks": len(local),
        "with_valid_entry": hits,
        "pct": round(100 * hits / (len(local) or 1), 1),
        "mood": moods.most_common(),
        "lufs_median": round(statistics.median(lufs), 1) if lufs else None,
        "key_confidence_median": round(statistics.median(key_conf), 2) if key_conf else None,
    }


def analyse(
    tracks: list[dict[str, Any]],
    atlas: GenreAtlas,
    top: int = 30,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    cov, results = coverage(tracks, atlas)
    return {
        "analysis_cache": analysis_cache_report(tracks, cache_dir),
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "tracks": len(tracks),
        "atlas": atlas.info(),
        "fields": field_report(tracks),
        "derived": derived_report(tracks),
        "genre_field": genre_vocabulary(tracks, atlas),
        "coverage": cov,
        "agreement": agreement(tracks, atlas),
        "gaps": gaps(tracks, atlas, results, top),
        "_results": results,
    }


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--api", default=DEFAULT_API, help="backend base URL (read-only GET)")
    ap.add_argument("--input", type=Path, help="saved JSON of /api/library/tracks instead")
    ap.add_argument("--save-input", type=Path, help="also save the fetched track list here")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--top", type=int, default=30, help="rows per ranked table")
    args = ap.parse_args(argv)

    if args.input:
        tracks = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        try:
            tracks = fetch_tracks(args.api)
        except (OSError, ValueError) as e:
            logger.error(
                "cannot read tracks from %s (%s); start the backend or use --input", args.api, e
            )
            return 2
        if args.save_input:
            args.save_input.write_text(json.dumps(tracks, ensure_ascii=False), encoding="utf-8")

    atlas = GenreAtlas.load()
    start = time.monotonic()
    rep = analyse(tracks, atlas, args.top)
    results = rep.pop("_results")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (args.out / "report.md").write_text(render_md(rep, atlas, args.top), encoding="utf-8")
    write_csv(args.out / "tracks.csv", tracks, results, atlas)
    k = rep["coverage"]["kinds"]
    logger.info(
        "%d tracks in %.1fs: metadata %s %%, tempo only %s %%, none %s %% -> %s",
        len(tracks),
        time.monotonic() - start,
        k.get("metadata", {}).get("pct", 0),
        k.get("bpm_only", {}).get("pct", 0),
        k.get("none", {}).get("pct", 0),
        args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
