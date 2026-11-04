"""app/main.py defines each top-level name once, so no request model or handler is shadowed.

PlCreateReq / PlRenameReq / PlDeleteReq / PlMoveReq / PlRemoveTrackReq were defined
twice and two different handlers were both named ``stream_audio`` (ruff F811). The
later definition won every time, so editing the first copy changed nothing at runtime.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from fastapi.routing import APIRoute

from app import main


def _api_routes() -> list[APIRoute]:
    return [r for r in main.app.routes if isinstance(r, APIRoute)]


def test_main_defines_each_top_level_name_once() -> None:
    tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))
    defs = Counter(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    assert {name: n for name, n in defs.items() if n > 1} == {}


def test_no_method_and_path_is_registered_twice() -> None:
    pairs = Counter((r.path, m) for r in _api_routes() for m in r.methods)
    assert [pair for pair, n in pairs.items() if n > 1] == []


def test_both_audio_stream_routes_keep_their_handlers() -> None:
    by_route = {(r.path, m): r.endpoint for r in _api_routes() for m in r.methods}
    assert by_route[("/api/stream", "GET")] is main.stream_audio
    assert by_route[("/api/audio/stream", "GET")] is main.stream_audio_file


def test_playlist_move_keeps_the_model_that_was_in_effect() -> None:
    # The dead first PlMoveReq defaulted parent_id to "ROOT"; the one routes used requires it.
    assert main.PlMoveReq.model_fields["parent_id"].is_required()
