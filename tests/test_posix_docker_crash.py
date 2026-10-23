#!/usr/bin/env python3
"""Real-Docker tier of the posix launch crash tests (#597). OPT-IN, and never a silent pass.

The `danger` launch's private git dir is crash-tested here against a REAL Docker daemon: a real
coordinator subprocess is SIGKILLed at each committed launch boundary (the same kill points as
the setsid tier in test_posix_crash_recovery.py, whose harness this module reuses) while the
worker runs in a container built from tests/fixtures/posix-crash-docker. That fixture is alpine
pinned by digest + git + an INERT `claude` that commits one file into the sandbox and sleeps;
no model is ever contacted.

Opt in with OPEN_FLEET_DOCKER_CRASH_TEST=1. The tier then runs only when `docker version`
reaches a daemon and the fixture image is present or builds (the build pulls the pinned base
and `apk add git`: the only network this module ever causes, and only when opted in). In every
other case the real-Docker cases are NOT LOADED (`load_tests` selects them) and the module
prints `real-docker crash tier: NOT RUN (<reason>)`: a skip decorator would read as a pass-shaped
skip, and the floor guard forbids them. What always runs is the gate itself (TestDockerTierGate).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "posix-crash-docker"
ENV_FLAG = "OPEN_FLEET_DOCKER_CRASH_TEST"
BASE_IMAGE = "alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc"

_spec = importlib.util.spec_from_file_location("_posix_crash_harness", Path(__file__).with_name("test_posix_crash_recovery.py"))
_harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)
CrashRecoveryBase = _harness.CrashRecoveryBase
_git, _wait_for, _alive = _harness._git, _harness._wait_for, _harness._alive


def image_tag() -> str:
    """`open-fleet-test/posix-crash:<content hash>`: a changed fixture is a new tag, never a stale image."""
    h = hashlib.sha256()
    for name in ("Dockerfile", "claude"):
        h.update(name.encode() + b"\0" + (FIXTURE / name).read_bytes() + b"\0")
    return "open-fleet-test/posix-crash:" + h.hexdigest()[:12]


def docker_tier(env=None, *, build=True) -> dict:
    """Whether the real-Docker tier can run, and why not when it cannot (never raises)."""
    env = os.environ if env is None else env
    out = {"tier": "real-docker", "run": False, "image": image_tag(), "base": BASE_IMAGE}
    if env.get(ENV_FLAG) != "1":
        out["reason"] = f"not opted in: set {ENV_FLAG}=1 with a reachable Docker daemon"
        return out
    docker = shutil.which("docker", path=env.get("PATH"))
    if not docker:
        out["reason"] = "docker CLI not on PATH"
        return out
    try:
        ver = subprocess.run([docker, "version", "--format", "{{.Server.Version}}"], env=dict(env),
                             capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        out["reason"] = f"docker daemon unreachable: {exc}"
        return out
    if ver.returncode != 0 or not ver.stdout.strip():
        out["reason"] = "docker daemon unreachable: " + (ver.stderr or ver.stdout or "no server version").strip()[:200]
        return out
    out["server"] = ver.stdout.strip()
    have = subprocess.run([docker, "image", "inspect", out["image"]], env=dict(env), capture_output=True,
                          timeout=60, stdin=subprocess.DEVNULL).returncode == 0
    if not have:
        if not build:
            out["reason"] = f"fixture image {out['image']} is not built"
            return out
        made = subprocess.run([docker, "build", "-q", "-t", out["image"], str(FIXTURE)], env=dict(env),
                              capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        if made.returncode != 0:
            out["reason"] = "fixture image did not build: " + (made.stderr or made.stdout).strip()[-300:]
            return out
        out["built"] = True
    out["run"] = True
    out["reason"] = f"Docker server {out['server']}, image {out['image']}"
    return out


RECORDED: dict = {}
LOADED: list[str] = []


def recorded_tier() -> dict:
    if not RECORDED:
        RECORDED.update(docker_tier())
    return RECORDED


def load_tests(loader, standard_tests, pattern):
    """Select the real-Docker cases at LOAD time; record the tier's outcome either way."""
    tier = recorded_tier()
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(TestDockerTierGate))
    if tier["run"]:
        real = loader.loadTestsFromTestCase(TestRealDockerCrash)
        LOADED.extend(t.id() for t in real)
        suite.addTests(real)
    print(f"real-docker crash tier: {'RUN' if tier['run'] else 'NOT RUN'} ({tier['reason']})", file=sys.stderr)
    return suite


