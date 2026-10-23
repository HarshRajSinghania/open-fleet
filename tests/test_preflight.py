#!/usr/bin/env python3
"""
Contract tests for runtime/scripts/preflight.py.

The docstring promises: exit 0 = OK, exit 1 = usage/dependency, exit 2 = invariant
violation. argparse's default SystemExit(2) on unknown flags and bad choices collapsed
usage errors into the invariant bucket — a typo'd flag was indistinguishable from a
tripped M-5 guardrail. These tests pin the boundary from both sides. They also pin
that gh subprocess calls carry a timeout (a hung gh must fail Phase 0 fast, not block
it forever) and that --offline starts without gh while keeping every git-based BASE
invariant.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "runtime" / "scripts" / "preflight.py"

_spec = importlib.util.spec_from_file_location("preflight", SCRIPT)
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


def run_preflight(*argv, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True, text=True, cwd=cwd, env=env, timeout=60,
    )


def make_repo(path, default="main", base=None):
    subprocess.run(["git", "init", "-q", "-b", default, str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "commit", "--allow-empty", "-q", "-m", "root"],
        check=True,
    )
    if base:
        subprocess.run(["git", "-C", str(path), "branch", base], check=True)


def wrapper(dirpath, name, real):
    """A PATH shim that execs the real binary — safer than a symlink, which can
    break a relocatable binary's own prefix resolution."""
    p = Path(dirpath) / name
    p.write_text(f'#!/bin/sh\nexec "{real}" "$@"\n', encoding="utf-8")
    p.chmod(0o755)
    return p


