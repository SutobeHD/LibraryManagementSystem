#!/usr/bin/env python3
"""
Auto-generate tiered code maps from the actual source tree.

Generates two files:
- docs/MAP.md       — Level 1: file path + one-line purpose
- docs/MAP_L2.md    — Level 2: L1 + public classes/functions + one-line each

Sources:
- Python: AST parse of `app/**/*.py` + `tests/**/*.py` + `scripts/**/*.py`
- Rust:   regex-based scan of `src-tauri/src/**/*.rs` (public items only)
- JS/JSX: regex-based scan of `frontend/src/**/*.{js,jsx}` (exports only)
- Other:  filename + 1-line for `.toml`, `.json`, `.md` configs and scripts

Usage:
    python scripts/regen_maps.py            # write MAP.md + MAP_L2.md
    python scripts/regen_maps.py --check    # exit 1 if files would change
    python scripts/regen_maps.py --stdout   # print to stdout, don't write

Design:
- Deterministic output (sorted, stable formatting) → safe for CI drift check.
- Module docstring → file's L1 description. First sentence only.
- Class/function docstring → L2 entry. First sentence only.
- No docstring? → fall back to source-based hint (e.g. "class Foo(BaseModel)").
- Never imports the modules — pure AST/regex parsing. Safe to run without the
  project's runtime deps installed.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ───────────────────────────────────────────────────────────────────────────
# Paths
# ───────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_L1 = REPO_ROOT / "docs" / "MAP.md"
OUT_L2 = REPO_ROOT / "docs" / "MAP_L2.md"

PYTHON_ROOTS = ["app", "tests", "scripts"]
RUST_ROOTS = ["src-tauri/src"]
JS_ROOTS = ["frontend/src"]

# Files to skip even if they live under a tracked root.
SKIP_PATTERNS = [
    r"__pycache__",
    r"node_modules",
    r"target/",
    r"\.test\.resolver",  # frontend dawReducer test resolver shims
    r"app/brute_force_",
    r"app/inspect_",
    r"app/debug_",
    r"app/diag_",
    r"app/check_",
    r"app/verify_",
    r"app/find_",
    r"app/fix_",
    r"app/calibrate_",
    r"app/final_",
    r"app/mass_verify",
    r"app/analysis_inspector\.py",
]

# ───────────────────────────────────────────────────────────────────────────
# Data shapes
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class Symbol:
    """A class or function entry."""
    name: str
    kind: str  # "class" | "func" | "method"
    summary: str  # one-line


@dataclass
class FileEntry:
    rel_path: str
    summary: str
    symbols: list[Symbol] = field(default_factory=list)


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

_SKIP_RE = re.compile("|".join(SKIP_PATTERNS))


def _skip(path: Path) -> bool:
    return bool(_SKIP_RE.search(path.as_posix()))


def _first_sentence(text: str | None) -> str:
    """First sentence of a docstring/comment, condensed to one line."""
    if not text:
        return ""
    text = text.strip()
    # Drop reST/sphinx markup lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    first = lines[0]
    # Cut at first period followed by space/EOL
    m = re.match(r"^(.*?[.!?])(\s|$)", first)
    return m.group(1) if m else first


def _truncate(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())  # collapse whitespace
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ───────────────────────────────────────────────────────────────────────────
# Python — AST extraction
# ───────────────────────────────────────────────────────────────────────────


def _parse_python(path: Path) -> FileEntry:
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return FileEntry(rel_path=rel, summary="(unreadable)")

    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as e:
        return FileEntry(rel_path=rel, summary=f"(syntax error: {e.msg})")

    module_doc = _first_sentence(ast.get_docstring(tree))

    # Fallback: first top-of-file comment line if no module docstring.
    if not module_doc:
        for line in source.splitlines()[:8]:
            s = line.strip()
            if s.startswith("#") and not s.startswith("#!"):
                module_doc = _first_sentence(s.lstrip("# ").rstrip())
                break

    symbols: list[Symbol] = []
    for node in tree.body:
        # Skip private (leading underscore) top-level items
        name = getattr(node, "name", None)
        if not name or name.startswith("_"):
            continue
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            symbols.append(
                Symbol(
                    name=f"{name}()",
                    kind="func",
                    summary=_first_sentence(ast.get_docstring(node)) or "",
                )
            )
        elif isinstance(node, ast.ClassDef):
            summary = _first_sentence(ast.get_docstring(node)) or ""
            symbols.append(Symbol(name=name, kind="class", summary=summary))
            # Also collect public methods on this class
            for sub in node.body:
                if isinstance(sub, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    if sub.name.startswith("_"):
                        continue
                    symbols.append(
                        Symbol(
                            name=f"  {name}.{sub.name}()",
                            kind="method",
                            summary=_first_sentence(ast.get_docstring(sub)) or "",
                        )
                    )

    return FileEntry(rel_path=rel, summary=module_doc, symbols=symbols)


# ───────────────────────────────────────────────────────────────────────────
# Rust — regex extraction (pub fn / pub struct / pub enum / pub trait)
# ───────────────────────────────────────────────────────────────────────────

_RUST_DOC = re.compile(r"^\s*///\s?(.*)$")
_RUST_ITEM = re.compile(
    r"^\s*pub\s+(?:async\s+)?(?:unsafe\s+)?(?:fn|struct|enum|trait|type|const|static)\s+(\w+)"
)
_RUST_MODULE_DOC = re.compile(r"^\s*//!\s?(.*)$")


def _parse_rust(path: Path) -> FileEntry:
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return FileEntry(rel_path=rel, summary="(unreadable)")

    # Module-level doc comments at top of file (//! ...)
    module_doc_lines = []
    for line in lines[:30]:
        m = _RUST_MODULE_DOC.match(line)
        if m:
            module_doc_lines.append(m.group(1))
        elif module_doc_lines:
            break
    module_doc = _first_sentence(" ".join(module_doc_lines))

    if not module_doc:
        # Fallback: first /// or // comment in first ~10 lines
        for line in lines[:10]:
            s = line.strip()
            if s.startswith("///") or (s.startswith("//") and not s.startswith("//!")):
                module_doc = _first_sentence(s.lstrip("/").strip())
                break

    symbols: list[Symbol] = []
    pending_doc: list[str] = []
    for line in lines:
        m = _RUST_DOC.match(line)
        if m:
            pending_doc.append(m.group(1))
            continue
        m = _RUST_ITEM.match(line)
        if m:
            name = m.group(1)
            # Classify by keyword
            stripped = line.strip()
            if " fn " in stripped:
                kind = "func"
                display = f"{name}()"
            elif " struct " in stripped:
                kind = "class"
                display = f"struct {name}"
            elif " enum " in stripped:
                kind = "class"
                display = f"enum {name}"
            elif " trait " in stripped:
                kind = "class"
                display = f"trait {name}"
            elif " type " in stripped:
                kind = "func"
                display = f"type {name}"
            else:
                kind = "func"
                display = name
            summary = _first_sentence(" ".join(pending_doc))
            symbols.append(Symbol(name=display, kind=kind, summary=summary))
            pending_doc = []
        elif line.strip() and not line.strip().startswith("//"):
            pending_doc = []  # docstring continuity broken

    return FileEntry(rel_path=rel, summary=module_doc, symbols=symbols)


# ───────────────────────────────────────────────────────────────────────────
# JS/JSX — regex extraction (export ... / function ...)
# ───────────────────────────────────────────────────────────────────────────

_JS_EXPORT = re.compile(
    r"^export\s+(?:default\s+)?"
    r"(?:async\s+)?"
    r"(?:function\s+(\w+)|const\s+(\w+)|class\s+(\w+))"
)
_JS_LEADING_BLOCK_COMMENT = re.compile(r"^/\*\*?\s*(.*?)\s*\*?/?\s*$")
_JS_LINE_COMMENT = re.compile(r"^//\s?(.*)$")


def _parse_js(path: Path) -> FileEntry:
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return FileEntry(rel_path=rel, summary="(unreadable)")
    lines = text.splitlines()

    # Module-level summary: first line of first /** */ block, or first // line
    module_doc = ""
    in_block = False
    block_buf: list[str] = []
    for line in lines[:30]:
        s = line.strip()
        if in_block:
            if "*/" in s:
                in_block = False
                if block_buf:
                    module_doc = _first_sentence(" ".join(block_buf))
                    break
            else:
                block_buf.append(s.lstrip("* ").rstrip())
        elif s.startswith("/**"):
            in_block = True
            tail = s.lstrip("/* ").rstrip()
            if tail:
                block_buf.append(tail)
        elif s.startswith("//") and not module_doc:
            m = _JS_LINE_COMMENT.match(s)
            if m:
                module_doc = _first_sentence(m.group(1))
                break

    symbols: list[Symbol] = []
    pending_doc: list[str] = []
    in_block_comment = False
    for line in lines:
        s = line.rstrip()
        if in_block_comment:
            if "*/" in s:
                in_block_comment = False
            else:
                stripped = s.lstrip().lstrip("* ").strip()
                if stripped:
                    pending_doc.append(stripped)
            continue
        if s.lstrip().startswith("/**"):
            in_block_comment = True
            tail = s.lstrip().lstrip("/* ").rstrip()
            if tail and not tail.endswith("*/"):
                pending_doc.append(tail)
            continue
        m = _JS_LINE_COMMENT.match(s.lstrip())
        if m:
            pending_doc.append(m.group(1))
            continue
        m = _JS_EXPORT.match(s)
        if m:
            name = next(g for g in m.groups() if g)
            kind = "class" if "class " in s else "func"
            display = name if kind == "class" else f"{name}()"
            summary = _first_sentence(" ".join(pending_doc))
            symbols.append(Symbol(name=display, kind=kind, summary=summary))
            pending_doc = []
        elif s.strip():
            pending_doc = []

    return FileEntry(rel_path=rel, summary=module_doc, symbols=symbols)


# ───────────────────────────────────────────────────────────────────────────
# Walk + collect
# ───────────────────────────────────────────────────────────────────────────


def _collect() -> dict[str, list[FileEntry]]:
    out: dict[str, list[FileEntry]] = {
        "app/ — Python FastAPI Backend": [],
        "frontend/src/ — React Frontend": [],
        "src-tauri/src/ — Rust Desktop Wrapper": [],
        "tests/ — Test Suites": [],
        "scripts/ — Dev/Build Utilities": [],
    }

    # Python
    for root in PYTHON_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if _skip(path):
                continue
            entry = _parse_python(path)
            if root == "app":
                out["app/ — Python FastAPI Backend"].append(entry)
            elif root == "tests":
                out["tests/ — Test Suites"].append(entry)
            else:
                out["scripts/ — Dev/Build Utilities"].append(entry)

    # Rust
    for root in RUST_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.rs")):
            if _skip(path):
                continue
            out["src-tauri/src/ — Rust Desktop Wrapper"].append(_parse_rust(path))

    # JS/JSX
    for root in JS_ROOTS:
        for ext in ("js", "jsx", "mjs", "cjs"):
            for path in sorted((REPO_ROOT / root).rglob(f"*.{ext}")):
                if _skip(path):
                    continue
                out["frontend/src/ — React Frontend"].append(_parse_js(path))

    return out


# ───────────────────────────────────────────────────────────────────────────
# Render
# ───────────────────────────────────────────────────────────────────────────

L1_HEADER = """\
# MAP.md — Level 1 navigation

