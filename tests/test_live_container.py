#!/usr/bin/env python3
"""The container-based live harness: its launcher (scripts/live_container.py), its credential
broker (scripts/live_broker.py) and the arm's `claude` (scripts/live_container_bin/claude).

The launcher's tests drive it against a STAND-IN `docker`, first on PATH, that records each call's
argv (and what the call could see: the token in its environment, the export, the attestation and
the token's file it was asked to mount) and answers from a scenario. The broker's tests run it on
127.0.0.1 against a stand-in API on 127.0.0.1. No test reaches the real docker or the network,
builds an image or downloads anything. What is pinned is what a careless harness gets wrong: a
token any process of the arm can read, on a command line, in an environment `docker inspect`
shows, in a receipt or a log; a model call that passes the cap; a ledger that dies with the
container; two launches at once; a container that outlives its limit; and a teardown that loses
the receipt.

    python3 -m unittest tests.test_live_container -v
"""
from __future__ import annotations

import contextlib
import fcntl
import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "live_container.py"
_spec = importlib.util.spec_from_file_location("live_container_under_test", SCRIPT)
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)
_spec = importlib.util.spec_from_file_location("live_broker_under_test", ROOT / "scripts" / "live_broker.py")
lb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lb)

CID = "c0ffee" + "0" * 58  # the arm's container
BID = "b40c3e" + "0" * 58  # the broker's container
SECRET = "/run/secrets/claude_token"  # where the broker reads the token: a read-only file mount
WRAPPER = ROOT / "scripts" / "live_container_bin" / "claude"  # the arm's `claude`, first on PATH
IMAGE_ID = "sha256:" + "ab" * 32

# The stand-in docker. It appends one JSON line per call to $FAKE_DOCKER_LOG and answers from the
# scenario in $FAKE_DOCKER_SCENARIO. At `create` it also reads what the launcher asked it to mount
# while it still exists: the export's HEAD and status, the attestation and the token file; a
# broker's create writes the scenario's ledger lines into the ledger directory it was given.
STAND_IN = r'''#!{python}
import json, os, subprocess, sys, time
argv = sys.argv[1:]
scenario = json.load(open(os.environ["FAKE_DOCKER_SCENARIO"]))
entry = {"argv": argv, "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")}
role = "arm" if "--network" in argv else "broker"
if argv[:1] == ["create"]:
    mounts = {}
    for i, arg in enumerate(argv):
        if arg == "--mount":
            fields = dict(f.split("=", 1) if "=" in f else (f, True) for f in argv[i + 1].split(","))
            mounts[fields["dst"]] = fields
    entry["mounts"], entry["role"] = mounts, role
    src = mounts.get("/repo", {}).get("src")
    if src:
        git = lambda *a: subprocess.run(["git", "-C", src, *a], capture_output=True, text=True).stdout
        entry["repo_head"], entry["repo_status"] = git("rev-parse", "HEAD").strip(), git("status", "--porcelain")
    att = mounts.get(scenario["attestation_path"], {}).get("src")
    if att:
        entry["attestation"] = json.load(open(att))
    sec = mounts.get(scenario["secret_path"], {}).get("src")
    if sec:
        entry["secret"] = open(sec).read().strip()
    settings = mounts.get("/run/open-fleet/claude.json", {}).get("src")
    if settings:
        entry["claude_settings"] = json.load(open(settings))
    ledger = mounts.get("/ledger", {}).get("src")
    if ledger and scenario.get("ledger_lines"):
        with open(os.path.join(ledger, "spend.jsonl"), "w") as fh:
            fh.write("".join(json.dumps(line) + "\n" for line in scenario["ledger_lines"]))
if argv[:1] == ["build"]:
    entry["context"] = sorted(os.listdir(argv[-1]))
with open(os.environ["FAKE_DOCKER_LOG"], "a") as fh:
    fh.write(json.dumps(entry) + "\n")
if argv[:1] == ["kill"] and "kill" in scenario.get("fail", []):
    sys.stderr.write("Error response from daemon: cannot kill container\n")
    sys.exit(1)
if argv[:1] in (["kill"], ["rm"], ["create"]) and argv[0] in scenario.get("hang", []):
    time.sleep(scenario.get("hang_s", 5))  # a create that hangs has already made its container: `orphan`
if argv[:2] == ["image", "inspect"]:
    if scenario.get("image") is None:
        sys.stderr.write("Error: No such image\n")
        sys.exit(1)
    print(json.dumps(scenario["image"]))
elif argv[:1] == ["ps"]:
    flt = argv[argv.index("--filter") + 1]
    if flt == "label=" + scenario["label"]:
        print(scenario.get("leftovers", ""))
    else:  # this launch's own containers, by its nonce: the verification
        if "verify" in scenario.get("hang", []):
            time.sleep(scenario.get("hang_s", 5))
        if scenario.get("survive_checks"):  # listed for the first N verifications, then gone
            seen = sum(1 for line in open(os.environ["FAKE_DOCKER_LOG"])
                       if json.loads(line)["argv"][:4] == argv[:4])
            if seen <= scenario["survive_checks"]:
                print(scenario["cid"])
                sys.exit(0)
        orphan = scenario.get("orphan")
        removed = any(json.loads(line)["argv"] == ["rm", "-f", orphan] for line in open(os.environ["FAKE_DOCKER_LOG"]))
        print(orphan if orphan and not removed else scenario.get("survivor", ""))
elif argv[:1] == ["create"]:
    print(scenario["cid"] if role == "arm" else scenario["bid"])
elif argv[:1] == ["start"] and "--attach" in argv:
    sys.stdout.write(scenario.get("output", ""))
    sys.stdout.flush()
    time.sleep(scenario.get("sleep", 0))
    sys.exit(scenario.get("exit", 0))
elif argv[:1] == ["start"]:
    sys.exit(scenario.get("broker_start_exit", 0))
elif argv[:1] == ["exec"]:  # the broker's /health, probed inside its container
    sys.exit(scenario.get("broker_ready_exit", 0))
elif argv[:1] == ["build"]:
    sys.exit(scenario.get("build_exit", 0))
'''


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


