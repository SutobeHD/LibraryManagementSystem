#!/usr/bin/env python3
"""
Feature registry plus a live overlay of which branch or worktree touches which feature.

One registry of everything the app has, builds and plans, and the git state on
top of it: who is working on what right now, and where that work overlaps.

Registry: docs/features/*.toml (one file per top-level area, `[[feature]]`
records). Overlay: every branch not merged into the base branch and every
worktree's uncommitted files, mapped onto features via their `paths` globs.

Usage:
    python scripts/feature_map.py --brief              # short digest (SessionStart hook)
    python scripts/feature_map.py --who <id|path|text> # before touching X: owner, deps, active work
    python scripts/feature_map.py --active             # every open construction site + overlaps
    python scripts/feature_map.py --list [--status S] [--area A]
    python scripts/feature_map.py --check              # validate registry (CI) — exit 1 on errors
    python scripts/feature_map.py --coverage           # source files no feature owns
    python scripts/feature_map.py --html [--open]      # interactive mindmap -> tmp/feature-map.html
    python scripts/feature_map.py --json               # dump the full model

Design:
- Stdlib only (tomllib, Python 3.11+). Never imports the app.
- Registry status is authoritative; the git overlay only annotates it.
- Stacked branches: a commit is attributed to the most established branch that
  contains it (open PR first, then fewest commits ahead), so a branch forked
  from PR #58 shows only its own work, not all of #58.
- Per-branch commit/file lists are cached in the git common dir, keyed by tip
  sha — repeat runs only re-read refs and worktree status.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parent.parent
FEATURE_DIR = REPO / "docs" / "features"
META_FILE = FEATURE_DIR / "_meta.toml"
TEMPLATE = REPO / "scripts" / "feature_map_template.html"
DEFAULT_HTML = REPO / "tmp" / "feature-map.html"
RESEARCH_DIR = REPO / "docs" / "research"

STATUSES: dict[str, tuple[str, str]] = {
    "shipped": ("Vorhanden", "auf main, nutzbar"),
    "partial": ("Teilweise", "auf main, aber mit Lücken oder bekannten Bugs"),
    "unmerged": ("Fertig auf Branch", "Code existiert, noch nicht in main"),
    "in_progress": ("In Bau", "wird gerade gebaut"),
    "planned": ("Geplant", "beschlossen / freigegeben, noch nicht begonnen"),
    "research": ("Recherche", "Research-Doc in Arbeit"),
    "idea": ("Idee", "nur Backlog, nichts entschieden"),
    "dropped": ("Verworfen", "bewusst nicht machen, Grund in notes"),
}
# Statuses whose `paths` must exist in the working tree (validated by --check).
LIVE_STATUSES = {"shipped", "partial"}

# Research-doc filename prefix -> registry statuses consistent with it.
RESEARCH_EXPECT: dict[str, set[str]] = {
    "idea": {"research", "idea"},
    "drafting": {"research"},
    "exploring": {"research"},
    "evaluated": {"research", "partial", "shipped", "unmerged"},
    "draftplan": {"research"},
    "review": {"research"},
    "approvalgate": {"research"},
    "rework": {"research"},
    "parked": {"research", "idea"},
    "accepted": {"planned", "in_progress", "partial", "unmerged"},
    "inprogress": {"in_progress", "partial", "unmerged", "shipped"},
    "blocked": {"in_progress", "planned", "partial"},
    "implemented": {"shipped", "partial"},
    "superseded": {"dropped", "shipped"},
    "abandoned": {"dropped"},
}

FEATURE_KEYS = {
    "id",
    "name",
    "group",
    "status",
    "desc",
    "paths",
    "routes",
    "branch",
    "pr",
    "research",
    "depends_on",
    "related",
    "parent",
    "todo",
    "notes",
}

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESEARCH_FILE_RE = re.compile(r"^([a-z]+)_(.+?)(?:_\d{4}-\d{2}-\d{2})?\.md$")


# ───────────────────────────────────────────────────────────────────────────
# Model
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class Feature:
    id: str
    name: str
    area: str
    group: str
    status: str
    desc: str = ""
    paths: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    branch: str = ""
    pr: int | None = None
    research: str = ""
    depends_on: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    parent: str = ""
    todo: list[str] = field(default_factory=list)
    notes: str = ""
    source: str = ""
    # derived
    research_state: str = ""
    research_path: str = ""
    dependents: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    shares: list[str] = field(default_factory=list)
    activity: list[dict] = field(default_factory=list)


@dataclass
class Area:
    id: str
    name: str
    desc: str
    order: int
    source: str
    groups: list[str] = field(default_factory=list)


@dataclass
class Registry:
    meta: dict
    areas: list[Area]
    features: dict[str, Feature]
    errors: list[str]
    warnings: list[str]


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]  # type: ignore[union-attr]


def load_registry() -> Registry:
    errors: list[str] = []
    warnings: list[str] = []
    meta: dict = {}
    if META_FILE.exists():
        meta = tomllib.loads(META_FILE.read_text(encoding="utf-8"))
    areas: list[Area] = []
    features: dict[str, Feature] = {}

    for path in sorted(FEATURE_DIR.glob("*.toml")):
        if path.name.startswith("_"):
            continue
        rel = path.relative_to(REPO).as_posix()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            errors.append(f"{rel}: TOML parse error: {e}")
            continue
        head = data.get("area", {})
        area_id = head.get("id") or path.stem
        area = Area(
            id=area_id,
            name=head.get("name", area_id),
            desc=head.get("desc", ""),
            order=int(head.get("order", 99)),
            source=rel,
        )
        areas.append(area)
        for i, raw in enumerate(data.get("feature", [])):
            where = f"{rel} feature #{i + 1}"
            unknown = set(raw) - FEATURE_KEYS
            if unknown:
                errors.append(f"{where}: unknown keys {sorted(unknown)}")
            fid = raw.get("id", "")
            if not fid or not ID_RE.match(fid):
                errors.append(f"{where}: id {fid!r} must be kebab-case")
                continue
            if fid in features:
                errors.append(f"{where}: duplicate id {fid!r} (first in {features[fid].source})")
                continue
            status = raw.get("status", "")
            if status not in STATUSES:
                errors.append(f"{rel} {fid}: status {status!r} not in {list(STATUSES)}")
            for key in ("name", "group"):
                if not raw.get(key):
                    errors.append(f"{rel} {fid}: missing {key!r}")
            if status == "dropped" and not raw.get("notes"):
                warnings.append(f"{rel} {fid}: dropped without a reason in notes")
            pr = raw.get("pr")
            feat = Feature(
                id=fid,
                name=raw.get("name", fid),
                area=area_id,
                group=raw.get("group", "Sonstiges"),
                status=status,
                desc=raw.get("desc", ""),
                paths=_as_list(raw.get("paths")),
                routes=_as_list(raw.get("routes")),
                branch=raw.get("branch", ""),
                pr=int(pr) if pr not in (None, "") else None,
                research=raw.get("research", ""),
                depends_on=_as_list(raw.get("depends_on")),
                related=_as_list(raw.get("related")),
                parent=raw.get("parent", ""),
                todo=_as_list(raw.get("todo")),
                notes=raw.get("notes", ""),
                source=rel,
            )
            features[fid] = feat
            if feat.group not in area.groups:
                area.groups.append(feat.group)

    areas.sort(key=lambda a: (a.order, a.name))
    seen_area: set[str] = set()
    for a in areas:
        if a.id in seen_area:
            errors.append(f"{a.source}: duplicate area id {a.id!r}")
        seen_area.add(a.id)

    reg = Registry(meta=meta, areas=areas, features=features, errors=errors, warnings=warnings)
    _link(reg)
    return reg


def _research_index() -> dict[str, tuple[str, str]]:
    """slug -> (state, repo-relative path) for every research doc on disk."""
    out: dict[str, tuple[str, str]] = {}
    for sub in ("research", "implement", "archived"):
        for p in sorted((RESEARCH_DIR / sub).glob("*.md")):
            m = RESEARCH_FILE_RE.match(p.name)
            if m:
                out[m.group(2)] = (m.group(1), p.relative_to(REPO).as_posix())
    return out


def _link(reg: Registry) -> None:
    feats = reg.features
    research = _research_index()
    for f in feats.values():
        for key in ("depends_on", "related"):
            for target in getattr(f, key):
                if target not in feats:
                    reg.errors.append(f"{f.source} {f.id}: {key} -> unknown id {target!r}")
                elif target == f.id:
                    reg.errors.append(f"{f.source} {f.id}: {key} points at itself")
        if f.parent:
            if f.parent not in feats:
                reg.errors.append(f"{f.source} {f.id}: parent -> unknown id {f.parent!r}")
            else:
                feats[f.parent].children.append(f.id)
        if f.research:
            hit = research.get(f.research)
            if hit is None:
                # Docs that live only on an unmerged branch are fine for non-live work.
                if f.status in LIVE_STATUSES:
                    reg.warnings.append(
                        f"{f.source} {f.id}: research slug {f.research!r} not found on disk"
                    )
            else:
                f.research_state, f.research_path = hit
                ok = RESEARCH_EXPECT.get(f.research_state)
                if ok and f.status not in ok:
                    reg.warnings.append(
                        f"{f.source} {f.id}: status {f.status!r} but research doc is "
                        f"{f.research_state}_ (expected one of {sorted(ok)})"
                    )
    for f in feats.values():
        for target in f.depends_on:
            if target in feats:
                feats[target].dependents.append(f.id)
    # Cycles in parent chains break the mindmap tree.
    for f in feats.values():
        seen = {f.id}
        cur = f.parent
        while cur and cur in feats:
            if cur in seen:
                reg.errors.append(f"{f.source} {f.id}: parent cycle via {cur!r}")
                break
            seen.add(cur)
            cur = feats[cur].parent


# ───────────────────────────────────────────────────────────────────────────
# Path matching
# ───────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=4096)
def _glob_re(pattern: str) -> re.Pattern[str]:
    pattern = pattern.strip().replace("\\", "/")
    if pattern.endswith("/"):
        pattern += "**"
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(path: str, pattern: str) -> bool:
    if not any(c in pattern for c in "*?["):
        return path.startswith(pattern) if pattern.endswith("/") else path == pattern
    return bool(_glob_re(pattern).match(path))


def _any_match(path: str, patterns: list[str]) -> bool:
    return any(path_matches(path, p) for p in patterns)


def _test_subject(path: str) -> str | None:
    """tests/test_library_format_swap.py -> 'library_format_swap'; X.test.js -> 'X'."""
    name = path.rsplit("/", 1)[-1]
    if path.startswith("tests/") and name.startswith("test_") and name.endswith(".py"):
        return name[5:-3]
    m = re.match(r"^(.+?)\.test\.(?:m?js|jsx)$", name)
    if m:
        return m.group(1)
    return None


class Mapper:
    """Maps repo file paths onto feature ids."""

    def __init__(self, reg: Registry) -> None:
        self.reg = reg
        self.hubs = _as_list(reg.meta.get("hubs"))
        self.ignore = _as_list(reg.meta.get("ignore"))
        self.research_slugs = {f.research: f.id for f in reg.features.values() if f.research}
        self.stems: dict[str, set[str]] = {}
        for f in reg.features.values():
            for p in f.paths:
                stem = p.rstrip("/").rsplit("/", 1)[-1].split(".", 1)[0]
                if stem and "*" not in stem:
                    self.stems.setdefault(stem, set()).add(f.id)

    def is_hub(self, path: str) -> bool:
        return _any_match(path, self.hubs)

    def is_ignored(self, path: str) -> bool:
        return _any_match(path, self.ignore)

    def features_for(self, path: str) -> set[str]:
        hits = {f.id for f in self.reg.features.values() if _any_match(path, f.paths)}
        if hits:
            return hits
        if path.startswith("docs/research/"):
            m = RESEARCH_FILE_RE.match(path.rsplit("/", 1)[-1])
            slug = m.group(2) if m else path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if slug in self.research_slugs:
                return {self.research_slugs[slug]}
        subject = _test_subject(path)
        if subject:
            best = ""
            for stem in self.stems:
                if subject.startswith(stem) and len(stem) > len(best):
                    best = stem
            if best:
                return set(self.stems[best])
        return set()


# ───────────────────────────────────────────────────────────────────────────
# Git overlay
# ───────────────────────────────────────────────────────────────────────────


def _git(*args: str, cwd: Path = REPO, timeout: int = 30) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr.strip()[:200]}")
    return res.stdout


def _cache_path() -> Path | None:
    try:
        common = _git("rev-parse", "--git-common-dir").strip()
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None
    p = Path(common)
    if not p.is_absolute():
        p = REPO / p
    return p / "feature-map-cache.json"


def _load_cache() -> dict:
    p = _cache_path()
    if p and p.exists():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    used = cache.pop("_used", set())
    cache["commits"] = {k: v for k, v in cache.get("commits", {}).items() if k in used}
    p = _cache_path()
    if p:
        with contextlib.suppress(OSError):
            p.write_text(json.dumps(cache), encoding="utf-8")


def _commits(base: str, tip: str, cache: dict) -> list[tuple[str, list[str]]]:
    key = f"{base}..{tip}"
    store = cache.setdefault("commits", {})
    cache.setdefault("_used", set()).add(key)
    if key in store:
        return [(c, files) for c, files in store[key]]
    out = _git("log", "--no-merges", "--name-only", "--format=@@%H", f"{base}..{tip}")
    commits: list[tuple[str, list[str]]] = []
    for line in out.splitlines():
        if line.startswith("@@"):
            commits.append((line[2:], []))
        elif line.strip() and commits:
            commits[-1][1].append(line.strip())
    store[key] = commits
    return commits


def _open_prs(cache: dict, max_age: float) -> dict[str, int]:
    """headRefName -> PR number. Cached `max_age` seconds; gh failures fall back to the cache."""
    now = datetime.now(UTC).timestamp()
    entry = cache.get("prs")
    if entry and now - entry.get("at", 0) < max_age:
        return entry.get("data", {})
    try:
        res = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,headRefName",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return entry.get("data", {}) if entry else {}
    if res.returncode != 0:
        return entry.get("data", {}) if entry else {}
    data = {pr["headRefName"]: pr["number"] for pr in json.loads(res.stdout or "[]")}
    cache["prs"] = {"at": now, "data": data}
    return data


@dataclass
class Site:
    """One construction site: an unmerged branch and/or a worktree."""

    name: str
    tip: str
    kind: str  # branch | remote | detached
    last: str = ""
    ahead: int = 0
    pr: int | None = None
    worktree: str = ""
    current: bool = False
    unpushed: int = 0
    commits: list[tuple[str, list[str]]] = field(default_factory=list)
    own_commits: int = 0
    files: set[str] = field(default_factory=set)
    dirty: set[str] = field(default_factory=set)
    features: dict[str, list[str]] = field(default_factory=dict)
    hubs: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    stale: bool = False
    parked: bool = False

    def label(self) -> str:
        bits = [self.name]
        if self.pr:
            bits.append(f"PR#{self.pr}")
        if self.current:
            bits.append("(dieser Checkout)")
        elif self.worktree:
            bits.append(f"[{self.worktree}]")
        return " ".join(bits)


def _worktrees() -> list[dict]:
    out = _git("worktree", "list", "--porcelain")
    items: list[dict] = []
    cur: dict = {}
    for line in [*out.splitlines(), ""]:
        if not line:
            if cur:
                items.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val or True
    return items


def _dirty_files(path: Path) -> set[str]:
    try:
        out = _git("status", "--porcelain=v1", "--untracked-files=normal", cwd=path, timeout=20)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return set()
    files: set[str] = set()
    for line in out.splitlines():
        p = line[3:].strip().strip('"')
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        if p:
            files.add(p.replace("\\", "/"))
    return files


def collect_sites(reg: Registry, mapper: Mapper, pr_max_age: float) -> tuple[list[Site], str]:
    base_name = reg.meta.get("base", "main")
    try:
        base = _git("rev-parse", "--verify", f"{base_name}^{{commit}}").strip()
    except RuntimeError:
        base = _git("rev-parse", "--verify", f"origin/{base_name}^{{commit}}").strip()
    skip = [
        *_as_list(reg.meta.get("skip_branches")),
        base_name,
        f"origin/{base_name}",
        "origin/HEAD",
    ]
    parked = _as_list(reg.meta.get("parked_branches"))
    stale_days = int(reg.meta.get("stale_days", 30))
    cache = _load_cache()
    prs = _open_prs(cache, pr_max_age)

    refs = _git(
        "for-each-ref",
        f"--no-merged={base}",
        "--format=%(refname)%09%(objectname)%09%(committerdate:short)",
        "refs/heads",
        "refs/remotes",
    )
    local: dict[str, tuple[str, str]] = {}
    remote: dict[str, tuple[str, str]] = {}
    for line in refs.splitlines():
        ref, tip, date = line.split("\t")
        if ref.startswith("refs/heads/"):
            local[ref[len("refs/heads/") :]] = (tip, date)
        elif ref.startswith("refs/remotes/origin/"):
            remote[ref[len("refs/remotes/origin/") :]] = (tip, date)

    def skipped(name: str) -> bool:
        return any(fnmatchcase(name, pat) for pat in skip)

    sites: dict[str, Site] = {}
    for name in sorted(set(local) | set(remote)):
        if skipped(name) or skipped(f"origin/{name}"):
            continue
        lt, rt = local.get(name), remote.get(name)
        if lt and rt and lt[0] != rt[0]:
            lc = {c for c, _ in _commits(base, lt[0], cache)}
            rc = {c for c, _ in _commits(base, rt[0], cache)}
            if rc <= lc:
                site = Site(name, lt[0], "branch", lt[1], unpushed=len(lc - rc))
            elif lc <= rc:
                site = Site(name, rt[0], "remote", rt[1])
            else:
                sites[f"origin/{name}"] = Site(f"origin/{name}", rt[0], "remote", rt[1])
                site = Site(name, lt[0], "branch", lt[1], unpushed=len(lc - rc))
        elif lt:
            site = Site(name, lt[0], "branch", lt[1], unpushed=-1 if not rt else 0)
        else:
            assert rt is not None
            site = Site(name, rt[0], "remote", rt[1])
        site.pr = prs.get(name)
        sites[site.name] = site

    try:
        current_top = Path(_git("rev-parse", "--show-toplevel").strip()).resolve()
    except RuntimeError:
        current_top = REPO
    worktrees = _worktrees()
    main_root = Path(str(worktrees[0]["worktree"])).resolve() if worktrees else REPO
    for wt in worktrees:
        if wt.get("prunable") or wt.get("bare"):
            continue
        path = Path(str(wt["worktree"]))
        if not path.exists():
            continue
        try:
            rel = path.resolve().relative_to(main_root).as_posix()
        except ValueError:
            rel = path.name
        rel = rel if rel not in ("", ".") else "Haupt-Checkout"
        branch = str(wt.get("branch", "")).removeprefix("refs/heads/")
        head = str(wt.get("HEAD", ""))
        site = sites.get(branch) if branch else None
        dirty = _dirty_files(path)
        if site is None:
            if branch == base_name or not head:
                if not dirty:
                    continue
                site = Site(f"{base_name} [{rel}]", head, "branch")
            elif branch:
                # Branch already merged into base: only uncommitted work counts.
                if not dirty:
                    continue
                site = Site(branch, head, "branch")
            else:
                ahead = _git("rev-list", "--count", f"{base}..{head}").strip()
                if ahead == "0" and not dirty:
                    continue
                site = Site(f"detached@{head[:7]}", head, "detached")
                with contextlib.suppress(RuntimeError):
                    site.last = _git("log", "-1", "--format=%cs", head).strip()
            sites[site.name] = site
        site.worktree = rel
        site.dirty = dirty
        site.current = path.resolve() == current_top

    ordered = list(sites.values())
    for s in ordered:
        s.commits = _commits(base, s.tip, cache)
        s.ahead = len(s.commits)
    # Most established first: open PR, then fewest commits ahead (a parent has
    # fewer commits than the branches stacked on it).
    ordered.sort(key=lambda s: (s.pr is None, s.ahead, s.name))
    claimed: set[str] = set()
    for s in ordered:
        own = [(c, files) for c, files in s.commits if c not in claimed]
        claimed.update(c for c, _ in s.commits)
        s.own_commits = len(own)
        for _, files in own:
            s.files.update(files)

    today = datetime.now(UTC).date()
    result: list[Site] = []
    for s in ordered:
        touched = s.files | s.dirty
        if not touched and not s.own_commits:
            continue
        for path in sorted(touched):
            if mapper.is_ignored(path):
                continue
            if mapper.is_hub(path):
                s.hubs.append(path)
                continue
            hits = mapper.features_for(path)
            if not hits:
                s.unmapped.append(path)
            for fid in hits:
                s.features.setdefault(fid, []).append(path)
        if s.last:
            with contextlib.suppress(ValueError):
                age = (today - datetime.strptime(s.last, "%Y-%m-%d").date()).days
                s.stale = age > stale_days and not s.dirty
        if any(fnmatchcase(s.name, pat) for pat in parked) and not s.dirty:
            s.parked = s.stale = True
        result.append(s)

    _save_cache(cache)
    result.sort(key=lambda s: s.last or "", reverse=True)
    result.sort(key=lambda s: (s.stale, not s.dirty))
    return result, base


def attach_activity(reg: Registry, sites: list[Site]) -> dict[str, list[str]]:
    """Fill Feature.activity; return feature id -> live site names when >= 2 (overlaps)."""
    for s in sites:
        for fid, files in s.features.items():
            reg.features[fid].activity.append(
                {
                    "site": s.name,
                    "pr": s.pr,
                    "files": len(files),
                    "dirty": len(set(files) & s.dirty),
                    "stale": s.stale,
                    "last": s.last,
                }
            )
    overlaps: dict[str, list[str]] = {}
    for f in reg.features.values():
        live = [a["site"] for a in f.activity if not a["stale"]]
        if len(live) >= 2:
            overlaps[f.id] = live
    return overlaps


def compute_shares(reg: Registry, tracked: list[str]) -> None:
    """Features whose paths resolve to the same tracked file share code."""
    owners: dict[str, set[str]] = {}
    for f in reg.features.values():
        for path in tracked:
            if _any_match(path, f.paths):
                owners.setdefault(path, set()).add(f.id)
    for ids in owners.values():
        if len(ids) < 2:
            continue
        for fid in ids:
            for other in ids:
                if other != fid and other not in reg.features[fid].shares:
                    reg.features[fid].shares.append(other)


def tracked_files() -> list[str]:
    try:
        out = _git("ls-files", "--cached", "--others", "--exclude-standard")
        return [p for p in out.splitlines() if p]
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return []


# ───────────────────────────────────────────────────────────────────────────
# Commands
# ───────────────────────────────────────────────────────────────────────────


def _counts(reg: Registry) -> dict[str, int]:
    counts = dict.fromkeys(STATUSES, 0)
    for f in reg.features.values():
        if f.status in counts:
            counts[f.status] += 1
    return counts


def _fmt_counts(reg: Registry, skip_zero: bool = True) -> str:
    return " | ".join(
        f"{n} {STATUSES[s][0]}" for s, n in _counts(reg).items() if n or not skip_zero
    )


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _site_line(s: Site, reg: Registry, limit: int = 6) -> str:
    feats = sorted(s.features, key=lambda fid: -len(s.features[fid]))
    shown = ", ".join(feats[:limit]) + (f" +{len(feats) - limit}" if len(feats) > limit else "")
    extra = []
    if s.own_commits:
        extra.append(_n(s.own_commits, "eigener Commit", "eigene Commits"))
    if s.dirty:
        extra.append(f"{len(s.dirty)} uncommitted")
    if s.unpushed > 0:
        extra.append(f"{s.unpushed} ungepusht")
    elif s.unpushed < 0:
        extra.append("nie gepusht")
    if s.last:
        extra.append(s.last)
    return f"  {s.label()} ({', '.join(extra)}) -> {shown or '(keine kartierten Features)'}"


def cmd_brief(reg: Registry, sites: list[Site], overlaps: dict[str, list[str]]) -> None:
    print(f"Feature-Map ({len(reg.features)} Features, docs/features/): {_fmt_counts(reg)}")
    live = [s for s in sites if not s.stale]
    stale = [s for s in sites if s.stale and not s.parked]
    parked = [s for s in sites if s.parked]
    if live:
        print("Aktive Baustellen (nicht in main):")
        for s in live[:12]:
            print(_site_line(s, reg, limit=5))
        if len(live) > 12:
            print(f"  ... +{len(live) - 12} weitere (--active)")
    if stale or parked:
        days = reg.meta.get("stale_days", 30)
        print(
            f"Liegengeblieben (>{days} Tage): {len(stale)} Branches, "
            f"geparkt (Backups): {len(parked)} - Details: --active"
        )
    if overlaps:
        items = [f"{fid} <- {' + '.join(names)}" for fid, names in list(overlaps.items())[:6]]
        print("Überschneidungen: " + "; ".join(items))
    if reg.errors:
        print(f"Registry-Fehler: {len(reg.errors)} (python scripts/feature_map.py --check)")
    print(
        "Regel: vor Arbeit an X -> python scripts/feature_map.py --who <id|pfad|text>; "
        "Status in docs/features/<area>.toml im selben Commit pflegen (.claude/rules/feature-map.md)."
    )


def cmd_active(reg: Registry, sites: list[Site], overlaps: dict[str, list[str]]) -> None:
    for title, group in (
        ("Aktive Baustellen", [s for s in sites if not s.stale]),
        ("Liegengeblieben", [s for s in sites if s.stale and not s.parked]),
        ("Geparkt (Backups)", [s for s in sites if s.parked]),
    ):
        if not group:
            continue
        print(f"{title}:")
        for s in group:
            print(_site_line(s, reg, limit=10))
            if s.hubs:
                print(f"      Hub-Dateien: {', '.join(s.hubs[:6])}")
            if s.unmapped:
                more = f" +{len(s.unmapped) - 5}" if len(s.unmapped) > 5 else ""
                print(f"      nicht kartiert: {', '.join(s.unmapped[:5])}{more}")
        print()
    if overlaps:
        print("Überschneidungen (Feature von >= 2 aktiven Baustellen berührt):")
        for fid, names in overlaps.items():
            print(f"  {fid}: {' + '.join(names)}")


def _feature_block(reg: Registry, f: Feature) -> None:
    area = next((a.name for a in reg.areas if a.id == f.area), f.area)
    print(f"{f.id} - {f.name}  [{STATUSES.get(f.status, (f.status,))[0]}]  {area} > {f.group}")
    if f.desc:
        print(f"  {f.desc}")
    if f.paths:
        print(f"  Dateien:  {', '.join(f.paths)}")
    if f.routes:
        print(f"  Routen:   {', '.join(f.routes)}")
    if f.branch or f.pr:
        print(f"  Branch:   {f.branch or '-'}{f'  PR#{f.pr}' if f.pr else ''}")
    if f.research:
        state = f"{f.research_state}_" if f.research_state else "nur auf Branch"
        print(f"  Research: {f.research} ({state}) {f.research_path}")
    if f.parent:
        print(f"  Teil von: {f.parent}")
    if f.children:
        print(f"  Teile:    {', '.join(f.children)}")
    if f.depends_on:
        print(f"  Braucht:  {', '.join(f.depends_on)}")
    if f.dependents:
        print(f"  Gebraucht von: {', '.join(f.dependents)}")
    if f.related:
        print(f"  Verwandt: {', '.join(f.related)}")
    if f.shares:
        print(f"  Teilt Dateien mit: {', '.join(sorted(f.shares))}")
    if f.todo:
        print("  Offen:")
        for t in f.todo:
            print(f"    - {t}")
    if f.notes:
        print(f"  Notiz:    {f.notes}")
    if f.activity:
        print("  Aktive Arbeit:")
        for a in f.activity:
            flag = " (liegengeblieben)" if a["stale"] else ""
            pr = f" PR#{a['pr']}" if a["pr"] else ""
            dirty = f", {a['dirty']} uncommitted" if a["dirty"] else ""
            print(f"    {a['site']}{pr}: {a['files']} Dateien{dirty}, {a['last']}{flag}")
        live = [a for a in f.activity if not a["stale"]]
        if len(live) >= 2:
            print("  !! Mehrere Baustellen berühren dieses Feature - vor Änderungen abstimmen.")


def cmd_who(reg: Registry, mapper: Mapper, query: str) -> int:
    q = query.strip().replace("\\", "/").removeprefix("./")
    feats = reg.features
    if q in feats:
        hits = [feats[q]]
    else:
        by_path = mapper.features_for(q) if ("/" in q or "." in q) else set()
        if not by_path and "/" in q:
            prefix = q.rstrip("/") + "/"
            by_path = {
                f.id for f in feats.values() if any(p.startswith(prefix) or p == q for p in f.paths)
            }
        if by_path:
            hits = [feats[i] for i in sorted(by_path)]
            if mapper.is_hub(q):
                print(f"{q} ist eine Hub-Datei (gehört keinem Feature allein).")
        else:
            low = q.lower()
            hits = [
                f
                for f in feats.values()
                if low in f.id or low in f.name.lower() or low in f.desc.lower()
            ]
    if not hits:
        if mapper.is_hub(q):
            print(
                f"{q} ist eine Hub-Datei (gehört keinem Feature allein) - Änderungen dort "
                "mit den aktiven Baustellen abstimmen (--active)."
            )
            return 0
        print(f"Kein Feature passt zu {query!r}. Neu? -> in docs/features/<area>.toml anlegen.")
        return 1
    if len(hits) > 4:
        print(f"{len(hits)} Treffer - genauer fragen oder id nehmen:")
        for f in hits[:40]:
            print(f"  {f.id:<40} [{STATUSES[f.status][0]}] {f.name}")
        return 0
    for f in hits:
        _feature_block(reg, f)
        print()
    return 0


def cmd_list(reg: Registry, status: str | None, area: str | None) -> None:
    for a in reg.areas:
        if area and a.id != area:
            continue
        rows = [
            f
            for f in reg.features.values()
            if f.area == a.id and (not status or f.status == status)
        ]
        if not rows:
            continue
        print(f"## {a.name} ({a.id})")
        for g in a.groups:
            grows = [f for f in rows if f.group == g]
            if not grows:
                continue
            print(f"  {g}")
            for f in grows:
                mark = " *" if f.activity else ""
                print(f"    {f.id:<42} {STATUSES[f.status][0]:<18} {f.name}{mark}")
        print()


def cmd_check(reg: Registry, tracked: list[str]) -> int:
    errors = list(reg.errors)
    warnings = list(reg.warnings)
    tracked_set = set(tracked)
    for f in reg.features.values():
        for p in f.paths:
            if f.status in LIVE_STATUSES and not any(path_matches(t, p) for t in tracked_set):
                errors.append(
                    f"{f.source} {f.id}: path {p!r} matches no tracked file (status {f.status})"
                )
    for w in warnings:
        print(f"warn: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(
        f"{len(reg.features)} features, {len(reg.areas)} areas, {len(errors)} errors, {len(warnings)} warnings"
    )
    return 1 if errors else 0


def cmd_coverage(reg: Registry, mapper: Mapper, tracked: list[str]) -> None:
    globs = _as_list(reg.meta.get("coverage"))
    pool = [p for p in tracked if _any_match(p, globs) and not mapper.is_hub(p)]
    missing = [p for p in pool if not mapper.features_for(p)]
    pct = 100 * (len(pool) - len(missing)) / max(len(pool), 1)
    print(
        f"Abdeckung: {len(pool) - len(missing)}/{len(pool)} Quelldateien einem Feature zugeordnet ({pct:.0f} %)"
    )
    by_dir: dict[str, list[str]] = {}
    for p in missing:
        by_dir.setdefault(p.rsplit("/", 1)[0], []).append(p.rsplit("/", 1)[-1])
    for d in sorted(by_dir):
        print(f"  {d}/: {', '.join(sorted(by_dir[d]))}")


def build_model(
    reg: Registry, sites: list[Site], overlaps: dict[str, list[str]], base: str
) -> dict:
    head = ""
    with contextlib.suppress(RuntimeError):
        head = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    return {
        "title": reg.meta.get("title", "Feature Map"),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "base": reg.meta.get("base", "main"),
        "base_sha": base[:9],
        "head": head,
        "statuses": [{"id": k, "label": v[0], "hint": v[1]} for k, v in STATUSES.items()],
        "areas": [
            {"id": a.id, "name": a.name, "desc": a.desc, "groups": a.groups, "source": a.source}
            for a in reg.areas
        ],
        "features": {
            f.id: {
                k: v
                for k, v in f.__dict__.items()
                if v not in ("", None, []) or k in ("id", "name", "status", "area", "group")
            }
            for f in reg.features.values()
        },
        "sites": [
            {
                "name": s.name,
                "label": s.label(),
                "kind": s.kind,
                "pr": s.pr,
                "worktree": s.worktree,
                "current": s.current,
                "last": s.last,
                "ahead": s.ahead,
                "own": s.own_commits,
                "unpushed": s.unpushed,
                "dirty": sorted(s.dirty),
                "stale": s.stale,
                "parked": s.parked,
                "features": {k: v for k, v in sorted(s.features.items())},
                "hubs": s.hubs,
                "unmapped": s.unmapped,
            }
            for s in sites
        ],
        "overlaps": overlaps,
        "errors": reg.errors,
        "warnings": reg.warnings,
    }


def cmd_html(model: dict, out: Path, open_it: bool) -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("/*__FEATURE_MAP_DATA__*/null", payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Mindmap: {out}")
    if open_it:
        webbrowser.open(out.resolve().as_uri())


def main(argv: list[str] | None = None) -> int:
    with contextlib.suppress(AttributeError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--brief", action="store_true", help="short digest for the SessionStart hook")
    mode.add_argument("--who", metavar="QUERY", help="feature id, file path or free text")
    mode.add_argument("--active", action="store_true", help="all construction sites + overlaps")
    mode.add_argument("--list", action="store_true", help="registry as text tree")
    mode.add_argument("--check", action="store_true", help="validate registry, exit 1 on errors")
    mode.add_argument("--coverage", action="store_true", help="source files no feature owns")
    mode.add_argument(
        "--html", nargs="?", const=str(DEFAULT_HTML), metavar="OUT", help="write mindmap"
    )
    mode.add_argument("--json", action="store_true", help="dump model as JSON")
    ap.add_argument(
        "--open", action="store_true", help="open the mindmap in the browser (with --html)"
    )
    ap.add_argument("--status", choices=list(STATUSES), help="filter for --list")
    ap.add_argument("--area", help="filter for --list")
    ap.add_argument("--no-git", action="store_true", help="skip the git overlay")
    ap.add_argument(
        "--no-gh", action="store_true", help="skip the gh PR lookup (cached PRs still used)"
    )
    args = ap.parse_args(argv)

    if args.brief:
        # Runs as a SessionStart hook: never fail the session, never print a traceback.
        try:
            reg = load_registry()
            mapper = Mapper(reg)
            sites, _ = collect_sites(reg, mapper, pr_max_age=24 * 3600)
            overlaps = attach_activity(reg, sites)
            cmd_brief(reg, sites, overlaps)
        except Exception as e:  # hook must stay silent-safe
            print(f"Feature-Map: Overlay nicht verfügbar ({type(e).__name__}: {e})")
        return 0

    reg = load_registry()
    mapper = Mapper(reg)
    if args.check:
        return cmd_check(reg, tracked_files())
    if args.coverage:
        cmd_coverage(reg, mapper, tracked_files())
        return 0

    sites: list[Site] = []
    overlaps: dict[str, list[str]] = {}
    base = ""
    if not args.no_git:
        sites, base = collect_sites(reg, mapper, pr_max_age=float("inf") if args.no_gh else 600)
        overlaps = attach_activity(reg, sites)

    if args.who:
        compute_shares(reg, tracked_files())
        return cmd_who(reg, mapper, args.who)
    if args.active:
        cmd_active(reg, sites, overlaps)
        return 0
    if args.list:
        cmd_list(reg, args.status, args.area)
        return 0

    compute_shares(reg, tracked_files())
    model = build_model(reg, sites, overlaps, base)
    if args.json:
        print(json.dumps(model, ensure_ascii=False, indent=1))
        return 0
    cmd_html(model, Path(args.html or DEFAULT_HTML), args.open)
    if reg.errors:
        print(f"{len(reg.errors)} Registry-Fehler - python scripts/feature_map.py --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