class TestDockerTierGate(unittest.TestCase):
    """The gate is what always runs: it proves an absent tier is recorded, never passed."""

    def test_fixture_pins_its_base_by_digest_and_ships_an_inert_claude(self):
        dockerfile = (FIXTURE / "Dockerfile").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"(?m)^FROM\s+(\S+)", dockerfile), [BASE_IMAGE])
        self.assertRegex(BASE_IMAGE, r"@sha256:[0-9a-f]{64}$")
        claude = (FIXTURE / "claude").read_text(encoding="utf-8")
        self.assertIn("exec sleep", claude)
        self.assertNotRegex(claude, r"(?i)https?://|curl|wget|anthropic", "the fixture agent must never reach a model")
        self.assertRegex(image_tag(), r"^open-fleet-test/posix-crash:[0-9a-f]{12}$")

    def _fake_docker(self, body):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        log = d / "docker.log"
        (d / "docker").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n{body}\n', encoding="utf-8")
        (d / "docker").chmod(0o755)
        return d, log

    def test_without_opt_in_docker_is_never_invoked(self):
        d, log = self._fake_docker("exit 0")
        tier = docker_tier({"PATH": str(d)})
        self.assertFalse(tier["run"])
        self.assertIn(ENV_FLAG, tier["reason"])
        self.assertFalse(log.exists(), "an unopted run must not touch Docker at all")

    def test_unreachable_daemon_is_recorded_as_not_run(self):
        d, log = self._fake_docker('echo "Cannot connect to the Docker daemon" >&2\nexit 1')
        tier = docker_tier({"PATH": str(d), ENV_FLAG: "1"})
        self.assertFalse(tier["run"])
        self.assertTrue(tier["reason"].startswith("docker daemon unreachable"), tier)
        self.assertNotIn("build", log.read_text(), "nothing is built for an unreachable daemon")

    def test_this_run_records_its_tier_and_loads_cases_only_when_it_runs(self):
        tier = recorded_tier()
        self.assertTrue(tier["reason"])
        if tier["run"]:
            self.assertTrue(LOADED, "a running tier must have loaded its real-Docker cases")
        else:
            self.assertEqual(LOADED, [], "a tier that cannot run loads no case that could pass")


