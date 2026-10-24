#!/usr/bin/env python3
"""Every claude PROFILE=ro launch row and alias carries the disallowed-tools set (#596).

The provider-certification first run found gastown's ro alias for claude registered as base.py's
short `command` label, `claude --permission-mode plan`, without the
`--disallowedTools Edit,Write,MultiEdit,NotebookEdit` the full posix line carries: a town-wide
alias that leaned on plan mode alone. Plan mode is a mode a session can leave; the disallowed set
is the CLI-level floor. This module enumerates every place the runtime spells a claude ro launch
(the base.py table in all three renderings, the gastown alias derived from it, emdash's extraArgs,
multiclaude's settings deny list, and spawn_worker.sh's non-Orca line and Orca row) and pins each to
the set. A source scan fails if a claude plan-mode launch appears anywhere it does not enumerate.

spawn_worker.sh's Orca `claude:ro` TUI row was the one exemption until the #596 follow-up. It is the
live-witnessed Orca route (docs/runs/2026-10-13-review-it-linux.md: the coordinator approves the
plan in-pane, which exits plan mode, and the worker then writes its report). It carries the set now,
so that witness predates the row and the route needs a fresh one; and tests/test_spawn_worker.py
pinned the old row exactly, so moving that pin needs a one-way floor waiver for an existing
assertion, which is a human decision, not this fix's.
"""
from __future__ import annotations

import importlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

base = importlib.import_module("runtime.providers.base")
gastown = importlib.import_module("runtime.providers.gastown")
emdash = importlib.import_module("runtime.providers.emdash")
multiclaude = importlib.import_module("runtime.providers.multiclaude")
local_state = importlib.import_module("runtime.providers.local_state")

DISALLOWED = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SPAWN = ROOT / "runtime" / "scripts" / "spawn_worker.sh"
# Files whose source spells a claude plan-mode launch; each is pinned below.
COVERED_SOURCES = {"runtime/providers/base.py", "runtime/providers/emdash.py", "runtime/scripts/spawn_worker.sh"}
_PLAN_MODE_RE = re.compile(r"""--permission-mode["',\s]+plan\b""")


def disallowed_tools(tokens: list[str]) -> set[str]:
    """The tool names a claude argv denies, in either spelling of the flag (`=` or a value)."""
    out: set[str] = set()
    for i, tok in enumerate(tokens):
        flag, eq, value = tok.partition("=")
        if flag not in ("--disallowedTools", "--disallowed-tools"):
            continue
        if not eq:
            value = tokens[i + 1] if i + 1 < len(tokens) else ""
        out |= {t for t in re.split(r"[,\s]+", value) if t}
    return out


class Runner:
    """gt/bd stand-in for a ro sling: answers what worker_start reads, records every call."""

    def __init__(self, clone: str) -> None:
        self.calls: list[list[str]] = []
        self.clone = clone

    def __call__(self, argv: list[str], **_kw: Any) -> Any:
        self.calls.append(list(argv))
        if argv[:2] == ["bd", "create"]:
            return {"id": "gt-abc"}
        if argv[:2] == ["gt", "sling"]:
            return "Slinging gt-abc to rig-alpha/polecats/Toast...\n"
        if argv[:3] == ["gt", "polecat", "status"]:
            return {"name": "Toast", "state": "working", "issue": "gt-abc", "clone_path": self.clone}
        return ""


