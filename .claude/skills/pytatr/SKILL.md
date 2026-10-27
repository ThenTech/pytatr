---
name: pytatr
description: List, find, create, update and close tasks in a folder-based task tracker (`tasks/<HUID>/TASK.md`) with the `pytatr` command line tool. Use when the user asks about tasks, issues, TODOs or the backlog, wants to create or close a task, or wants to convert `TODO`/`FIXME` comments into tasks. Explains how to run the tool through `just`, `uv run` or plain Python.
---

# pytatr

`pytatr` is a Python reimplementation inspired by [tsoding/tatr](https://github.com/tsoding/tatr).
Each task is a folder `tasks/<HUID>/TASK.md` with YAML frontmatter.
`tasks/README.md` is the reference for the format. Read it before you create or change a task by hand.

## 1. Find the script

The script is one file with no dependencies: `pytatr.py`.

- In the `pytatr` repository, it is `src/pytatr.py`.
- In a repository that includes `pytatr` as a git submodule, it is `<submodule path>/src/pytatr.py`
  (for example `tools/pytatr/src/pytatr.py`).

If you do not know the path, search for `pytatr.py`. Below, `<SCRIPT>` is that path.

The script looks for the `tasks/` folder in the current folder and then in each parent folder.
Run it from the repository root or from a folder below it.

## 2. Select how to run it

Use the first option that is available. Each option runs the same script with the same arguments.

| Check                                       | Command prefix                  |
| ------------------------------------------- | ------------------------------- |
| `just --list` shows the `task` recipe       | `just task <command>`           |
| `uv --version` works                        | `uv run --quiet <SCRIPT> <command>` |
| Python 3.13 or newer (`python3 --version`)  | `python3 <SCRIPT> <command>`    |

- `just tasks [FILTERS]` is the same as `just task ls [FILTERS]`.
- On Windows, the Python command can be `python` or `py -3` instead of `python3`.
- `uv run` reads the PEP 723 metadata in the script and gets a correct Python version automatically.
- If no option is available, tell the user. Do not install tools without approval.

In the examples below, `task` means the prefix that you selected.

## 3. Commands

| Command                                  | Description                                                              |
| ---------------------------------------- | ------------------------------------------------------------------------ |
| `task ls [FILTERS] [-u ACTIONS]`         | List tasks, highest priority first. Optionally apply a mass update.      |
| `task new [TITLE] [-p N] [-t TAG] [-s SUFFIX]` | Create a task. The author is the git user. The HUID is the UTC time. |
| `task find <HUID-prefix> [--path-only]`  | Show tasks whose HUID starts with the prefix, open or closed.            |
| `task ref <HUID-prefix>`                 | Show each line in the repo (outside the task folder) that refers to the task. |
| `task summary [-c]`                      | Count the open (or closed) tasks for each tag.                           |
| `task todo <FILE...> -y [-s SUFFIX]`     | Create tasks from `TODO ` / `FIXME ` comments and add `TASK(<HUID>)` above them. |
| `task help`, `task <command> --help`     | Show all options.                                                        |

Filters for `ls`. A task must match all filters (AND):

| Filter                                                    | Meaning                                     |
| --------------------------------------------------------- | ------------------------------------------- |
| `--status open\|closed\|all`, `-c`                        | Status (default `open`, `-c` = closed)      |
| `-t TAG` / `-x TAG`                                       | Has / does not have the tag (repeatable)    |
| `--tagged` / `--untagged`                                 | Has at least one tag / has no tags          |
| `--lt N`, `--le N`, `--gt N`, `--ge N`, `--eq N`, `--ne N` | Compare the priority with `N`              |
| `--huid PREFIX`                                           | The HUID starts with the prefix             |
| `-a`, `--by-id`                                           | Ascending order / sort by HUID              |

Each output line starts with `path:line:`. Use the path to open or edit the task file.

## 4. Rules for agents

- `todo` asks a question for each marker. You cannot answer it. Always add `-y`.
  Before you run `todo`, tell the user which files you will change.
- A mass update (`ls -u ...`) changes every task that matches. First run the same `ls` without `-u` and examine the list.
  A mass update without a filter needs `--any`. Use `--any` only when the user asks to update all tasks.
- The update actions are a comma-separated list of `open`, `close`, `+tag` and `-tag`. Example: `-u close,-scope`.
- To close one task, use `ls --huid <HUID> -u close`. Then add a short note about the solution to the task description.
- To change the title, the priority or the description, edit `TASK.md` directly. Keep the frontmatter valid.
- Do not test the tool against the real `tasks/` folder. Use a temporary folder that contains its own `tasks/`.

## 5. Examples

```bash
just tasks -t bug --lt 50                            # open bugs with priority below 50
just task new Fix login redirect -p 150 -t bug       # create a task
uv run --quiet src/pytatr.py find 202610             # tasks created in October 2026
python3 src/pytatr.py ref 20261026-101500            # where is this task referenced?
just tasks -t scope                                  # check the list first
just tasks -t scope -u close,-scope                  # then close everything in scope
```