class TestRealDockerCrash(CrashRecoveryBase):
    """SIGKILL a real coordinator at each boundary while the worker runs in a REAL container."""

    def setUp(self):
        super().setUp()
        self.image = recorded_tier()["image"]
        self.branch = f"refs/heads/fleet/{self.task}"
        self.addCleanup(self._remove_containers)

    def start_kwargs(self, **over):
        return super().start_kwargs(**{"profile": "danger", "on_env": self.image, **over})

    # --- Docker probes: only containers this test's launches name are ever touched ---
    def _docker(self, *args):
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)

    def _remove_containers(self):
        db = self.base / "state" / "runtime.db"
        if not db.exists():
            return
        with self.restart().state._connect() as conn:
            ids = {r["dispatch_id"] for r in conn.execute("SELECT dispatch_id FROM launch_intents").fetchall()}
        for disp in ids:
            self._docker("rm", "-f", f"openfleet-{disp}")

    def container_state(self, disp):
        p = self._docker("ps", "-a", "--filter", f"name=^openfleet-{disp}$", "--format", "{{.State}}")
        return p.stdout.strip() or None

    def inert_runs(self, info):
        log = Path(info["worktree"]) / ".open-fleet" / "inert-claude.log"
        return log.read_text().splitlines() if log.exists() else []

    def sandbox_head(self, info):
        return _git("--git-dir", str(Path(info["laneDir"]) / "sandbox.git"), "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def head(self, ref):
        return _git("rev-parse", "--verify", "--quiet", ref, cwd=self.repo, check=False).stdout.strip()

    # --- shared assertions ---
    def assert_rolled_back_without_a_container(self, boundary):
        info = self.crash_at(boundary, retry_request="req-1")
        prov = self.restart()
        r = prov.launch_reconcile()["reconciled"][0]
        self.assertEqual((r["resolution"], r["requestState"]), ("failed", "failed"))
        self.assertEqual(r["task"]["after"], "ready")
        time.sleep(2.0)
        self.assertIsNone(self.container_state(info["dispatchId"]), "no container may start for a rolled-back launch")
        self.assertEqual(self.inert_runs(info), [])
        return info, r

    def assert_adopted_then_synced(self, info, prov, *, recovered=True):
        disp = info["dispatchId"]
        self.assertTrue(_wait_for(lambda: self.inert_runs(info), timeout=60), "the containerised worker never ran")
        self.assertEqual(self.container_state(disp), "running")
        res = prov.worker_start(**self.start_kwargs(retry_request="req-1"))
        self.assertEqual((res["state"], res["dispatchId"]), ("ready", disp))
        if recovered:
            self.assertEqual(res["recovery"]["resolution"], "live")
        else:
            self.assertNotIn("recovery", res)
        work = self.sandbox_head(info)
        self.assertEqual(self.inert_runs(info)[0].split(), [disp, "run-r04", work])
        self.assertNotEqual(self.head(self.branch), work, "until its monitor syncs, the commit lives only in the sandbox")
        time.sleep(1.0)
        self.assertEqual(len(self.inert_runs(info)), 1, "retrying the same request starts no second container")
        stop = prov.worker_fence("stop", disp)
        self.assertEqual(stop["termination"]["container"]["rc"], 0, stop)
        self.assertEqual(stop["termination"]["sandboxSync"].get("headSha"), work, stop)
        self.assertEqual(self.head(self.branch), work, "the worker's sandbox commit reached the host branch")
        self.assertEqual(self.head(f"refs/open-fleet/sandbox/{disp}"), work)
        self.assertTrue(_wait_for(lambda: self.container_state(disp) is None, timeout=30))

    # --- the kill points ---
    def test_kill_after_intent_claimed_starts_no_container(self):
        self.assert_rolled_back_without_a_container("intent_claimed")

    def test_kill_after_worktree_created_starts_no_container(self):
        info, r = self.assert_rolled_back_without_a_container("worktree_created")
        self.assertTrue((Path(info["laneDir"]) / "sandbox.git").is_dir(), "the private git dir was prepared")
        self.assertIn({"kind": "lane", "target": info["laneDir"], "action": "kept", "why": "logs, exit.json and this receipt"}, r["cleanup"])

    def test_kill_after_registered_starts_no_container(self):
        info, r = self.assert_rolled_back_without_a_container("registered")
        self.assertEqual(r["dispatch"]["after"], "abandoned")

    def test_kill_after_monitor_spawned_adopts_the_container_and_syncs_its_commit(self):
        info = self.crash_at("monitor_spawned", retry_request="req-1")
        self.assert_adopted_then_synced(info, self.restart())

    def test_kill_after_published_adopts_the_container_and_syncs_its_commit(self):
        info = self.crash_at("published", retry_request="req-1")
        self.assert_adopted_then_synced(info, self.restart())

    def test_kill_after_receipted_needs_no_recovery(self):
        info = self.crash_at("receipted", retry_request="req-1")
        prov = self.restart()
        self.assertEqual(prov.launch_reconcile()["count"], 0)
        self.assert_adopted_then_synced(info, prov, recovered=False)

    def test_host_crash_removes_the_orphan_container_and_salvages_its_commit(self):
        info = self.crash_at("published", retry_request="req-1")
        disp = info["dispatchId"]
        self.assertTrue(_wait_for(lambda: self.inert_runs(info), timeout=60))
        prov = self.restart()
        pid = self.dispatch(prov, disp)["pid"]
        os.killpg(pid, signal.SIGKILL)  # the monitor and its `docker run` client die; the container does not
        self.assertTrue(_wait_for(lambda: not _alive(pid)))
        self.assertEqual(self.container_state(disp), "running", "a killed client leaves the container orphaned")
        work = self.sandbox_head(info)
        r = prov.launch_reconcile()["reconciled"][0]
        self.assertEqual(r["resolution"], "exited")
        self.assertIn({"kind": "container", "target": f"openfleet-{disp}", "action": "removed", "rc": 0}, r["cleanup"])
        self.assertIsNone(self.container_state(disp), "recovery removes the orphan before it syncs")
        self.assertIn({"ref": f"refs/open-fleet/sandbox/{disp}", "sha": work, "source": "sandbox"}, r["preservedRefs"])
        self.assertEqual(self.head(self.branch), work, "the worker's commit survived the host crash")
        self.assertEqual(r["dispatch"]["after"], "died")

    def test_uninterrupted_control_runs_one_container_and_syncs(self):
        c = self.coordinator(None, retry_request="req-1")
        out = c.finish()
        self.assertEqual(c.seen, list(self.posix.LAUNCH_BOUNDARIES))
        self.assertEqual(out[-1]["result"]["state"], "ready")
        prov = self.restart()
        self.assertEqual(prov.launch_reconcile()["count"], 0)
        self.assert_adopted_then_synced(c.info, prov, recovered=False)


if __name__ == "__main__":
    unittest.main()
