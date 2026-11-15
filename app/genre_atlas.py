"""Genre suggestions from the genre-atlas snapshot (read-only, explainable).

Data: ``app/data/genre_atlas.json``, a slim snapshot of the sibling ``genre-atlas`` repo written by
``scripts/sync_genre_atlas.py``. It holds sound-based genres (ids, names, aliases, parents, BPM
windows), tags (labels as platforms and scenes use them, e.g. SoundCloud "trance" or Beatport
"Techno (Peak Time / Driving)", each resolving to ordered candidate genres with an audio test) and
scenes (labels, clubs, platforms with SoundCloud permalinks and the genres they stand for).

``suggest()`` turns a track's metadata into ranked candidate genres. Every candidate carries the
reasons that produced it (scene, tag, genre name, BPM window), so the UI can show why. Nothing is
written anywhere: the user picks a suggestion and saves it through the normal track update route.

Matching uses the canonical key of the genre-normalization research (NFKC, casefold, ``&``/``+``
to ``and``, every non-alphanumeric run to one space), so "Drum & Bass", "drum n bass" and
"DRUM-AND-BASS" compare equal without storing variants.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ATLAS_FILE = Path(__file__).resolve().parent / "data" / "genre_atlas.json"

# Evidence weights. A scene (uploader / label) is the strongest prior, a genre named in the
# genre field is a direct statement, tags are labels that need resolving, titles are noisy.
W_SCENE_SOUNDCLOUD = 3.0
W_SCENE_NAME = {"label": 2.5, "artist": 2.5, "title": 1.5}
W_TAG = {"genre": 2.5, "comment": 2.0, "title": 1.5, "label": 1.5}
W_GENRE = {"genre": 3.0, "comment": 2.0, "title": 1.2}
W_BPM_ONLY = 0.5
POSITION_DECAY = 0.3  # candidate i in an ordered list gets base / (1 + 0.3 * i)

BPM_TYPICAL = 1.25
BPM_WINDOW = 1.0
BPM_OCTAVE = 0.85  # fits at half or double tempo (analysis octave errors)
BPM_OUTSIDE = 0.5

MIN_TERM_LEN = 3
_SOUNDCLOUD_RE = re.compile(r"soundcloud\.com/([A-Za-z0-9_-]+)", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")


def normalize_key(text: str | None) -> str:
    """Canonical comparison key: NFKC, casefold, '&'/'+' -> 'and', non-alphanumerics -> space."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).casefold()
    s = s.replace("&", " and ").replace("+", " and ")
    s = re.sub(r"(?<=\s)n(?=\s)", "and", f" {s} ")
    # casefold keeps letters like "ä"; strip accents only for the ASCII-alnum split below
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return _NON_ALNUM_RE.sub(" ", s).strip()


def soundcloud_permalink(*texts: str | None) -> str | None:
    """'soundcloud.com/<uploader>' from the first text containing a SoundCloud URL."""
    for t in texts:
        if t:
            m = _SOUNDCLOUD_RE.search(str(t))
            if m:
                return f"soundcloud.com/{m.group(1)}".lower()
    return None


def _contains(haystack: str, term: str) -> bool:
    return bool(term) and f" {term} " in f" {haystack} "


def _remove(haystack: str, term: str) -> str:
    return f" {haystack} ".replace(f" {term} ", " ").strip()


@dataclass
class Reason:
    source: str  # scene | tag | genre | bpm
    field: str  # soundcloud | label | artist | title | genre | comment | bpm
    ref: str | None  # scene / tag / genre id
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "field": self.field, "ref": self.ref, "text": self.text}


@dataclass
class Candidate:
    genre_id: str
    score: float = 0.0
    reasons: list[Reason] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)