> Auto-generated by `scripts/regen_maps.py`. Do not edit by hand — re-run
> the script and commit the result. CI checks this is in sync with the code.
>
> **What this is:** file path + one-line purpose for every source file. Use
> this as your **first stop** when looking for where logic lives. If you
> need symbol-level detail (classes, functions, methods), go to `MAP_L2.md`.
> For deeper detail (routes, props, IPC commands), see `backend-index.md`,
> `frontend-index.md`, `rust-index.md`.

"""

L2_HEADER = """\
# MAP_L2.md — Level 2 navigation

> Auto-generated by `scripts/regen_maps.py`. Do not edit by hand.
>
> **What this is:** Level 1 + public classes / functions / methods with
> one-line summary each. Use this when you know the area but not the
> exact symbol. For full signatures, types, or invariants, read the
> source or the Level 3 indexes (`backend-index.md`, etc.).

"""


def _render_l1(groups: dict[str, list[FileEntry]]) -> str:
    out: list[str] = [L1_HEADER]
    for section, entries in groups.items():
        if not entries:
            continue
        out.append(f"## {section}\n")
        out.append("| File | Purpose |")
        out.append("|------|---------|")
        for e in entries:
            summary = _truncate(e.summary or "*(no module docstring)*", 110)
            out.append(f"| `{e.rel_path}` | {summary} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _render_l2(groups: dict[str, list[FileEntry]]) -> str:
    out: list[str] = [L2_HEADER]
    for section, entries in groups.items():
        if not entries:
            continue
        out.append(f"## {section}\n")
        for e in entries:
            summary = _truncate(e.summary or "*(no module docstring)*", 140)
            out.append(f"### `{e.rel_path}`")
            out.append("")
            out.append(summary)
            if e.symbols:
                out.append("")
                for s in e.symbols:
                    sym_summary = _truncate(s.summary, 100)
                    if sym_summary:
                        out.append(f"- `{s.name}` — {sym_summary}")
                    else:
                        out.append(f"- `{s.name}`")
            out.append("")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="Exit 1 if outputs would change")
    p.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing")
    args = p.parse_args()

    groups = _collect()
    l1 = _render_l1(groups)
    l2 = _render_l2(groups)

    if args.stdout:
        print("─── docs/MAP.md ───")
        print(l1)
        print("─── docs/MAP_L2.md ───")
        print(l2)
        return 0

    if args.check:
        rc = 0
        for path, expected in [(OUT_L1, l1), (OUT_L2, l2)]:
            actual = path.read_text(encoding="utf-8") if path.exists() else ""
            if actual != expected:
                print(f"::error::{path.relative_to(REPO_ROOT)} is out of date — run scripts/regen_maps.py")
                rc = 1
        return rc

    OUT_L1.parent.mkdir(parents=True, exist_ok=True)
    OUT_L1.write_text(l1, encoding="utf-8")
    OUT_L2.write_text(l2, encoding="utf-8")
    print(f"wrote {OUT_L1.relative_to(REPO_ROOT)} ({len(l1.splitlines())} lines)")
    print(f"wrote {OUT_L2.relative_to(REPO_ROOT)} ({len(l2.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
