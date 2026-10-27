#!/usr/bin/env python3
"""capabilities.json may claim a harness for a provider only if spawn_worker.sh launches it (#596).

The provider-certification first run found Orca's entry claiming opencode, omp and pi while the
public wrapper refused all three there for every profile: the matrix advertised routes no
coordinator could dispatch. test_capability_harnesses.py holds each list to the ADAPTER's table;
this holds every claimed (provider, harness) pair to the WRAPPER. A pair agrees when
spawn_worker.sh resolves a launch for at least one profile the provider advertises (ro or rw;
danger is gated on a sandbox doctor, never on the harness table), read through the script's own
SW_PRINT_LAUNCH contract hook, which stops before any orchestration call or launch.

The only claim outside the CLI harness roster is openhands' own SDK agent. It is named below so
no other non-CLI claim can hide behind it, and since the #596 follow-up spawn_worker.sh launches it
too, on the openhands runtime only: the stricter test below holds EVERY claim, that one included,
to the wrapper, and an end-to-end run against a loopback agent-server shows what the launch sends.
"""
from __future__ import annotations

import concurrent.futures
import functools
import http.server
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

base = importlib.import_module("runtime.providers.base")
SPAWN = ROOT / "runtime" / "scripts" / "spawn_worker.sh"
CAPS = json.loads((ROOT / "runtime" / "providers" / "capabilities.json").read_text(encoding="utf-8"))["providers"]
CLI_HARNESSES = frozenset(base.SUPPORTED_HARNESSES)
# (provider, harness) claims outside base.py's CLI roster, each with the reason it is allowed.
NON_CLI_CLAIMS = {("openhands", "openhands"): "the provider runs the OpenHands SDK agent itself"}
LAUNCH_PROFILES = ("rw", "ro")  # rw first: it is the profile most harnesses can launch


