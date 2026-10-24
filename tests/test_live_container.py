#!/usr/bin/env python3
"""The container-based live harness's launcher (scripts/live_container.py; PR #668).

Every test drives the launcher against a STAND-IN `docker`, first on PATH, that records each call's
argv (and what the call could see: the token in its environment, the export and the attestation
it was asked to mount) and answers from a scenario. No test reaches the real docker, builds an
image or downloads anything. What is pinned is what a careless launcher gets wrong: a token on a
command line or in a receipt, a container with a privileged flag or a host namespace, a dirty or
writable checkout, a container that outlives its limit, and a destroy nobody verified.

    python3 -m unittest tests.test_live_container -v
"""
from __future__ import annotations

import importlib.util
import io
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "live_container.py"
_spec = importlib.util.spec_from_file_location("live_container_under_test", SCRIPT)
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)

CID = "c0ffee" + "0" * 58
IMAGE_ID = "sha256:" + "ab" * 32

# The stand-in docker. It appends one JSON line per call to $FAKE_DOCKER_LOG and answers from the
# scenario in $FAKE_DOCKER_SCENARIO. At `create` it also reads what the launcher asked it to mount:
# the export's HEAD and status, and the attestation, while they still exist.
STAND_IN = r'''#!{python}
import json, os, subprocess, sys, time
argv = sys.argv[1:]
scenario = json.load(open(os.environ["FAKE_DOCKER_SCENARIO"]))
entry = {"argv": argv, "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")}
if argv[:1] == ["create"]:
    mounts = {}
    for i, arg in enumerate(argv):
        if arg == "--mount":
            fields = dict(f.split("=", 1) if "=" in f else (f, True) for f in argv[i + 1].split(","))
            mounts[fields["dst"]] = fields
    entry["mounts"] = mounts
    src = mounts.get("/repo", {}).get("src")
    if src:
        git = lambda *a: subprocess.run(["git", "-C", src, *a], capture_output=True, text=True).stdout
        entry["repo_head"], entry["repo_status"] = git("rev-parse", "HEAD").strip(), git("status", "--porcelain")
        entry["repo_files"] = sorted(os.listdir(src))
    att = mounts.get(scenario["attestation_path"], {}).get("src")
    if att:
        entry["attestation"] = json.load(open(att))
if argv[:1] == ["build"]:
    entry["context"] = sorted(os.listdir(argv[-1]))
with open(os.environ["FAKE_DOCKER_LOG"], "a") as fh:
    fh.write(json.dumps(entry) + "\n")
if argv[:2] == ["image", "inspect"]:
    if scenario.get("image") is None:
        sys.stderr.write("Error: No such image\n")
        sys.exit(1)
    print(json.dumps(scenario["image"]))
elif argv[:1] == ["ps"]:
    flt = argv[argv.index("--filter") + 1]
    print(scenario.get("leftovers", "") if flt.startswith("label=") else scenario.get("survivor", ""))
elif argv[:1] == ["create"]:
    print(scenario["cid"])
elif argv[:1] == ["start"]:
    sys.stdout.write(scenario.get("output", ""))
    sys.stdout.flush()
    time.sleep(scenario.get("sleep", 0))
    sys.exit(scenario.get("exit", 0))
elif argv[:1] == ["build"]:
    sys.exit(scenario.get("build_exit", 0))
'''


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


