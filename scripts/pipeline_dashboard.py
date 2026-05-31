#!/usr/bin/env python3
"""
Local web dashboard for the research pipeline.

Serves an auto-refreshing HTML view of docs/research/ — docs grouped by
state, open user gates, open routine PRs, and blockers. Read-only:
it never edits files or git. Stop it with Ctrl+C.

Usage:
    python scripts/pipeline_dashboard.py            # serve on http://127.0.0.1:8765
    python scripts/pipeline_dashboard.py --port 9000
    python scripts/pipeline_dashboard.py --once     # render HTML once to stdout, exit

Design:
- Reuses the scan logic from pipeline_status.py (same scripts/ folder).
- Stdlib only — no Flask, no npm, no build step.
- Binds 127.0.0.1 only (local-only, never exposed to the network).
- The gh PR lookup is cached 60 s so a 30 s page refresh stays snappy.
"""

from __future__ import annotations

import argparse
import html
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_status import (
    GATE_STATES,
    STAGE_STATES,
    compute_trends,
    fetch_routine_prs,
    open_gates,
    scan,
)

DEFAULT_PORT = 8765
REFRESH_SECONDS = 30
STALE_DAYS = 7

_PR_CACHE: dict = {"at": 0.0, "data": None}
_PR_CACHE_TTL = 60.0

_ROUTINES = (
    "Daily: research-draft 05:00 &middot; research-explore 06:00+14:00 &middot; "
    "research-plan 13:00 &middot; research-implement 03:00+15:00 &middot; "
    "research-triage 07:30. "
    "Cross-cutting: research-spawn Sun 04:00 &middot; "
    "research-watchdog 1st-of-month 04:00 &middot; "
    "research-cross-linker Tue 04:30 (Berlin)"
)

CSS = """
* { box-sizing: border-box; }
body { margin:0; background:#0d1117; color:#e6edf3;
  font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; font-size:14px; }
.wrap { max-width:1180px; margin:0 auto; padding:28px 22px 60px; }
header { display:flex; justify-content:space-between; align-items:baseline;
  flex-wrap:wrap; gap:8px; }
h1 { font-size:21px; margin:0; font-weight:650; }
.meta { color:#7d8590; font-size:12.5px; }
h2 { font-size:11px; text-transform:uppercase; letter-spacing:.09em;
  color:#7d8590; margin:32px 0 12px; font-weight:600; }
.empty-note { padding:11px 14px; border-radius:8px; background:#161b22;
  border:1px solid #30363d; color:#7d8590; }
.empty-note.ok { color:#3fb950; }
.gates { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; }
.gate-card { display:flex; gap:13px; background:#2a2310; border:1px solid #46391a;
  border-left:4px solid #e3b341; border-radius:9px; padding:13px 15px; }
.gate-badge { background:#e3b341; color:#1c1500; font-weight:700; font-size:12px;
  padding:5px 9px; border-radius:6px; height:fit-content; white-space:nowrap; }
.gate-slug { font-weight:650; font-size:15px; word-break:break-word; }
.gate-sub { color:#9a8e6b; font-size:12px; margin:2px 0 8px; }
.gate-cmds { display:flex; flex-direction:column; gap:4px; }
code { font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px; }
.gate-cmds code { background:#1c2128; border:1px solid #30363d; color:#e6edf3;
  padding:3px 7px; border-radius:5px; }
.lane { margin-bottom:16px; }
.lane-title { font-family:ui-monospace,monospace; color:#7d8590; font-size:12px; margin-bottom:7px; }
.lane-row { display:flex; flex-wrap:wrap; gap:8px; }
.state-card { background:#161b22; border:1px solid #30363d; border-radius:9px;
  padding:9px 11px; min-width:140px; flex:1 1 140px; max-width:210px; }
.state-card.has { background:#1c2128; border-color:#3d444d; }
.state-card.gate.has { border-color:#e3b341; }
.state-card.empty { opacity:.45; }
.state-head { font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
  color:#7d8590; display:flex; justify-content:space-between; align-items:center; gap:4px; }
.gate-tag { background:#e3b341; color:#1c1500; font-weight:700; font-size:9px;
  padding:1px 5px; border-radius:4px; white-space:nowrap; }
.state-count { font-size:26px; font-weight:680; margin:3px 0 4px; }
.state-card.empty .state-count { color:#7d8590; }
.state-docs { list-style:none; margin:8px 0 0; padding:0;
  display:flex; flex-direction:column; gap:5px; }
.state-docs li { font-size:11px; color:#c9d1d9; line-height:1.4;
  background:#0d1117; border:1px solid #30363d; border-radius:5px;
  padding:5px 8px; word-break:break-word; }
.state-docs li.none { color:#484f58; background:none; border:0;
  padding:2px 0; font-style:italic; }
.pr-card,.blocker-item { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
  background:#161b22; border:1px solid #30363d; border-radius:8px;
  padding:9px 13px; margin-bottom:7px; }
.pr-num { color:#58a6ff; font-weight:650; font-family:ui-monospace,monospace; }
.pr-branch { color:#7d8590; font-family:ui-monospace,monospace; font-size:12px; }
.spacer { margin-left:auto; }
.blocker-item { border-left:3px solid #f85149; }
.blocker-tag { color:#f85149; font-size:12px; font-family:ui-monospace,monospace; }
.trend-row { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:7px; }
.trend-tile { background:#161b22; border:1px solid #30363d; border-radius:8px;
  padding:9px 11px; min-width:120px; flex:0 1 auto; }
.trend-tile.slow { border-color:#e3b341; }
.trend-state { font-size:11px; color:#7d8590; text-transform:uppercase; letter-spacing:.05em; }
.trend-val { font-family:ui-monospace,monospace; font-size:15px; font-weight:650; }
.trend-n { color:#7d8590; font-size:11px; font-family:ui-monospace,monospace; }
.trend-foot { color:#7d8590; font-size:12px; margin-top:4px; }
footer { margin-top:36px; color:#56606b; font-size:11.5px;
  border-top:1px solid #21262d; padding-top:14px; line-height:1.7; }
"""


