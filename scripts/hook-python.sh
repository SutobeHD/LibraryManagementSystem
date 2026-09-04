#!/usr/bin/env bash
# Interpreter resolver for pre-commit `language: system` hooks.
#
# WHY: uv's .venv/Scripts/python.exe is a trampoline that exports
# PYTHONHOME=<uv base install> to every child process. pre-commit runs
# `language: system` entries with the inherited environment, so a bare
# `python` picks the first interpreter on PATH — a different minor version —
# while PYTHONHOME still forces the uv stdlib onto it. Result: every hook dies
# with `AssertionError: SRE module mismatch` before running a single line.
#
# Resolve the project interpreter explicitly (same order as
# scripts/run-backend.mjs). Only when there is no venv do we fall back to PATH,
# and then with -E so a leaked PYTHONHOME cannot mismatch the stdlib.
set -euo pipefail

if [ -n "${LMS_PYTHON:-}" ] && [ -x "${LMS_PYTHON}" ]; then
  exec "${LMS_PYTHON}" "$@"
elif [ -x ".venv/Scripts/python.exe" ]; then
  exec ".venv/Scripts/python.exe" "$@"
elif [ -x ".venv/bin/python" ]; then
  exec ".venv/bin/python" "$@"
else
  exec python -E "$@"
fi
