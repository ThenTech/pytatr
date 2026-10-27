# pytatr

A folder-based task tracker for repositories using `git` version control. It is a reimplementation inspired by [tsoding/tatr](https://github.com/tsoding/tatr).

Each task is a folder `tasks/<HUID>/TASK.md`. The file starts with YAML frontmatter, so each task is also a native
[Obsidian](https://obsidian.md/) note. The tool is one Python file without dependencies: `src/pytatr.py`.

- [tasks/README.md](tasks/README.md): the full task format, the conventions and the commands.
- [.claude/skills/pytatr/SKILL.md](.claude/skills/pytatr/SKILL.md): instructions for LLM agents.

## Why

Work items (bugs, follow-ups, ideas, `TODO` comments) are often in many places: comments without a status,
an external issue tracker, chat messages. `pytatr` keeps them in the repository instead:

- The tasks have the same versions, branches and merges as the code. A pull request can add, update and close its tasks.
- Humans, scripts and LLM agents read and write the same plain Markdown files. No accounts, network or services.
- Humans can browse and query the tasks in Obsidian, together with the other notes in the repository.

The costs: there is no web UI, no notifications and no permissions. People without access to the repository
cannot create tasks. Contributors must keep the `status` up to date themselves.

## Format

```
tasks/
+-README.md
+-20261026-101500/
| +-TASK.md                     <- mandatory task description
| +-screenshot.png              <- optional small attachments
```

- **HUID**: the **UTC** creation time `YYYYMMDD-HHMMSS` with an optional suffix, `[0-9]{8}-[0-9]{6}(-[a-zA-Z0-9\-]*)?`.
  HUIDs from different branches merge without conflicts and sort in chronological order.
  Use a personal suffix (for example a GitHub handle) to prevent collisions in parallel branches.
- **TASK.md**: YAML frontmatter with `title`, `author`, `creation date`, `status` (`OPEN` or `CLOSED`),
  `priority` (integer, highest first, default `100`) and `tags` (a flat list). Then a free Markdown description.
  Other properties are allowed. The tool does not change them.
- **References**: in source code, a `TASK(<HUID>)` comment goes on the line directly above the `TODO` or `FIXME` it tracks.
  The history of a task comes from `git log` and `git blame`.

## Differences from tatr

| Topic        | `tatr`                                        | `pytatr`                                                       |
| ------------ | --------------------------------------------- | -------------------------------------------------------------- |
| Properties   | Markdown list under a `# title` heading       | YAML frontmatter, so Obsidian reads them as note properties    |
| Tool         | C program, compile it, Linux only             | One Python file, standard library only, Linux, macOS, Windows  |
| Queries      | Tatr Query Language                           | Command line flags, combined with AND (`-t`, `-x`, `--lt`, ...) |
| Mass update  | `ls -update`                                  | `ls -u` with the same language (`open`, `close`, `+tag`, `-tag`), and a filter or `--any` is mandatory |
| `TODO` links | `todo` replaces `TODO:` with `TASK(<HUID>):`  | `just task todo` adds `TASK(<HUID>)` above `TODO`/`FIXME` comments |

The commands keep the `tatr` names: `just task ls`, `just task new`, `just task find`, `just task ref`,
`just task summary` and `just task todo`. Each output line starts with `path:line:`, so editors can go to the task file.

## Usage

Python 3.13 or newer. Run the script from the repository that contains the `tasks/` folder:

```bash
just task help                     # with just
uv run --quiet src/pytatr.py help  # with uv
python3 src/pytatr.py help         # with Python only
```

## Use it in another repository

Copy these files and folders to the root of your repository:

- `src/pytatr.py`, for example to `tools/pytatr.py`.
- `tasks/`, with `README.md` and `Tasks Kanban.base`. Remove the task folders of this repository, if any.
- `.obsidian/`, to open the repository as an Obsidian vault with the same settings and plugins.
- Optional: `.claude/skills/pytatr/`, so that Claude Code knows how to use the tool.

Optionally add [`just`](https://github.com/casey/just?tab=readme-ov-file#packages) recipes that call the script if using `just` as a command runner. Change the path if you put the script in a different place:

```just
[positional-arguments]
tasks *args:
    @uv run --quiet tools/pytatr.py ls "$@"

[positional-arguments]
task command="help" *args:
    @uv run --quiet tools/pytatr.py "$@"
```

To receive updates to the tool, you can add this repository as a git submodule instead of a copy of the script,
for example `git submodule add https://github.com/ThenTech/pytatr tools/pytatr`.
Then the script is `tools/pytatr/src/pytatr.py`. You must still copy `tasks/` and `.obsidian/`.

## Tests

```bash
just test                          # all tests
just test -k Local                 # only the differences from tatr
```

`TestTatr*` tests cover the behavior from `tatr`. `TestLocal*` tests cover the differences above.
`TestLocalDocs` compares the script with `tasks/README.md` and this file.

If you use pytatr as a submodule, also test the copy of `tasks/README.md` in your repository.
Run this command from your repository root:

```bash
uv run --quiet tools/pytatr/src/test_pytatr.py --readme tasks/README.md
```

## Obsidian

The repository is also an Obsidian vault. Open the folder in Obsidian to browse the tasks.
`tasks/Tasks Kanban.base` shows them as a table or a kanban board.

## License

MIT. See [LICENSE](LICENSE).