def _esc(value: object) -> str:
    return html.escape(str(value))


def _age_label(age_days: int | None) -> str:
    if age_days is None:
        return "age unknown"
    if age_days == 0:
        return "today"
    if age_days == 1:
        return "1 day"
    return f"{age_days} days"


def _cached_prs() -> list[dict] | None:
    now = time.time()
    if now - _PR_CACHE["at"] > _PR_CACHE_TTL:
        _PR_CACHE["data"] = fetch_routine_prs()
        _PR_CACHE["at"] = now
    return _PR_CACHE["data"]


def _render_gates(docs: list) -> str:
    gates = open_gates(docs)
    if not gates:
        return '<div class="empty-note ok">No open approvals &mdash; nothing waiting on you.</div>'
    cards = []
    for d in gates:
        label = GATE_STATES[d.state]
        cards.append(
            '<div class="gate-card">'
            f'<div class="gate-badge">{_esc(label.upper())}</div>'
            '<div class="gate-body">'
            f'<div class="gate-slug">{_esc(d.slug)}</div>'
            f'<div class="gate-sub">{_esc(d.state)}_ &middot; waiting {_age_label(d.age_days)}</div>'
            '<div class="gate-cmds">'
            f"<code>/approve {_esc(d.slug)}</code>"
            f'<code>/reject {_esc(d.slug)} "&hellip;"</code>'
            "</div></div></div>"
        )
    return '<div class="gates">' + "".join(cards) + "</div>"


def _render_lane(title: str, states: list[str], by_state: dict) -> str:
    cards = []
    for state in states:
        entries = by_state.get(state, [])
        css = "state-card"
        if state in GATE_STATES:
            css += " gate"
        css += " has" if entries else " empty"
        tag = (
            f'<span class="gate-tag">{_esc(GATE_STATES[state].upper())}</span>'
            if state in GATE_STATES
            else ""
        )
        if entries:
            docs_html = "".join(f"<li>{_esc(d.slug)}</li>" for d in entries)
        else:
            docs_html = '<li class="none">empty</li>'
        cards.append(
            f'<div class="{css}">'
            f'<div class="state-head"><span>{_esc(state)}</span>{tag}</div>'
            f'<div class="state-count">{len(entries)}</div>'
            f'<ul class="state-docs">{docs_html}</ul>'
            "</div>"
        )
    return (
        f'<div class="lane"><div class="lane-title">{_esc(title)}</div>'
        f'<div class="lane-row">{"".join(cards)}</div></div>'
    )


def _render_prs(prs: list[dict] | None) -> str:
    if prs is None:
        return '<div class="empty-note">Routine PRs &mdash; gh CLI unavailable.</div>'
    if not prs:
        return '<div class="empty-note">No open <code>routine/*</code> PRs.</div>'
    rows = []
    for p in prs:
        rows.append(
            '<div class="pr-card">'
            f'<span class="pr-num">#{_esc(p.get("number", "?"))}</span>'
            f'<span class="pr-title">{_esc(p.get("title", ""))}</span>'
            f'<span class="pr-branch spacer">{_esc(p.get("headRefName", ""))}</span>'
            "</div>"
        )
    return "".join(rows)