class GenreAtlas:
    """In-memory index over the atlas snapshot."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.genres: dict[str, dict[str, Any]] = {g["id"]: g for g in data.get("genres", [])}
        self.tags: dict[str, dict[str, Any]] = {t["id"]: t for t in data.get("tags", [])}
        self.scenes: dict[str, dict[str, Any]] = {s["id"]: s for s in data.get("scenes", [])}
        self._genre_terms = self._terms(self.genres.values())
        self._tag_terms = self._terms(self.tags.values())
        self._scene_terms = self._terms(self.scenes.values())
        self._scene_by_sc = {
            str(s["soundcloud"]).lower(): s for s in self.scenes.values() if s.get("soundcloud")
        }

    @staticmethod
    def _terms(entries) -> list[tuple[str, str, str]]:
        """(normalized term, id), longest first so multi-word labels win over their parts."""
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str, str]] = []
        for e in entries:
            names = [e.get("name") or "", *(e.get("aliases") or [])]
            for n in names:
                key = normalize_key(n)
                if len(key) >= MIN_TERM_LEN and (key, e["id"]) not in seen:
                    seen.add((key, e["id"]))
                    out.append((key, e["id"], str(n)))
        out.sort(key=lambda x: (-len(x[0]), x[1]))
        return out

    @classmethod
    def load(cls, path: Path = ATLAS_FILE) -> GenreAtlas:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("op=genre_atlas_load path=%s err=%s", path, e)
            data = {"genres": [], "tags": [], "scenes": []}
        atlas = cls(data)
        logger.info(
            "op=genre_atlas_load genres=%d tags=%d scenes=%d commit=%s",
            len(atlas.genres),
            len(atlas.tags),
            len(atlas.scenes),
            ((data.get("source") or {}).get("commit") or "unknown")[:10],
        )
        return atlas

    # ------------------------------------------------------------------ #

    def info(self) -> dict[str, Any]:
        return {
            "schema_version": self.data.get("schema_version"),
            "source": self.data.get("source"),
            "counts": {
                "genres": len(self.genres),
                "tags": len(self.tags),
                "scenes": len(self.scenes),
            },
        }

    def suggest(
        self,
        *,
        title: str | None = None,
        artist: str | None = None,
        genre: str | None = None,
        comment: str | None = None,
        label: str | None = None,
        soundcloud: str | None = None,
        bpm: float | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Ranked candidate genres with reasons. Pure function of the inputs; never writes."""
        cands: dict[str, Candidate] = {}
        matched_scenes: dict[str, dict[str, Any]] = {}
        matched_tags: dict[str, dict[str, Any]] = {}

        def add(gid: str, weight: float, pos: int, reason: Reason, test: str | None = None) -> None:
            if gid not in self.genres:
                return  # planned id without a note in the snapshot
            c = cands.setdefault(gid, Candidate(gid))
            c.score += weight / (1 + POSITION_DECAY * pos)
            c.reasons.append(reason)
            if test and test not in c.tests:
                c.tests.append(test)

        fields = {
            "genre": normalize_key(genre),
            "comment": normalize_key(comment),
            "title": normalize_key(title),
            "label": normalize_key(label),
            "artist": normalize_key(artist),
        }

        # 1. Scene by SoundCloud uploader permalink (download comment holds the track URL).
        permalink = soundcloud_permalink(soundcloud, comment)
        if permalink and permalink in self._scene_by_sc:
            s = self._scene_by_sc[permalink]
            matched_scenes[s["id"]] = s
            for i, gid in enumerate(s.get("genres") or []):
                add(
                    gid,
                    W_SCENE_SOUNDCLOUD,
                    i,
                    Reason("scene", "soundcloud", s["id"], f"Uploader {permalink} = {s['name']}"),
                )

        # 2. Scene by name in label / artist / title.
        for fname, weight in W_SCENE_NAME.items():
            text = fields[fname]
            for term, sid, _orig in self._scene_terms:
                if sid in matched_scenes or not _contains(text, term):
                    continue
                s = self.scenes[sid]
                matched_scenes[sid] = s
                for i, gid in enumerate(s.get("genres") or []):
                    add(gid, weight, i, Reason("scene", fname, sid, f"{s['name']} in {fname}"))

        # 3. Tags; consume matched tag terms so a genre named inside a tag is not counted twice.
        # Longest term first; a matched term is removed before shorter ones are tried, so
        # "Hard Trance" does not also count as "Trance".
        for fname, weight in W_TAG.items():
            by_term: dict[str, list[tuple[str, str]]] = {}
            for term, tid, orig in self._tag_terms:
                by_term.setdefault(term, []).append((tid, orig))
            for term, owners in by_term.items():
                if not _contains(fields[fname], term):
                    continue
                share = weight / len(owners)  # one label claimed by several tags splits its weight
                for tid, orig in owners:
                    t = self.tags[tid]
                    matched_tags[tid] = t
                    for i, gid in enumerate(t.get("resolves_to") or []):
                        add(
                            gid,
                            share,
                            i,
                            Reason("tag", fname, tid, f'"{orig}" in {fname} ({t["name"]})'),
                            (t.get("resolution") or {}).get(gid),
                        )
                fields[fname] = _remove(fields[fname], term)

        # 4. Genre names / aliases (after tag terms were consumed).
        for fname, weight in W_GENRE.items():
            text = fields[fname]
            for term, gid, _orig in self._genre_terms:
                if _contains(text, term):
                    add(
                        gid,
                        weight,
                        0,
                        Reason("genre", fname, gid, f"{self.genres[gid]['name']} in {fname}"),
                    )
                    text = _remove(text, term)

        # 5. BPM-only fallback when no metadata matched at all.
        bpm_val = float(bpm) if bpm else 0.0
        if not cands and bpm_val > 0:
            for gid, g in self.genres.items():
                w = g.get("bpm") or {}
                typ = w.get("typical") or []
                if (
                    g.get("family") == "electronic"
                    and g.get("level") == 1
                    and len(typ) == 2
                    and typ[0] <= bpm_val <= typ[1]
                ):
                    add(
                        gid,
                        W_BPM_ONLY,
                        0,
                        Reason(
                            "bpm",
                            "bpm",
                            gid,
                            f"{bpm_val:.0f} BPM in typical window {typ[0]}-{typ[1]}",
                        ),
                    )

        # 6. BPM adjusts every candidate that has a window.
        if bpm_val > 0:
            for c in cands.values():
                if all(r.source == "bpm" for r in c.reasons):
                    continue  # BPM-only candidates already carry their tempo reason
                factor, text = self._bpm_factor(self.genres[c.genre_id], bpm_val)
                if factor is not None:
                    c.score *= factor
                    c.reasons.append(Reason("bpm", "bpm", c.genre_id, text))

        ranked = sorted(cands.values(), key=lambda c: (-c.score, c.genre_id))[: max(1, limit)]
        total = sum(c.score for c in ranked) or 1.0
        out: list[dict[str, Any]] = []
        for c in ranked:
            g = self.genres[c.genre_id]
            parent = self.genres.get(g.get("parent") or "")
            out.append(
                {
                    "id": c.genre_id,
                    "name": g.get("name"),
                    "aliases": g.get("aliases") or [],
                    "family": g.get("family"),
                    "parent": g.get("parent"),
                    "parent_name": parent.get("name") if parent else None,
                    "bpm": g.get("bpm"),
                    "definition": g.get("definition") or "",
                    "score": round(c.score, 3),
                    "confidence": round(c.score / total, 3),
                    "reasons": [r.as_dict() for r in c.reasons],
                    "tests": c.tests,
                }
            )
        return {
            "candidates": out,
            "matched": {
                "scenes": [
                    {"id": s["id"], "name": s["name"], "kind": s.get("kind")}
                    for s in matched_scenes.values()
                ],
                "tags": [
                    {"id": t["id"], "name": t["name"], "meaning": t.get("meaning", "")}
                    for t in matched_tags.values()
                ],
            },
            "bpm_only": bool(out) and all(r["source"] == "bpm" for c in out for r in c["reasons"]),
            "atlas": self.info(),
        }

    @staticmethod
    def _bpm_factor(genre: dict[str, Any], bpm: float) -> tuple[float | None, str]:
        w = genre.get("bpm") or {}
        lo, hi, typ = w.get("min"), w.get("max"), w.get("typical") or []
        if not lo or not hi or len(typ) != 2:
            return None, ""
        if typ[0] <= bpm <= typ[1]:
            return BPM_TYPICAL, f"{bpm:.0f} BPM in typical window {typ[0]}-{typ[1]}"
        if lo <= bpm <= hi:
            return BPM_WINDOW, f"{bpm:.0f} BPM inside {lo}-{hi}"
        for alt, word in ((bpm * 2, "double"), (bpm / 2, "half")):
            if lo <= alt <= hi:
                return BPM_OCTAVE, f"{bpm:.0f} BPM fits {lo}-{hi} at {word} tempo"
        return BPM_OUTSIDE, f"{bpm:.0f} BPM outside {lo}-{hi}"


@lru_cache(maxsize=1)
def get_atlas() -> GenreAtlas:
    """Process-wide atlas instance (the snapshot is read-only at runtime)."""
    return GenreAtlas.load()


def library_spelling(candidate: dict[str, Any], library_genres: list[str]) -> str | None:
    """The user's own spelling of a candidate genre if the library already uses it.

    An exact match on the atlas name or an alias wins, so "Hard Techno" beats "HARD TECHNO"
    when a library holds both; otherwise the first spelling with the same canonical key.
    """
    present = set(library_genres)
    for wanted in [candidate.get("name"), *(candidate.get("aliases") or [])]:
        if wanted and wanted in present:
            return str(wanted)
    keys = {normalize_key(candidate.get("name"))} | {
        normalize_key(a) for a in candidate.get("aliases") or []
    }
    keys.discard("")
    for g in library_genres:
        if normalize_key(g) in keys:
            return g
    return None
