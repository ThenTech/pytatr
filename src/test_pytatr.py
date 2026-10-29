#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ThenTech
# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Tests for `src/pytatr.py`, based on `tasks/README.md` and `README.md`.

Run them with `just test` or `uv run src/test_pytatr.py [--readme PATH] [-v] [-k PATTERN]`.

`--readme PATH` replaces `tasks/README.md` of this repository with another copy, for example the
`tasks/README.md` of a repository that uses pytatr as a submodule. The other arguments go to `unittest`.

Each test class has one of two prefixes:

- `TestTatr*`: behavior from the tatr specification (HUIDs, statuses, priority, update language, commands).
  When you reimplement a change from tatr, change or add tests in these classes.
- `TestLocal*`: the differences from tatr that `README.md` defines (YAML frontmatter, flag filters,
  `--any`, `TASK(<HUID>)` references, the docs). A port from tatr must not break these tests.
  To run only these tests, use `-k Local`.

All tests use a temporary folder. They do not read or write the tasks in this repository.
`TestLocalDocs` reads `tasks/README.md` and `README.md`, but does not change them.
"""

import argparse
import contextlib
import importlib.util
import io
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest import mock

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent
SCRIPT = TOOL_DIR / "pytatr.py"
README = REPO_ROOT / "tasks" / "README.md"
OVERVIEW = REPO_ROOT / "README.md"
HAS_GIT = shutil.which("git") is not None


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tasks_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tasks = load_script()
REAL_NEW_HUID = tasks.new_huid
REAL_GET_GIT = tasks.get_git
REAL_GIT_USER_NAME = tasks.git_user_name


def fake_huid(index: int, suffix: str | None = None) -> str:
    huid = f"20261027-12{index:04d}"
    return f"{huid}-{suffix}" if suffix else huid


class TaskTestCase(unittest.TestCase):
    """Run each test in a new temporary folder that contains `tasks/`, with a predictable HUID clock."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.tasks_dir = self.root / "tasks"
        self.tasks_dir.mkdir()

        previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_cwd)

        clock = itertools.count()
        self.huid_mock = self.patch(
            tasks, "new_huid", side_effect=lambda suffix: fake_huid(next(clock), suffix)
        )
        self.sleep_mock = self.patch(tasks.time, "sleep")
        self.patch(tasks, "git_user_name", return_value="Test User")

    def patch(self, target: object, name: str, **kwargs: object) -> mock.MagicMock:
        patcher = mock.patch.object(target, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def add_task(
        self,
        huid: str,
        title: str = "Task",
        *,
        status: str = "OPEN",
        priority: int = 100,
        tags: tuple[str, ...] = (),
        extra: str = "",
        body: str = "",
    ) -> Path:
        tag_lines = "".join(f"  - {tag}\n" for tag in tags)
        tags_block = f"tags:\n{tag_lines}" if tags else "tags: []\n"
        text = (
            f"---\ntitle: {title}\nauthor: Someone\ncreation date: 2026-10-27\nstatus: {status}\n"
            f"priority: {priority}\n{tags_block}{extra}---\n{body}"
        )
        return self.write(f"tasks/{huid}/TASK.md", text)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                args = tasks.build_parser().parse_args(list(argv))
                code = args.run(args)
            except SystemExit as error:
                if isinstance(error.code, str):
                    print(error.code, file=sys.stderr)
                code = error.code if isinstance(error.code, int) else 1
        return code, stdout.getvalue(), stderr.getvalue()

    def listed(self, *argv: str) -> list[str]:
        """The HUIDs that `ls` prints, in output order."""
        code, out, err = self.run_cli("ls", *argv)
        self.assertEqual(code, 0, err)
        return re.findall(r"^tasks/([^/]+)/TASK\.md:1:", out, re.MULTILINE)

    def snapshot(self) -> dict[str, str]:
        return {task.huid: task.path.read_text(encoding="utf-8") for task in tasks.load_tasks(self.tasks_dir)}


# ----------------------------------------------------------------------------
# Docs and script must agree
# ----------------------------------------------------------------------------


class TestLocalDocs(TaskTestCase):
    """`tasks/README.md` and `README.md` describe the same system as the script."""

    @classmethod
    def setUpClass(cls) -> None:
        # Read when the tests run, not on import, so that `--readme` can select the file.
        cls.readme = README.read_text(encoding="utf-8")
        cls.overview = OVERVIEW.read_text(encoding="utf-8")

    def test_huid_pattern_matches_docs(self) -> None:
        pattern = tasks.HUID_RE.pattern.removeprefix("^").removesuffix("$")
        self.assertIn(pattern, self.readme)
        self.assertIn(pattern, self.overview)

    def test_documented_commands_exist(self) -> None:
        commands = set(re.findall(r"`just task (\w+)", self.readme + self.overview)) - {"help"}
        self.assertTrue(commands)
        for command in sorted(commands):
            with self.subTest(command=command):
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    tasks.build_parser().parse_args([command, "--help"])
                self.assertEqual(raised.exception.code, 0)

    def test_documented_filters_exist(self) -> None:
        table = self.readme.split("Filters for `just tasks`", 1)[1].split("\n\n", 2)[1]
        flags = set(re.findall(r"`(-{1,2}[a-z][\w-]*)", table))
        self.assertTrue(flags)
        help_text = io.StringIO()
        with contextlib.redirect_stdout(help_text), self.assertRaises(SystemExit):
            tasks.build_parser().parse_args(["ls", "--help"])
        for flag in sorted(flags):
            with self.subTest(flag=flag):
                self.assertRegex(help_text.getvalue(), rf"(?<![\w-]){re.escape(flag)}\b")

    def test_frontmatter_template_matches_new_tasks(self) -> None:
        template = re.search(r"```markdown\n---\n(.*?)\n---", self.readme, re.DOTALL).group(1)
        expected = [line.split(":")[0] for line in template.splitlines() if not line.startswith(" ")]
        task = tasks.create_task(self.tasks_dir, "Title", 100, ("a",), None)
        frontmatter = task.path.read_text(encoding="utf-8").split("---\n")[1]
        self.assertEqual(re.findall(r"^([^\s-][^:]*):", frontmatter, re.MULTILINE), expected)


# ----------------------------------------------------------------------------
# HUIDs
# ----------------------------------------------------------------------------


class TestTatrHuid(TaskTestCase):
    def test_new_huid_is_current_utc_time(self) -> None:
        before = datetime.now(UTC).replace(microsecond=0)
        huid = REAL_NEW_HUID(None)
        after = datetime.now(UTC)
        stamp = datetime.strptime(huid, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        self.assertTrue(before <= stamp <= after, huid)

    def test_new_huid_with_suffix(self) -> None:
        huid = REAL_NEW_HUID("thentech")
        self.assertTrue(huid.endswith("-thentech"))
        self.assertRegex(huid, tasks.HUID_RE)

    def test_git_user_name_uses_os_home_folder(self) -> None:
        # A shell such as MSYS2 can set HOME to a folder without the global .gitconfig (Windows).
        run_mock = self.patch(tasks.subprocess, "run")
        run_mock.return_value.stdout = "Home User\n"
        with mock.patch.dict(os.environ, {"HOME": str(self.root)}):
            self.assertEqual(REAL_GIT_USER_NAME(), "Home User")
            self.assertEqual(run_mock.call_args.kwargs["env"]["HOME"], str(Path.home()))

    def test_huid_pattern(self) -> None:
        for huid in ("20261026-101500", "20261026-101500-thentech", "20261026-101500-a-b-1"):
            with self.subTest(huid=huid):
                self.assertRegex(huid, tasks.HUID_RE)
        for name in (
            "2026102-101500",
            "20261026101500",
            "20261026-101500_x",
            "20261026-101500-a b",
            "README.md",
        ):
            with self.subTest(name=name):
                self.assertNotRegex(name, tasks.HUID_RE)

    def test_collision_waits_one_second(self) -> None:
        (self.tasks_dir / fake_huid(0)).mkdir()
        self.huid_mock.side_effect = [fake_huid(0), fake_huid(1)]
        task = tasks.create_task(self.tasks_dir, "Title", 100, (), None)
        self.assertEqual(task.huid, fake_huid(1))
        self.sleep_mock.assert_called_once_with(1)

    def test_collision_gives_up_after_one_retry(self) -> None:
        (self.tasks_dir / fake_huid(0)).mkdir()
        self.huid_mock.side_effect = [fake_huid(0), fake_huid(0)]
        with self.assertRaises(SystemExit):
            tasks.create_task(self.tasks_dir, "Title", 100, (), None)
        self.assertEqual([path.name for path in self.tasks_dir.iterdir()], [fake_huid(0)])


# ----------------------------------------------------------------------------
# TASK.md format
# ----------------------------------------------------------------------------


class TestLocalFrontmatter(TaskTestCase):
    def test_new_task_file(self) -> None:
        task = tasks.create_task(self.tasks_dir, "Fix login", 150, ("bug", "web"), None, description="Line 1")
        today = datetime.now().astimezone().date().isoformat()
        expected = (
            f"---\ntitle: Fix login\nauthor: Test User\ncreation date: {today}\nstatus: OPEN\n"
            "priority: 150\ntags:\n  - bug\n  - web\n---\n\nLine 1\n"
        )
        self.assertEqual(task.path.read_text(encoding="utf-8"), expected)

    def test_new_task_without_tags(self) -> None:
        task = tasks.create_task(self.tasks_dir, "Title", 100, (), None)
        self.assertIn("\ntags: []\n", task.path.read_text(encoding="utf-8"))
        self.assertEqual(task.tags, ())

    def test_titles_survive_quoting(self) -> None:
        titles = (
            "Plain title",
            "Fix: the login",
            "#hashtag",
            "- dash",
            "trailing space ",
            " leading space",
            '"quoted"',
            "it's",
            "a # comment",
            "[bracket]",
            "{brace}",
            "50% done",
            "@user",
            "Unicode ümläut ✓",
            "back\\slash",
        )
        for title in titles:
            with self.subTest(title=title):
                task = tasks.create_task(self.tasks_dir, title, 100, (), None)
                self.assertEqual(tasks.load_task(task.path).title, title)

    def test_plain_title_is_not_quoted(self) -> None:
        task = tasks.create_task(self.tasks_dir, "Plain title", 100, (), None)
        self.assertIn("\ntitle: Plain title\n", task.path.read_text(encoding="utf-8"))

    def test_tag_formats(self) -> None:
        cases = {
            "tags: [a, b]": ("a", "b"),
            "tags: a, b": ("a", "b"),
            "tags: a b": ("a", "b"),
            "tags:\n  - a\n  - b": ("a", "b"),
            "tags:\n  - '#a'\n  - \"b\"": ("a", "b"),
            "tags: []": (),
            "tags:": (),
        }
        for index, (block, expected) in enumerate(cases.items()):
            with self.subTest(block=block):
                path = self.write(f"tasks/{fake_huid(index)}/TASK.md", f"---\ntitle: T\n{block}\n---\n")
                self.assertEqual(tasks.load_task(path).tags, expected)

    def test_defaults_for_missing_properties(self) -> None:
        task = tasks.load_task(self.write(f"tasks/{fake_huid(0)}/TASK.md", "---\ntitle: T\n---\n"))
        self.assertEqual((task.status, task.priority, task.tags), ("OPEN", tasks.DEFAULT_PRIORITY, ()))

    def test_status_is_case_insensitive(self) -> None:
        task = tasks.load_task(self.add_task(fake_huid(0), status="closed"))
        self.assertEqual(task.status, "CLOSED")

    def test_invalid_priority_warns_and_uses_default(self) -> None:
        path = self.write(f"tasks/{fake_huid(0)}/TASK.md", "---\ntitle: T\npriority: high\n---\n")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            task = tasks.load_task(path)
        self.assertEqual(task.priority, tasks.DEFAULT_PRIORITY)
        self.assertIn("WARNING: invalid priority", stderr.getvalue())

    def test_load_tasks_ignores_other_entries(self) -> None:
        self.write("tasks/README.md", "# Tasks\n")
        self.write("tasks/notes/TASK.md", "---\ntitle: Not a HUID\n---\n")
        (self.tasks_dir / fake_huid(9)).mkdir()
        self.add_task(fake_huid(2))
        self.add_task(fake_huid(1))
        self.assertEqual(
            [task.huid for task in tasks.load_tasks(self.tasks_dir)], [fake_huid(1), fake_huid(2)]
        )

    def test_update_changes_only_status_and_tags(self) -> None:
        path = self.add_task(
            fake_huid(0),
            title='"Fix: login"',
            tags=("old",),
            extra="assignee: me\ndue date: 2026-11-01\n",
            body="\nBody text.\n\n---\n\nMore text.\n",
        )
        tasks.write_task_fields(tasks.load_task(path), "CLOSED", ("new", "done"))
        expected = (
            '---\ntitle: "Fix: login"\nauthor: Someone\ncreation date: 2026-10-27\nstatus: CLOSED\n'
            "priority: 100\ntags:\n  - new\n  - done\nassignee: me\ndue date: 2026-11-01\n---\n"
            "\nBody text.\n\n---\n\nMore text.\n"
        )
        self.assertEqual(path.read_text(encoding="utf-8"), expected)

    def test_update_adds_missing_status_and_tags(self) -> None:
        path = self.write(f"tasks/{fake_huid(0)}/TASK.md", "---\ntitle: T\nassignee: me\n---\nBody\n")
        task = tasks.write_task_fields(tasks.load_task(path), "CLOSED", ("x",))
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            "---\ntitle: T\nassignee: me\nstatus: CLOSED\ntags:\n  - x\n---\nBody\n",
        )
        self.assertEqual((task.status, task.tags), ("CLOSED", ("x",)))


class TestTatrTitleFallback(TaskTestCase):
    """A task without a `title` property uses the tatr `# heading`, then the HUID."""

    def test_title_from_heading(self) -> None:
        path = self.write(
            f"tasks/{fake_huid(0)}/TASK.md", "---\nstatus: OPEN\n---\n# Heading title\n\nText\n"
        )
        self.assertEqual(tasks.load_task(path).title, "Heading title")

    def test_title_from_huid(self) -> None:
        path = self.write(f"tasks/{fake_huid(0)}/TASK.md", "---\nstatus: OPEN\n---\nText\n")
        self.assertEqual(tasks.load_task(path).title, fake_huid(0))


# ----------------------------------------------------------------------------
# Update language
# ----------------------------------------------------------------------------


class TestTatrUpdateLanguage(TaskTestCase):
    def test_parse_valid_actions(self) -> None:
        self.assertEqual(tasks.parse_update("open, close,+a,-b,"), ["open", "close", "+a", "-b"])

    def test_parse_invalid_actions(self) -> None:
        for source in ("reopen", "+", "-", "tag", "open,+"):
            with self.subTest(source=source), self.assertRaises(SystemExit):
                tasks.parse_update(source)

    def test_apply_actions_in_order(self) -> None:
        task = tasks.load_task(self.add_task(fake_huid(0), tags=("a", "b")))
        result = tasks.apply_update(task, ["close", "+c", "-a", "+b", "+c"])
        self.assertEqual(result, ("CLOSED", ("b", "c")))
        self.assertEqual(tasks.apply_update(task, ["close", "open"]), ("OPEN", ("a", "b")))


# ----------------------------------------------------------------------------
# Listing, filters and mass updates
# ----------------------------------------------------------------------------


class TestLocalListing(TaskTestCase):
    A, B, C, D = "20261027-100000", "20261027-100001", "20261027-100002", "20261027-100003-x"

    def setUp(self) -> None:
        super().setUp()
        self.add_task(self.A, "Alpha", priority=100, tags=("bug", "api"))
        self.add_task(self.B, "Beta", priority=50, tags=("web",))
        self.add_task(self.C, "Gamma", status="CLOSED", priority=200, tags=("bug",))
        self.add_task(self.D, "Delta", priority=150)

    def test_sort_order(self) -> None:
        a, b, d = self.A, self.B, self.D
        cases = {
            (): [d, a, b],
            ("-a",): [b, a, d],
            ("--by-id",): [d, b, a],
            ("--by-id", "-a"): [a, b, d],
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(self.listed(*argv), expected)

    def test_filters(self) -> None:
        a, b, c, d = self.A, self.B, self.C, self.D
        cases = {
            ("--status", "all"): [c, d, a, b],
            ("--status", "closed"): [c],
            ("-c",): [c],
            ("-t", "bug"): [a],
            ("-t", "bug", "--status", "all"): [c, a],
            ("-t", "bug", "-t", "api"): [a],
            ("-t", "bug,api"): [a],
            ("-t", "bug", "-t", "web"): [],
            ("-x", "bug"): [d, b],
            ("--tagged",): [a, b],
            ("--untagged",): [d],
            ("--lt", "100"): [b],
            ("--le", "100"): [a, b],
            ("--gt", "100"): [d],
            ("--ge", "100"): [d, a],
            ("--eq", "50"): [b],
            ("--ne", "50"): [d, a],
            ("--huid", "20261027-100003"): [d],
            ("--status", "all", "-t", "bug", "--gt", "150"): [c],
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(self.listed(*argv), expected)

    def test_output_format(self) -> None:
        cases = {
            self.A: f"tasks/{self.A}/TASK.md:1: OPEN [PRIORITY: 100] [bug, api] Alpha",
            self.B: f"tasks/{self.B}/TASK.md:1: OPEN [PRIORITY:  50] [web] Beta",
            self.D: f"tasks/{self.D}/TASK.md:1: OPEN [PRIORITY: 150] Delta",
        }
        for huid, expected in cases.items():
            with self.subTest(huid=huid):
                _, out, _ = self.run_cli("ls", "--huid", huid)
                self.assertEqual(out.splitlines(), [expected])

    def test_no_match(self) -> None:
        self.assertEqual(self.run_cli("ls", "--eq", "1")[1], "No matching tasks\n")

    def test_update_needs_a_filter(self) -> None:
        before = self.snapshot()
        code, _, err = self.run_cli("ls", "-u", "close")
        self.assertEqual(code, 1)
        self.assertIn("--any", err)
        self.assertEqual(self.snapshot(), before)

    def test_update_only_changes_matching_tasks(self) -> None:
        before = self.snapshot()
        code, out, _ = self.run_cli("ls", "-t", "web", "-u", "close,+done")
        self.assertEqual(code, 0)
        self.assertIn(f"tasks/{self.B}/TASK.md:1: <UPDATED: close,+done> CLOSED", out)
        self.assertIn("Updated 1 task(s)", out)
        task = tasks.load_task(self.tasks_dir / self.B / "TASK.md")
        self.assertEqual((task.status, task.tags), ("CLOSED", ("web", "done")))
        after = self.snapshot()
        for huid in (self.A, self.C, self.D):
            self.assertEqual(after[huid], before[huid])

    def test_update_any_uses_the_status_filter(self) -> None:
        before = self.snapshot()
        code, out, _ = self.run_cli("ls", "--any", "-u", "+triage")
        self.assertEqual(code, 0)
        self.assertIn("Updated 3 task(s)", out)
        self.assertEqual(self.snapshot()[self.C], before[self.C])

    def test_update_without_change_does_not_write(self) -> None:
        before = self.snapshot()
        _, out, _ = self.run_cli("ls", "-t", "bug", "-u", "+bug")
        self.assertNotIn("Updated", out)
        self.assertEqual(self.snapshot(), before)


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------


class TestTatrCommands(TaskTestCase):
    def test_new(self) -> None:
        code, out, _ = self.run_cli("new", "Fix", "login", "-p", "150", "-t", "bug,web", "-s", "me")
        self.assertEqual(code, 0)
        [task] = tasks.load_tasks(self.tasks_dir)
        self.assertEqual(task.huid, fake_huid(0, "me"))
        self.assertEqual((task.title, task.priority, task.tags), ("Fix login", 150, ("bug", "web")))
        self.assertEqual(out, f"tasks/{task.huid}/TASK.md:1: OPEN [PRIORITY: 150] [bug, web] Fix login\n")

    def test_new_defaults(self) -> None:
        self.run_cli("new")
        [task] = tasks.load_tasks(self.tasks_dir)
        self.assertEqual(
            (task.title, task.priority, task.tags), (tasks.DEFAULT_TITLE, tasks.DEFAULT_PRIORITY, ())
        )

    def test_find(self) -> None:
        self.add_task("20261027-100000", "Open")
        self.add_task("20261027-100001", "Closed", status="CLOSED")
        _, out, _ = self.run_cli("find", "20261027-10")
        self.assertEqual(len(out.splitlines()), 2)
        _, out, _ = self.run_cli("find", "20261027-100001", "--path-only")
        self.assertEqual(out, "tasks/20261027-100001/TASK.md\n")

    def test_find_errors(self) -> None:
        self.add_task("20261027-100000")
        code, _, err = self.run_cli("find", "1999")
        self.assertEqual(code, 1)
        self.assertIn("no task matches the HUID prefix", err)
        code, _, err = self.run_cli("find", "bad/prefix")
        self.assertEqual(code, 1)
        self.assertIn("not a valid", err)

    def test_summary(self) -> None:
        self.add_task(fake_huid(0), tags=("bug", "api"))
        self.add_task(fake_huid(1), tags=("bug",))
        self.add_task(fake_huid(2))
        self.add_task(fake_huid(3), status="CLOSED", tags=("web",))
        _, out, _ = self.run_cli("summary")
        self.assertEqual(out.splitlines(), ["3 OPEN task(s), 1 without tags", "  bug  2", "  api  1"])
        _, out, _ = self.run_cli("summary", "-c")
        self.assertEqual(out.splitlines(), ["1 CLOSED task(s), 0 without tags", "  web  1"])

    def test_summary_sorts_equal_counts_by_tag(self) -> None:
        self.add_task(fake_huid(0), tags=("zeta", "alpha"))
        _, out, _ = self.run_cli("summary")
        self.assertEqual(out.splitlines()[1:], ["  alpha  1", "  zeta   1"])

    @unittest.skipUnless(HAS_GIT, "git is not available")
    def test_ref(self) -> None:
        subprocess.run([REAL_GET_GIT(), "init", "-q"], cwd=self.root, check=True)
        huid, other = fake_huid(0), fake_huid(1)
        self.add_task(huid)
        self.add_task(other)
        self.write("src/app.py", f"# TASK({huid})\n# TODO x\n")
        self.write(f"tasks/{huid}/notes.md", f"Self reference {huid}\n")
        code, out, _ = self.run_cli("ref", huid)
        self.assertEqual(code, 0)
        self.assertIn(f"src/app.py:1:# TASK({huid})", out)
        self.assertNotIn("notes.md", out)
        _, out, _ = self.run_cli("ref", other)
        self.assertIn("No references found", out)


class TestLocalTaskDiscovery(TaskTestCase):
    """The commands find tasks that people write by hand, and only in HUID folders."""

    def manual_task_text(self, title: str) -> str:
        """Fill in the frontmatter template from `tasks/README.md`, as a person or an LLM does."""
        readme = README.read_text(encoding="utf-8")
        template = re.search(r"```markdown\n(---\n.*?\n---\n)", readme, re.DOTALL).group(1)
        values = {
            "<title>": title,
            "<current git user name>": "Manual Author",
            "<current date, YYYY-MM-DD>": "2026-10-27",
            "<tag>": "manual",
        }
        for placeholder, value in values.items():
            template = template.replace(placeholder, value)
        self.assertNotIn("<", template)
        return f"{template}\nWritten by hand.\n"

    def test_manual_task_is_found(self) -> None:
        huid = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.write(f"tasks/{huid}/TASK.md", self.manual_task_text("Hand-written task"))
        expected = f"tasks/{huid}/TASK.md:1: OPEN [PRIORITY: 100] [manual] Hand-written task"

        self.assertEqual(self.run_cli("ls")[1].splitlines(), [expected])
        self.assertEqual(self.run_cli("find", huid[:8])[1].splitlines(), [expected])
        self.assertEqual(self.listed("-t", "manual"), [huid])
        self.assertIn("  manual  1", self.run_cli("summary")[1])

    def test_manual_task_with_suffix_is_found(self) -> None:
        huid = "20261027-120000-thentech"
        self.write(f"tasks/{huid}/TASK.md", self.manual_task_text("With suffix"))
        self.assertEqual(self.listed(), [huid])
        self.assertEqual(
            self.run_cli("find", "20261027-120000-then", "--path-only")[1], f"tasks/{huid}/TASK.md\n"
        )

    def test_folders_that_are_not_huids_are_ignored(self) -> None:
        names = (
            "notes",
            "archive",
            ".obsidian",
            "2026-10-27",
            "20261027",
            "20261027-1200",
            "20261027-12000000",
            "20261027_120000",
            "20261027-120000_x",
            "20261027-120000-bad.suffix",
            "x20261027-120000",
        )
        for name in names:
            self.write(f"tasks/{name}/TASK.md", self.manual_task_text(f"Not a task {name}"))
        self.write("tasks/20261027-130000/TASK.md", self.manual_task_text("Real task"))

        self.assertEqual(self.listed("--status", "all"), ["20261027-130000"])
        self.assertEqual(self.listed("--status", "all", "--huid", "2026"), ["20261027-130000"])
        _, out, _ = self.run_cli("find", "2026")
        self.assertEqual(out, "tasks/20261027-130000/TASK.md:1: OPEN [PRIORITY: 100] [manual] Real task\n")
        self.assertTrue(self.run_cli("summary")[1].startswith("1 OPEN task(s),"))
        self.assertEqual(self.run_cli("find", "notes")[0], 1)


# ----------------------------------------------------------------------------
# TODO / FIXME markers
# ----------------------------------------------------------------------------


class TestLocalTodo(TaskTestCase):
    def todo(self, text: str, *, name: str = "src/file.py", yes: bool = True) -> str:
        self.write(name, text)
        self.run_cli("todo", name, *(["-y"] if yes else []))
        return (self.root / name).read_bytes().decode("utf-8")

    def task(self, index: int) -> tuple[object, str]:
        path = self.tasks_dir / fake_huid(index) / "TASK.md"
        text = path.read_text(encoding="utf-8")
        return tasks.load_task(path), text.split("---\n", 2)[2].strip("\n")

    def test_python_comment(self) -> None:
        source = "def f():\n    # TODO replace the polling loop\n    # The interval causes lag.\n    poll()\n"
        result = self.todo(source)
        self.assertEqual(
            result,
            f"def f():\n    # TASK({fake_huid(0)})\n    # TODO replace the polling loop\n"
            "    # The interval causes lag.\n    poll()\n",
        )
        task, description = self.task(0)
        self.assertEqual((task.title, task.tags), ("replace the polling loop", ()))
        self.assertEqual(description, "The interval causes lag.")

    def test_fixme_gets_bug_tag(self) -> None:
        result = self.todo("// FIXME the poller leaks a connection\nint x;\n", name="src/file.c")
        self.assertTrue(result.startswith(f"// TASK({fake_huid(0)})\n// FIXME"))
        task, _ = self.task(0)
        self.assertEqual((task.title, task.tags), ("the poller leaks a connection", ("bug",)))

    def test_next_marker_starts_a_new_task(self) -> None:
        result = self.todo("# TODO first\n# description one\n# FIXME second\npoll()\n")
        self.assertEqual(
            result,
            f"# TASK({fake_huid(0)})\n# TODO first\n# description one\n"
            f"# TASK({fake_huid(1)})\n# FIXME second\npoll()\n",
        )
        self.assertEqual(self.task(0)[1], "description one")
        self.assertEqual((self.task(1)[0].tags, self.task(1)[1]), (("bug",), ""))

    def test_comment_styles(self) -> None:
        cases = {
            "/* TODO fix the thing */\nint x;\n": ("/* TASK({}) */\n", "fix the thing"),
            "<!-- TODO add alt text -->\n<img>\n": ("<!-- TASK({}) -->\n", "add alt text"),
            "-- TODO add an index\nSELECT 1;\n": ("-- TASK({})\n", "add an index"),
            "; TODO check the value\nmov ax, 1\n": ("; TASK({})\n", "check the value"),
            "TODO plain text marker\n": ("TASK({})\n", "plain text marker"),
        }
        for index, (source, (ref_line, title)) in enumerate(cases.items()):
            with self.subTest(source=source):
                result = self.todo(source, name=f"src/file{index}.txt")
                self.assertEqual(result, ref_line.format(fake_huid(index)) + source)
                self.assertEqual(self.task(index)[0].title, title)

    def test_block_comment_description_stops_at_closer(self) -> None:
        cases = {
            "/* TODO refactor the parser\n * It is too slow.\n */\nint x;\n": "It is too slow.",
            "/* TODO refactor the parser\n   It is too slow. */\nint x;\n": "It is too slow.",
            "/**\n * TODO handle errors\n * Retry three times.\n */\nint x;\n": "Retry three times.",
        }
        for index, (source, expected) in enumerate(cases.items()):
            with self.subTest(source=source):
                self.todo(source, name=f"src/file{index}.c")
                self.assertEqual(self.task(index)[1], expected)

    def test_marker_needs_a_space(self) -> None:
        source = "# TODO: no space\n# TODO\n# TODOS later\n"
        self.assertEqual(self.todo(source), source)
        self.assertEqual(tasks.load_tasks(self.tasks_dir), [])

    def test_second_run_changes_nothing(self) -> None:
        first = self.todo("# TODO once\n")
        self.run_cli("todo", "src/file.py", "-y")
        self.assertEqual(self.read("src/file.py"), first)
        self.assertEqual(len(tasks.load_tasks(self.tasks_dir)), 1)

    def test_line_endings_are_kept(self) -> None:
        result = self.todo("x = 1\r\n# TODO once\r\ny = 2\r\n")
        self.assertEqual(result, f"x = 1\r\n# TASK({fake_huid(0)})\r\n# TODO once\r\ny = 2\r\n")

    def test_prompt_answers(self) -> None:
        source = "# TODO first\nx = 1\n# TODO second\n"
        with mock.patch("builtins.input", side_effect=["n", "y"]):
            result = self.todo(source, yes=False)
        self.assertEqual(result, f"# TODO first\nx = 1\n# TASK({fake_huid(0)})\n# TODO second\n")
        self.assertEqual(self.task(0)[0].title, "second")

    def test_prompt_quit(self) -> None:
        source = "# TODO first\n# TODO second\n"
        with mock.patch("builtins.input", side_effect=["q"]):
            self.assertEqual(self.todo(source, yes=False), source)
        self.assertEqual(tasks.load_tasks(self.tasks_dir), [])

    def test_prompt_all_converts_the_rest_of_the_file(self) -> None:
        source = "# TODO first\n# TODO second\n# TODO third\n"
        with mock.patch("builtins.input", side_effect=["n", "a"]) as answers:
            self.todo(source, yes=False)
        self.assertEqual(answers.call_count, 2)
        self.assertEqual([task.title for task in tasks.load_tasks(self.tasks_dir)], ["second", "third"])

    def test_prompt_skip_leaves_the_rest_of_the_file(self) -> None:
        source = "# TODO first\n# TODO second\n"
        with mock.patch("builtins.input", side_effect=["s"]):
            self.assertEqual(self.todo(source, yes=False), source)
        self.assertEqual(tasks.load_tasks(self.tasks_dir), [])

    def test_prompt_asks_again_after_an_invalid_answer(self) -> None:
        with mock.patch("builtins.input", side_effect=["maybe", "Y"]):
            self.todo("# TODO once\n", yes=False)
        self.assertEqual(len(tasks.load_tasks(self.tasks_dir)), 1)

    def test_prompt_end_of_input_quits(self) -> None:
        source = "# TODO once\n"
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertEqual(self.todo(source, yes=False), source)


# ----------------------------------------------------------------------------
# Script entry point
# ----------------------------------------------------------------------------


class TestTatrScript(unittest.TestCase):
    """Run the real script in a separate process, with the real clock and git."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "tasks").mkdir()

    def run_script(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_help(self) -> None:
        result = self.run_script("help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("ls", "new", "find", "ref", "summary", "todo"):
            self.assertIn(command, result.stdout)

    @unittest.skipUnless(HAS_GIT, "git is not available")
    def test_new_uses_git_user_and_real_huid(self) -> None:
        subprocess.run([REAL_GET_GIT(), "init", "-q"], cwd=self.root, check=True)
        subprocess.run([REAL_GET_GIT(), "config", "user.name", "Script User"], cwd=self.root, check=True)
        result = self.run_script("new", "Real", "task", "-t", "x")
        self.assertEqual(result.returncode, 0, result.stderr)
        [folder] = (self.root / "tasks").iterdir()
        self.assertRegex(folder.name, tasks.HUID_RE)
        self.assertIn("\nauthor: Script User\n", (folder / "TASK.md").read_text(encoding="utf-8"))

    def test_without_tasks_folder(self) -> None:
        (self.root / "tasks").rmdir()
        result = self.run_script("ls")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no tasks/ folder in", result.stderr)


if __name__ == "__main__":
    # `-h` stays with unittest, so `--readme` is documented in the module docstring.
    options_parser = argparse.ArgumentParser(add_help=False)
    options_parser.add_argument("--readme", type=Path)
    options, unittest_args = options_parser.parse_known_args()
    if options.readme:
        if not options.readme.is_file():
            options_parser.error(f"--readme: {options.readme} is not a file")
        README = options.readme.resolve()
        print(f"Docs tests use {README}", file=sys.stderr)
    unittest.main(argv=[sys.argv[0], *unittest_args])
