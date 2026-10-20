#!/usr/bin/env python3
"""capabilities.json `supported_harnesses` must equal what each adapter actually honours (#591 review).

A provider may list a harness only if `worker_start(agent=<harness>)` reaches upstream with that
harness selected. Each list is checked against the adapter's own table (`SUPPORTED_HARNESSES`,
`OV_RUNTIMES`, `build_harness_command`) or, where the adapter forwards the name verbatim to an
upstream registry, against that registry's ids as read from the upstream source:

  - emdash      `packages/plugins/src/agents/impl/*` provider ids (`providerId` is sent verbatim)
  - gastown     `internal/config/agents.go` AgentPreset values (rw `gt sling --agent <name>`)
  - superset    `packages/shared/src/builtin-terminal-agents.ts` ids (rw `agents create --agent`),
                intersected with what `build_harness_command` can launch with a prompt
  - t3code      `packages/contracts/src/model.ts` driver kinds (`codex`, `claudeAgent`); the
                adapter sends no agent — the T3 project's default model picks one of the two
  - openhands   runs the OpenHands SDK `Agent` itself; no CLI harness is launched

For the four adapters that refuse an unknown agent before any upstream call (paperclip,
vibe-kanban, multiclaude, ao — plus overstory and jcode-swarm) every UNLISTED harness is driven
through `worker_start` and must be refused with `unsupported_agent` without touching upstream,
and every LISTED harness must get past that check.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_mod = importlib.import_module  # repo-local package loaded by path, not a distributable import
base = _mod("runtime.providers.base")
ProviderError = base.ProviderError
LocalStateStore = _mod("runtime.providers.local_state").LocalStateStore
paperclip = _mod("runtime.providers.paperclip")
vibe_kanban = _mod("runtime.providers.vibe_kanban")
multiclaude = _mod("runtime.providers.multiclaude")
ao = _mod("runtime.providers.ao")
overstory = _mod("runtime.providers.overstory")
jcode_swarm = _mod("runtime.providers.jcode_swarm")
openhands = _mod("runtime.providers.openhands")

CAPS = json.loads((ROOT / "runtime" / "providers" / "capabilities.json").read_text(encoding="utf-8"))["providers"]
HARNESSES = tuple(base.SUPPORTED_HARNESSES)
CANDIDATES = HARNESSES + ("openhands", "jcode-swarm", "aider")

# Upstream registries the adapters forward the agent name into verbatim (read-only source reads).
EMDASH_PROVIDER_IDS = frozenset({
    "amp", "antigravity", "auggie", "autohand", "charm", "claude", "cline", "codebuddy", "codebuff", "codex",
    "commandcode", "continue", "copilot", "cursor", "devin", "droid", "freebuff", "goose", "grok", "hermes",
    "jules", "junie", "kilocode", "kimi", "kiro", "letta", "mimocode", "mistral", "muse", "oh-my-pi",
    "opencode", "pi", "prime-agent", "qoder", "qwen", "rovo", "zero",
})
GASTOWN_PRESETS = frozenset({
    "claude", "gemini", "codex", "kiro", "cursor", "auggie", "amp", "opencode", "copilot", "pi", "omp",
    "vibe", "groq-compound",
})
SUPERSET_AGENT_PRESETS = frozenset({
    "claude", "amp", "codex", "gemini", "mastracode", "opencode", "omp", "pi", "pdev", "copilot", "vibe",
    "kimi", "grok", "cursor-agent", "droid", "polygraph", "kiro", "agy", "fx", "hermes", "muse", "devin", "ufo",
})
T3_DRIVERS = {"codex": "codex", "claude": "claudeAgent"}


def caps(provider: str) -> list[str]:
    return list(CAPS[provider]["supported_harnesses"])


def launchable_with_prompt(profile: str = "rw") -> set[str]:
    """Harnesses `build_harness_command` can launch WITH the task prompt (the others refuse)."""
    ok: set[str] = set()
    with tempfile.TemporaryDirectory() as wt:
        for h in HARNESSES:
            try:
                base.build_harness_command(h, profile, wt, prompt="task")
            except ProviderError:
                continue
            ok.add(h)
    return ok


class Reached(Exception):
    """Raised by the probe runner: worker_start got past its agent check to an upstream call."""


class Recorder:
    """Upstream runner stand-in: records every call; with `reach=True` it stops the start there."""

    def __init__(self, reach: bool = False) -> None:
        self.calls: list[Any] = []
        self.reach = reach

    def __call__(self, *args: Any, **_kw: Any) -> Any:
        self.calls.append(args)
        if self.reach:
            raise Reached(args)
        return None


class TestSupportedHarnessesMatchAdapters(unittest.TestCase):
    def test_every_provider_is_covered_lists_are_unique_and_named(self) -> None:
        self.assertEqual(set(CAPS), set(base.SUPPORTED_PROVIDERS))
        for name in CAPS:
            with self.subTest(provider=name):
                hs = caps(name)
                self.assertGreaterEqual(len(hs), 1)
                self.assertEqual(len(hs), len(set(hs)), f"{name} lists a harness twice")
                if name != "openhands":
                    self.assertTrue(set(hs) <= set(HARNESSES), f"{name}: {set(hs) - set(HARNESSES)} are not harnesses")

    def test_own_adapters_publish_the_table_worker_start_uses(self) -> None:
        tables = {
            "paperclip": (paperclip.SUPPORTED_HARNESSES, set(paperclip.PAPERCLIP_ADAPTERS)),
            "vibe-kanban": (vibe_kanban.SUPPORTED_HARNESSES, set(vibe_kanban.VIBE_EXECUTORS)),
            "multiclaude": (multiclaude.SUPPORTED_HARNESSES, {"claude"}),
            "ao": (ao.SUPPORTED_HARNESSES, set(ao.AO_HARNESSES)),
        }
        for name, (declared, routed) in tables.items():
            with self.subTest(provider=name):
                self.assertEqual(set(declared), routed)
                self.assertEqual(set(caps(name)), set(declared))

    def test_table_and_registry_derived_lists(self) -> None:
        launch_rw = launchable_with_prompt("rw")
        expected = {
            "orca": set(HARNESSES),  # pass-through to Orca, which owns the full harness table
            "posix": launch_rw,
            "worktrunk": launch_rw,
            "superset": launch_rw & SUPERSET_AGENT_PRESETS,
            "gastown": set(HARNESSES) & GASTOWN_PRESETS,
            "emdash": set(HARNESSES) & EMDASH_PROVIDER_IDS,
            "overstory": set(HARNESSES) & set(overstory.OV_RUNTIMES),
            "t3code": set(T3_DRIVERS),
            "jcode-swarm": {"jcode"},
            "openhands": {"openhands"},
        }
        for name, want in expected.items():
            with self.subTest(provider=name):
                self.assertEqual(set(caps(name)), want)
        # Negative controls on the derivations themselves.
        self.assertNotIn("crush", expected["emdash"])  # emdash's id is `charm`, sent verbatim
        self.assertNotIn("omp", expected["emdash"])  # emdash's id is `oh-my-pi`
        self.assertNotIn("goose", expected["gastown"])  # no gt preset
        self.assertNotIn("cursor", launch_rw)  # no verified headless prompt flag
        self.assertEqual(inspect.signature(openhands.OpenHandsProvider.worker_start).parameters["agent"].default, "openhands")


class TestWorkerStartRefusesUnlistedHarnesses(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="caph-")
        self.tmp = Path(self._tmp.name)
        self.state = LocalStateStore(db_path=self.tmp / "state.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _state(self) -> Any:
        return self.state  # refusals and probes record nothing, so one store serves every probe

    def _probe(self, provider: str, make: Callable[[Callable[..., Any]], Any], **start: Any) -> None:
        listed = set(caps(provider))
        for agent in CANDIDATES:
            runner = Recorder(reach=True)
            prov = make(runner)
            with self.subTest(provider=provider, agent=agent):
                if agent in listed:
                    with self.assertRaises(Reached):
                        prov.worker_start(agent=agent, **start)
                else:
                    with self.assertRaises(ProviderError) as ctx:
                        prov.worker_start(agent=agent, **start)
                    self.assertEqual(ctx.exception.code, "unsupported_agent")
                    self.assertEqual(runner.calls, [])

    def test_paperclip(self) -> None:
        self._probe("paperclip", lambda r: paperclip.PaperclipProvider(state=self._state(), runner=r, company_id="co"),
                    task_id="t", profile="rw", prompt="x")

    def test_vibe_kanban(self) -> None:
        env = {"OPEN_FLEET_VIBE_KANBAN_REPO_ID": "r1", "OPEN_FLEET_VIBE_KANBAN_TARGET_BRANCH": "main"}
        self._probe("vibe-kanban", lambda r: vibe_kanban.VibeKanbanProvider(state=self._state(), runner=r, env=env),
                    task_id="t", profile="rw", prompt="x")

    def test_multiclaude(self) -> None:
        home = self.tmp / "mch"
        (home / "repos" / "proj").mkdir(parents=True)
        self._probe("multiclaude",
                    lambda r: multiclaude.MulticlaudeProvider(state=self._state(), runner=r, home=home, repo="proj"),
                    task_id="t", name="mc-probe", profile="rw", prompt="x")

    def test_ao(self) -> None:
        self._probe("ao", lambda r: ao.ComposioAOProvider(state=self._state(), runner=r, project="p1"),
                    task_id="t", profile="rw", prompt="x")

    def test_overstory_refuses_runtimes_it_does_not_have(self) -> None:
        listed = set(caps("overstory"))
        for agent in sorted(set(CANDIDATES) - listed - set(overstory.OV_RUNTIMES)):
            with self.subTest(agent=agent):
                runner = Recorder()
                prov = overstory.OverstoryProvider(state=self._state(), runner=runner)
                with self.assertRaises(ProviderError) as ctx:
                    prov.worker_start(task_id="t", agent=agent, profile="rw", prompt="x")
                self.assertEqual(ctx.exception.code, "unsupported_agent")
                self.assertEqual(runner.calls, [])

    def test_jcode_swarm_refuses_every_other_harness(self) -> None:
        for agent in sorted(set(CANDIDATES) - set(caps("jcode-swarm")) - {"jcode-swarm"}):
            with self.subTest(agent=agent):
                runner = Recorder()
                prov = jcode_swarm.JCodeSwarmProvider(state=self._state(), runner=runner)
                with self.assertRaises(ProviderError) as ctx:
                    prov.worker_start(task_id="t", agent=agent, profile="rw", prompt="x")
                self.assertEqual(ctx.exception.code, "unsupported_agent")
                self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
