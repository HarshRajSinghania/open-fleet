#!/usr/bin/env python3
"""Provider/harness certification and the reproducible first run (#596).

The local certification subset CI runs without paid agents:

  - the record (`runtime/providers/certification.json`) validates, covers every advertised
    cell exactly once, and refuses a live-witnessed claim no bound run report backs;
  - a pin refresh voids the provider's cells (they read `stale`) until they are rechecked;
  - every `unsupported` cell is refused before a launch by the code that owns it, and every
    other cell gets past those refusals — the record cannot drift from the adapters;
  - `first_run.py` drives create -> dispatch -> delivery -> result -> independent verify ->
    retain/release through the public wrappers on the posix route, for every posix harness
    name, with an inert stand-in (setsid only; tripwires shadow every real harness);
  - the five negative probes refuse before a launch, and a probe whose guard is removed sees it.

No test here starts tmux or reaches a real agent: every subprocess runs with SHELL=/bin/sh and
a tripwire for each harness name first on PATH, and the tripwire log must stay empty.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import copy
import importlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "runtime" / "scripts"
RECORD = ROOT / "runtime" / "providers" / "certification.json"
CAPS = json.loads((ROOT / "runtime" / "providers" / "capabilities.json").read_text(encoding="utf-8"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

base = importlib.import_module("runtime.providers.base")
LocalStateStore = importlib.import_module("runtime.providers.local_state").LocalStateStore
ProviderError = base.ProviderError


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


certification = _load("certification_under_test", SCRIPTS / "certification.py")
first_run = _load("first_run_under_test", SCRIPTS / "first_run.py")

LEAKY = ("ORCA_CLI_COMMAND", "OPEN_FLEET_CLI_COMMAND", "OPEN_FLEET_RUNTIME", "ORCA_FLEET_RUNTIME",
         "OPEN_FLEET_STATE_DB", "OPEN_FLEET_STATE_DIR", "OPEN_FLEET_SANDBOX_PROFILE", "ORCA_SANDBOX_PROFILE",
         "OPEN_FLEET_PARENT_PROFILE", "ORCA_PARENT_PROFILE", "WORKER_CMD", "CLAUDE_CMD", "CODEX_CMD",
         "ORCA_TERMINAL_HANDLE", "OPEN_FLEET_TERMINAL_HANDLE", "OPEN_FLEET_DENY_HOOK_SETTINGS",
         "ORCA_DENY_HOOK_SETTINGS", "OPEN_FLEET_POSIX_BACKEND", "ORCA_POSIX_BACKEND")


def cert_main(*args):
    """certification.main() in-process: (rc, stdout, stderr) without an interpreter start."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = certification.main(list(args))
    return subprocess.CompletedProcess(args, rc, out.getvalue(), err.getvalue())