class TestExitCodeContract(unittest.TestCase):
    """Usage errors are 1; invariant violations are 2. Never the same bucket."""

    def test_unknown_flag_is_usage_exit_1(self):
        r = run_preflight("--bogus-flag")
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_bad_mode_value_is_usage_exit_1(self):
        r = run_preflight("--mode", "wrong")
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_missing_base_is_usage_exit_1(self):
        # Pin: this side of the boundary was already correct.
        r = run_preflight()
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_underivable_default_branch_is_dependency_exit_1(self):
        # gh reachable but defaultBranchRef empty: a dependency/config failure
        # ("pass --default"), not a tripped invariant — must not share exit 2.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            make_repo(repo, base="integ")
            fakebin = Path(tmp) / "bin"
            fakebin.mkdir()
            gh = fakebin / "gh"
            gh.write_text(
                '#!/bin/sh\ncase "$*" in\n'
                '  *nameWithOwner*) echo "owner/repo";;\n'
                '  *defaultBranchRef*) exit 0;;\n'
                'esac\n',
                encoding="utf-8",
            )
            gh.chmod(0o755)
            env = dict(os.environ, PATH=f"{fakebin}{os.pathsep}{os.environ['PATH']}")
            r = run_preflight("--base", "integ", cwd=str(repo), env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("could not derive default branch", r.stderr)

    def test_base_equals_default_is_invariant_exit_2(self):
        # The tripped M-5 guardrail must stay distinguishable from a typo'd flag.
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            r = run_preflight("--offline", "--base", "main", "--default", "main", cwd=tmp)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("DEFAULT_BRANCH", r.stderr)


class TestOfflineStart(unittest.TestCase):

    def test_offline_requires_default(self):
        r = run_preflight("--offline", "--base", "x")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("--default", r.stderr)

    def test_offline_passes_without_gh_on_path(self):
        # A host that STARTS offline: no gh anywhere, git-only invariants still run.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            make_repo(repo, base="integ")
            fakebin = Path(tmp) / "bin"
            fakebin.mkdir()
            wrapper(fakebin, "git", shutil.which("git"))
            env = dict(os.environ, PATH=str(fakebin))
            r = run_preflight("--offline", "--base", "integ", "--default", "main",
                              cwd=str(repo), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("preflight: OK", r.stdout)


class TestAuthoritativeDefault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="preflight-default-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        make_repo(self.repo, base="stale")
        self.old = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "integ")
        self.git("-c", "user.name=t", "-c", "user.email=t@t.invalid",
                 "commit", "--allow-empty", "-qm", "fresh")
        self.fresh = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.fresh)
        self.fakebin = Path(self.tmp.name) / "bin"
        self.fakebin.mkdir()
        gh = self.fakebin / "gh"
        gh.write_text('#!/bin/sh\ncase "$*" in\n'
                      '*nameWithOwner*) echo owner/repo;;\n'
                      '*defaultBranchRef*) echo main;;\n'
                      '*) exit 99;;\nesac\n', encoding="utf-8")
        gh.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.fakebin}{os.pathsep}{os.environ['PATH']}")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                              text=True, check=True).stdout.strip()

    def run_check(self, *args, base="integ", fork=None):
        return run_preflight("--base", base, "--fork-point", fork or self.fresh, *args,
                             cwd=self.repo, env=self.env)

    def test_online_derived_default_uses_fresh_remote_despite_stale_local_main(self):
        self.assertNotEqual(self.old, self.fresh)
        for alias in ("refs/remotes/origin/main", "origin/refs/remotes/origin/main"):
            self.git("branch", alias, self.old)
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("default=refs/remotes/origin/main", r.stdout)
        self.assertIn("BASE tip == default tip", r.stderr)

    def test_online_missing_remote_ref_cannot_fall_back_to_local_main(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        r = self.run_check(fork=self.old)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_online_missing_remote_ref_cannot_use_synthetic_local_alias(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        for alias in ("origin/refs/remotes/origin/main", "refs/remotes/origin/main"):
            with self.subTest(alias=alias):
                self.git("branch", alias, self.fresh)
                try:
                    r = self.run_check()
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("no merge-base", r.stderr)
                finally:
                    self.git("update-ref", "-d", f"refs/heads/{alias}")

    def test_missing_qualified_refs_do_not_fall_back_in_either_resolver(self):
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            for ref in ("refs/heads/missing", "refs/remotes/origin/missing"):
                self.git("branch", f"origin/{ref}", self.fresh)
                self.git("branch", ref, self.fresh)
                for resolver, args in ((preflight._tip_sha, (ref,)),
                                       (preflight._merge_base, (ref, "integ")),
                                       (preflight._merge_base, ("integ", ref))):
                    with self.subTest(ref=ref, resolver=resolver.__name__, args=args):
                        self.assertIsNone(resolver(*args))
        finally:
            os.chdir(cwd)

    def test_remote_only_base_remains_valid(self):
        self.git("update-ref", "refs/remotes/origin/remote-integ", self.fresh)
        for base in ("remote-integ", "origin/remote-integ", "refs/remotes/origin/remote-integ"):
            for mode in ((), ("--offline", "--default", "refs/remotes/origin/main")):
                with self.subTest(base=base, mode=mode):
                    r = self.run_check(*mode, base=base)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertIn("BASE tip == default tip", r.stderr)

    def test_genuinely_stale_base_still_fails(self):
        r = self.run_check(base="stale")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("BASE is stale", r.stderr)

    def test_default_branch_aliases_still_fail(self):
        for alias in ("main", "origin/main", "refs/heads/main", "refs/remotes/origin/main"):
            with self.subTest(alias=alias):
                r = self.run_check(base=alias)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("DEFAULT_BRANCH", r.stderr)

    def test_explicit_local_and_offline_defaults_keep_their_meaning(self):
        for mode in ((), ("--offline",)):
            with self.subTest(mode=mode):
                local = self.run_check(*mode, "--default", "main", fork=self.old)
                self.assertEqual(local.returncode, 0, local.stderr)
                stale = self.run_check(*mode, "--default", "main")
                self.assertEqual(stale.returncode, 2, stale.stderr)
                remote = self.run_check(*mode, "--default", "origin/main")
                self.assertEqual(remote.returncode, 0, remote.stderr)


class TestTimeoutSentinel(unittest.TestCase):
    """A timeout must be unambiguous: real processes exit 0-255 (or negative on a
    signal death), so a synthetic rc of 124 collides with a real `exit 124`."""

    def test_real_exit_124_is_not_a_timeout(self):
        # Pin: a genuine 124 passes through untouched, with no timeout message.
        rc, _, err = preflight._run(["sh", "-c", "exit 124"])
        self.assertEqual(rc, 124)
        self.assertNotIn("timed out", err)

    def test_timeout_returns_the_none_sentinel(self):
        rc, _, err = preflight._run(["sh", "-c", "sleep 30"], timeout=1)
        self.assertIsNone(rc, "timeout must return a sentinel no real process can produce")
        self.assertIn("timed out", err)


class TestHungGh(unittest.TestCase):

    def test_hung_gh_fails_fast_with_timeout_message(self):
        # merge-serialization.md handles gh dying MID-run; Phase 0 must not hang
        # on a gh that never answers. Stub gh sleeps far past the patched timeout.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            make_repo(repo)
            fakebin = Path(tmp) / "bin"
            fakebin.mkdir()
            hung = fakebin / "gh"
            hung.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
            hung.chmod(0o755)
            err = io.StringIO()
            cwd = os.getcwd()
            os.chdir(repo)
            try:
                with mock.patch.dict(os.environ, {"PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}"}), \
                        mock.patch.object(preflight, "_GH_TIMEOUT", 1):
                    start = time.monotonic()
                    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                        rc = preflight.main(["--base", "whatever"])
                    elapsed = time.monotonic() - start
            finally:
                os.chdir(cwd)
        self.assertEqual(rc, 1, err.getvalue())
        self.assertLess(elapsed, 10, "a hung gh must fail preflight fast, not block Phase 0")
        self.assertIn("timed out", err.getvalue())
        self.assertIn("--offline", err.getvalue())


class TestQuarantineInvariant(unittest.TestCase):
    """#558: --mission refuses (exit 2) on a quarantined mission, in readonly
    mode too. The deny-list resolves from the fleet catalog ($OPEN_FLEET_ROOT
    here; the pre-rename $ORCA_FLEET_ROOT when it is unset), never from the
    target repo in cwd."""

    def _repo_with_quarantine(self, tmp, quarantined, layout="catalog"):
        repo = Path(tmp) / "repo"
        make_repo(repo, base="integ")
        (repo / "runtime").mkdir()
        (repo / "runtime" / "quarantine.json").write_text(
            json.dumps({"quarantined": quarantined}))
        skill = repo if layout == "copied" else repo / "skills" / "ship-it"
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text("# ship-it fixture\n")
        if layout != "catalog":
            (skill / "references").mkdir()
        return repo

    def _run(self, repo, *extra):
        env = {**os.environ, "OPEN_FLEET_ROOT": str(repo)}
        return run_preflight("--mode", "readonly", "--mission", "ship-it",
                             *extra, cwd=repo, env=env)

    def test_quarantined_mission_refused_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo_with_quarantine(tmp, [{
                "component": "mission:ship-it", "ref": "*",
                "reason": "compromised", "date": "2026-10-14",
                "by": "human:maintainer"}])
            result = self._run(repo)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("QUARANTINED", result.stderr)

    def test_clean_mission_passes_and_absent_list_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo_with_quarantine(tmp, [])
            self.assertEqual(self._run(repo).returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            make_repo(repo)
            self.assertEqual(self._run(repo).returncode, 0)

    def test_malformed_deny_list_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            make_repo(repo)
            (repo / "runtime").mkdir()
            (repo / "runtime" / "quarantine.json").write_text("{broken")
            self.assertEqual(self._run(repo).returncode, 2)

    def test_directory_deny_list_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            make_repo(repo)
            (repo / "runtime" / "quarantine.json").mkdir(parents=True)
            self.assertEqual(self._run(repo).returncode, 2)

    def _generic(self, root, mode, mission=None):
        env = {**os.environ, "OPEN_FLEET_ROOT": str(root), "ORCA_FLEET_ROOT": str(root)}
        args = (["--mode", "readonly"] if mode == "readonly" else
                ["--offline", "--base", "integ", "--default", "main"])
        if mission:
            args += ["--mission", mission]
        return run_preflight(*args, cwd=root, env=env)

    def test_named_mission_missing_dependency_refuses_in_either_mode(self):
        for layout in ("catalog", "bundle", "copied"):
            for mode in ("write", "readonly"):
                with self.subTest(layout=layout, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    repo = self._repo_with_quarantine(tmp, [], layout)
                    skill = repo if layout == "copied" else repo / "skills" / "ship-it"
                    (skill / "SKILL.md").write_text("Composes `risk-review`.\n")
                    result = self._generic(repo, mode, mission="ship-it")
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("missing composed dependency risk-review.md", result.stderr)

    def test_omitted_mission_refuses_active_policy_in_either_mode(self):
        # CLI seam: a valid start with no identity must not skip quarantine.
        # Synthetic policies live only in temporary repositories.
        for layout in ("catalog", "bundle", "copied"):
            for mode in ("write", "readonly"):
                for component in ("mission:ship-it", "playbook:risk-review", "pack:gstack"):
                    with self.subTest(layout=layout, mode=mode, component=component), \
                            tempfile.TemporaryDirectory() as tmp:
                        repo = self._repo_with_quarantine(tmp, [{
                            "component": component, "ref": "*", "reason": "compromised",
                            "date": "2026-10-14", "by": "human:maintainer"}], layout)
                        result = self._generic(repo, mode)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertIn("--mission", result.stderr)
                        self.assertIn("quarantine", result.stderr.lower())

    def test_omitted_mission_refuses_unusable_policy(self):
        for mode in ("write", "readonly"):
            for state in ("bad-json", "bad-shape", "invalid-utf8", "directory", "broken-link"):
                with self.subTest(mode=mode, state=state), tempfile.TemporaryDirectory() as tmp:
                    repo = self._repo_with_quarantine(tmp, [])
                    policy = repo / "runtime" / "quarantine.json"
                    policy.unlink()
                    if state == "directory":
                        policy.mkdir()
                    elif state == "broken-link":
                        policy.symlink_to("missing-policy.json")
                    else:
                        policy.write_bytes({"bad-json": b"{broken", "bad-shape": b"{}",
                                            "invalid-utf8": b"\xff\xfe"}[state])
                    result = self._generic(repo, mode)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("quarantine.json", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_omitted_mission_allows_empty_policy_diagnostics(self):
        for layout in ("catalog", "bundle", "copied"):
            for mode in ("write", "readonly"):
                with self.subTest(layout=layout, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    repo = self._repo_with_quarantine(tmp, [], layout)
                    result = self._generic(repo, mode)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_copied_runtime_without_checker_cannot_clear_generic_start(self):
        for mode in ("write", "readonly"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                repo = self._repo_with_quarantine(tmp, [], "copied")
                scripts = repo / "runtime" / "scripts"
                scripts.mkdir()
                for name in ("preflight.py", "gitexec.py"):
                    shutil.copy2(SCRIPT.parent / name, scripts / name)
                args = (["--mode", "readonly"] if mode == "readonly" else
                        ["--offline", "--base", "integ", "--default", "main"])
                env = {k: v for k, v in os.environ.items() if k not in
                       {"OPEN_FLEET_ROOT", "ORCA_FLEET_ROOT", "CLAUDE_PLUGIN_ROOT"}}
                result = subprocess.run([sys.executable, str(scripts / "preflight.py"), *args],
                                        capture_output=True, text=True, cwd=repo, env=env, timeout=60)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("quarantine_check.py unloadable", result.stderr)

    def test_target_repo_cannot_shadow_the_fleet_list(self):
        # cwd holds a (forged empty) deny-list; the fleet root holds the real
        # one. The fleet list wins: the run is refused.
        with tempfile.TemporaryDirectory() as tmp:
            fleet = self._repo_with_quarantine(tmp, [{
                "component": "mission:ship-it", "ref": "*",
                "reason": "compromised", "date": "2026-10-14",
                "by": "human:maintainer"}])
            target = Path(tmp) / "target"
            make_repo(target)
            (target / "runtime").mkdir()
            (target / "runtime" / "quarantine.json").write_text(
                json.dumps({"quarantined": []}))
            env = {**os.environ, "OPEN_FLEET_ROOT": str(fleet)}
            result = run_preflight("--mode", "readonly", "--mission", "ship-it",
                                   cwd=target, env=env)
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_the_pre_rename_root_name_still_binds_the_fleet_list(self):
        # Installed users still export ORCA_FLEET_ROOT. With OPEN_FLEET_ROOT unset it must
        # still name the catalog: the fleet's list refuses the mission, where this script's
        # own catalog (the fallback were the old name ignored) would let it start.
        with tempfile.TemporaryDirectory() as tmp:
            fleet = self._repo_with_quarantine(tmp, [{
                "component": "mission:ship-it", "ref": "*",
                "reason": "compromised", "date": "2026-10-14",
                "by": "human:maintainer"}])
            target = Path(tmp) / "target"
            make_repo(target)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPEN_FLEET_ROOT", "CLAUDE_PLUGIN_ROOT")}
            env["ORCA_FLEET_ROOT"] = str(fleet)
            result = run_preflight("--mode", "readonly", "--mission", "ship-it",
                                   cwd=target, env=env)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("QUARANTINED", result.stderr)
            del env["ORCA_FLEET_ROOT"]
            result = run_preflight("--mode", "readonly", "--mission", "ship-it",
                                   cwd=target, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_root_names_naming_different_catalogs_refuses(self):
        # Which deny-list binds the run must not depend on which spelling is read first.
        with tempfile.TemporaryDirectory() as tmp:
            fleet = self._repo_with_quarantine(tmp, [])
            other = Path(tmp) / "other"
            other.mkdir()
            env = {**os.environ, "OPEN_FLEET_ROOT": str(fleet), "ORCA_FLEET_ROOT": str(other)}
            result = run_preflight("--mode", "readonly", "--mission", "ship-it",
                                   cwd=fleet, env=env)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("ORCA_FLEET_ROOT", result.stderr)
            self.assertIn("disagree", result.stderr)
            # One catalog under both names is no conflict.
            env["ORCA_FLEET_ROOT"] = str(fleet)
            result = run_preflight("--mode", "readonly", "--mission", "ship-it",
                                   cwd=fleet, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