class EveryClaudeRoLaunchCarriesTheSet(unittest.TestCase):
    def assert_carries(self, tokens: list[str], where: str) -> None:
        self.assertTrue(DISALLOWED <= disallowed_tools(tokens), f"{where} lacks --disallowedTools: {tokens}")

    def test_base_py_ro_line_in_every_rendering(self) -> None:
        launch = base.build_harness_command("claude", "ro", "/w", prompt="TASK")
        self.assert_carries(launch["argv"], "base.py argv")
        self.assert_carries(shlex.split(launch["shell"]), "base.py shell")
        self.assert_carries(launch["command"].split(), "base.py command label")

    def test_the_label_keeps_the_prompt_out_of_the_tool_list(self) -> None:
        # Something appends a prompt to the label (a gt alias): claude's --disallowedTools is
        # variadic, so its value must be `=`-joined and the line must not end on it.
        tokens = base.build_harness_command("claude", "ro", "/w")["command"].split()
        flag = next(t for t in tokens if t.startswith("--disallowedTools"))
        self.assertIn("=", flag)
        self.assertEqual(tokens[-2:], ["--permission-mode", "plan"])

    def test_gastown_ro_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / "clone"
            clone.mkdir()
            runner = Runner(str(clone))
            prov = gastown.GastownProvider(state=local_state.LocalStateStore(db_path=Path(tmp) / "s.db"),
                                           runner=runner, rig="rig-alpha", env={},
                                           install_hooks=lambda *a, **k: {"deny_hook": "fake"})
            tid = prov.task_create(spec="review it")["task"]["id"]
            prov.worker_start(task_id=tid, agent="claude", profile="ro")
            alias = [c for c in runner.calls if c[:4] == ["gt", "config", "agent", "set"]]
            self.assertEqual([a[4] for a in alias], ["claude-ro"])
            # gt splits the alias on whitespace (strings.Fields): pin the tokens it will run.
            self.assert_carries(alias[0][5].split(), "gastown claude-ro alias")

    def test_emdash_ro_extra_args(self) -> None:
        self.assert_carries(list(emdash.EMDASH_CLAUDE_RO_ARGS), "emdash EMDASH_CLAUDE_RO_ARGS")

    def test_multiclaude_ro_settings_deny_the_set(self) -> None:
        deny = set(multiclaude.worker_settings("ro", "/w")["permissions"]["deny"])
        self.assertTrue(DISALLOWED <= deny, deny)

    def test_spawn_worker_off_orca_launches_the_base_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", tmp), "SP": tmp, "SHELL": "/bin/sh",
                   "OPEN_FLEET_RUNTIME": "posix", "OPEN_FLEET_STATE_DB": str(Path(tmp) / "s.db"),
                   "SW_PRINT_LAUNCH": "1", "PROFILE": "ro"}
            p = subprocess.run(["bash", str(SPAWN), "task_x", "path:/tmp/of-wt", "t", "claude", "high"],
                               env=env, capture_output=True, text=True, timeout=120)
        launch = next((ln[len("LAUNCH="):] for ln in p.stdout.splitlines() if ln.startswith("LAUNCH=")), "")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assert_carries(shlex.split(launch), "spawn_worker.sh posix ro line")

    def test_spawn_worker_on_orca_launches_the_ro_row_with_the_set(self) -> None:
        # The Orca custom-argv lane runs this row as the worker's TUI: plan mode stays (it is the
        # witnessed prefix and the reviewer's working mode), and the set is the floor that holds
        # once the coordinator's in-pane approval exits plan mode (#596 follow-up).
        for spelled in ("orca", "ORCA"):
            with self.subTest(runtime=spelled), tempfile.TemporaryDirectory() as tmp:
                env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", tmp), "SP": tmp, "SHELL": "/bin/sh",
                       "ORCA_CLI_COMMAND": "orca", "OPEN_FLEET_RUNTIME": spelled, "SW_PRINT_LAUNCH": "1",
                       "PROFILE": "ro"}
                p = subprocess.run(["bash", str(SPAWN), "task_x", "current", "t", "claude", "high"],
                                   env=env, capture_output=True, text=True, timeout=120)
                launch = next((ln[len("LAUNCH="):] for ln in p.stdout.splitlines() if ln.startswith("LAUNCH=")), "")
                self.assertEqual(p.returncode, 0, p.stderr)
                tokens = shlex.split(launch)
                self.assert_carries(tokens, "spawn_worker.sh Orca ro row")
                self.assertEqual(tokens[:3], ["claude", "--permission-mode", "plan"], launch)
                self.assertEqual([t for t in tokens if t.startswith("--disallowedTools")],
                                 ["--disallowedTools=" + base.CLAUDE_RO_DISALLOWED_TOOLS], "one `=`-joined set")

    def test_no_claude_plan_mode_launch_hides_outside_this_module(self) -> None:
        spelled = set()
        for path in [*(ROOT / "runtime" / "providers").glob("*.py"), *(ROOT / "runtime" / "scripts").iterdir()]:
            if path.is_file() and _PLAN_MODE_RE.search(path.read_text(encoding="utf-8", errors="replace")):
                spelled.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(spelled - COVERED_SOURCES, set(), "a new claude ro launch: pin it in this module")

    def test_the_parser_reads_both_spellings_and_misses_neither(self) -> None:
        self.assertEqual(disallowed_tools(["claude", "--disallowedTools", "Edit,Write"]), {"Edit", "Write"})
        self.assertEqual(disallowed_tools(["claude", "--disallowedTools=Edit,Write"]), {"Edit", "Write"})
        self.assertEqual(disallowed_tools(["claude", "--permission-mode", "plan"]), set())


if __name__ == "__main__":
    unittest.main()
