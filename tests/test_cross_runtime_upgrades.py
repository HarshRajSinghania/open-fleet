#!/usr/bin/env python3
"""#590 negative controls driven through the watchdog's real CLI / run_tick path,
plus the runtime-aware install prerequisite (#586).

* Identical CI failure signatures across two ticks produce exactly ONE nudge
  (the second tick reads the persisted ci_signatures and suppresses).
* waiting_input never hides a WEDGED worker's stop-redispatch recommendation.
* scripts/install.sh warns "no orca CLI" only when the active runtime is orca.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCHDOG = ROOT / "runtime" / "scripts" / "watchdog.py"

FAILING = [
    {"name": "unit", "step": "pytest", "conclusion": "failure", "exit_code": 1,
     "run_id": 101, "log_url": "https://ci.example/101"},
]
# Same failure, different run id / log URL: the signature ignores both.
FAILING_RERUN = [dict(FAILING[0], run_id=102, log_url="https://ci.example/102")]


def run_cli(*argv):
    return subprocess.run([sys.executable, str(WATCHDOG), *argv],
                          capture_output=True, text=True, cwd=ROOT, timeout=60)


class CiDedupAcrossTicks(unittest.TestCase):
    def test_identical_signature_two_ticks_one_nudge(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            sink = tmp / "sink.txt"
            conf = tmp / "w.json"
            conf.write_text(json.dumps({"nudge_command": [
                "sh", "-c", "echo \"{worker_id} {dispatch_id}\" >> " + str(sink)]}))
            state, log, beats = tmp / "s.json", tmp / "w.jsonl", tmp / "beats.json"

            def tick(now, checks):
                beats.write_text(json.dumps({"run_id": "run_ci", "workers": [{
                    "worker_id": "w1", "dispatch_id": "d1",
                    "dispatched_at": "2026-10-19T11:59:00Z",
                    "last_movement_at": now, "ci_checks": checks}]}))
                return run_cli("--heartbeats", str(beats), "--config", str(conf),
                               "--state", str(state), "--log", str(log), "--now", now)

            first = tick("2026-10-19T12:00:00Z", FAILING)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("NUDGED", first.stdout)
            second = tick("2026-10-19T13:30:00Z", FAILING_RERUN)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotIn("NUDGED", second.stdout)
            self.assertIn("duplicate CI failure signature", second.stdout)
            self.assertEqual(sink.read_text(encoding="utf-8").splitlines(), ["w1 d1"])
            saved = json.loads(state.read_text(encoding="utf-8"))["workers"]["w1"]
            self.assertEqual(len(saved["ci_signatures"]), 1)
            self.assertEqual(len(saved["ci_nudges"]), 1)
            self.assertEqual(saved["nudges"], [], "a CI nudge must not spend the hang budget")


class WaitingInputDoesNotHideWedged(unittest.TestCase):
    def test_wedged_waiting_worker_is_recommended(self):
        with tempfile.TemporaryDirectory() as raw:
            beats = Path(raw) / "beats.json"
            beats.write_text(json.dumps({"run_id": "run_w", "workers": [{
                "worker_id": "w2", "dispatch_id": "d2",
                "dispatched_at": "2026-10-19T11:00:00Z",
                "last_movement_at": "2026-10-19T11:55:00Z",
                "wedge_markers": ["provider_stream_dead"],
                "waiting_input": True}]}))
            proc = run_cli("--heartbeats", str(beats),
                           "--config", str(ROOT / "runtime" / "watchdog.json"),
                           "--now", "2026-10-19T12:00:00Z", "--dry-run")
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("w2 WEDGED WOULD-RECOMMEND", proc.stdout)


class InstallIsRuntimeAware(unittest.TestCase):
    def _check(self, runtime, extra_env=None, stubs=()):
        """install.sh --check with no real orca on PATH; `stubs` are fake CLIs that
        log their invocation. Returns (rc, output, invoked stub names)."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            bindir = tmp / "bin"
            bindir.mkdir()
            calls = tmp / "calls.log"
            for name in stubs:
                stub = bindir / name
                stub.write_text(f"#!/bin/sh\necho {name} >> '{calls}'\n"
                                "case \"$1\" in --version) echo 99.0.0 ;; esac\n", encoding="utf-8")
                stub.chmod(0o755)
            skills = tmp / "skills"
            skills.mkdir()
            for d in (ROOT / "skills").iterdir():
                if d.is_dir() and (d / "SKILL.md").is_file() and not d.name.startswith((".", "_")):
                    (skills / d.name).symlink_to(d)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPEN_FLEET_RUNTIME", "ORCA_FLEET_RUNTIME")}
            base = os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)
            env["PATH"] = os.pathsep.join([str(bindir)] + [
                d for d in base
                if not ((Path(d) / "orca").exists() or (Path(d) / "orca-ide").exists())])
            env["HOME"] = str(tmp)
            for var in ("ORCA_CLI_COMMAND", "OPEN_FLEET_CLI_COMMAND", "ORCA_DEV_REPO_ROOT"):
                env.pop(var, None)
            if runtime is not None:
                env["OPEN_FLEET_RUNTIME"] = runtime
            env.update(extra_env or {})
            proc = subprocess.run(["sh", str(ROOT / "scripts" / "install.sh"), "--check",
                                   f"--skills-dir={skills}"],
                                  env=env, capture_output=True, text=True, timeout=300)
            invoked = set(calls.read_text().split()) if calls.exists() else set()
            return proc.returncode, proc.stdout + proc.stderr, invoked

    def test_orca_runtime_still_warns_without_orca(self):
        rc, out, _ = self._check(None)
        self.assertEqual(rc, 0, out)
        self.assertIn("no orca CLI", out)

    def test_non_orca_runtime_does_not_warn(self):
        for runtime in ("posix", "AUTO", " PoSiX ", "local-posix"):
            with self.subTest(runtime=runtime):
                rc, out, _ = self._check(runtime)
                self.assertEqual(rc, 0, out)
                self.assertNotIn("WARN: no orca CLI", out)

    def test_env_precedence_matches_active_provider_name(self):
        # OPEN_FLEET_RUNTIME wins over ORCA_FLEET_RUNTIME, but a blank/whitespace
        # value falls through (runtime/providers env_get), exactly as dispatch reads it.
        rc, out, _ = self._check("posix", {"ORCA_FLEET_RUNTIME": "orca"})
        self.assertNotIn("WARN: no orca CLI", out)
        rc, out, _ = self._check("orca", {"ORCA_FLEET_RUNTIME": "posix"})
        self.assertIn("no orca CLI", out)
        rc, out, _ = self._check("   ", {"ORCA_FLEET_RUNTIME": "posix"})
        self.assertEqual(rc, 0, out)
        self.assertNotIn("WARN: no orca CLI", out)
        self.assertIn("posix provider", out)

    def test_auto_is_orca_only_when_the_resolved_binary_is_on_path(self):
        # auto resolves through orca.resolve_orca_binary: with ORCA_CLI_COMMAND naming
        # the binary, an unrelated `orca` on PATH does not make auto mean orca.
        rc, out, invoked = self._check("auto", {"ORCA_CLI_COMMAND": "orca-custom"},
                                       stubs=("orca",))
        self.assertEqual(rc, 0, out)
        self.assertIn("runtime auto: orca-custom not in PATH", out)
        self.assertIn("posix provider", out)
        self.assertEqual(invoked, set(), "auto->posix must not probe an orca CLI")
        rc, out, invoked = self._check("auto", {"ORCA_CLI_COMMAND": "orca-custom"},
                                       stubs=("orca-custom",))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("runtime auto:", out)
        self.assertEqual(invoked, {"orca-custom"}, out)

    def test_unknown_runtime_warns(self):
        rc, out, _ = self._check("not-a-provider")
        self.assertEqual(rc, 0, out)
        self.assertIn("not a registered provider", out)


if __name__ == "__main__":
    unittest.main()
