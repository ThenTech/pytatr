#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ThenTech
# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Folder-based task tracker, inspired by tsoding/tatr.

Each task lives in `tasks/<HUID>/TASK.md` with Obsidian-compatible YAML frontmatter.
See `tasks/README.md` for the format and `just task help` for the commands.
Source, documentation and license: https://github.com/ThenTech/pytatr
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TASKS_DIR_NAME = "tasks"
TASK_FILE_NAME = "TASK.md"
DEFAULT_PRIORITY = 100
DEFAULT_TITLE = "New Task"
STATUSES = ("OPEN", "CLOSED")
MARKER_TAGS: dict[str, tuple[str, ...]] = {"TODO": (), "FIXME": ("bug",)}
BLOCK_COMMENTS = {"/*": "*/", "<!--": "-->"}
COMMENT_CLOSERS = tuple(BLOCK_COMMENTS.values())
TODO_ANSWERS = {"y": "convert", "n": "keep", "a": "convert-file", "s": "skip-file", "q": "quit"}
TODO_QUESTION = "Convert to a task? y = yes, n = no, a = all in this file, s = skip this file, q = quit: "

HUID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}(-[a-zA-Z0-9\-]*)?$")
HUID_PREFIX_RE = re.compile(r"^[a-zA-Z0-9\-]+$")
KEY_LINE_RE = re.compile(r"^([^\s#\-][^:]*):(.*)$")
MARKER_RE = re.compile(r"\b(TODO|FIXME) ")
TASK_REF_RE = re.compile(r"\bTASK\([0-9]{8}-[0-9]{6}")
COMMENT_LEADER_RE = re.compile(r"(#+|//+|/\*+|<!--|--|;+|\*)\s*$")
TITLE_NEEDS_QUOTES_RE = re.compile(r"""^[\s\-?:,\[\]{}#&*!|>'"%@`]|: | #|\s$""")


@dataclass(frozen=True)
class Task:
    huid: str
    path: Path
    title: str
    status: str
    priority: int
    tags: tuple[str, ...]

    def report(self, note: str = "") -> str:
        location = f"{display_path(self.path)}:1:"
        parts = [location]
        if note:
            parts.append(f"<UPDATED: {note}>")
        parts.append(self.status)
        parts.append(f"[PRIORITY: {self.priority:3d}]")
        if self.tags:
            parts.append(f"[{', '.join(self.tags)}]")
        parts.append(self.title)
        return " ".join(parts)


# ----------------------------------------------------------------------------
# Paths and HUIDs
# ----------------------------------------------------------------------------


def find_tasks_dir() -> Path:
    """Walk up from the current directory until a `tasks/` folder is found."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / TASKS_DIR_NAME
        if candidate.is_dir():
            return candidate
    raise SystemExit(f"ERROR: no {TASKS_DIR_NAME}/ folder in {Path.cwd()} or its parent folders")


def display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def new_huid(suffix: str | None) -> str:
    huid = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{huid}-{suffix}" if suffix else huid


def git_user_name() -> str:
    # On Windows, a shell such as MSYS2 (for example the shell of `just`) can set HOME to a folder
    # without the global .gitconfig. Path.home() uses USERPROFILE on Windows and HOME on other systems.
    env = {**os.environ, "HOME": str(Path.home())}
    result = subprocess.run(
        ["git", "config", "user.name"], check=False, capture_output=True, text=True, env=env
    )
    return result.stdout.strip()


# ----------------------------------------------------------------------------
# Frontmatter
# ----------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter lines without the `---` fences, body)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return [], text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], "".join(lines[index + 1 :])
    return [], text


def parse_blocks(fm_lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group frontmatter lines into (key, lines) blocks, keeping them verbatim."""
    blocks: list[tuple[str, list[str]]] = []
    for line in fm_lines:
        match = KEY_LINE_RE.match(line)
        if match:
            blocks = [*blocks, (match.group(1).strip().lower(), [line])]
        elif blocks:
            key, block_lines = blocks[-1]
            blocks = [*blocks[:-1], (key, [*block_lines, line])]
        else:
            blocks = [*blocks, ("", [line])]
    return blocks


