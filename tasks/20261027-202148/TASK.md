---
title: Create a test file for src/pytatr.py
author: ThenTech
creation date: 2026-10-27
status: CLOSED
priority: 100
tags:
  - tooling
---
We need to add a test file to verify the `pytatr.py` functionality and make sure it follows our `TASK.md` format. If we would reimplement more features from `tatr`, we can check that we still adhere to our spec instead.

## Solution

`src/test_pytatr.py` has 60 tests (standard library `unittest`, no dependencies). Run them with `just test-tasks`. `just test` also runs them.

- `TestTatr*` classes test the behavior from tatr. Change these tests when you reimplement a tatr feature.
- `TestLocal*` classes test the differences from tatr in [tasks/README.md]. A reimplementation must not break them. Run them with `just test-tasks -k Local`.
- `TestLocalDocs` compares the script with [tasks/README.md] and the [README.md] (HUID pattern, commands, filters, frontmatter template).

The tests found one bug: in a `/**` block, the closing ` */` line became part of the task description. `marker_description` in `scripts/tasks.py` now stops at each line that starts with a block closer.