def _render_trends(docs: list) -> str:
    t = compute_trends(docs)
    avg = t["avg_per_state"]
    if not avg:
        return '<div class="empty-note">No completed transitions yet (no history to average).</div>'
    slowest = t["slowest_state"]
    tiles = []
    for _stage, states in STAGE_STATES.items():
        for state in states:
            if state not in avg:
                continue
            css = "trend-tile slow" if state == slowest else "trend-tile"
            tiles.append(
                f'<div class="{css}">'
                f'<div class="trend-state">{_esc(state)}</div>'
                f'<div class="trend-val">{avg[state]:.1f}d</div>'
                f'<div class="trend-n">n={t["sample_size"][state]}</div>'
                "</div>"
            )
    foot = (
        f'<div class="trend-foot">Throughput: {t["throughput_30"]} docs '
        f'&rarr; implemented_ in last 30 days, {t["throughput_90"]} in last 90'
    )
    if slowest:
        foot += f' &middot; slowest work state: <strong>{_esc(slowest)}</strong> ({t["slowest_avg"]:.1f}d avg)'
    foot += "</div>"
    return f'<div class="trend-row">{"".join(tiles)}</div>{foot}'


def _render_blockers(docs: list) -> str:
    items = []
    for d in docs:
        if d.state in ("parked", "blocked"):
            items.append((d, f"{d.state}_"))
        elif (
            d.stage != "archived"
            and d.state not in GATE_STATES
            and (d.age_days or 0) > STALE_DAYS
        ):
            items.append((d, f"stale {d.age_days}d in {d.state}_"))
    if not items:
        return '<div class="empty-note ok">No blockers.</div>'
    rows = []
    for d, reason in items:
        rows.append(
            '<div class="blocker-item">'
            f"<span>{_esc(d.slug)}</span>"
            f'<span class="blocker-tag spacer">{_esc(reason)}</span>'
            "</div>"
        )
    return "".join(rows)


def render_html() -> str:
    docs = scan()
    prs = _cached_prs()
    by_state: dict[str, list] = {}
    for d in docs:
        by_state.setdefault(d.state, []).append(d)

    lanes = "".join(
        _render_lane(f"{stage}/", states, by_state)
        for stage, states in STAGE_STATES.items()
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(docs)

    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<meta http-equiv='refresh' content='{REFRESH_SECONDS}'>"
        "<title>Research Pipeline</title>"
        "<style>" + CSS + "</style></head><body><div class='wrap'>"
        "<header><h1>Research Pipeline</h1>"
        f"<span class='meta'>{total} docs &middot; updated {now} "
        f"&middot; auto-refresh {REFRESH_SECONDS}s</span></header>"
        "<h2>Waiting on you</h2>" + _render_gates(docs)
        + "<h2>Pipeline</h2>" + lanes
        + "<h2>Trends (avg days per state, completed visits)</h2>" + _render_trends(docs)
        + "<h2>Open routine PRs (test + merge)</h2>" + _render_prs(prs)
        + "<h2>Blockers</h2>" + _render_blockers(docs)
        + "<footer>Read-only view of docs/research/. Approve docs with "
        "<code>/approve</code> / <code>/reject</code>; routines never "
        "merge to main &mdash; you test the branch, then merge.<br>Routines: " + _ROUTINES + "</footer>"
        "</div></body></html>"
    )


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
            self.send_error(404, "Not found")
            return
        try:
            body = render_html().encode("utf-8")
        except Exception as exc:
            body = f"<pre>dashboard render error: {html.escape(str(exc))}</pre>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass  # silent — no per-request console spam


def main() -> int:
    parser = argparse.ArgumentParser(description="Local research-pipeline web dashboard.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default 8765)")
    parser.add_argument("--once", action="store_true", help="render HTML once to stdout, exit")
    args = parser.parse_args()

    if args.once:
        sys.stdout.buffer.write(render_html().encode("utf-8"))
        return 0

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    except OSError as exc:
        print(f"Cannot bind port {args.port}: {exc}", file=sys.stderr)
        print("Another process may be using it — try --port <other>.", file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{args.port}"
    print(f"Research dashboard running at {url}")
    print("Open it in a browser. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