def unquote(value: str) -> str:
    value = value.strip()
    is_quoted = len(value) >= len('""') and value[0] == value[-1]
    if is_quoted and value[0] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if is_quoted and value[0] == "'":
        return value[1:-1].replace("''", "'")
    return value


def block_scalar(block_lines: list[str]) -> str:
    match = KEY_LINE_RE.match(block_lines[0])
    return unquote(match.group(2)) if match else ""


def block_list(block_lines: list[str]) -> tuple[str, ...]:
    inline = block_scalar(block_lines)
    if inline.startswith("[") and inline.endswith("]"):
        items = inline[1:-1].split(",")
    elif inline:
        items = re.split(r"[,\s]+", inline)
    else:
        items = [line.strip()[1:] for line in block_lines[1:] if line.strip().startswith("-")]
    return tuple(tag for tag in (unquote(item).lstrip("#") for item in items) if tag)


def quote_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False) if TITLE_NEEDS_QUOTES_RE.search(value) else value


def render_tags(tags: tuple[str, ...]) -> list[str]:
    if not tags:
        return ["tags: []\n"]
    return ["tags:\n", *(f"  - {tag}\n" for tag in tags)]


def load_task(task_md: Path) -> Task:
    text = task_md.read_text(encoding="utf-8")
    fm_lines, body = split_frontmatter(text)
    blocks = dict(parse_blocks(fm_lines))

    title = block_scalar(blocks["title"]) if "title" in blocks else ""
    if not title:
        heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), "")
        title = heading or task_md.parent.name

    status = block_scalar(blocks["status"]).upper() if "status" in blocks else "OPEN"
    try:
        priority = int(block_scalar(blocks["priority"])) if "priority" in blocks else DEFAULT_PRIORITY
    except ValueError:
        print(
            f"{display_path(task_md)}:1: WARNING: invalid priority, using {DEFAULT_PRIORITY}", file=sys.stderr
        )
        priority = DEFAULT_PRIORITY

    return Task(
        huid=task_md.parent.name,
        path=task_md,
        title=title,
        status=status,
        priority=priority,
        tags=block_list(blocks["tags"]) if "tags" in blocks else (),
    )


def load_tasks(tasks_dir: Path) -> list[Task]:
    return [
        load_task(entry / TASK_FILE_NAME)
        for entry in sorted(tasks_dir.iterdir())
        if entry.is_dir() and HUID_RE.match(entry.name) and (entry / TASK_FILE_NAME).is_file()
    ]


def write_task_fields(task: Task, status: str, tags: tuple[str, ...]) -> Task:
    """Rewrite only the `status` and `tags` blocks, leaving everything else untouched."""
    text = task.path.read_text(encoding="utf-8")
    fm_lines, body = split_frontmatter(text)
    blocks = parse_blocks(fm_lines)
    replacements = {"status": [f"status: {status}\n"], "tags": render_tags(tags)}

    new_blocks = [(key, replacements.get(key, lines)) for key, lines in blocks]
    present = {key for key, _ in blocks}
    missing = [(key, lines) for key, lines in replacements.items() if key not in present]
    new_fm = "".join(line for _, lines in [*new_blocks, *missing] for line in lines)

    task.path.write_text(f"---\n{new_fm}---\n{body}", encoding="utf-8")
    return load_task(task.path)


def create_task(
    tasks_dir: Path,
    title: str,
    priority: int,
    tags: tuple[str, ...],
    suffix: str | None,
    description: str = "",
) -> Task:
    huid = new_huid(suffix)
    if (tasks_dir / huid).exists():
        # HUIDs have a resolution of one second (see tasks/README.md), so the next second gives a new one.
        time.sleep(1)
        huid = new_huid(suffix)
        if (tasks_dir / huid).exists():
            raise SystemExit(
                f"ERROR: HUID {huid} is still in use after one second. Check the system clock or use -s SUFFIX."
            )

    task_dir = tasks_dir / huid
    task_dir.mkdir()
    lines = [
        "---\n",
        f"title: {quote_scalar(title)}\n",
        f"author: {quote_scalar(git_user_name())}\n",
        f"creation date: {datetime.now().astimezone().date().isoformat()}\n",
        "status: OPEN\n",
        f"priority: {priority}\n",
        *render_tags(tags),
        "---\n",
        "\n",
        *([f"{description}\n"] if description else []),
    ]
    (task_dir / TASK_FILE_NAME).write_text("".join(lines), encoding="utf-8")
    return load_task(task_dir / TASK_FILE_NAME)


