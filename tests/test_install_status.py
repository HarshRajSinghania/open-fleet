#!/usr/bin/env python3
"""Contract tests for scripts/install.sh `orca status` readiness (S23).

Assessment: `orca status --json` readiness IS machine-checkable
(app.running + runtime.reachable + runtime.state == ready; graph is folded
into runtime.state upstream). But install.sh's orca prerequisites are SOFT
by doctrine — warnings only, since the catalog installs without a running
app. So readiness lands as a soft WARN like the version floor, and the HARD
gate stays PARKED (needs-human policy: it would refuse headless/CI installs
where the app simply is not launched yet).

These tests pin the soft behavior via --check: ready → no readiness warn;
not-ready/unreadable → WARN, still exit 0.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "scripts" / "install.sh"

READY = {"app": {"running": True, "pid": 123},
         "runtime": {"state": "ready", "reachable": True,
                     "runtimeId": "rt_1"},
         "graph": {"state": "ready"}}
NOT_RUNNING = {"app": {"running": False, "pid": None},
               "runtime": {"state": "not_running", "reachable": False,
                           "runtimeId": None},
               "graph": {"state": "not_running"}}
GRAPH_DOWN = {"app": {"running": True, "pid": 123},
              "runtime": {"state": "graph_not_ready", "reachable": True,
                          "runtimeId": "rt_1"},
              "graph": {"state": "starting"}}


def run_check(status_payload="__ready__", version="1.4.209", no_orca=False):
    """Run install.sh --check with a stub orca; return (rc, stdout, stderr).

    status_payload: dict for `status --json`, "garbage" for unparseable, or
    "__ready__" for the READY receipt.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bindir = tmp / "bin"
        bindir.mkdir()
        skills = tmp / "skills"
        skills.mkdir()
        for d in (ROOT / "skills").iterdir():
            if d.is_dir() and (d / "SKILL.md").is_file() \
                    and not d.name.startswith((".", "_")):
                (skills / d.name).symlink_to(d)
        if not no_orca:
            status_doc = READY if status_payload == "__ready__" \
                else status_payload
            status_text = status_doc if isinstance(status_doc, str) \
                else json.dumps({"result": status_doc})
            (bindir / "status.txt").write_text(status_text)
            stub = bindir / "orca"
            stub.write_text(
                "#!/bin/sh\n"
                f"if [ \"$1\" = \"status\" ]; then cat \"{bindir / 'status.txt'}\";\n"
                f"else echo \"{version}\"; fi\n")
            stub.chmod(0o755)
        env = dict(os.environ)
        base = os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)
        if no_orca:
            # Drop every dir shipping an orca binary so the stub-less run
            # really sees no orca CLI.
            base = [d for d in base if not (
                (Path(d) / "orca").exists()
                or (Path(d) / "orca-ide").exists())]
        env["PATH"] = os.pathsep.join([str(bindir), *base])
        env["HOME"] = str(tmp)
        p = subprocess.run(["sh", str(INSTALL), "--check",
                            f"--skills-dir={skills}"],
                           env=env, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout, p.stderr


class TestReadinessWarn(unittest.TestCase):
    def test_ready_status_warns_nothing_about_readiness(self):
        rc, out, err = run_check()
        self.assertEqual(rc, 0, err)
        blob = out + err
        self.assertNotIn("not ready", blob)
        self.assertNotIn("readiness", blob)

    def test_app_not_running_warns_but_install_verifies(self):
        rc, out, err = run_check(status_payload=NOT_RUNNING)
        self.assertEqual(rc, 0, err)
        self.assertIn("not ready", out + err)

    def test_graph_not_ready_warns(self):
        rc, out, err = run_check(status_payload=GRAPH_DOWN)
        self.assertEqual(rc, 0, err)
        self.assertIn("not ready", out + err)

    def test_unreadable_status_warns(self):
        rc, out, err = run_check(status_payload="garbage{{{")
        self.assertEqual(rc, 0, err)
        self.assertIn("readiness", out + err)

    def test_no_orca_keeps_the_old_warn_only(self):
        rc, out, err = run_check(no_orca=True)
        self.assertEqual(rc, 0, err)
        self.assertIn("no orca CLI", out + err)


def run_install(script, skills, home, *extra):
    """A real install (not --check) with HOME in a tempdir; orca/gh absence only warns."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    p = subprocess.run(["sh", str(script), f"--skills-dir={skills}", *extra],
                       env=env, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout, p.stderr


class TestInstallPaths(unittest.TestCase):
    """Real installs through the path shapes that used to break them."""

    def test_install_through_a_symlinked_checkout_path(self):
        # macOS /tmp -> /private/tmp: the script was reached through a logical
        # path while the verify step compared against realpath — every link
        # "resolved elsewhere" and a clean install died at verification.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            alias = tmp / "alias"
            alias.symlink_to(ROOT, target_is_directory=True)
            skills = tmp / "skills"
            rc, out, err = run_install(alias / "scripts" / "install.sh", skills, tmp)
            self.assertEqual(rc, 0, out + err)
            self.assertIn("verified", out)
            # links name the PHYSICAL clone, so they survive the alias going away
            link = next(skills.iterdir())
            self.assertEqual(Path(os.readlink(link)).parent, ROOT / "skills")

    def _foreign_clone(self, tmp, mission="ship-it"):
        other = tmp / "other-clone" / "skills" / mission
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("---\nname: x\n---\n")
        skills = tmp / "skills"
        skills.mkdir()
        (skills / mission).symlink_to(other)
        return skills, other

    def test_link_into_another_clone_is_refused_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            skills, other = self._foreign_clone(tmp)
            rc, out, err = run_install(INSTALL, skills, tmp)
            self.assertEqual(rc, 1, out + err)
            self.assertIn("another clone", err)
            self.assertIn("--force", err)
            # refused BEFORE linking anything: no partial install, link untouched
            self.assertEqual([p.name for p in skills.iterdir()], ["ship-it"])
            self.assertEqual(Path(os.readlink(skills / "ship-it")), other)

    def test_force_repoints_a_foreign_link_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            skills, _other = self._foreign_clone(tmp)
            rc, out, err = run_install(INSTALL, skills, tmp, "--force")
            self.assertEqual(rc, 0, out + err)
            self.assertIn("points into another clone", out)
            self.assertEqual(os.path.realpath(skills / "ship-it"),
                             str(ROOT / "skills" / "ship-it"))

    def test_dangling_link_is_repointed_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            skills = tmp / "skills"
            skills.mkdir()
            (skills / "ship-it").symlink_to(tmp / "deleted-clone" / "skills" / "ship-it")
            rc, out, err = run_install(INSTALL, skills, tmp)
            self.assertEqual(rc, 0, out + err)
            self.assertIn("dangling", out)
            self.assertEqual(os.path.realpath(skills / "ship-it"),
                             str(ROOT / "skills" / "ship-it"))


def _shallow_clone(dest):
    """A REAL `git clone --depth 1` of this checkout, with the working-tree copies of the
    files under test laid over it (the clone carries only what HEAD committed)."""
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{ROOT}", str(dest)],
                   check=True, capture_output=True, timeout=300)
    shutil.copytree(ROOT / "scripts", dest / "scripts", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "runtime/scripts/run_report.py", dest / "runtime/scripts/run_report.py")
    probe = subprocess.run(["git", "-C", str(dest), "rev-parse", "--is-shallow-repository"],
                           capture_output=True, text=True, check=True)
    if probe.stdout.strip() != "true":
        raise AssertionError("fixture clone is not shallow")


class TestShallowClone(unittest.TestCase):
    """`git clone --depth 1` cannot resolve run-report pins. Both entry points must say so
    and name the fix, rather than blame the catalog — and must still fail closed."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.clone = cls.base / "shallow"
        _shallow_clone(cls.clone)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_install_refuses_with_the_unshallow_command(self):
        skills = self.base / "skills"
        rc, out, err = run_install(self.clone / "scripts" / "install.sh", skills, self.base)
        self.assertEqual(rc, 1, out + err)
        self.assertIn("shallow clone", err)
        self.assertIn("fetch --unshallow", err)
        self.assertNotIn("broken catalog", err)
        self.assertFalse(skills.exists(), "a refused install must link nothing")

    def test_validate_fails_closed_but_names_the_remedy(self):
        p = subprocess.run([sys.executable, str(self.clone / "scripts" / "validate.py")],
                           cwd=self.clone, capture_output=True, text=True, timeout=300)
        # A pin the clone cannot resolve is never skipped...
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        # ...but each failing pin and the summary say WHY, with the command.
        self.assertIn("SHALLOW clone", p.stdout)
        self.assertIn("NOTE:", p.stdout)
        self.assertIn("git fetch --unshallow", p.stdout)
        self.assertNotIn("is not a commit in this repository", p.stdout)


class TestInstallerOperands(unittest.TestCase):
    """W2-05 / W5-22 (2026-10-27 audit): `--skills-dir=-x` reached `mkdir -p` and `ln -sfn` as an
    OPTION (no `--`), half the install ran before GNU ln died on `invalid option`, an unset HOME
    aborted on `set -u` with no hint, and mission directory names were never validated."""

    def run_sh(self, args, env, cwd, script=INSTALL):
        return subprocess.run(["sh", str(script), *args], env=env, cwd=str(cwd),
                              capture_output=True, text=True, timeout=300)

    def test_an_option_shaped_skills_dir_is_refused_before_anything_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ([], ["--check"]):
                for value in ("-x", "-p", "--help"):
                    with self.subTest(mode=mode, value=value):
                        p = self.run_sh([*mode, f"--skills-dir={value}"],
                                        dict(os.environ, HOME=tmp), tmp)
                        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                        self.assertIn("starts with '-'", p.stderr)
                        self.assertNotIn("validating the catalog", p.stdout)
                        self.assertNotIn("invalid option", p.stderr)
                        self.assertEqual(os.listdir(tmp), [], "a refused install created something")

    def test_an_empty_skills_dir_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.run_sh(["--check", "--skills-dir="], dict(os.environ, HOME=tmp), tmp)
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertIn("--skills-dir needs a directory", p.stderr)

    def test_an_unset_home_fails_with_a_message_not_a_set_u_abort(self):
        env = {k: v for k, v in os.environ.items() if k != "HOME"}
        with tempfile.TemporaryDirectory() as tmp:
            p = self.run_sh(["--check"], env, tmp)
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertIn("HOME is not set", p.stderr)
            self.assertIn("--skills-dir", p.stderr)
            self.assertNotIn("parameter not set", p.stderr)
            # ...and an explicit --skills-dir needs no HOME at all.
            skills = Path(tmp) / "skills"
            skills.mkdir()
            for d in (ROOT / "skills").iterdir():
                if (d / "SKILL.md").is_file() and not d.name.startswith((".", "_")):
                    (skills / d.name).symlink_to(d)
            p = self.run_sh(["--check", f"--skills-dir={skills}"], env, tmp)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("verified", p.stdout)

    def test_a_mission_directory_name_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            for sub in ("scripts", "playbooks", "runtime", "hooks", "skills/ok-mission", "skills/-x"):
                (root / sub).mkdir(parents=True)
            shutil.copy2(INSTALL, root / "scripts" / "install.sh")
            shutil.copy2(ROOT / "runtime" / "pins.json", root / "runtime" / "pins.json")
            for m in ("ok-mission", "-x"):
                (root / "skills" / m / "SKILL.md").write_text("---\nname: x\n---\n")
            skills = Path(tmp) / "skills"
            skills.mkdir()
            p = self.run_sh(["--check", f"--skills-dir={skills}"], dict(os.environ, HOME=tmp), tmp,
                            script=root / "scripts" / "install.sh")
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertIn("skills/-x is not a mission directory name", p.stderr)

    def test_a_name_ending_in_a_newline_is_refused_before_any_mutation(self):
        # W5-22 re-attack: `$(basename …)` strips a trailing newline, so `ok\n` passed the name
        # check as `ok`, and the check ran after `mkdir -p`: a partial install. The directory
        # entry itself is judged now, before the skills dir is created.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            for sub in ("scripts", "playbooks", "runtime", "hooks", "skills/ok-mission", "skills/ok\n"):
                (root / sub).mkdir(parents=True)
            shutil.copy2(INSTALL, root / "scripts" / "install.sh")
            shutil.copy2(ROOT / "runtime" / "pins.json", root / "runtime" / "pins.json")
            (root / "scripts" / "validate.py").write_text("raise SystemExit(0)\n")
            for m in ("ok-mission", "ok\n"):
                (root / "skills" / m / "SKILL.md").write_text("---\nname: x\n---\n")
            skills = Path(tmp) / "skills-out"
            p = self.run_sh([f"--skills-dir={skills}"], dict(os.environ, HOME=tmp), tmp,
                            script=root / "scripts" / "install.sh")
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertIn("is not a mission directory name", p.stderr)
            self.assertFalse(skills.exists(), "the skills dir was created before the refusal")


if __name__ == "__main__":
    unittest.main()
