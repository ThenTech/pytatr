# Tasks

This folder contains the issues, TODOs and planned work for this repository, as plain Markdown files in version control.
The system is based on [tsoding/tatr](https://github.com/tsoding/tatr).
[ThenTech/pytatr](https://github.com/ThenTech/pytatr) gives the reasons for this system and the differences from `tatr`.

## Layout

```
tasks/
+-README.md                     <- this file
+-20261026-101500/
| +-TASK.md                     <- mandatory task description
| +-screenshot.png              <- optional attachments, link them from TASK.md
+-20261026-143012-thentech/
| +-TASK.md
+-...
```

Each task is a folder with its **HUID** (Human-Unique IDentifier) as name. The folder contains a mandatory `TASK.md`.
Other files in the folder are attachments. Keep them small, because git stores them.

## HUID

The HUID is the **UTC** date and time when the task was created, in the format `YYYYMMDD-HHMMSS`, with an optional suffix:

```
[0-9]{8}-[0-9]{6}(-[a-zA-Z0-9\-]*)?
```

Examples: `20261026-101500`, `20261026-101500-thentech`.
If the HUID already exists, wait one second and make a new one.
Teams can agree on personal suffixes (for example a GitHub handle). This prevents collisions in parallel branches.

## TASK.md format

`TASK.md` starts with YAML frontmatter. Because of this, each task is a native [Obsidian](https://obsidian.md/) note with properties:

```markdown
---
title: <title>
author: <current git user name>
creation date: <current date, YYYY-MM-DD>
status: OPEN
priority: 100
tags:
  - <tag>
---

[description]
```

| Property        | Required | Description                                                                                          |
| --------------- | -------- | ---------------------------------------------------------------------------------------------------- |
| `title`         | yes      | Short summary. Put it in quotes if it contains `: ` or starts with a YAML special character.         |
| `author`        | yes      | The `git config user.name` of the person who created the task.                                       |
| `creation date` | yes      | Local date when the task was created, `YYYY-MM-DD`.                                                  |
| `status`        | yes      | `OPEN` or `CLOSED`, nothing else. Use tags for more detailed states (for example `bug`, `scope`, `wontfix`). |
| `priority`      | yes      | Integer. The highest value sorts first. Default `100`. It is a sort key, not an absolute importance. |
| `tags`          | no       | YAML list of tag names. Use `tags: []` for no tags. Tag names contain no spaces and no square brackets. |

You may add other properties (for example `assignee` or `due date`). The tooling ignores them and does not change them.

When you work on a task, add your findings, decisions and progress to the description.
To see who changed what and when, use `git log` and `git blame` on `TASK.md`.

### Common tags

| Tag           | Meaning                                         |
| ------------- | ----------------------------------------------- |
| `bug`         | Unintended behaviour that needs a correction    |
| `enhancement` | New feature or improvement                      |
| `docs`        | Documentation, ADRs, context                    |
| `scope`       | Somebody works on it now                        |
| `wontfix`     | Closed without a fix                            |

You can add new tags at any time. When a tag becomes common, add it to this table.

## Referencing tasks

Use the HUID to refer to a task anywhere in the repo: in code, docs, commits and PRs.
In source code, put a `TASK(<HUID>)` comment on the line directly above the `TODO` or `FIXME` that it tracks.
Use the same indentation and comment style:

```python
# TASK(20261026-101500)
# TODO replace the polling loop with a websocket subscription
```

`just task todo <FILE...>` adds these references for you. For each file, the command does these steps:

1. It finds each `TODO ` and `FIXME ` (followed by a space) that has no `TASK(...)` line above it.
2. It creates a task for each marker. The rest of the marker line becomes the title.
3. It inserts the reference line.

Comment lines directly below the marker become the task description.
The description stops at the first line that is not a comment, or at the end of a block comment.
A comment line that starts with `TODO ` or `FIXME ` starts a new task:

```python
# TASK(20261026-101500)
# TODO replace the polling loop with a websocket subscription
# The poll interval causes visible lag in the dashboard.    <- description of the first task
# TASK(20261026-101501)
# FIXME the poller leaks a connection on timeout             <- second task (tagged bug)
poll()                                                       <- end of the comment block
```

The marker stays in the code. A task from a `TODO` gets no tags. A task from a `FIXME` gets the `bug` tag.
If you run the command again, it skips the markers that already have a reference.

In Obsidian notes, link directly to the task file: `[[tasks/20261026-101500/TASK|Websocket subscription]]`.

## Commands

You can run all commands through `just` from any folder in the repo. They run `uv run src/pytatr.py`.
To test the tool, run `just test`.
For all options, run `just task help` or `just task <command> --help`.

| Command                                 | Description                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------------- |
| `just tasks [FILTERS]`                  | List the open tasks, highest priority first. Same as `just task ls`.         |
| `just task new [TITLE] [-p N] [-t TAG]` | Create a task with a new HUID, the git user as author, and today's date.     |
| `just task find <HUID-prefix>`          | Show the tasks whose HUID starts with the prefix, open or closed.            |
| `just task ref <HUID-prefix>`           | Show each line in the repo (outside the task folder) that refers to the task. |
| `just task summary [-c]`                | Count the open (or closed) tasks for each tag.                               |
| `just task todo <FILE...> [-y]`         | Create tasks from `TODO ` / `FIXME ` markers and add `TASK(<HUID>)` above them. |

Filters for `just tasks` and `just task ls`. A task must match all filters (AND):

| Filter                                                  | Meaning                                         |
| ------------------------------------------------------- | ----------------------------------------------- |
| `--status open\|closed\|all`, `-c`                      | Status to show (default `open`, `-c` = closed)  |
| `-t TAG` / `--tag TAG`                                  | Has the tag (repeat for more tags)              |
| `-x TAG` / `--not-tag TAG`                              | Does not have the tag                           |
| `--tagged` / `--untagged`                               | Has at least one tag / has no tags              |
| `--lt N`, `--le N`, `--gt N`, `--ge N`, `--eq N`, `--ne N` | Compare the priority with `N`                 |
| `--huid PREFIX`                                         | The HUID starts with the prefix                 |
| `-a`, `--by-id`                                         | Ascending order / sort by HUID                  |

A mass update changes each task that matches the filters. `-u` / `--update` takes a comma-separated list of
`open`, `close`, `+tag` and `-tag`. A mass update needs a filter. To update all tasks on purpose, use `--any`.

```bash
just tasks -t bug --lt 50                  # open bugs with priority below 50
just tasks --status all -t api -x wontfix  # every api task that is not wontfix
just task new Fix login redirect -p 150 -t bug -t web
just task find 202610                      # all tasks created in October 2026
just task ref 20261026-101500              # where is this task referenced?
just tasks -t scope -u close,-scope        # close everything in scope and drop the tag
```

### Without `just`

The format is plain text, so standard tools also work:

```bash
ls tasks                               # all task folders
ls -d tasks/202610*                    # find by HUID prefix
grep -l "status: OPEN" tasks/*/TASK.md # open tasks
git grep -n 20261026-101500            # references to a task
```

## Create a task manually (or as an LLM)

1. Make the HUID from the current UTC time: `date -u +%Y%m%d-%H%M%S`.
2. Create `tasks/<HUID>/TASK.md` with the frontmatter template above. Fill in all required properties.
3. Write the description below the frontmatter: what to do, why, and how to make sure that it is done.
   Use [ASD-STE100](https://en.wikipedia.org/wiki/Simplified_Technical_English) language if possible.
4. Where it is useful, refer to the HUID from the related code with `TASK(<HUID>)`.
5. To close the task, set `status: CLOSED` and add a short note about the solution.