def parse_tag_args(values: list[str] | None) -> tuple[str, ...]:
    """Accept `-t a -t b` as well as `-t "a, b"`, like tatr."""
    return tuple(tag for value in values or [] for tag in re.split(r"[,\s]+", value) if tag)


def match_prefix(tasks: list[Task], prefix: str) -> list[Task]:
    if not HUID_PREFIX_RE.match(prefix):
        raise SystemExit(f"ERROR: `{prefix}` is not a valid (partial) HUID")
    return [task for task in tasks if task.huid.startswith(prefix)]


# ----------------------------------------------------------------------------
# Filtering and updates
# ----------------------------------------------------------------------------

PRIORITY_OPS = {
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def has_filters(args: argparse.Namespace) -> bool:
    priority_filters = any(getattr(args, op) is not None for op in PRIORITY_OPS)
    return bool(
        args.any or args.tag or args.not_tag or args.tagged or args.untagged or args.huid or priority_filters
    )


def task_matches(task: Task, args: argparse.Namespace) -> bool:
    checks = (
        args.status == "all" or task.status == args.status.upper(),
        not args.huid or task.huid.startswith(args.huid),
        all(tag in task.tags for tag in parse_tag_args(args.tag)),
        not any(tag in task.tags for tag in parse_tag_args(args.not_tag)),
        not (args.tagged and not task.tags),
        not (args.untagged and task.tags),
        *(
            PRIORITY_OPS[op](task.priority, getattr(args, op))
            for op in PRIORITY_OPS
            if getattr(args, op) is not None
        ),
    )
    return all(checks)


def parse_update(source: str) -> list[str]:
    actions = [action.strip() for action in source.split(",") if action.strip()]
    for action in actions:
        if action not in ("open", "close") and not (action[0] in "+-" and len(action) > 1):
            raise SystemExit(f"ERROR: unknown update action `{action}` (use open, close, +tag, -tag)")
    return actions


def apply_update(task: Task, actions: list[str]) -> tuple[str, tuple[str, ...]]:
    status, tags = task.status, task.tags
    for action in actions:
        if action == "open":
            status = "OPEN"
        elif action == "close":
            status = "CLOSED"
        elif action.startswith("+") and action[1:] not in tags:
            tags = (*tags, action[1:])
        elif action.startswith("-"):
            tags = tuple(tag for tag in tags if tag != action[1:])
    return status, tags


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------


def cmd_ls(args: argparse.Namespace) -> int:
    actions = parse_update(args.update) if args.update else []
    if actions and not has_filters(args):
        print(
            "ERROR: --update without a filter is not allowed. Pass --any to update every task.",
            file=sys.stderr,
        )
        return 1

    tasks = [task for task in load_tasks(find_tasks_dir()) if task_matches(task, args)]
    sort_key = (lambda t: t.huid) if args.by_id else (lambda t: (t.priority, t.huid))
    tasks = sorted(tasks, key=sort_key, reverse=not args.asc)

    if not tasks:
        print("No matching tasks")
        return 0

    updated = 0
    for task in tasks:
        status, tags = apply_update(task, actions)
        if (status, tags) != (task.status, task.tags):
            print(write_task_fields(task, status, tags).report(note=args.update))
            updated += 1
        else:
            print(task.report())
    if updated:
        print(f"Updated {updated} task(s)")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    title = " ".join(args.title).strip() or DEFAULT_TITLE
    task = create_task(find_tasks_dir(), title, args.priority, parse_tag_args(args.tag), args.suffix)
    print(task.report())
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    tasks = match_prefix(load_tasks(find_tasks_dir()), args.huid)
    if not tasks:
        print(f"ERROR: no task matches the HUID prefix `{args.huid}`", file=sys.stderr)
        return 1
    for task in tasks:
        print(display_path(task.path) if args.path_only else task.report())
    return 0


def cmd_ref(args: argparse.Namespace) -> int:
    tasks_dir = find_tasks_dir()
    tasks = match_prefix(load_tasks(tasks_dir), args.huid)
    if not tasks:
        print(f"ERROR: no task matches the HUID prefix `{args.huid}`", file=sys.stderr)
        return 1

    repo_root = tasks_dir.parent
    for task in tasks:
        print(f"# {task.report()}")
        exclude = f":(exclude){TASKS_DIR_NAME}/{task.huid}"
        result = subprocess.run(
            ["git", "grep", "--untracked", "-n", "-I", "-F", "-e", task.huid, "--", ".", exclude],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode > 1:
            print(result.stderr, file=sys.stderr, end="")
            return result.returncode
        print(result.stdout or "No references found\n", end="")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    status = "CLOSED" if args.closed else "OPEN"
    tasks = [task for task in load_tasks(find_tasks_dir()) if task.status == status]
    counts = Counter(tag for task in tasks for tag in task.tags)
    untagged = sum(1 for task in tasks if not task.tags)

    print(f"{len(tasks)} {status} task(s), {untagged} without tags")
    width = max((len(tag) for tag in counts), default=0)
    for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {tag:<{width}}  {count}")
    return 0


def prompt_choice() -> str:
    """Ask what to do with one marker. Return a value of `TODO_ANSWERS`."""
    while True:
        try:
            answer = input(TODO_QUESTION).strip().lower()
        except EOFError:
            return "quit"
        if answer in TODO_ANSWERS:
            return TODO_ANSWERS[answer]
        print(f"Unknown answer `{answer}`. Type one of: {', '.join(TODO_ANSWERS)}.")


def strip_closer(text: str) -> str:
    closer = next((closer for closer in COMMENT_CLOSERS if text.endswith(closer)), "")
    return text.removesuffix(closer).rstrip()


def marker_title(line: str, match: re.Match[str]) -> str:
    return strip_closer(line[match.end() :].strip()).strip() or DEFAULT_TITLE


def block_closer(token: str) -> str:
    """The closer for a block comment opener (`/*` -> `*/`), or "" for line comments."""
    return next((closer for opener, closer in BLOCK_COMMENTS.items() if token.startswith(opener)), "")


def marker_opener(line: str, match: re.Match[str]) -> re.Match[str] | None:
    """The comment leader right before the marker, e.g. `# ` or `// `."""
    return COMMENT_LEADER_RE.search(line[: match.start()])


def marker_description(lines: list[str], index: int, match: re.Match[str]) -> list[str]:
    """Collect the comment lines right below the marker line, in the same comment style.

    Stops at the first line that is not such a comment, or that holds a new marker or task reference.
    """
    opener = marker_opener(lines[index], match)
    if not opener:
        return []
    token = opener.group(1)
    closer = block_closer(token)
    # Inside an unclosed block comment every line belongs to it until the closer, with or without a ` * ` prefix.
    in_block = bool(closer) and not lines[index].rstrip().endswith(closer)
    leaders = (token, *(("*",) if token.startswith("/*") else ()), "") if in_block else (token,)

    description: list[str] = []
    for line in lines[index + 1 :]:
        stripped = line.strip()
        # Also ends a ` * ` style block when the marker line itself has no opener (e.g. `/**` above it).
        if stripped.startswith(COMMENT_CLOSERS):
            break
        leader = next((leader for leader in leaders if stripped.startswith(leader)), None)
        if leader is None or MARKER_RE.search(line) or TASK_REF_RE.search(line):
            break
        description = [*description, strip_closer(stripped[len(leader) :].removeprefix(" "))]
        if in_block and stripped.endswith(closer):
            break
    return description


def task_ref_line(line: str, match: re.Match[str], huid: str) -> str:
    """Build `TASK(<HUID>)` with the indentation and comment style of the marker line."""
    body = line.rstrip("\r\n")
    newline = line[len(body) :]
    indent = body[: len(body) - len(body.lstrip())]
    opener = marker_opener(body, match)
    if not opener:
        return f"{indent}TASK({huid}){newline}"
    closer = block_closer(opener.group(1))
    return f"{indent}{opener.group(0)}TASK({huid}){f' {closer}' if closer else ''}{newline}"


def cmd_todo(args: argparse.Namespace) -> int:
    """Create tasks from `TODO ` / `FIXME ` markers and insert a `TASK(<HUID>)` line above each one."""
    tasks_dir = find_tasks_dir()
    for file_name in args.files:
        path = Path(file_name)
        lines = path.read_text(encoding="utf-8", newline="").splitlines(keepends=True)
        yes_to_file = args.yes
        index = 0
        while index < len(lines):
            line = lines[index]
            match = MARKER_RE.search(line)
            already_linked = index > 0 and TASK_REF_RE.search(lines[index - 1])
            if not match or already_linked:
                index += 1
                continue

            title = marker_title(line, match)
            description = marker_description(lines, index, match)
            print(f"{display_path(path)}:{index + 1}: {match.group(1)} marker without a task: {title}")
            print("".join(lines[max(0, index - 2) : index + len(description) + 3]), end="")

            if not yes_to_file:
                choice = prompt_choice()
                if choice == "quit":
                    return 0
                if choice == "skip-file":
                    break
                if choice == "keep":
                    index += 1
                    continue
                yes_to_file = choice == "convert-file"

            task = create_task(
                tasks_dir,
                title,
                DEFAULT_PRIORITY,
                MARKER_TAGS[match.group(1)],
                args.suffix,
                description="\n".join(description).strip("\n"),
            )
            print(task.report())
            lines = [*lines[:index], task_ref_line(line, match, task.huid), *lines[index:]]
            path.write_text("".join(lines), encoding="utf-8", newline="")
            index += 2
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--status", choices=["open", "closed", "all"], default="open", help="default: open")
    parser.add_argument(
        "-c", "--closed", dest="status", action="store_const", const="closed", help="--status closed"
    )
    parser.add_argument("-t", "--tag", action="append", help="must have tag (repeatable, AND)")
    parser.add_argument("-x", "--not-tag", action="append", help="must not have tag (repeatable)")
    parser.add_argument("--tagged", action="store_true", help="has at least one tag")
    parser.add_argument("--untagged", action="store_true", help="has no tags")
    parser.add_argument("--huid", help="HUID prefix")
    parser.add_argument("--any", action="store_true", help="match every task (needed for --update on all)")
    for op in PRIORITY_OPS:
        parser.add_argument(f"--{op}", type=int, metavar="N", help=f"priority {op} N")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="just task", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    ls = sub.add_parser("ls", help="list (and update) tasks, sorted by priority (high first)")
    add_filter_args(ls)
    ls.add_argument("-a", "--asc", action="store_true", help="ascending order")
    ls.add_argument("--by-id", action="store_true", help="sort by HUID instead of priority")
    ls.add_argument("-u", "--update", metavar="ACTIONS", help="comma-separated: open, close, +tag, -tag")
    ls.set_defaults(run=cmd_ls)

    new = sub.add_parser("new", help="create a new task")
    new.add_argument("title", nargs="*", help=f"task title (default: {DEFAULT_TITLE})")
    new.add_argument(
        "-p", "--priority", type=int, default=DEFAULT_PRIORITY, help=f"default: {DEFAULT_PRIORITY}"
    )
    new.add_argument("-t", "--tag", action="append", help="tag to add (repeatable or comma-separated)")
    new.add_argument("-s", "--suffix", help="HUID suffix, e.g. your handle")
    new.set_defaults(run=cmd_new)

    find = sub.add_parser("find", help="find tasks by HUID prefix, regardless of status")
    find.add_argument("huid", help="full or partial HUID")
    find.add_argument("--path-only", action="store_true", help="print only the path to TASK.md")
    find.set_defaults(run=cmd_find)

    ref = sub.add_parser("ref", help="show places in the repo that reference a task")
    ref.add_argument("huid", help="full or partial HUID")
    ref.set_defaults(run=cmd_ref)

    summary = sub.add_parser("summary", help="count tasks per tag")
    summary.add_argument("-c", "--closed", action="store_true", help="summarize closed tasks")
    summary.set_defaults(run=cmd_summary)

    todo = sub.add_parser("todo", help="create tasks from `TODO ` and `FIXME ` markers in files")
    todo.add_argument("files", nargs="+", help="files to scan")
    todo.add_argument("-y", "--yes", action="store_true", help="convert every marker without asking")
    todo.add_argument("-s", "--suffix", help="HUID suffix, e.g. your handle")
    todo.set_defaults(run=cmd_todo)

    return parser


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    argv = sys.argv[1:]
    if argv and argv[0] == "help":
        argv = [*argv[1:], "--help"]
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