class Tripwired(unittest.TestCase):
    """A tripwire for every harness name first on PATH; no test may ever reach one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="of-cert-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.trip = self.tmp / "tripwire"
        self.trip.mkdir()
        self.trip_log = self.tmp / "tripwire.log"
        for name in first_run.all_harness_binaries():
            path = self.trip / name
            path.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.trip_log}"\nexit 97\n', encoding="utf-8")
            path.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k not in LEAKY}
        env["PATH"] = os.pathsep.join([str(self.trip), os.path.dirname(sys.executable), env.get("PATH", "")])
        env["SHELL"] = "/bin/sh"
        self.env = env
        self.addCleanup(self._no_tripwire_hit)

    def _no_tripwire_hit(self):
        hits = self.trip_log.read_text() if self.trip_log.exists() else ""
        self.assertEqual(hits, "", f"something resolved a real harness name: {hits!r}")

    def run_py(self, script, *args, env=None, cwd=None, timeout=300):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args], env={**self.env, **(env or {})},
                              cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=timeout)


# --- the record -----------------------------------------------------------------------------

class TestRecordValidates(Tripwired):
    def check(self, *args):
        return cert_main("check", *args)

    def mutated(self, fn):
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        fn(record)
        path = self.tmp / "record.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return ["--record", str(path)]

    def test_the_shipped_record_is_valid_and_fresh(self):
        p = self.run_py("certification.py", "check")  # the CLI itself, as CI and an operator run it
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("certification: OK", p.stdout)

    def test_every_advertised_cell_is_classified_exactly_once(self):
        errors, _stale, cells = certification.validate(ROOT)
        self.assertEqual(errors, [])
        want = {("provider", name, p, h) for name, entry in CAPS["providers"].items()
                for p in entry["supported_profiles"] for h in entry["supported_harnesses"]}
        want |= {("harness", h, p, h) for h in base.SUPPORTED_HARNESSES for p in ("ro", "rw")}
        got = [(c["kind"], c["name"], c["profile"], c["harness"]) for c in cells]
        self.assertEqual(len(got), len(set(got)), "a cell is classified twice")
        self.assertEqual(set(got), want)

    def test_only_bound_run_reports_carry_live_witnessed(self):
        _errors, _stale, cells = certification.validate(ROOT)
        live = {(c["name"], c["profile"], c["harness"]) for c in cells if c["tier"] == "live-witnessed"}
        self.assertEqual(live, {("orca", "ro", "claude"), ("orca", "rw", "claude")})
        unknown = [c for c in cells if c["kind"] == "provider" and c["name"] not in ("orca", "posix")]
        self.assertTrue(unknown and all(certification.version_label(c["upstream"]) == "unknown" for c in unknown),
                        "an external adapter's upstream version was never recorded: it must read unknown")

    def test_a_fixture_cell_relabelled_live_is_refused(self):
        def relabel(rec):
            rec["providers"]["posix"]["routes"][0]["tier"] = "live-witnessed"
        p = self.check(*self.mutated(relabel))
        self.assertEqual(p.returncode, 1)
        self.assertIn("live-witnessed needs `witnessed`", p.stderr)
        self.assertIn("without a binding run report", p.stderr)

    def test_a_live_claim_on_an_unbound_report_is_refused(self):
        def rebind(rec):
            group = rec["providers"]["orca"]["routes"][0]
            group["evidence"] = ["docs/runs/2026-10-12-pin-it-224.md"]  # receipts, not a GREEN proof report
        p = self.check(*self.mutated(rebind))
        self.assertEqual(p.returncode, 1)
        self.assertIn("without a binding run report", p.stderr)

    def test_a_dropped_doubled_or_unadvertised_cell_is_refused(self):
        cases = {
            "dropped": (lambda rec: rec["providers"]["ao"]["routes"][0]["harnesses"].remove("droid"),
                        "advertised route rw/droid is not classified"),
            "doubled": (lambda rec: rec["providers"]["ao"]["routes"].append(
                copy.deepcopy(rec["providers"]["ao"]["routes"][0])), "already classified"),
            "unadvertised": (lambda rec: rec["providers"]["ao"]["routes"][0]["profiles"].append("ro"),
                             "is not an advertised provider route"),
        }
        for name, (fn, needle) in cases.items():
            with self.subTest(case=name):
                p = self.check(*self.mutated(fn))
                self.assertEqual(p.returncode, 1)
                self.assertIn(needle, p.stderr)

    def test_dangling_evidence_and_missing_refusals_are_refused(self):
        cases = {
            "missing file": (lambda rec: rec["providers"]["ao"]["routes"][0]["evidence"].append("tests/no_such_test.py"),
                             "does not exist"),
            "missing symbol": (lambda rec: rec["providers"]["ao"]["routes"][0]["evidence"].append(
                "tests/test_certification.py::NoSuchClass"), "defines no class/def NoSuchClass"),
            "no refusal": (lambda rec: rec["providers"]["paperclip"]["routes"][0].pop("refusal"),
                           "unsupported needs the typed `refusal`"),
            "no limitation": (lambda rec: rec["providers"]["ao"]["routes"][0].update(limitations=[]),
                              "limitations must be a non-empty list"),
        }
        for name, (fn, needle) in cases.items():
            with self.subTest(case=name):
                p = self.check(*self.mutated(fn))
                self.assertEqual(p.returncode, 1)
                self.assertIn(needle, p.stderr)


class TestPinRefreshInvalidatesCells(Tripwired):
    """Refreshing a provider version voids its cells until a maintainer rechecks them."""

    def pins(self, mutate=None):
        pins = json.loads((ROOT / "runtime" / "pins.json").read_text(encoding="utf-8"))
        if mutate:
            mutate(pins["orca"])
        path = self.tmp / "pins.json"
        path.write_text(json.dumps(pins), encoding="utf-8")
        return path

    def matrix(self, *args):
        p = cert_main("matrix", "--json", *args)
        return p, {(r["name"], r["profile"], r["harness"]): r["effective"] for r in json.loads(p.stdout)
                   if r["kind"] == "provider"}

    def test_an_unchanged_pin_keeps_every_cell_fresh(self):
        p, cells = self.matrix("--pins", str(self.pins()))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(cells[("orca", "ro", "claude")], "live-witnessed")

    def test_a_new_pin_turns_every_orca_cell_stale(self):
        for name, mutate in {
            "commit": lambda e: e.update(commit="f" * 40),
            "version": lambda e: e.update(version="v1.4.240"),
            "live receipts": lambda e: e["live_receipts"].update(version="v1.4.240"),
        }.items():
            with self.subTest(moved=name):
                pins = self.pins(mutate)
                check = cert_main("check", "--pins", str(pins))
                self.assertEqual(check.returncode, 1)
                self.assertIn("STALE provider orca", check.stderr)
                _p, cells = self.matrix("--pins", str(pins))
                orca = {k: v for k, v in cells.items() if k[0] == "orca"}
                self.assertEqual(set(orca.values()), {"stale"}, "a cell kept its tier after the pin moved")
                self.assertEqual(cells[("posix", "ro", "claude")], "fixture-tested", "staleness is per provider")

    def test_rechecking_and_re_recording_makes_the_cells_fresh_again(self):
        pins = self.pins(lambda e: e.update(commit="e" * 40, version="v1.4.240"))
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        record["providers"]["orca"]["certified_against"].update(commit="e" * 40, version="v1.4.240")
        rec_path = self.tmp / "record.json"
        rec_path.write_text(json.dumps(record), encoding="utf-8")
        p = cert_main("check", "--pins", str(pins), "--record", str(rec_path))
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_the_cli_exits_nonzero_on_a_stale_pin(self):
        p = self.run_py("certification.py", "check", "--pins", str(self.pins(lambda e: e.update(version="v9.9.9"))))
        self.assertEqual(p.returncode, 1)
        self.assertIn("STALE provider orca", p.stderr)


# --- the record against the code that owns each cell ------------------------------------------

class Reached(Exception):
    """The adapter got past every pre-launch refusal to its first upstream call."""


def _reach(*args, **_kw):
    raise Reached(args)


class TestAdapterRefusalsMatchTheRecord(Tripwired):
    """An `unsupported` cell is refused with its recorded code before any upstream call; any
    other cell gets past the refusals to the upstream boundary."""

    def adapter(self, name):
        def m(mod):
            return importlib.import_module(f"runtime.providers.{mod}")

        state = LocalStateStore(db_path=self.tmp / f"{name}.db")
        wt = self.tmp / f"wt-{name}"
        wt.mkdir(exist_ok=True)
        def hooks(*_a, **_k):
            return {}

        table = {
            "overstory": (lambda: m("overstory").OverstoryProvider(state=state, runner=_reach), {}),
            "t3code": (lambda: m("t3code").T3CodeProvider(state=state, runner=_reach, project_id="p", git_runner=_reach,
                                                         install_hooks=hooks), {}),
            "ao": (lambda: m("ao").ComposioAOProvider(state=state, runner=_reach, project="p1"), {}),
            "superset": (lambda: m("superset").SupersetProvider(
                state=state, runner=_reach, install_hooks=hooks, env={"OPEN_FLEET_SUPERSET_PROJECT": "p"}), {}),
            "gastown": (lambda: m("gastown").GastownProvider(state=state, runner=_reach, rig="r", install_hooks=hooks), {}),
            "worktrunk": (lambda: m("worktrunk").WorktrunkProvider(state=state, runner=_reach, install_hooks=hooks), {}),
            "jcode-swarm": (lambda: m("jcode_swarm").JCodeSwarmProvider(
                state=state, runner=_reach, coordinator_session="coord"), {"worktree": str(wt)}),
            "emdash": (lambda: m("emdash").EmdashProvider(state=state, runner=_reach, git_runner=_reach,
                                                         env={"OPEN_FLEET_EMDASH_REPOSITORY_ID": "r"}), {"base": "main"}),
            "vibe-kanban": (lambda: m("vibe_kanban").VibeKanbanProvider(
                state=state, runner=_reach,
                env={"OPEN_FLEET_VIBE_KANBAN_REPO_ID": "r1", "OPEN_FLEET_VIBE_KANBAN_TARGET_BRANCH": "main"}), {}),
            "paperclip": (lambda: m("paperclip").PaperclipProvider(state=state, runner=_reach, company_id="co"),
                          {"worktree": str(wt)}),
            "multiclaude": (lambda: self._multiclaude(state), {"name": "mc"}),
            "openhands": (lambda: m("openhands").OpenHandsProvider(
                state=state, runner=_reach, env={"OPEN_FLEET_OPENHANDS_MODEL": "m"}), {}),
        }
        make, extra = table[name]
        return make(), extra

    def _multiclaude(self, state):
        home = self.tmp / "mch"
        (home / "repos" / "proj").mkdir(parents=True, exist_ok=True)
        mod = importlib.import_module("runtime.providers.multiclaude")
        return mod.MulticlaudeProvider(state=state, runner=_reach, home=home, repo="proj")

    def test_external_adapters_refuse_exactly_the_unsupported_cells(self):
        _errors, _stale, cells = certification.validate(ROOT)
        external = [c for c in cells if c["kind"] == "provider" and c["name"] not in ("orca", "posix")]
        self.assertGreater(len(external), 100)
        for cell in external:
            with self.subTest(provider=cell["name"], profile=cell["profile"], harness=cell["harness"]):
                prov, extra = self.adapter(cell["name"])
                if cell["name"] == "gastown" and cell["profile"] == "ro":
                    # gastown registers a ro gt alias after `bd create` and before `gt sling` (the
                    # launch): the alias builder is where a ro cell is refused.
                    if cell["tier"] == "unsupported":
                        with self.assertRaises(ProviderError) as ctx:
                            prov._ro_alias_command(cell["harness"])
                        self.assertEqual(ctx.exception.code, cell["refusal"])
                    else:
                        self.assertTrue(prov._ro_alias_command(cell["harness"]))
                    continue
                kwargs = dict(task_id="t", agent=cell["harness"], profile=cell["profile"], prompt="x", **extra)
                if cell["tier"] == "unsupported":
                    with self.assertRaises(ProviderError) as ctx:
                        prov.worker_start(**kwargs)
                    self.assertEqual(ctx.exception.code, cell["refusal"])
                else:
                    with self.assertRaises(Reached):
                        prov.worker_start(**kwargs)

    def test_posix_refuses_hermes_danger_and_frees_the_task(self):
        repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                        "commit", "-q", "--allow-empty", "-m", "i"], check=True)
        env = {**self.env, "OPEN_FLEET_STATE_DB": str(self.tmp / "s" / "r.db"), "OPEN_FLEET_POSIX_BACKEND": "dry-run",
               "OPEN_FLEET_CLI_CWD": str(repo)}
        providers = importlib.import_module("runtime.providers")
        _errors, _stale, cells = certification.validate(ROOT)
        danger = [c for c in cells if c["name"] == "posix" and c["profile"] == "danger"]
        self.assertEqual(len(danger), len(CAPS["providers"]["posix"]["supported_harnesses"]))
        for cell in danger:
            with self.subTest(harness=cell["harness"]):
                prov = providers.get_provider("posix", env=env)
                task = prov.dispatch(["orchestration", "task-create", "--spec", f"danger {cell['harness']}"])["task"]
                kwargs = dict(task_id=task["id"], worktree="new-child", agent=cell["harness"], profile="danger",
                              on_env="img", name=f"d-{cell['harness']}")
                if cell["tier"] == "unsupported":
                    with self.assertRaises(ProviderError) as ctx:
                        prov.worker_start(**kwargs)
                    self.assertEqual(ctx.exception.code, cell["refusal"])
                    self.assertEqual(prov.worker_list(task=task["id"])["workers"], [], "nothing was dispatched")
                    status = {t["id"]: t["status"] for t in prov.task_list()["tasks"]}
                    self.assertEqual(status[task["id"]], "ready", "a refused start must hand the task back")
                else:
                    res = prov.worker_start(**kwargs)  # dry-run backend: composed, never executed
                    self.assertIn("docker run", res["launch"]["effective"]["command"])


class TestOrcaRouteCellsMatchTheWrapper(Tripwired):
    """On Orca the fleet's wrapper is spawn_worker.sh: each orca cell is accepted or refused there
    exactly as the record says (SW_PRINT_LAUNCH stops before any orchestration side effect)."""

    def stub(self):
        doctor = {"ok": True, "result": {
            "recipeId": "lane-7", "backend": "docker", "ok": True, "ephemeral": True, "credential_mounts": [],
            "prelaunch_placement_bound": True, "checks": [{"id": "isolation-flags", "status": "pass"}],
            "isolation": {"capDrop": ["ALL"], "noNewPrivileges": True, "pidsLimit": 512, "privileged": False,
                          "network": "bridge"}, "mounts": [], "failures": [], "warnings": []}}
        (self.tmp / "doctor.json").write_text(json.dumps(doctor), encoding="utf-8")
        stub = self.tmp / "orca"
        stub.write_text(f"""#!/bin/sh
