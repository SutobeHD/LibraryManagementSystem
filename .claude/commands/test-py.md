---
description: Run the Python test suite (pytest). Optional pattern to filter tests.
argument-hint: "[optional: file or -k pattern, e.g. test_analysis.py or -k beatgrid]"
allowed-tools: Bash
---

Run pytest with the user's filter (if provided):

```bash
pytest $ARGUMENTS -v
```

If no arguments given, run the full suite: `pytest -v`.

Default test root is `tests/`. Focus on actionable output: print failing tests + first stack-frame, but skip the success spam. If a failure looks like a flaky timing issue (rbox panic, ProcessPoolExecutor timeout), say so explicitly — those are known-fragile areas.