class Harness(unittest.TestCase):
    """A fixture checkout holding every entry point, a token file, and the stand-in docker."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="live-container-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        for script in [s for s, *_prefix in lc.ARMS.values()] + [lc.BROKER_SCRIPT]:
            path = self.repo / script
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("print('arm')\n", encoding="utf-8")
        (self.repo / WRAPPER.parent.relative_to(ROOT)).mkdir(parents=True)
        shutil.copy2(WRAPPER, self.repo / WRAPPER.relative_to(ROOT))
        git(self.repo.parent, "init", "-q", str(self.repo))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "fixture")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        self.token = "fixture-oauth-token-" + os.urandom(8).hex()
        self.token_file = self.tmp / "oauth-token"
        self.token_file.write_text(self.token + "\n", encoding="utf-8")
        self.token_file.chmod(0o600)
        self.results, self.receipts, self.lock = self.tmp / "results", self.tmp / "receipts", self.tmp / "launch.lock"
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
               "cid": CID, "bid": BID, "label": lc.LABEL, "attestation_path": lc.containment.ATTESTATION,
               "secret_path": SECRET, **overrides}
        self.scenario_path.write_text(json.dumps(doc), encoding="utf-8")

    def launch(self, *extra, arm="wip_curve", arm_args=("run", "--results", "/results/wip"), timeout="600",
               cap="50"):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = lc.main(["run", "--arm", arm, "--results", str(self.results), "--timeout", timeout, "--cap-usd", cap,
                          "--token-file", str(self.token_file), "--receipts", str(self.receipts),
                          "--lock", str(self.lock), *extra, "--", *arm_args])
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

    def create(self, role):
        found = [c for c in self.calls() if c["argv"][:1] == ["create"] and c["role"] == role]
        self.assertEqual(len(found), 1, [c["argv"][:2] for c in self.calls()])
        return found[0]

    def creates(self):
        return [c for c in self.calls() if c["argv"][:1] == ["create"]]

    def receipt(self):
        found = sorted(self.receipts.glob("*.json"))
        self.assertEqual(len(found), 1, found)
        return json.loads(found[0].read_text(encoding="utf-8"))


class OneArmRunsAndBothContainersAreVerifiedDestroyed(Harness):
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
        self.assertEqual((r["container"]["id"], r["broker"]["id"]), (CID, BID))
        self.assertEqual(r["broker"]["cap_usd"], 50.0)
        self.assertTrue(r["started_at"] and r["ended_at"])
        self.assertEqual((r["exit_status"], r["timed_out"], r["refused"]), (7, False, None))
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertEqual(r["destroyed"]["check"],
                         ["docker", "ps", "-a", "--filter", f"label={lc.LABEL}={r['nonce']}", "--format", "{{.ID}}"])
        verbs = [c["argv"][:2] if c["argv"][0] == "start" else c["argv"][:1] for c in self.calls()]
        self.assertLess(verbs.index(["start", BID]), verbs.index(["start", "--attach"]), "the arm started first")
        self.assertLess(verbs.index(["start", "--attach"]), verbs.index(["rm"]), verbs)
        self.assertEqual(verbs[-1], ["ps"], "the last word is the verification")
        for cid in (CID, BID):
            self.assertIn(["rm", "-f", cid], [c["argv"] for c in self.calls()])

    def test_the_arm_starts_only_once_the_broker_answers_inside_its_container(self):
        self.launch()
        argvs = [c["argv"] for c in self.calls()]
        probe = next(i for i, a in enumerate(argvs) if a[:2] == ["exec", BID])
        self.assertEqual(argvs[probe][2:4], ["python3", "-I"])
        self.assertIn(f"http://127.0.0.1:{lc.BROKER_PORT}/health", argvs[probe][-1])
        self.assertLess(probe, argvs.index(["start", "--attach", CID]))

    def test_the_arm_runs_the_pinned_commit_read_only_and_writes_only_the_results(self):
        self.launch()
        create = self.create("arm")
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
        arm, broker, r = self.create("arm"), self.create("broker"), self.receipt()
        # the arm's container joins the broker's network namespace, and with it the broker's hostname
        self.assertNotIn("--hostname", arm["argv"])
        hostname = broker["argv"][broker["argv"].index("--hostname") + 1]
        self.assertEqual(arm["attestation"]["nonce"], r["nonce"])
        self.assertEqual(arm["attestation"]["commit"], self.commit)
        self.assertEqual(hostname, lc.containment.HARNESS_HOSTNAME + r["nonce"])
        for create in (arm, broker):
            self.assertIn(f"{lc.LABEL}={r['nonce']}", create["argv"])
        # what the launcher writes is what the check inside the container reads
        root = self.tmp / "container-root"
        att = root / lc.containment.ATTESTATION.lstrip("/")
        att.parent.mkdir(parents=True)
        att.write_text(json.dumps(arm["attestation"]), encoding="utf-8")
        (root / ".dockerenv").write_text("", encoding="utf-8")
        self.assertIsNone(lc.containment.harness_problem(root=root, hostname=hostname, probe=lambda: None))

    def test_each_arm_runs_its_own_entry_point_under_an_in_container_backstop(self):
        for arm, (script, *prefix) in lc.ARMS.items():
            with self.subTest(arm=arm):
                shutil.rmtree(self.receipts, ignore_errors=True)
                self.log.unlink(missing_ok=True)
                outs = ("--out", "/results/o", "--workdir", "/results/w")
                rc, err = self.launch(arm=arm, arm_args=("--x", "1", *outs), timeout="600")
                self.assertEqual(rc, 0, err)
                argv = self.create("arm")["argv"]
                tail = argv[argv.index(IMAGE_ID) + 1:]
                self.assertEqual(tail, ["timeout", "--kill-after=30", str(600 + lc.BACKSTOP_S), "python3",
                                        f"/repo/{script}", *prefix, "--x", "1", *outs])
        self.assertEqual(sorted(lc.ARMS), ["ablation", "first_run", "hint_replay", "trajectories", "wip_curve"])
        self.assertEqual(sorted(lc.OUTPUTS), sorted(lc.ARMS))


class BothContainersAreHardened(Harness):
    def test_non_root_limited_unprivileged_and_on_no_host_namespace(self):
        self.launch()
        for create in self.creates():
            role, argv = create["role"], create["argv"]
            with self.subTest(role=role):
                pairs = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
                limits = lc.LIMITS if role == "arm" else lc.BROKER_LIMITS
                self.assertIn("--rm", argv)
                self.assertIn("--init", argv)
                # the arm as the image's runner; the broker as the operator, so it can read their token on Linux
                self.assertEqual(pairs["--user"], lc.USER if role == "arm" else f"{os.getuid()}:{os.getgid()}")
                self.assertFalse(pairs["--user"].split(":")[0] in ("0", "root"))
                self.assertEqual(pairs["--pids-limit"], str(limits["pids"]))
                self.assertEqual((pairs["--memory"], pairs["--memory-swap"]), (limits["memory"], limits["memory"]))
                self.assertEqual(pairs["--cpus"], limits["cpus"])
                self.assertEqual(pairs["--cap-drop"], "ALL")
                self.assertEqual(pairs["--security-opt"], "no-new-privileges")
                self.assertEqual(pairs["--log-driver"], "none")
                for banned in ("--privileged", "--cap-add", "--device", "--pid", "--ipc", "--uts", "--userns", "--net",
                               "-v", "--volume", "--volumes-from", "--add-host", "--group-add", "--env-file", "-p",
                               "--publish", "--publish-all"):
                    self.assertNotIn(banned, argv)
                self.assertFalse(any("docker.sock" in a for a in argv))
                networks = [argv[i + 1] for i, a in enumerate(argv) if a == "--network"]
                self.assertEqual(networks, [f"container:{BID}"] if role == "arm" else [],
                                 "the arm shares anything but the broker's network, or the broker anything at all")

    def test_the_limits_are_the_operators_to_set(self):
        self.launch("--pids-limit", "64", "--memory", "1g", "--cpus", "1.5")
        argv = self.create("arm")["argv"]
        self.assertEqual(argv[argv.index("--pids-limit") + 1], "64")
        self.assertEqual(argv[argv.index("--memory") + 1], "1g")
        self.assertEqual(argv[argv.index("--cpus") + 1], "1.5")
        self.assertEqual(self.receipt()["container"]["limits"], {"pids": 64, "memory": "1g", "cpus": "1.5"})


class TheTokenStaysInTheBrokersContainer(Harness):
    """Codex at 47e0616eac: a token mounted in the arm's container is readable by uid 10001, which
    runs the agents and every test they write. The token is mounted in the broker's container
    alone; the arm's holds no credential and shares only the broker's network namespace."""

    def test_the_arms_container_holds_no_credential(self):
        rc, err = self.launch()
        self.assertEqual(rc, 0, err)
        arm = self.create("arm")
        self.assertNotIn(SECRET, arm["mounts"])
        self.assertNotIn("secret", arm, "the arm's container was given the token file")
        envs = [arm["argv"][i + 1] for i, a in enumerate(arm["argv"]) if a in ("--env", "-e")]
        self.assertEqual(envs, [f"PATH={lc.CONTAINER_PATH}"], "the arm's environment carries anything but PATH")

    def test_the_broker_alone_mounts_it_read_only_and_runs_under_the_cap(self):
        self.launch(cap="12.5")
        broker, r = self.create("broker"), self.receipt()
        mount = broker["mounts"][SECRET]
        self.assertEqual(mount["src"], str(self.token_file))
        self.assertIs(mount.get("readonly"), True)
        self.assertEqual(broker["secret"], self.token, "the mount does not carry the operator's token")
        argv = broker["argv"]
        envs = [argv[i + 1] for i, a in enumerate(argv) if a in ("--env", "-e")]
        self.assertEqual(envs, ["PATH=/usr/local/bin:/usr/bin:/bin"])
        tail = argv[argv.index(IMAGE_ID) + 1:]
        self.assertEqual(tail[3:6], ["python3", "-I", f"/repo/{lc.BROKER_SCRIPT}"])
        self.assertEqual(tail[tail.index("--cap-usd") + 1], "12.5")
        self.assertEqual(tail[tail.index("--token-file") + 1], SECRET)
        self.assertEqual(tail[tail.index("--port") + 1], str(lc.BROKER_PORT))
        ledger = Path(broker["mounts"]["/ledger"]["src"])
        self.assertNotIn("readonly", broker["mounts"]["/ledger"])
        self.assertEqual(ledger.parent, self.receipts, "the broker's ledger is not beside the receipt")
        self.assertFalse(lc.inside(ledger, self.results), "the arm could reach the broker's ledger")
        self.assertEqual(stat.S_IMODE(ledger.stat().st_mode), 0o700)
        self.assertEqual(r["token"]["mounted_at"], SECRET)

    def test_no_command_line_environment_receipt_or_log_carries_it(self):
        self.scenario({"output": f"an arm that printed it: {self.token}\n"})
        rc, err = self.launch()
        self.assertEqual(rc, 0, err)
        for c in self.calls():
            self.assertFalse(any(self.token in a for a in c["argv"]), c["argv"][:2])
            self.assertFalse(any(lc.TOKEN_ENV in a for a in c["argv"]), f"docker {c['argv'][0]} names the token")
            self.assertIsNone(c["token"], f"docker {c['argv'][0]} ran with the token in its environment")
        r = self.receipt()
        self.assertNotIn(self.token, json.dumps(r))
        self.assertNotIn(self.token, err)
        log = Path(r["log"])
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600, "the log is readable by others")
        text = log.read_text(encoding="utf-8")
        self.assertNotIn(self.token, text)
        self.assertIn("[REDACTED]", text)
        self.assertEqual(r["token_redactions"], 1)

    def test_a_token_file_the_arm_could_reach_is_refused(self):
        # Codex at 8585b35789: a token file inside the results mount reached the arm as /results/<name>
        self.results.mkdir()
        inside_results = self.results / "sub" / "oauth-token"
        inside_results.parent.mkdir()
        shutil.copy2(self.token_file, inside_results)
        alias = self.tmp / "alias"
        alias.symlink_to(self.results / "sub")  # a symlinked ancestor reaches the same file
        for token_file in (inside_results, alias / "oauth-token", self.repo / "oauth-token"):
            with self.subTest(token_file=token_file):
                self.token_file = token_file
                rc, err = self.launch()
                self.assertEqual(rc, 2, err)
                self.assertIn("which the arm's container mounts", err)
        self.assertEqual(self.calls(), [])

    def test_a_missing_token_file_is_refused_before_docker_is_called(self):
        self.token_file.unlink()
        rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("cannot be opened", err)
        self.assertEqual(self.calls(), [])

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


class TheLogIsRedactedAsItIsWritten(unittest.TestCase):
    """Greptile and Codex at 47e0616eac: the output reached the disk first and was redacted at the
    end, so a killed launcher left the token in a world-readable file. Now no byte of it is ever
    written: the stream passes a redactor that holds back only what could begin the token."""

    class Sink(io.BytesIO):
        def close(self):  # the redactor closes its file at the end: keep the bytes readable
            pass

    def redact(self, chunks, secret=b"sk-ant-oat01-SECRET"):
        out = self.Sink()
        redactor = lc.Redactor(out, secret)
        written = []
        for chunk in chunks:
            redactor.write(chunk)
            written.append(out.getvalue())
        redactor.close()
        return out.getvalue(), redactor.count, written

    def test_a_token_split_across_reads_never_reaches_the_file(self):
        secret = b"sk-ant-oat01-SECRET"
        for cut in range(1, len(secret)):
            with self.subTest(cut=cut):
                text, count, written = self.redact([b"before " + secret[:cut], secret[cut:] + b" after"])
                self.assertEqual(text, b"before [REDACTED] after")
                self.assertEqual(count, 1)
                self.assertEqual(written[0], b"before ", "a piece of the token was written before the rest came")

    def test_what_only_looked_like_a_start_is_written_out_at_the_end(self):
        text, count, _ = self.redact([b"sk-ant", b"-oat01-SEC"])
        self.assertEqual((text, count), (b"sk-ant-oat01-SEC", 0))

    def test_every_occurrence_is_counted(self):
        text, count, _ = self.redact([b"a sk-ant-oat01-SECRET b sk-ant-oat01-SECRET", b"sk-ant-oat01-SECRET"])
        self.assertEqual((text, count), (b"a [REDACTED] b [REDACTED][REDACTED]", 3))


class TheBrokersLedgerIsSummarisedInTheReceipt(Harness):
    def test_the_receipt_carries_what_the_broker_settled_and_left_open(self):
        self.scenario({"ledger_lines": [
            {"event": "open", "cap_usd": 50.0},
            {"event": "start", "call": 1, "reserved_usd": 2.0},
            {"event": "settle", "call": 1, "cost_usd": 0.75, "complete": True},
            {"event": "start", "call": 2, "reserved_usd": 1.5},
            {"event": "refuse", "why": "the cap"}]})
        rc, err = self.launch()
        self.assertEqual(rc, 0, err)
        spend = self.receipt()["broker"]["spend"]
        self.assertEqual({k: v for k, v in spend.items() if k != "ledger"},
                         {"read": True, "cap_usd": 50.0, "calls": 2, "refused": 1, "settled_usd": 0.75,
                          "unsettled_calls": 1, "unsettled_reserved_usd": 1.5})

    def test_a_ledger_the_broker_never_wrote_says_so(self):
        self.launch()
        spend = self.receipt()["broker"]["spend"]
        self.assertEqual((spend["read"], spend["error"]), (False, "FileNotFoundError"))


class OutputsStayUnderResults(Harness):
    """Codex at 47e0616eac: ablation and trajectories defaulted --out to a temp dir inside the
    container, so destroying it erased the ledger. An arm whose ledger defaults to a temp dir must
    name one, and every output flag must name a path under /results."""

    def refused(self, arm, arm_args, why):
        self.log.unlink(missing_ok=True)
        rc, err = self.launch(arm=arm, arm_args=arm_args)
        self.assertEqual(rc, 2, err)
        self.assertIn(why, err)
        self.assertEqual(self.calls(), [], "docker was called for a launch whose ledger would die with it")

    def test_an_arm_whose_ledger_defaults_to_a_temp_dir_must_name_one(self):
        self.assertEqual(lc.REQUIRED["first_run"], "--workdir", "first_run's receipt.json dies in a temp workdir")
        for arm in sorted(lc.REQUIRED):
            with self.subTest(arm=arm):
                self.refused(arm, ("run", "--tier", "live"), f"needs {lc.REQUIRED[arm]} under /results")

    def test_an_output_outside_results_is_refused(self):
        cases = [("ablation", ("run", "--out", "/tmp/x")), ("ablation", ("run", "--out=../x")),
                 ("ablation", ("run", "--ou", "/repo/x")), ("trajectories", ("--out", "/results/../etc")),
                 ("wip_curve", ("run", "--results", "/tmp/wip")), ("wip_curve", ("report", "--out", "/home/x")),
                 ("first_run", ("run", "--workdir", "/tmp/sb"))]
        for arm, arm_args in cases:
            with self.subTest(arm=arm, arm_args=arm_args):
                self.refused(arm, arm_args, "is outside /results")
        self.refused("ablation", ("run", "--out"), "names no path")

    def test_an_output_under_results_runs(self):
        for arm, arm_args in (("ablation", ("run", "--out", "out")), ("hint_replay", ("--out=/results/a/r.json",)),
                              ("trajectories", ("--out", "/results")), ("first_run", ("run", "--workdir", "w"))):
            with self.subTest(arm=arm, arm_args=arm_args):
                shutil.rmtree(self.receipts, ignore_errors=True)
                rc, err = self.launch(arm=arm, arm_args=arm_args)
                self.assertEqual(rc, 0, err)


class OneLaunchAtATime(Harness):
    def test_a_held_lock_refuses_before_any_container(self):
        fd = os.open(self.lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another launcher, mid-launch
        rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("another launch holds", err)
        self.assertEqual([c["argv"][0] for c in self.calls() if c["argv"][0] in ("ps", "create")], [],
                         "the leftover check or a create ran without the lock")

    def test_the_lock_is_released_however_the_launch_ends(self):
        for scenario in ({"exit": 1}, {"leftovers": "deadbeef"}):
            with self.subTest(scenario=scenario):
                self.scenario(scenario)
                shutil.rmtree(self.receipts, ignore_errors=True)
                self.launch()
                fd = os.open(self.lock, os.O_RDWR)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(fd)

    def test_a_harness_container_that_still_exists_refuses_the_next_launch(self):
        self.scenario({"leftovers": "deadbeef"})
        rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("already exists", err)
        self.assertEqual(self.creates(), [])


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
        self.assertEqual(self.creates(), [])

    def test_a_cap_that_is_not_positive_is_refused(self):
        for cap in ("0", "-5", "nan"):
            with self.subTest(cap=cap):
                rc, err = self.launch(cap=cap)
                self.assertEqual(rc, 2, err)
                self.assertIn("--cap-usd", err)
        self.assertEqual(self.calls(), [])

    def test_results_or_receipts_the_container_could_reach_are_refused(self):
        for results, receipts in ((self.repo / "out", self.receipts), (self.results, self.results / "receipts")):
            with self.subTest(results=results, receipts=receipts):
                self.results, self.receipts = results, receipts
                rc, err = self.launch()
                self.assertEqual(rc, 2, err)
                self.assertIn("overlaps", err)
        self.assertEqual(self.creates(), [])


class TeardownNeverLosesTheReceipt(Harness):
    """Codex and Greptile at 47e0616eac: a `docker kill` that timed out raised out of the teardown,
    skipping the removal, the verification and the receipt. Every teardown step is now attempted
    and recorded, and the receipt is written whatever happens."""

    def test_a_hanging_kill_still_removes_verifies_and_writes_the_receipt(self):
        self.scenario({"sleep": 60, "hang": ["kill"], "hang_s": 5})
        with mock.patch.object(lc, "TEARDOWN_TIMEOUT_S", 0.5):
            rc, err = self.launch(timeout="1")
        self.assertEqual(rc, lc.EXIT_TIMED_OUT, err)
        r = self.receipt()
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertIn("docker kill", " ".join(r["destroyed"]["errors"]))
        self.assertIn(["rm", "-f", CID], [c["argv"] for c in self.calls(partial=True)])

    def test_a_teardown_step_that_fails_is_recorded_in_the_receipt(self):
        # Codex at 0116e8ae34: a nonzero kill vanished from a receipt that read verified, no errors
        self.scenario({"fail": ["kill"]})
        rc, err = self.launch()
        self.assertEqual(rc, 0, err)
        destroyed = self.receipt()["destroyed"]
        self.assertIs(destroyed["verified"], True)
        self.assertIn(f"docker kill {CID}: exit 1: Error response from daemon: cannot kill container",
                      destroyed["nonzero"])

    def test_a_retried_teardown_keeps_what_the_first_one_saw(self):
        # #673: the retry replaced the first teardown's record, so its diagnostics vanished
        self.scenario({"sleep": 60, "fail": ["kill"], "survive_checks": 2})
        with mock.patch.object(lc, "DESTROY_WAIT_S", 0.3):
            rc, err = self.launch(timeout="1")
        self.assertEqual(rc, lc.EXIT_TIMED_OUT, err)
        destroyed = self.receipt()["destroyed"]
        self.assertIs(destroyed["verified"], True)
        kills = [n for n in destroyed["nonzero"] if n.startswith(f"docker kill {CID}")]
        self.assertEqual(len(kills), 2, f"one teardown's kill failure is missing: {destroyed['nonzero']}")

    def test_a_verification_that_keeps_timing_out_fails_closed_with_a_receipt(self):
        self.scenario({"hang": ["verify"], "hang_s": 5})
        with mock.patch.object(lc, "TEARDOWN_TIMEOUT_S", 0.5), mock.patch.object(lc, "DESTROY_WAIT_S", 0.5):
            rc, err = self.launch()
        self.assertEqual(rc, lc.EXIT_NOT_DESTROYED, err)
        self.assertIn("FAIL-CLOSED", err)
        r = self.receipt()
        self.assertIs(r["destroyed"]["verified"], False)
        self.assertIn("TimeoutExpired", r["destroyed"]["output"])

    def test_a_create_whose_answer_is_lost_is_found_by_its_nonce_destroyed_and_receipted(self):
        # Codex at 3c01b90b5e: docker made the broker but the launcher never got its id back
        self.scenario({"hang": ["create"], "hang_s": 5, "orphan": BID})
        with mock.patch.object(lc, "CREATE_TIMEOUT_S", 0.5):
            rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("docker create of the broker timed out", err)
        r = self.receipt()
        self.assertIsNone(r["broker"]["id"])
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertIn(["rm", "-f", BID], [c["argv"] for c in self.calls(partial=True)])

    def test_a_broker_that_does_not_start_is_destroyed_and_the_launch_refused(self):
        self.scenario({"broker_start_exit": 1})
        rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("docker start of the broker failed", err)
        r = self.receipt()
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertIn("docker start of the broker failed", r["refused"])
        self.assertNotIn(["start", "--attach"], [c["argv"][:2] for c in self.calls()])


class APerCallLimitReachesEveryClaudeCall(Harness):
    """A registration may fix a per-call limit (#604's claude --max-budget-usd 1.60). The launcher
    hands it to the arm's claude as a read-only settings file; the wrapper appends it."""

    def test_the_arm_gets_the_limit_read_only(self):
        rc, err = self.launch("--per-call-usd", "1.6")
        self.assertEqual(rc, 0, err)
        arm = self.create("arm")
        self.assertIs(arm["mounts"][lc.CLAUDE_SETTINGS].get("readonly"), True)
        self.assertEqual(arm["claude_settings"], {"max_budget_usd": "1.60"})
        self.assertNotIn(lc.CLAUDE_SETTINGS, self.create("broker")["mounts"])
        r = self.receipt()
        self.assertEqual(r["per_call_usd"], 1.6)
        self.assertIn(lc.CLAUDE_SETTINGS, r["container"]["mounts"])

    def test_without_one_no_settings_are_mounted(self):
        self.launch()
        self.assertNotIn(lc.CLAUDE_SETTINGS, self.create("arm")["mounts"])
        self.assertIsNone(self.receipt()["per_call_usd"])

    def test_a_limit_that_is_not_positive_or_passes_the_cap_is_refused(self):
        for limit in ("0", "-1", "60"):
            with self.subTest(limit=limit):
                rc, err = self.launch("--per-call-usd", limit)
                self.assertEqual(rc, 2, err)
                self.assertIn("--per-call-usd", err)
        self.assertEqual(self.calls(), [])


class ABrokerNeverRunsAsRoot(Harness):
    def test_a_root_launcher_is_refused(self):
        with mock.patch.object(lc.os, "getuid", return_value=0):
            rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("not root", err)
        self.assertEqual(self.creates(), [])


class ABrokerThatNeverAnswersStartsNoArm(Harness):
    def test_it_is_destroyed_and_the_launch_refused(self):
        self.scenario({"broker_ready_exit": 1})
        with mock.patch.object(lc, "BROKER_READY_S", 0.3):
            rc, err = self.launch()
        self.assertEqual(rc, 2, err)
        self.assertIn("the broker never answered", err)
        r = self.receipt()
        self.assertIs(r["destroyed"]["verified"], True)
        self.assertIn("could not open the token file or its ledger", r["refused"])
        self.assertNotIn(["start", "--attach"], [c["argv"][:2] for c in self.calls()])


class TheWallClockLimitEndsIt(Harness):
    def test_the_launcher_kills_removes_and_verifies(self):
        self.scenario({"sleep": 60})
        started = time.monotonic()
        rc, err = self.launch(timeout="1")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(rc, lc.EXIT_TIMED_OUT, err)
        argvs = [c["argv"] for c in self.calls()]
        for cid in (CID, BID):
            self.assertIn(["kill", cid], argvs)
            self.assertIn(["rm", "-f", cid], argvs)
        self.assertLess(argvs.index(["kill", CID]), argvs.index(["kill", BID]),
                        "the broker went before the arm, leaving its calls unsettled")
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

    def test_a_signal_destroys_both_containers_before_the_launcher_exits(self):
        self.scenario({"sleep": 60})

        def interrupt():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if any(c["argv"][:2] == ["start", "--attach"] for c in self.calls(partial=True)):
                    os.kill(os.getpid(), signal.SIGTERM)  # only while the launcher's handler is in place
                    return
                time.sleep(0.05)
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
        for cid in (CID, BID):
            self.assertIn(["kill", cid], [c["argv"][:2] for c in self.calls()])


class TheImageIsBuiltFromTheCommittedDockerfile(Harness):
    def test_build_labels_the_dockerfiles_digest_and_sends_an_empty_context(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = lc.main(["build"])
        self.assertEqual(rc, 0)
        build = [c for c in self.calls() if c["argv"][:1] == ["build"]]
        self.assertEqual(len(build), 1)
        self.assertEqual(build[0]["argv"][:5], ["build", "-f", str(lc.DOCKERFILE), "-t", lc.IMAGE])
        self.assertIn(f"{lc.DOCKERFILE_LABEL}={lc.sha256_file(lc.DOCKERFILE)}", build[0]["argv"])
        self.assertEqual(build[0]["context"], [], "the build context is not empty")

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


# ---------------------------------------------------------------------------- the credential broker

def usage_events(usage_start, usage_delta, stop=True):
    """An SSE answer as the API streams one: message_start, a delta, message_delta, message_stop."""
    events = [{"type": "message_start", "message": {"id": "msg_1", "usage": usage_start}},
              {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
              {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": usage_delta}]
    if stop:
        events.append({"type": "message_stop"})
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


USAGE = {"input_tokens": 2, "cache_creation_input_tokens": 6392, "cache_read_input_tokens": 10307, "output_tokens": 1,
         "cache_creation": {"ephemeral_5m_input_tokens": 6392, "ephemeral_1h_input_tokens": 0},
         "inference_geo": "global"}  # as the API reported it on the live smoke call


class StandInAPI:
    """The API on 127.0.0.1: records each request and answers with the next scripted reply."""

    def __init__(self, test):
        self.requests, self.replies = [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append({"path": self.path, "headers": dict(self.headers.items()), "body": body})
                status, ctype, data = outer.replies.pop(0) if outer.replies else (200, "text/event-stream",
                                                                                   usage_events(USAGE, {"output_tokens": 4}))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"


class TheBrokerHoldsTheTokenAndTheCap(unittest.TestCase):
    """scripts/live_broker.py: the one process with the token. It forwards a model call with the
    token in place of the arm's placeholder, refuses everything else, and refuses any call whose
    worst case would pass the cap; it settles each call as the API bills it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="live-broker-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.token = "sk-ant-oat01-fixture-" + os.urandom(8).hex()
        self.api = StandInAPI(self)
        self.ledger_path = self.tmp / "spend.jsonl"

    def broker(self, cap=5.0):
        server, ledger = lb.serve(self.token, self.ledger_path, cap, port=0, upstream=self.api.url)
        self.addCleanup(ledger.fh.close)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        return ledger

    def post(self, path="/v1/messages?beta=true", doc=None, raw=None, headers=None):
        body = raw if raw is not None else json.dumps(doc if doc is not None else self.body()).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01",
                                                       "Authorization": "Bearer open-fleet-live-broker",
                                                       "x-api-key": "not-a-key", **(headers or {})})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def body(self, **extra):
        return {"model": "claude-haiku-5-5", "max_tokens": 1000, "stream": True,
                "messages": [{"role": "user", "content": "Reply with the single word ok"}], **extra}

    def events(self):
        return [json.loads(line) for line in self.ledger_path.read_text(encoding="utf-8").splitlines()]

    def test_a_call_reaches_the_api_with_the_token_in_place_of_the_placeholder(self):
        self.broker()
        status, data = self.post(headers={"anthropic-beta": "claude-code-20250219"})
        self.assertEqual(status, 200)
        self.assertEqual(data, usage_events(USAGE, {"output_tokens": 4}), "the answer was not relayed unchanged")
        (req,) = self.api.requests
        headers = {k.lower(): v for k, v in req["headers"].items()}
        self.assertEqual(headers["authorization"], f"Bearer {self.token}")
        self.assertNotIn("x-api-key", headers)
        self.assertEqual(headers["anthropic-beta"], "claude-code-20250219,oauth-2025-04-20")
        self.assertEqual(req["path"], "/v1/messages?beta=true")
        self.assertEqual(json.loads(req["body"]), self.body())
        start, settle = self.events()[1:]
        self.assertEqual((start["event"], settle["event"], settle["complete"]), ("start", "settle", True))
        self.assertAlmostEqual(settle["cost_usd"], lb.priced({**USAGE, "output_tokens": 4}, "claude-haiku-5-5"), 6)
        self.assertNotIn(self.token, self.ledger_path.read_text(encoding="utf-8"))
        self.assertNotIn(self.token.encode(), data)
        self.assertEqual(stat.S_IMODE(self.ledger_path.stat().st_mode), 0o600)

    def test_usage_settles_as_the_api_bills_it(self):
        # The live smoke run through the broker on 2026-10-25 (Claude Code 2.1.304, Haiku 5.5): the
        # API reported USAGE with 4 output tokens, and Claude Code's own total_cost_usd was 0.00090427.
        self.assertAlmostEqual(lb.priced({**USAGE, "output_tokens": 4}, "claude-haiku-5-5"), 0.00090427, 8)
        one_hour = {"cache_creation_input_tokens": 1000, "cache_creation": {"ephemeral_1h_input_tokens": 1000}}
        unsplit = {"cache_creation_input_tokens": 1000}
        self.assertAlmostEqual(lb.priced(one_hour, "claude-opus-5-5"), 1000 * 4.0 * 2.0 / 1e6)
        self.assertAlmostEqual(lb.priced(unsplit, "claude-opus-5-5"), 1000 * 4.0 * 2.0 / 1e6, msg="unsplit is not the 1h rate")
        self.assertAlmostEqual(lb.priced({"input_tokens": 200_000}, "claude-haiku-5-5"), 200_000 * 0.50 / 1e6)
        self.assertAlmostEqual(lb.priced({"output_tokens": 10}, "claude-opus-5-5", lb.FAST), 10 * 40.0 / 1e6)
        self.assertAlmostEqual(lb.priced({"output_tokens": 10}, "claude-haiku-4-5-20251001"), 10 * 5.0 / 1e6)
        self.assertGreaterEqual(lb.reservation(100, 1000, "claude-haiku-5-5"),
                                lb.priced({"input_tokens": 100 + lb.FRAMING_TOKENS, "output_tokens": 1000},
                                          "claude-haiku-5-5"))

    def test_a_call_whose_worst_case_would_pass_the_cap_never_reaches_the_api(self):
        self.broker(cap=0.001)
        status, data = self.post()
        self.assertEqual(status, 403, data)
        self.assertIn(b"spend cap", data)
        self.assertEqual(self.api.requests, [])
        self.assertEqual(self.events()[-1]["event"], "refuse")

    def test_calls_in_flight_count_against_the_cap(self):
        ledger = lb.Ledger(self.ledger_path, 1.0)
        self.addCleanup(ledger.fh.close)
        first = ledger.reserve("claude-opus-5-5", 0.6)
        self.assertIsNotNone(first)
        self.assertIsNone(ledger.reserve("claude-opus-5-5", 0.6), "a second call passed the cap beside the first")
        ledger.settle(first, 0.1, 200, {}, True)
        self.assertIsNotNone(ledger.reserve("claude-opus-5-5", 0.6))
        ledger.settle(2, None, None, {}, False)  # an unfinished call settles its whole reservation
        self.assertAlmostEqual(ledger.settled, 0.7)

    def test_a_stream_without_its_end_settles_its_whole_reservation(self):
        self.broker()
        self.api.replies.append((200, "text/event-stream", usage_events(USAGE, {"output_tokens": 4}, stop=False)))
        self.post()
        start, settle = self.events()[1:]
        self.assertIs(settle["complete"], False)
        self.assertEqual(settle["cost_usd"], start["reserved_usd"])

    def test_an_error_the_api_answers_at_once_settles_nothing(self):
        self.broker()
        self.api.replies.append((529, "application/json", b'{"type":"error","error":{"type":"overloaded_error"}}'))
        status, _data = self.post(doc=self.body(stream=False))
        self.assertEqual(status, 529)
        self.assertEqual((self.events()[-1]["cost_usd"], self.events()[-1]["complete"]), (0.0, True))

    def test_a_non_streamed_answer_settles_its_usage(self):
        self.broker()
        answer = json.dumps({"id": "msg_1", "content": [], "usage": {"input_tokens": 100, "output_tokens": 10,
                                                                      "inference_geo": "global"}}).encode()
        self.api.replies.append((200, "application/json", answer))
        self.post(doc=self.body(stream=False))
        self.assertAlmostEqual(self.events()[-1]["cost_usd"], (100 * 0.10 + 10 * 0.50) / 1e6, 9)

    def test_anything_unpriced_or_unlisted_never_reaches_the_api(self):
        self.broker()
        for path in ("/v1/complete", "/api/oauth/profile", "/v1/messages/batches"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path=path)[0], 403)
        bodies = {"not JSON": b"{", "an unpriced model": self.body(model="claude-3-opus"),
                  "no max_tokens": {k: v for k, v in self.body().items() if k != "max_tokens"},
                  "a server tool": self.body(tools=[{"type": "web_search_20260209", "name": "web_search"}]),
                  "an MCP server": self.body(mcp_servers=[{"type": "url", "url": "https://x.invalid", "name": "x"}])}
        for what, body in bodies.items():
            with self.subTest(what=what):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.assertEqual(self.post(raw=raw)[0], 400)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", "/v1/models")
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual(self.api.requests, [], "a refused request reached the API")
        self.assertNotIn("start", [e["event"] for e in self.events()])

    def test_only_the_checked_path_and_query_are_forwarded(self):
        self.broker()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        body = json.dumps(self.body()).encode()
        conn.request("POST", "http://elsewhere.invalid/v1/messages?beta=true", body=body,
                     headers={"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()
        self.assertEqual(self.api.requests[0]["path"], "/v1/messages?beta=true")

    def test_content_its_bytes_do_not_bound_never_reaches_the_api(self):
        # Codex at 8585b35789: an image by URL reserved its JSON bytes, not what the API bills for it
        self.broker()
        image = lambda source: {"role": "user", "content": [{"type": "image", "source": source}]}
        bodies = {
            "an image by URL": [image({"type": "url", "url": "https://x.invalid/a.png"})],
            "an image by file": [image({"type": "file", "file_id": "file_1"})],
            "a document by file id": [{"role": "user", "content": [{"type": "document", "source": {"type": "file",
                                                                                                   "file_id": "f"}}]}],
            "a PDF": [{"role": "user", "content": [{"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}}]}],
            "a URL inside a tool result": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                                                          "content": [{"type": "image", "source": {
                                                                              "type": "url", "url": "https://x.invalid"}}]}]}],
        }
        for what, messages in bodies.items():
            with self.subTest(what=what):
                status, data = self.post(doc=self.body(messages=messages))
                self.assertEqual(status, 400, data)
        self.assertEqual(self.api.requests, [])

    def test_an_inline_image_is_reserved_at_its_worst_case(self):
        img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
        why, mult, images = lb.terms(self.body(messages=[{"role": "user", "content": [img, img]}], inference_geo="global"))
        self.assertEqual((why, mult, images), (None, 1.0, 2))
        self.assertAlmostEqual(lb.reservation(100, 10, "claude-opus-5-5", 1.0, 2) - lb.reservation(100, 10, "claude-opus-5-5"),
                               2 * lb.IMAGE_TOKENS * 4.0 * lb.WRITE_1H / 1e6)
        self.assertGreaterEqual(lb.IMAGE_TOKENS, 4784, "below the most one image costs")

    def test_only_the_clients_own_tools_and_the_fields_it_prices_pass(self):
        # Codex at 8585b35789: an advisor tool passed, and its sub-inference was neither reserved nor settled
        self.broker()
        refused = {"an advisor tool": self.body(tools=[{"type": "advisor_20260301", "name": "advisor",
                                                        "model": "claude-fable-5-1"}]),
                   "an Anthropic-defined tool": self.body(tools=[{"type": "bash_20250124", "name": "bash"}]),
                   "an unpriced field": self.body(betas=["x"]),
                   "a container": self.body(container="c"),
                   "a priority tier": self.body(service_tier="auto"),
                   "an unpriced geography": self.body(inference_geo="eu"),
                   "an unknown speed": self.body(speed="turbo"),
                   "server-side compaction": self.body(context_management={"edits": [{"type": "compact_20260112"}]})}
        for what, body in refused.items():
            with self.subTest(what=what):
                self.assertEqual(self.post(doc=body)[0], 400, what)
        self.assertEqual(self.api.requests, [])
        tool = {"name": "Bash", "description": "run", "input_schema": {"type": "object"}}
        ok = self.body(tools=[tool, {**tool, "type": "custom"}], tool_choice={"type": "auto"}, metadata={"user_id": "u"},
                       context_management={"edits": [{"type": "clear_tool_uses_20250919"}]},
                       thinking={"type": "adaptive"}, system="s", output_config={"effort": "low"})
        self.assertEqual(self.post(doc=ok)[0], 200)

    def test_a_tool_defined_inside_the_content_is_held_to_the_same_rule(self):
        # Codex at 0116e8ae34: with inline-tools, a system message's tool_addition defined web_search
        self.broker()
        addition = lambda definition: {"role": "system", "content": [{"type": "tool_addition",
                                                                      "tool_definition": definition}]}
        user = {"role": "user", "content": "hi"}
        inline = self.body(messages=[user, addition({"type": "web_search_20250305", "name": "web_search"})])
        status, data = self.post(doc=inline, headers={"anthropic-beta": "inline-tools-2026-09-15"})
        self.assertEqual(status, 400, data)
        listed = self.body(messages=[user, addition([{"type": "advisor_20260301", "name": "advisor"}])])
        self.assertEqual(self.post(doc=listed)[0], 400)
        stray = self.body(messages=[{"role": "user", "content": [{"type": "code_execution_20260521", "name": "x"}]}])
        self.assertEqual(self.post(doc=stray)[0], 400)
        self.assertEqual(self.api.requests, [])
        own = self.body(messages=[user, addition({"name": "Lookup", "input_schema": {"type": "object"}})])
        self.assertEqual(self.post(doc=own)[0], 200, "the client's own inline tool was refused")

    def test_a_reported_web_search_is_charged(self):
        self.assertAlmostEqual(lb.settled({"server_tool_use": {"web_search_requests": 12}}, "claude-haiku-5-5"),
                               12 * lb.SEARCH_USD)
        merged = lb.merged_usage({}, {"server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 1}})
        self.assertEqual(merged["server_tool_use"], {"web_search_requests": 2, "web_fetch_requests": 1})

    def test_us_inference_is_reserved_and_settled_at_its_premium(self):
        # Codex at 8585b35789: inference_geo "us" is billed at 1.1x every category
        self.assertEqual(lb.terms(self.body(inference_geo="us"))[1], 1.1)
        self.assertEqual(lb.terms(self.body(inference_geo="us", speed="fast"))[1], 1.1 * lb.FAST)
        self.broker()
        self.api.replies.append((200, "text/event-stream",
                                 usage_events({**USAGE, "inference_geo": "us"}, {"output_tokens": 4})))
        self.post(doc=self.body(inference_geo="us"))
        start, settle = self.events()[1:]
        usage = {**USAGE, "output_tokens": 4}
        self.assertAlmostEqual(settle["cost_usd"], lb.priced(usage, "claude-haiku-5-5") * 1.1, 6)
        self.assertAlmostEqual(start["reserved_usd"], lb.reservation(len(json.dumps(self.body(inference_geo="us"))),
                                                                     1000, "claude-haiku-5-5") * 1.1, 4)

    def test_an_omitted_geography_reserves_at_the_us_premium_and_settles_as_reported(self):
        # Codex at 3c01b90b5e: a request naming no geography runs in the workspace default, maybe US
        self.assertEqual(lb.terms(self.body())[1], lb.GEO_WORST)
        self.assertEqual(lb.terms(self.body(inference_geo="global"))[1], 1.0)
        usage = {**USAGE, "output_tokens": 4}
        for reported, mult in (("global", 1.0), ("us", 1.1), (None, lb.GEO_WORST), ("mars", lb.GEO_WORST)):
            with self.subTest(reported=reported):
                self.assertEqual(lb.settle_mult({**usage, "inference_geo": reported}, False), mult)
        self.assertEqual(lb.settle_mult({"inference_geo": "global", "speed": "fast"}, False), lb.FAST)
        self.broker()
        no_geo = {k: v for k, v in USAGE.items() if k != "inference_geo"}
        self.api.replies.append((200, "text/event-stream", usage_events(no_geo, {"output_tokens": 4})))
        self.post()
        start, settle = self.events()[1:]
        self.assertAlmostEqual(start["reserved_usd"], lb.reservation(len(json.dumps(self.body())), 1000,
                                                                     "claude-haiku-5-5") * lb.GEO_WORST, 4)
        self.assertAlmostEqual(settle["cost_usd"], lb.priced(usage, "claude-haiku-5-5") * lb.GEO_WORST, 6)

    def test_iterations_settle_when_they_cost_more(self):
        top = {"input_tokens": 10, "output_tokens": 10}
        iterations = [{"input_tokens": 10, "output_tokens": 10},
                      {"model": "claude-fable-5-1", "input_tokens": 1000, "output_tokens": 500},
                      {"model": "claude-unknown", "input_tokens": 100}]
        expected = (lb.priced(iterations[0], "claude-haiku-5-5") + lb.priced(iterations[1], "claude-fable-5-1")
                    + lb.priced(iterations[2], lb.COSTLIEST))
        self.assertAlmostEqual(lb.settled({**top, "iterations": iterations}, "claude-haiku-5-5"), expected)
        self.assertEqual(lb.merged_usage({}, {"iterations": iterations})["iterations"], iterations)

    def test_count_tokens_is_forwarded_and_free(self):
        self.broker()
        self.api.replies.append((200, "application/json", b'{"input_tokens": 12}'))
        status, data = self.post(path="/v1/messages/count_tokens", doc={"model": "claude-haiku-5-5", "messages": []})
        self.assertEqual((status, data), (200, b'{"input_tokens": 12}'))
        self.assertEqual(self.api.requests[0]["headers"]["Authorization"], f"Bearer {self.token}")
        self.assertEqual([e["event"] for e in self.events()], ["open"])

    def test_health_answers_without_the_token(self):
        self.broker(cap=7.0)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        self.assertEqual((resp.status, json.loads(resp.read())), (200, {"ok": True, "cap_usd": 7.0}))
        conn.close()


# ---------------------------------------------------------------------------- the arm's `claude`

def load_wrapper():
    """The arm's `claude` wrapper as a module (it has no .py suffix), writing no bytecode."""
    loader = importlib.machinery.SourceFileLoader("live_container_claude_under_test", str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    prior, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prior
    return mod


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TheArmsClaudeTalksToTheBroker(unittest.TestCase):
    """Inside the arm's container `claude` on PATH is scripts/live_container_bin/claude. It holds no
    token: it execs the pinned Claude Code with the broker as its API and a placeholder credential,
    dropping any credential, endpoint or proxy the arm's environment carries."""

    def setUp(self):
        self.wrapper = load_wrapper()

    def run_wrapper(self, *argv, environ=None, ready=True):
        execs = []

        def execve(path, args, env):  # exec never returns
            execs.append((path, list(args), dict(env)))
            raise SystemExit(0)
        err = io.StringIO()
        env = {"PATH": "/usr/bin:/bin", "HOME": "/home/runner", **(environ or {})}
        with mock.patch.object(self.wrapper.os, "execve", execve), contextlib.redirect_stderr(err), \
                mock.patch.object(self.wrapper, "broker_ready", lambda *a: ready), \
                mock.patch.dict(os.environ, env, clear=True):
            try:
                rc = self.wrapper.main(list(argv))
            except SystemExit as exc:
                rc = exc.code
        return rc, execs, err.getvalue()

    def test_claude_gets_the_broker_and_a_placeholder_never_a_credential(self):
        planted = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-planted", "ANTHROPIC_API_KEY": "sk-ant-api-planted",
                   "ANTHROPIC_BASE_URL": "https://elsewhere.invalid", "HTTPS_PROXY": "http://proxy.invalid:3128"}
        rc, execs, err = self.run_wrapper("-p", "hello", environ=planted)
        self.assertEqual(rc, 0, err)
        (path, args, env), = execs
        self.assertEqual((path, args), (self.wrapper.REAL, [self.wrapper.REAL, "-p", "hello"]))
        self.assertEqual(env["ANTHROPIC_BASE_URL"], f"http://127.0.0.1:{lc.BROKER_PORT}")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], self.wrapper.PLACEHOLDER)
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "HTTPS_PROXY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["PATH"], "/usr/bin:/bin")

    def test_a_broker_that_never_answers_refuses(self):
        rc, execs, err = self.run_wrapper("-p", "hello", ready=False)
        self.assertEqual((rc, execs), (2, []), err)
        self.assertIn("no credential broker answers", err)
        self.assertIn("live_container.py", err)

    def test_it_waits_for_the_broker_to_answer(self):
        port = free_port()
        with mock.patch.object(self.wrapper, "BROKER", f"http://127.0.0.1:{port}"):
            self.assertFalse(self.wrapper.broker_ready(0.5), "nothing listens, yet the broker was ready")
            server = ThreadingHTTPServer(("127.0.0.1", port), type("H", (BaseHTTPRequestHandler,), {
                "do_GET": lambda self: (self.send_response(200), self.end_headers()),
                "log_message": lambda self, *a: None}))
            threading.Timer(0.6, lambda: threading.Thread(target=server.serve_forever, daemon=True).start()).start()
            try:
                self.assertTrue(self.wrapper.broker_ready(10))
            finally:
                server.shutdown()
                server.server_close()

    def test_a_version_query_needs_no_broker(self):
        rc, execs, err = self.run_wrapper("--version", ready=False)
        self.assertEqual(rc, 0, err)
        self.assertEqual(execs[0][1], [self.wrapper.REAL, "--version"])
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", execs[0][2])

    def settings(self, content):
        path = Path(tempfile.mkdtemp(prefix="claude-settings-")) / "claude.json"
        self.addCleanup(shutil.rmtree, path.parent, True)
        path.write_text(content, encoding="utf-8")
        patch = mock.patch.object(self.wrapper, "SETTINGS", str(path))
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_per_call_limit_reaches_every_call(self):
        self.settings('{"max_budget_usd": "1.60"}')
        rc, execs, err = self.run_wrapper("-p", "hello")
        self.assertEqual(rc, 0, err)
        self.assertEqual(execs[0][1], [self.wrapper.REAL, "-p", "hello", "--max-budget-usd", "1.60"])

    def test_a_callers_own_limit_is_left_alone(self):
        self.settings('{"max_budget_usd": "1.60"}')
        for argv in (("-p", "x", "--max-budget-usd", "0.5"), ("-p", "x", "--max-budget-usd=0.5")):
            with self.subTest(argv=argv):
                rc, execs, err = self.run_wrapper(*argv)
                self.assertEqual(execs[0][1], [self.wrapper.REAL, *argv])

    def test_a_version_query_takes_no_limit(self):
        self.settings('{"max_budget_usd": "1.60"}')
        rc, execs, err = self.run_wrapper("--version")
        self.assertEqual(execs[0][1], [self.wrapper.REAL, "--version"])

    def test_settings_that_cannot_be_read_refuse(self):
        for content in ("not json", '{"max_budget_usd": "abc"}', '{"max_budget_usd": 0}', "[1]"):
            with self.subTest(content=content):
                self.settings(content)
                rc, execs, err = self.run_wrapper("-p", "hello")
                self.assertEqual((rc, execs), (2, []), err)
                self.assertIn("cannot be read", err)

    def test_without_settings_no_limit_is_added(self):
        missing = Path(tempfile.mkdtemp(prefix="claude-settings-")) / "absent.json"
        self.addCleanup(shutil.rmtree, missing.parent, True)
        with mock.patch.object(self.wrapper, "SETTINGS", str(missing)):
            rc, execs, err = self.run_wrapper("-p", "hello")
        self.assertEqual(execs[0][1], [self.wrapper.REAL, "-p", "hello"])

    def test_the_wrapper_the_broker_and_the_launcher_agree(self):
        self.assertEqual(self.wrapper.BROKER, f"http://127.0.0.1:{lb.PORT}")
        self.assertEqual(self.wrapper.SETTINGS, lc.CLAUDE_SETTINGS)
        self.assertEqual(lb.PORT, lc.BROKER_PORT)
        entries = lc.CONTAINER_PATH.split(":")
        self.assertEqual(entries[0], f"{lc.REPO_IN}/{WRAPPER.parent.relative_to(ROOT)}")
        self.assertNotIn("/home/runner/.local/bin", entries, "the raw claude is on the arm's PATH")
        self.assertTrue(os.access(WRAPPER, os.X_OK), "the wrapper is not executable")
        self.assertIn(f"{self.wrapper.REAL} --version", lc.DOCKERFILE.read_text(encoding="utf-8"),
                      "the image does not verify the binary the wrapper execs")
        self.assertNotIn("SECRET", vars(self.wrapper), "the arm's claude knows where a token would be")


if __name__ == "__main__":
    unittest.main()