echo "$*" >> "{self.tmp}/orca-calls.log"
case "$*" in *"recipe doctor"*) cat "{self.tmp}/doctor.json" ;; *) echo '{{"result": {{}}}}' ;; esac
""", encoding="utf-8")
        stub.chmod(0o755)
        return stub

    def spawn(self, stub, cell):
        env = {"ORCA_CLI_COMMAND": str(stub), "SW_PRINT_LAUNCH": "1", "PROFILE": cell["profile"], "SP": str(self.tmp),
               "ORCA_COORD_ALLOW_AUTONOMOUS_WRITE": "1"}
        if cell["profile"] == "danger":
            env.update(ORCA_COORD_ALLOW_DANGER="1", ORCA_SANDBOX_RECIPE="lane-7")
        return subprocess.run(["bash", str(SCRIPTS / "spawn_worker.sh"), "task_x", "new-child", "t", cell["harness"]],
                              env={**self.env, **env}, cwd=str(self.tmp), capture_output=True, text=True, timeout=120)

    def test_every_orca_cell_is_accepted_or_refused_as_recorded(self):
        stub = self.stub()
        _errors, _stale, cells = certification.validate(ROOT)
        orca = [c for c in cells if c["name"] == "orca"]
        self.assertEqual(len(orca), 3 * len(CAPS["providers"]["orca"]["supported_harnesses"]))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda c: (c, self.spawn(stub, c)), orca))
        for cell, p in results:
            with self.subTest(profile=cell["profile"], harness=cell["harness"]):
                if cell["tier"] == "unsupported":
                    self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                    self.assertIn(cell["refusal"], p.stderr)
                    self.assertNotIn("LAUNCH=", p.stdout)
                else:
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    self.assertIn("LAUNCH=", p.stdout)
        calls = (self.tmp / "orca-calls.log").read_text() if (self.tmp / "orca-calls.log").exists() else ""
        for verb in ("worker-start", "terminal create", "task-create", "--inject"):
            self.assertNotIn(verb, calls, "a refusal or a printed launch must precede every side effect")


class TestHarnessCellsMatchTheLaunchTable(unittest.TestCase):
    def test_each_harness_cell_builds_or_refuses_as_recorded(self):
        _errors, _stale, cells = certification.validate(ROOT)
        harness = [c for c in cells if c["kind"] == "harness"]
        with tempfile.TemporaryDirectory() as wt:
            for cell in harness:
                with self.subTest(harness=cell["harness"], profile=cell["profile"]):
                    if cell["tier"] == "unsupported":
                        with self.assertRaises(ProviderError) as ctx:
                            base.build_harness_command(cell["harness"], cell["profile"], wt, prompt="TASK-SENTINEL")
                        self.assertEqual(ctx.exception.code, cell["refusal"])
                    else:
                        launch = base.build_harness_command(cell["harness"], cell["profile"], wt, prompt="TASK-SENTINEL")
                        self.assertIn("TASK-SENTINEL", launch["argv"], "the task must ride the launch argv")


# --- the first run ----------------------------------------------------------------------------

class TestFirstRunFixture(Tripwired):
    STEPS = ["prereqs", "target", "preflight", "create", "dispatch", "guard", "delivery", "result",
             "evidence", "verify", "release", "isolation"]

    def first_run(self, *args, workdir=None):
        wd = workdir or self.tmp / "fr"
        p = self.run_py("first_run.py", *args, "--workdir", str(wd), "--json", timeout=600)
        try:
            receipt = json.loads(p.stdout)
        except ValueError:
            self.fail(f"no receipt: rc={p.returncode}\n{p.stdout}\n{p.stderr}")
        return p, receipt

    def assert_go(self, p, receipt):
        self.assertEqual(p.returncode, 0, json.dumps(receipt.get("failure"), indent=1))
        self.assertEqual(receipt["verdict"], "GO")
        self.assertEqual([s["step"] for s in receipt["steps"]], self.STEPS)
        self.assertTrue(all(s["ok"] for s in receipt["steps"]))
        self.assertEqual(receipt["tier"], "fixture-tested", "an inert run is never labelled live")
        facts = receipt["facts"]
        self.assertRegex(facts["evidence"]["head_sha"], r"^[0-9a-f]{40}$")
        self.assertNotEqual(facts["evidence"]["head_sha"], facts["evidence"]["base_sha"])
        self.assertEqual(facts["verify"]["rc"], 0)
        self.assertIn("verify: OK", "\n".join(facts["verify"]["out"]))
        self.assertTrue(all(isinstance(s["elapsed_s"], float) for s in receipt["steps"]))

    def test_ro_review_unit_is_go_through_the_public_wrappers(self):
        p, receipt = self.first_run("--profile", "ro")
        self.assert_go(p, receipt)
        wrappers = {Path(c["argv"][1]).name for c in receipt["commands"] if len(c["argv"]) > 1}
        for script in ("task_ops.py", "spawn_worker.sh", "worker_ops.py", "check_reply.py", "verify.py",
                       "preflight.py"):
            self.assertIn(script, wrappers, f"{script} never ran: the lifecycle bypassed the public wrapper")
        self.assertIn("--permission-mode plan", receipt["facts"]["launch_effective"]["command"])
        self.assertTrue(receipt.get("sandbox_pruned"), "a GO prunes the sandbox down to its receipt")

    def test_rw_unit_commits_its_report_and_the_commit_survives_release(self):
        p, receipt = self.first_run("--profile", "rw")
        self.assert_go(p, receipt)
        facts = receipt["facts"]
        self.assertEqual(facts["worker_claim"]["head"], facts["evidence"]["head_sha"])

    def test_every_posix_harness_runs_the_whole_route(self):
        cells = [(h, p) for h in CAPS["providers"]["posix"]["supported_harnesses"] for p in ("ro", "rw")
                 if h != "claude"]

        def one(cell):
            h, prof = cell
            return cell, self.first_run("--agent", h, "--profile", prof, workdir=self.tmp / f"fr-{h}-{prof}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(one, cells))
        for (h, prof), (p, receipt) in results:
            with self.subTest(harness=h, profile=prof):
                self.assert_go(p, receipt)
                self.assertEqual(receipt["route"]["harness"], h)

    def in_process(self, *args):
        """first_run.main() in this process, so a test can mutate what it binds."""
        buf = io.StringIO()
        clean = {k: v for k, v in self.env.items()}
        with mock.patch.dict(os.environ, clean, clear=True), contextlib.redirect_stdout(buf):
            rc = first_run.main([*args, "--workdir", str(self.tmp / "inproc"), "--json"])
        return rc, json.loads(buf.getvalue())

    def test_verify_goes_red_when_the_manifest_binds_the_wrong_sha(self):
        real = first_run.write_manifest

        def bind_the_base(path, manifest):
            real(path, {**manifest, "head_sha": manifest["base_sha"]})

        with mock.patch.object(first_run, "write_manifest", bind_the_base):
            rc, receipt = self.in_process("--profile", "ro")
        self.assertEqual(rc, 1)
        self.assertEqual(receipt["verdict"], "NO-GO")
        self.assertEqual(receipt["failure"]["step"], "verify")
        self.assertIn("base_sha == head_sha", receipt["failure"]["detail"])

    def test_a_worker_that_ignores_its_spec_is_no_go(self):
        deaf = first_run.INERT_WORKER.replace(
            'report = f"FIRST-RUN-REPORT {m.group(1)} {m.group(2)}\\n"', 'report = "I reviewed something\\n"')
        self.assertNotEqual(deaf, first_run.INERT_WORKER, "the mutant must change the stand-in")
        with mock.patch.object(first_run, "INERT_WORKER", deaf):
            rc, receipt = self.in_process("--profile", "ro")
        self.assertEqual((rc, receipt["failure"]["step"]), (1, "result"))
        self.assertIn("report does not open with", receipt["failure"]["detail"])

    def test_a_worker_claim_that_git_contradicts_is_no_go(self):
        liar = first_run.INERT_WORKER.replace('{"head": head, "report": rel}', '{"head": "f" * 40, "report": rel}')
        self.assertNotEqual(liar, first_run.INERT_WORKER, "the mutant must change the stand-in")
        with mock.patch.object(first_run, "INERT_WORKER", liar):
            rc, receipt = self.in_process("--profile", "rw")
        self.assertEqual((rc, receipt["failure"]["step"]), (1, "evidence"))
        self.assertIn("the claim is not evidence", receipt["failure"]["recovery"])

    def test_live_mode_without_the_harness_stops_at_prerequisites(self):
        bare = os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"])
        agent = next((h for h in CAPS["providers"]["posix"]["supported_harnesses"]
                      if not shutil.which(first_run.HARNESS_BINARIES.get(h, h), path=bare)), None)
        self.assertIsNotNone(agent, "every posix harness is installed system-wide; nothing safe to probe")
        p = self.run_py("first_run.py", "--worker", "live", "--agent", agent, "--workdir", str(self.tmp / "live"),
                        "--json", env={"PATH": bare})
        receipt = json.loads(p.stdout)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(receipt["tier"], "live-unreviewed")
        self.assertEqual(receipt["failure"]["step"], "prereqs")
        self.assertEqual([s["step"] for s in receipt["steps"]], ["prereqs"], "nothing ran after the refusal")


class TestNegativeProbes(Tripwired):
    REQUIRED = {"unsupported-profile", "privilege-escalation", "unarmed-deny-hook",
                "malformed-upstream-response", "missing-capability"}

    def test_every_probe_refuses_before_a_launch(self):
        p = self.run_py("first_run.py", "probes", "--workdir", str(self.tmp / "probes"), "--json")
        receipt = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, json.dumps(receipt["probes"], indent=1))
        self.assertEqual({r["probe"] for r in receipt["probes"]}, self.REQUIRED)
        for r in receipt["probes"]:
            with self.subTest(probe=r["probe"]):
                self.assertTrue(r["refused"], r["problems"])
                self.assertTrue(r["evidence"], "the refusal text must be on record")

    def test_a_probe_whose_guard_trigger_is_removed_sees_the_launch(self):
        # The detectors are not vacuous: privilege-escalation WITHOUT the ro parent launches,
        # and the same checks that pass the real probes report it.
        real = first_run.probe_table

        def with_control(sb, unarmed, garbage):
            table = real(sb, unarmed, garbage)
            name, why, argv, env, rc, text = next(t for t in table if t[0] == "privilege-escalation")
            control = {k: v for k, v in env.items() if k != "OPEN_FLEET_PARENT_PROFILE"}
            return table + [("control-no-parent", why, argv, control, rc, text)]

        buf = io.StringIO()
        with mock.patch.object(first_run, "probe_table", with_control), \
                mock.patch.dict(os.environ, dict(self.env), clear=True), contextlib.redirect_stdout(buf):
            rc = first_run.main(["probes", "--workdir", str(self.tmp / "ctl"), "--json"])
        receipt = json.loads(buf.getvalue())
        self.assertEqual(rc, 1)
        control = next(r for r in receipt["probes"] if r["probe"] == "control-no-parent")
        self.assertFalse(control["refused"])
        self.assertTrue(any("a worker launched" in x for x in control["problems"]), control["problems"])
        self.assertTrue(any("a dispatch was recorded" in x for x in control["problems"]), control["problems"])
        self.assertTrue(all(r["refused"] for r in receipt["probes"] if r["probe"] != "control-no-parent"))


class TestDocsCarryTheGeneratedMatrix(unittest.TestCase):
    BEGIN = "<!-- BEGIN GENERATED: certification-matrix — runtime/scripts/certification.py markdown -->"
    END = "<!-- END GENERATED: certification-matrix -->"

    def test_the_certification_page_matches_the_record(self):
        text = (ROOT / "docs" / "certification.md").read_text(encoding="utf-8")
        self.assertIn(self.BEGIN, text)
        block = text.split(self.BEGIN, 1)[1].split(self.END, 1)[0].strip("\n")
        _errors, _stale, cells = certification.validate(ROOT)
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        self.assertEqual(block, certification.render_markdown(cells, record).strip("\n"),
                         "regenerate: python3 runtime/scripts/certification.py markdown")

    def test_mocked_and_live_results_are_labelled_apart(self):
        text = (ROOT / "docs" / "certification.md").read_text(encoding="utf-8")
        for heading in ("## Live-witnessed results", "## Fixture (mocked) results"):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