def resolve_launch(provider: str, agent: str, profile: str) -> tuple[int, str | None, str]:
    """spawn_worker.sh's resolved launch for `agent` under `profile` on `provider` (no side effect)."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", tmp), "SP": tmp, "SHELL": "/bin/sh",
               "SW_PRINT_LAUNCH": "1", "PROFILE": profile, "OPEN_FLEET_RUNTIME": provider,
               "OPEN_FLEET_STATE_DB": str(Path(tmp) / "s.db")}
        if provider == "orca":
            env["ORCA_CLI_COMMAND"] = "orca"
        if profile == "rw":
            env["ORCA_COORD_ALLOW_AUTONOMOUS_WRITE"] = "1"
        p = subprocess.run(["bash", str(SPAWN), "task_x", "path:/tmp/of-wt", "t", agent, "high"],
                           env=env, capture_output=True, text=True, timeout=120)
        launch = next((ln[len("LAUNCH="):] for ln in p.stdout.splitlines() if ln.startswith("LAUNCH=")), None)
        return p.returncode, launch, p.stderr


@functools.lru_cache(maxsize=None)  # both claim tests read the same verdicts: probe each pair once
def pair_launches(provider: str, agent: str) -> tuple[bool, str]:
    """True when some advertised non-danger profile resolves a launch; else the last refusal."""
    why = "the provider advertises neither ro nor rw"
    for profile in LAUNCH_PROFILES:
        if profile not in CAPS[provider]["supported_profiles"]:
            continue
        rc, launch, err = resolve_launch(provider, agent, profile)
        if rc == 0 and launch:
            return True, f"{profile}: {launch}"
        why = f"{profile}: rc={rc} {err.strip()[-200:]}"
    return False, why


class CapabilityClaimsMatchTheWrapper(unittest.TestCase):
    def test_every_claimed_cli_pair_launches_through_spawn_worker(self) -> None:
        pairs = [(p, h) for p, entry in sorted(CAPS.items()) for h in entry["supported_harnesses"]
                 if (p, h) not in NON_CLI_CLAIMS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            verdicts = dict(zip(pairs, pool.map(lambda ph: pair_launches(*ph), pairs), strict=True))
        refused = {f"{p}/{h}": why for (p, h), (ok, why) in verdicts.items() if not ok}
        self.assertEqual(sorted(refused), [], "capabilities.json claims pairs spawn_worker.sh refuses:\n"
                         + "\n".join(f"  {pair}  {why}" for pair, why in sorted(refused.items())))

    def test_only_the_named_claims_sit_outside_the_cli_roster(self) -> None:
        outside = {(p, h) for p, entry in CAPS.items() for h in entry["supported_harnesses"]
                   if h not in CLI_HARNESSES}
        self.assertEqual(outside, set(NON_CLI_CLAIMS))

    def test_the_probe_sees_a_refusal_and_a_launch(self) -> None:
        # Negative control on the checker itself: a pair the wrapper refuses for every profile
        # reads as refused, and one it launches reads as launched.
        ok, why = pair_launches("orca", "opencode")
        self.assertFalse(ok, why)
        rc, launch, err = resolve_launch("orca", "opencode", "rw")
        self.assertEqual((rc, launch), (2, None), err)
        self.assertIn("no verified PROFILE=rw launch flag", err)
        ok, why = pair_launches("orca", "claude")
        self.assertTrue(ok, why)

    def test_every_claimed_pair_launches_with_no_exception(self) -> None:
        # #596: the CLI test above names openhands as its one exception; this one has none.
        pairs = [(p, h) for p, entry in sorted(CAPS.items()) for h in entry["supported_harnesses"]]
        self.assertIn(("openhands", "openhands"), pairs)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            verdicts = dict(zip(pairs, pool.map(lambda ph: pair_launches(*ph), pairs), strict=True))
        refused = {f"{p}/{h}": why for (p, h), (ok, why) in verdicts.items() if not ok}
        self.assertEqual(refused, {}, "capabilities.json claims pairs spawn_worker.sh refuses")


class _AgentServer(http.server.BaseHTTPRequestHandler):
    """A loopback OpenHands agent-server: records each request, answers the two worker-start calls."""

    calls: list = []

    def log_message(self, *_args) -> None:
        return None

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(size) or b"null") if size else None
        type(self).calls.append({"method": "POST", "path": self.path, "body": body})
        if self.path == "/api/conversations":
            reply = {"id": f"conv{len(type(self).calls)}", "workspace": (body or {}).get("workspace")}
        else:
            reply = {"success": True}
        raw = json.dumps(reply).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        type(self).calls.append({"method": "GET", "path": self.path, "body": None})
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


class OpenHandsLaunchesThroughTheWrapper(unittest.TestCase):
    """#596: capabilities.json claimed openhands/openhands while spawn_worker.sh refused the agent
    name. The wrapper now launches the OpenHands SDK agent on the openhands runtime, through
    worker-start, and checks the receipt for the profile's toolset like any other launch."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _AgentServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _AgentServer.calls = []
        self._tmp = tempfile.TemporaryDirectory(prefix="of-oh-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(os.path.realpath(self._tmp.name))
        self.wt = self.tmp / "wt"
        subprocess.run(["git", "init", "-q", str(self.wt)], check=True)
        self.env = {"PATH": os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"]),
                    "HOME": str(self.tmp), "SP": str(self.tmp), "SHELL": "/bin/sh",
                    "OPEN_FLEET_RUNTIME": "openhands", "OPEN_FLEET_STATE_DB": str(self.tmp / "s.db"),
                    "OPEN_FLEET_OPENHANDS_URL": self.url, "OPEN_FLEET_OPENHANDS_MODEL": "fixture-model"}

    def task(self, spec: str) -> str:
        p = subprocess.run([sys.executable, str(ROOT / "runtime" / "scripts" / "orca_cli.py"), "orchestration",
                            "task-create", "--spec", spec, "--json"], env=self.env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)["result"]["task"]["id"]

    def spawn(self, task: str, agent: str, profile: str, **extra: str) -> subprocess.CompletedProcess:
        env = {**self.env, "PROFILE": profile, **extra}
        if profile == "rw":
            env["ORCA_COORD_ALLOW_AUTONOMOUS_WRITE"] = "1"
        return subprocess.run(["bash", str(SPAWN), "--mark-ready", task, f"path:{self.wt}", "review", agent, "high"],
                              env=env, capture_output=True, text=True, timeout=120)

    def conversations(self) -> list:
        return [c["body"] for c in _AgentServer.calls if c["path"] == "/api/conversations"]

    def test_each_profile_starts_a_conversation_with_its_own_toolset(self) -> None:
        tools = {"ro": ["glob", "grep", "planning_file_editor"],
                 "rw": ["terminal", "file_editor", "glob", "grep", "task_tracker"]}
        for profile, want in tools.items():
            with self.subTest(profile=profile):
                _AgentServer.calls = []
                spec = f"review the change ({profile})"
                p = self.spawn(self.task(spec), "openhands", profile)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                [conv] = self.conversations()
                self.assertEqual([t["name"] for t in conv["agent"]["tools"]], want)
                self.assertEqual(conv["workspace"]["working_dir"], str(self.wt), "the selector is a path, not a name")
                self.assertIn(spec, conv["initial_message"]["content"][0]["text"], "the task must reach the agent")
                hook = conv["hook_config"]["pre_tool_use"][0]["hooks"][0]["command"]
                self.assertIn("deny-hook.sh", hook)
                self.assertIn(f"OPEN_FLEET_SANDBOX_PROFILE={profile}", hook)
                self.assertTrue(any(c["path"].endswith("/run") for c in _AgentServer.calls), "the agent never ran")
                self.assertIn("DISPATCH=conv", p.stdout)
                effective = json.loads(next(ln for ln in p.stdout.splitlines()
                                            if ln.startswith("LAUNCH_EFFECTIVE="))[len("LAUNCH_EFFECTIVE="):])
                self.assertEqual(effective["profile_flag"], "tools=" + ",".join(want))

    def test_the_printed_launch_names_the_conversation_toolset(self) -> None:
        for profile in ("ro", "rw"):
            with self.subTest(profile=profile):
                rc, launch, err = resolve_launch("openhands", "openhands", profile)
                self.assertEqual(rc, 0, err)
                self.assertIn("tools=", launch)
        self.assertEqual(_AgentServer.calls, [], "a printed launch makes no upstream call")

    def test_a_cli_harness_on_the_openhands_runtime_is_refused_before_any_call(self) -> None:
        # The provider runs its own SDK agent whatever the name: `claude` there would print a
        # claude launch line and start an OpenHands conversation instead.
        task = self.task("review it")
        for agent in ("claude", "codex"):
            with self.subTest(agent=agent):
                p = self.spawn(task, agent, "ro")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("runs only its own OpenHands SDK agent", p.stderr)
                self.assertNotIn("LAUNCH=", p.stdout)
        self.assertEqual(self.conversations(), [])

    def test_the_openhands_agent_is_refused_on_every_other_runtime(self) -> None:
        for runtime in ("posix", "worktrunk"):
            with self.subTest(runtime=runtime):
                rc, launch, err = resolve_launch(runtime, "openhands", "rw")
                self.assertEqual((rc, launch), (2, None), err)
                self.assertIn("only the openhands runtime runs", err)
        rc, launch, err = resolve_launch("orca", "openhands", "rw")
        self.assertEqual((rc, launch), (2, None), err)


if __name__ == "__main__":
    unittest.main()