class Harness(unittest.TestCase):
    """A fixture checkout holding every arm's entry point, a token file, and the stand-in docker."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="live-container-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        for script, *_prefix in lc.ARMS.values():
            path = self.repo / script
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("print('arm')\n", encoding="utf-8")
        git(self.repo.parent, "init", "-q", str(self.repo))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "fixture")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        self.token = "fixture-oauth-token-" + os.urandom(8).hex()
        self.token_file = self.tmp / "oauth-token"
        self.token_file.write_text(self.token + "\n", encoding="utf-8")
        self.token_file.chmod(0o600)
        self.results, self.receipts = self.tmp / "results", self.tmp / "receipts"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        stand_in = bin_dir / "docker"
        stand_in.write_text(STAND_IN.replace("{python}", sys.executable), encoding="utf-8")
        stand_in.chmod(0o755)
        self.log = self.tmp / "docker.jsonl"
        self.scenario_path = self.tmp / "scenario.json"
        self.scenario({})
        env = {k: v for k, v in os.environ.items() if k != lc.TOKEN_ENV}
        env.update(PATH=os.pathsep.join([str(bin_dir), env.get("PATH", "")]), FAKE_DOCKER_LOG=str(self.log),
                   FAKE_DOCKER_SCENARIO=str(self.scenario_path))
        for patch in (mock.patch.dict(os.environ, env, clear=True), mock.patch.object(lc, "REPO", self.repo)):
            patch.start()
            self.addCleanup(patch.stop)
        self.assertEqual(shutil.which("docker"), str(stand_in), "a test would reach the real docker")

    def scenario(self, overrides):
        doc = {"image": {"Id": IMAGE_ID, "RepoDigests": ["open-fleet-live@sha256:" + "cd" * 32],
                         "Config": {"Labels": {lc.DOCKERFILE_LABEL: lc.sha256_file(lc.DOCKERFILE)}}},
               "cid": CID, "attestation_path": lc.containment.ATTESTATION, **overrides}
        self.scenario_path.write_text(json.dumps(doc), encoding="utf-8")

    def launch(self, *extra, arm="wip_curve", arm_args=("run", "--results", "/results/wip"), timeout="600"):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = lc.main(["run", "--arm", arm, "--results", str(self.results), "--timeout", timeout,
                          "--token-file", str(self.token_file), "--receipts", str(self.receipts), *extra,
                          "--", *arm_args])
        return rc, err.getvalue()

    def calls(self, partial=False):
        """Every call the stand-in recorded; `partial`: tolerate a line it is still writing."""
        if not self.log.is_file():
            return []
        out = []
        for line in self.log.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                if not partial:
                    raise
        return out

    def call(self, verb):
        found = [c for c in self.calls() if c["argv"][:1] == [verb]]
        self.assertEqual(len(found), 1, [c["argv"][:2] for c in self.calls()])
        return found[0]

    def receipt(self):
        found = sorted(self.receipts.glob("*.json"))
        self.assertEqual(len(found), 1, found)
        return json.loads(found[0].read_text(encoding="utf-8"))


class OneArmRunsAndItsContainerIsVerifiedDestroyed(Harness):
    def test_the_receipt_binds_the_run(self):
        self.scenario({"exit": 7})
        rc, err = self.launch()
        self.assertEqual(rc, 7, err)
        r = self.receipt()
        self.assertEqual(r["schema"], lc.RECEIPT_SCHEMA)
        self.assertEqual((r["arm"], r["arm_args"]), ("wip_curve", ["run", "--results", "/results/wip"]))
        self.assertEqual(r["commit"], self.commit)
        self.assertEqual(r["image"]["id"], IMAGE_ID)
        self.assertTrue(r["image"]["from_committed_dockerfile"])
        self.assertRegex(r["nonce"], r"^[0-9a-f]{32}$")
        self.assertEqual(r["container"]["id"], CID)
        self.assertTrue(r["started_at"] and r["ended_at"])
        self.assertEqual((r["exit_status"], r["timed_out"]), (7, False))
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertEqual(r["destroyed"]["check"], ["docker", "ps", "-a", "--filter", f"id={CID}", "--format", "{{.ID}}"])
        verbs = [c["argv"][0] for c in self.calls()]
        self.assertLess(verbs.index("start"), verbs.index("rm"), verbs)
        self.assertEqual(verbs[-1], "ps", "the last word is the verification")

    def test_the_container_runs_the_pinned_commit_read_only_and_writes_only_the_results(self):
        self.launch()
        create = self.call("create")
        self.assertEqual(create["repo_head"], self.commit)
        self.assertEqual(create["repo_status"], "", "the mounted export is not a clean checkout of the commit")
        mounts = create["mounts"]
        self.assertEqual(sorted(mounts), sorted(["/repo", "/results", lc.containment.ATTESTATION]))
        self.assertIs(mounts["/repo"].get("readonly"), True)
        self.assertIs(mounts[lc.containment.ATTESTATION].get("readonly"), True)
        self.assertNotIn("readonly", mounts["/results"])
        self.assertEqual(mounts["/results"]["src"], str(self.results))
        self.assertNotEqual(Path(mounts["/repo"]["src"]).resolve(), self.repo, "the operator's checkout was mounted")
        self.assertFalse(Path(mounts["/repo"]["src"]).exists(), "the export outlived the run")

    def test_the_attestation_is_this_launchs_nonce_and_lifts_the_check_inside(self):
        self.launch()
        create, r = self.call("create"), self.receipt()
        argv = create["argv"]
        hostname = argv[argv.index("--hostname") + 1]
        self.assertEqual(create["attestation"]["nonce"], r["nonce"])
        self.assertEqual(create["attestation"]["commit"], self.commit)
        self.assertEqual(hostname, lc.containment.HARNESS_HOSTNAME + r["nonce"])
        self.assertIn(f"{lc.LABEL}={r['nonce']}", argv)
        # what the launcher writes is what the check inside the container reads
        root = self.tmp / "container-root"
        att = root / lc.containment.ATTESTATION.lstrip("/")
        att.parent.mkdir(parents=True)
        att.write_text(json.dumps(create["attestation"]), encoding="utf-8")
        (root / ".dockerenv").write_text("", encoding="utf-8")
        self.assertIsNone(lc.containment.harness_problem(root=root, hostname=hostname, probe=lambda: None))

    def test_each_arm_runs_its_own_entry_point_under_an_in_container_backstop(self):
        for arm, (script, *prefix) in lc.ARMS.items():
            with self.subTest(arm=arm):
                shutil.rmtree(self.receipts, ignore_errors=True)
                self.log.unlink(missing_ok=True)
                rc, err = self.launch(arm=arm, arm_args=("--x", "1"), timeout="600")
                self.assertEqual(rc, 0, err)
                argv = self.call("create")["argv"]
                tail = argv[argv.index(IMAGE_ID) + 1:]
                self.assertEqual(tail, ["timeout", "--kill-after=30", str(600 + lc.BACKSTOP_S), "python3",
                                        f"/repo/{script}", *prefix, "--x", "1"])
        self.assertEqual(sorted(lc.ARMS), ["ablation", "first_run", "hint_replay", "trajectories", "wip_curve"])


class TheContainerIsHardened(Harness):
    def test_non_root_limited_unprivileged_and_on_no_host_namespace(self):
        self.launch()
        argv = self.call("create")["argv"]
        pairs = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
        self.assertIn("--rm", argv)
        self.assertIn("--init", argv)
        self.assertEqual(pairs["--user"], lc.USER)
        self.assertFalse(pairs["--user"].split(":")[0] in ("0", "root"))
        self.assertEqual(pairs["--pids-limit"], str(lc.LIMITS["pids"]))
        self.assertEqual((pairs["--memory"], pairs["--memory-swap"]), (lc.LIMITS["memory"], lc.LIMITS["memory"]))
        self.assertEqual(pairs["--cpus"], lc.LIMITS["cpus"])
        self.assertEqual(pairs["--cap-drop"], "ALL")
        self.assertEqual(pairs["--security-opt"], "no-new-privileges")
        self.assertEqual(pairs["--log-driver"], "none")
        for banned in ("--privileged", "--cap-add", "--device", "--pid", "--ipc", "--uts", "--userns", "--network",
                       "--net", "-v", "--volume", "--volumes-from", "--add-host", "--group-add", "--env-file"):
            self.assertNotIn(banned, argv)
        self.assertFalse(any("docker.sock" in a for a in argv))

    def test_the_limits_are_the_operators_to_set(self):
        self.launch("--pids-limit", "64", "--memory", "1g", "--cpus", "1.5")
        argv = self.call("create")["argv"]
        self.assertEqual(argv[argv.index("--pids-limit") + 1], "64")
        self.assertEqual(argv[argv.index("--memory") + 1], "1g")
        self.assertEqual(argv[argv.index("--cpus") + 1], "1.5")
        self.assertEqual(self.receipt()["container"]["limits"], {"pids": 64, "memory": "1g", "cpus": "1.5"})


class TheTokenGoesByNameOnly(Harness):
    def test_no_command_line_receipt_or_log_carries_it(self):
        self.scenario({"output": f"an arm that printed it: {self.token}\n"})
        rc, err = self.launch()
        self.assertEqual(rc, 0, err)
        for c in self.calls():
            self.assertFalse(any(self.token in a for a in c["argv"]), c["argv"][:2])
        create = self.call("create")
        argv = create["argv"]
        self.assertEqual(argv[argv.index("--env") + 1], lc.TOKEN_ENV, "the token is passed by name")
        self.assertEqual(argv.count("--env"), 1, "the container gets the token and nothing else from the host")
        self.assertEqual(create["token"], self.token, "docker create could not resolve the name")
        self.assertEqual([c["argv"][0] for c in self.calls() if c["token"]], ["create"])
        r = self.receipt()
        self.assertNotIn(self.token, json.dumps(r))
        self.assertNotIn(self.token, err)
        log = Path(r["log"]).read_text(encoding="utf-8")
        self.assertNotIn(self.token, log)
        self.assertIn("[REDACTED]", log)
        self.assertEqual(r["token_redactions"], 1)

    def test_a_token_file_others_can_read_a_link_or_an_empty_file_is_refused(self):
        def refused():
            rc, err = self.launch()
            self.assertEqual(rc, 2, err)
            self.assertNotIn(self.token, err)
            self.assertEqual(self.calls(), [], "docker was called with no usable token")
            return err
        self.token_file.chmod(0o644)
        self.assertIn("readable by others", refused())
        self.token_file.chmod(0o600)
        link = self.tmp / "token-link"
        link.symlink_to(self.token_file)
        self.token_file, real = link, self.token_file
        refused()
        self.token_file = real
        real.write_text("\n", encoding="utf-8")
        self.assertIn("one line", refused())


class RefusalsCreateNothing(Harness):
    def test_a_dirty_checkout_is_refused_before_docker_is_called(self):
        (self.repo / "untracked.py").write_text("x = 1\n", encoding="utf-8")
        rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("dirty", err)
        self.assertEqual(self.calls(), [])

    def test_an_unbuilt_image_is_refused(self):
        self.scenario({"image": None})
        rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("build it first", err)
        self.assertEqual([c["argv"][0] for c in self.calls() if c["argv"][0] == "create"], [])

    def test_a_harness_container_that_still_exists_refuses_the_next_launch(self):
        self.scenario({"leftovers": "deadbeef"})
        rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("already exists", err)
        self.assertEqual([c["argv"][0] for c in self.calls() if c["argv"][0] == "create"], [])

    def test_results_or_receipts_the_container_could_reach_are_refused(self):
        for results, receipts in ((self.repo / "out", self.receipts), (self.results, self.results / "receipts")):
            with self.subTest(results=results, receipts=receipts):
                self.results, self.receipts = results, receipts
                rc, err = self.launch()
                self.assertEqual(rc, 2, err)
                self.assertIn("overlaps", err)
        self.assertEqual([c["argv"][0] for c in self.calls() if c["argv"][0] == "create"], [])


class TheWallClockLimitEndsIt(Harness):
    def test_the_launcher_kills_removes_and_verifies(self):
        self.scenario({"sleep": 60})
        started = time.monotonic()
        rc, err = self.launch(timeout="1")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(rc, lc.EXIT_TIMED_OUT, err)
        verbs = [c["argv"][:2] for c in self.calls()]
        self.assertIn(["kill", CID], verbs)
        self.assertIn(["rm", "-f"], verbs)
        r = self.receipt()
        self.assertIs(r["timed_out"], True)
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertIsNone(r["exit_status"])

    def test_a_container_still_listed_fails_closed(self):
        self.scenario({"survivor": CID})
        with mock.patch.object(lc, "DESTROY_WAIT_S", 0.5):
            rc, err = self.launch()
        self.assertEqual(rc, lc.EXIT_NOT_DESTROYED, err)
        self.assertIn("FAIL-CLOSED", err)
        r = self.receipt()
        self.assertIs(r["destroyed"]["verified"], False)
        self.assertIn(CID, r["destroyed"]["output"])

    def test_a_signal_destroys_the_container_before_the_launcher_exits(self):
        self.scenario({"sleep": 60})

        def interrupt():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not any(c["argv"][:1] == ["start"] for c in self.calls(partial=True)):
                time.sleep(0.05)
            os.kill(os.getpid(), signal.SIGTERM)
        thread = threading.Thread(target=interrupt)
        thread.start()
        try:
            with self.assertRaises(SystemExit) as raised:
                self.launch()
        finally:
            thread.join()
        self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)
        r = self.receipt()
        self.assertEqual(r["interrupted"], 128 + signal.SIGTERM)
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertIn(["kill", CID], [c["argv"][:2] for c in self.calls()])


class TheImageIsBuiltFromTheCommittedDockerfile(Harness):
    def test_build_labels_the_dockerfiles_digest_and_sends_an_empty_context(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = lc.main(["build"])
        self.assertEqual(rc, 0)
        build = self.call("build")
        self.assertEqual(build["argv"][:5], ["build", "-f", str(lc.DOCKERFILE), "-t", lc.IMAGE])
        self.assertIn(f"{lc.DOCKERFILE_LABEL}={lc.sha256_file(lc.DOCKERFILE)}", build["argv"])
        self.assertEqual(build["context"], [], "the build context is not empty")

    def test_the_dockerfile_pins_its_base_and_installs_claude_code_as_a_non_root_user(self):
        text = lc.DOCKERFILE.read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()]
        froms = [ln for ln in lines if ln.startswith("FROM ")]
        self.assertEqual(len(froms), 1)
        self.assertRegex(froms[0], r"^FROM python:3\.13\.15-slim@sha256:[0-9a-f]{64}$")
        self.assertIn("git", re.search(r"apt-get install[^\n]*", text).group(0))
        install = f"curl -fsSL https://claude.ai/install.sh | bash -s {lc.CLAUDE_CODE}"
        self.assertIn(install, text)
        users = [i for i, ln in enumerate(lines) if ln.startswith("USER ")]
        at = next(i for i, ln in enumerate(lines) if install in ln)
        self.assertTrue(users and users[-1] < at and lines[users[-1]] == "USER runner", "installed as root")
        self.assertEqual(lc.IMAGE, f"open-fleet-live:claude-{lc.CLAUDE_CODE}")


if __name__ == "__main__":
    unittest.main()
