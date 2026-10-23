#!/usr/bin/env python3
"""#629: the coordinator-side gates must not run a command the worker named in its own repo.

Global and system git config were already off, but a worker that can write its worktree's
`.git/config` (and `.git/info/attributes`) could still get a command run on the COORDINATOR
the next time a gate diffs or reads its work, through a repository-config channel git honours:

  - a `filter.<driver>.clean/smudge/process` selected by `.gitattributes`, run when a gate
    materialises or diffs a working-tree file;
  - `core.fsmonitor`, run on `status`/`add`;
  - and the diff/textconv/hook/replace/graft channels the fixed belt and the
    `--no-ext-diff`/`--no-textconv` flags already closed, pinned here so they stay closed.

Each gate is driven the way the coordinator runs it, against a repo whose config names a
harmless probe that only touches a marker file in this test's temp dir. GREEN = the marker
is never created. Every case carries its mutation control: with the hardening removed the
marker comes back, so the test proves the hardening is load-bearing, not that the channel
was dormant. Stdlib only; no network.
"""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "runtime" / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gitexec = _load("gitexec", "gitexec.py")
floor_guard = _load("floor_guard", "floor_guard.py")
diff_scope = _load("diff_scope", "diff_scope.py")
evidence_run = _load("evidence_run", "evidence-run.py")

# The setup git runs with global/system config off, so the only driver the fixtures declare is
# the probe (a stray ~/.gitconfig git-lfs filter never changes a test's outcome).
_CLEAN_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class _Probe:
    """A git repo whose config names a probe on every exec channel. The probe appends ONE token
    per fire to a marker file; `fired()` returns the set of channels seen."""

    def __init__(self, tmp):
        self.dir = Path(tmp)
        self.repo = self.dir / "repo"
        self.marker = self.dir / "marker"
        self.probe = self.dir / "probe.sh"
        # The probe ONLY touches its marker and never reads stdin: git hands an fsmonitor hook
        # its own stdin, so a probe that read it blocked forever under an inherited pipe that
        # never closes. A filter that fires is the failure under test, so what it outputs (here,
        # nothing) never matters to a GREEN case; the 'process' protocol is never selected.
        self.probe.write_text('#!/bin/sh\necho "$1" >> ' + _sh(self.marker) + "\nexit 0\n",
                              encoding="utf-8")
        self.probe.chmod(0o755)
        self.repo.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("config", "user.email", "a@b")
        self._git("config", "user.name", "a")

    def _git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], env=_CLEAN_ENV,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def commit(self, name, body):
        (self.repo / name).write_text(body, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", name)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def arm_filter(self, pattern="*.txt"):
        """Select a clean/smudge filter whose command is the probe, via $GIT_DIR/info/attributes
        (the vector --attr-source cannot override) so blanking the config command is the only
        defence."""
        for key in ("filter.p.clean", "filter.p.smudge"):
            self._git("config", key, f"{self.probe} {key.split('.')[-1]}")
        info = self.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text(f"{pattern} filter=p\n", encoding="utf-8")

    def arm_fsmonitor(self):
        self._git("config", "core.fsmonitor", f"{self.probe} fsmonitor")

    def fired(self):
        if not self.marker.exists():
            return set()
        seen = {ln.strip() for ln in self.marker.read_text().splitlines() if ln.strip()}
        self.marker.unlink()
        return seen


def _sh(path):
    return "'" + str(path).replace("'", "'\\''") + "'"


class GitexecDriverBlanks(unittest.TestCase):
    """gitexec.driver_blanks reads the driver names the repo's OWN config declares and blanks
    each command — the attribute-selected channel a fixed -c cannot name."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "one\n")
        return p

    def test_a_clean_repo_declares_no_drivers(self):
        self.assertEqual(gitexec.driver_blanks(self._repo().repo), [])

    def test_every_declared_filter_and_diff_driver_command_is_blanked(self):
        p = self._repo()
        p._git("config", "filter.media.clean", "danger clean")
        p._git("config", "filter.media.smudge", "danger smudge")
        p._git("config", "filter.media.process", "danger process")
        p._git("config", "diff.jpg.textconv", "danger textconv")
        p._git("config", "diff.jpg.command", "danger command")
        # A driver name with a dot is still one subsection, so it is still covered.
        p._git("config", "filter.my.lfs.clean", "danger clean")
        blanks = gitexec.driver_blanks(p.repo)
        tokens = {blanks[i + 1] for i in range(0, len(blanks), 2)}
        self.assertEqual({t for t in blanks if t == "-c"}, {"-c"})
        self.assertEqual(tokens, {
            "filter.media.clean=", "filter.media.smudge=", "filter.media.process=",
            "diff.jpg.textconv=", "diff.jpg.command=", "filter.my.lfs.clean="})

    def test_a_non_command_key_is_not_blanked(self):
        p = self._repo()
        p._git("config", "filter.media.required", "true")
        p._git("config", "diff.jpg.binary", "true")
        self.assertEqual(gitexec.driver_blanks(p.repo), [])

    def test_the_toolchain_copies_blank_exactly_what_gitexec_blanks(self):
        # diff_scope.py inlines driver_blanks and verify.py's _Authority mirrors it (each runs its
        # own git under its own env); a copy that falls behind reopens the channel at that gate.
        verify = _load("verify_parity", "verify.py")
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)
        p = self._repo()
        for key in ("filter.media.clean", "filter.media.smudge", "filter.media.process",
                    "diff.jpg.textconv", "diff.jpg.command", "filter.my.lfs.clean"):
            p._git("config", key, "danger")
        p._git("config", "filter.media.required", "true")
        want = gitexec.driver_blanks(p.repo)
        self.assertEqual(len(want), 12)
        self.assertEqual(diff_scope._driver_blanks(p.repo), want)
        self.assertEqual(verify._Authority.driver_blanks(p.repo), want)


class StaticBeltClosesTheFixedKeyChannels(unittest.TestCase):
    """The env belt (command-line precedence, so it overrides repo .git/config) names every
    command-bearing key a fixed -c can name."""

    def test_belt_pins_the_command_bearing_keys(self):
        env = gitexec.env({"LANG": "C"})
        pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                 for i in range(int(env["GIT_CONFIG_COUNT"]))}
        self.assertEqual(pairs["core.fsmonitor"], "false")
        self.assertEqual(pairs["core.hooksPath"], os.devnull)
        self.assertEqual(pairs["diff.external"], "")
        self.assertEqual(pairs["protocol.ext.allow"], "never")
        self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(env["GIT_GRAFT_FILE"], os.devnull)

    def test_diff_scope_mirrors_the_whole_gitexec_floor(self):
        env = diff_scope._git_env()
        plain = {k: v for k, v in gitexec.HARDENED.items()
                 if not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_", "GIT_CONFIG_COUNT"))}
        self.assertEqual({k: env.get(k) for k in plain}, plain)

        def pairs(e):
            return {e[f"GIT_CONFIG_KEY_{i}"]: e[f"GIT_CONFIG_VALUE_{i}"]
                    for i in range(int(e["GIT_CONFIG_COUNT"]))}
        ours = pairs(env)
        self.assertEqual({k: ours.get(k) for k in pairs(gitexec.HARDENED)}, pairs(gitexec.HARDENED))


class FloorGuardWorktreeDiff(unittest.TestCase):
    """floor_guard diffs the working tree against the base — which runs a repo-config clean
    filter a .gitattributes selects, the one channel --no-ext-diff/--no-textconv leave open."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        (p.repo / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        (p.repo / "b.txt").write_text("brand new\n", encoding="utf-8")  # untracked -> --no-index
        return p, base

    def _collect(self, p, base):
        mb = floor_guard.merge_base(p.repo, base)
        floor_guard.collect_diff(p.repo, mb)

    def test_no_driver_command_runs_when_the_guard_reads_the_diff(self):
        p, base = self._repo()
        self._collect(p, base)
        self.assertEqual(p.fired(), set(), "a repo-config filter ran inside floor_guard")

    def test_mutation_control_without_the_blanks_the_filter_fires(self):
        p, base = self._repo()
        with mock.patch.object(floor_guard.gitexec, "driver_blanks", lambda repo: []):
            self._collect(p, base)
        self.assertIn("clean", p.fired(),
                      "control: with the driver blanks removed the clean filter must fire")


class DiffScopeWorktreeDiff(unittest.TestCase):
    """diff_scope classifies the changed paths, diffing the working tree against the base."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        base = p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        (p.repo / "a.txt").write_text("line1\nCHANGED\n", encoding="utf-8")
        return p, base

    def test_no_driver_command_runs_when_scope_reads_the_diff(self):
        p, base = self._repo()
        diff_scope.scope(p.repo, base)
        self.assertEqual(p.fired(), set(), "a repo-config filter ran inside diff_scope")

    def test_mutation_control_without_the_blanks_the_filter_fires(self):
        p, base = self._repo()
        with mock.patch.object(diff_scope, "_driver_blanks", lambda repo: []):
            diff_scope.scope(p.repo, base)
        self.assertIn("clean", p.fired(),
                      "control: with the driver blanks removed the clean filter must fire")


class WtreeFingerprint(unittest.TestCase):
    """evidence-run.py fingerprints the working tree through wtree.sh (`git add -A` + write-tree),
    which runs both core.fsmonitor and a selected clean filter against the worker's repo."""

    def _repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        p = _Probe(tmp)
        p.commit("a.txt", "line1\nline2\n")
        p.arm_filter()
        p.arm_fsmonitor()
        (p.repo / "a.txt").write_text("line1\nDIRTY\n", encoding="utf-8")  # dirty -> add re-hashes
        return p

    def test_the_fingerprint_runs_no_config_command(self):
        p = self._repo()
        out, err = evidence_run.working_tree_fingerprint(str(p.repo))
        self.assertIsNone(err, err)
        self.assertTrue(out)
        self.assertEqual(p.fired(), set(), "wtree.sh ran a repo-config command on the coordinator")

    def test_mutation_control_a_stripped_wtree_fires_fsmonitor_and_the_filter(self):
        # The control is a COPY of wtree.sh with the two hardening hunks removed, run the same way,
        # so the planted channels prove they were dormant only because of the hardening.
        p = self._repo()
        src = (SCRIPTS / "wtree.sh").read_text(encoding="utf-8")
        stripped = src.replace('git -C "$TOP" "$@" add -A', 'git -C "$TOP" add -A')
        stripped = stripped.replace('git -C "$TOP" "$@" write-tree', 'git -C "$TOP" write-tree')
        # Drop the env belt so core.fsmonitor is honoured again.
        stripped = stripped.replace("GIT_CONFIG_COUNT=3", "GIT_CONFIG_COUNT=0")
        self.assertNotEqual(stripped, src, "the control did not change wtree.sh")
        mutant = p.dir / "wtree_control.sh"
        mutant.write_text(stripped, encoding="utf-8")
        subprocess.run(["sh", str(mutant), str(p.repo)], capture_output=True, timeout=120,
                       stdin=subprocess.DEVNULL)
        self.assertTrue(p.fired() & {"clean", "fsmonitor"},
                        "control: the stripped wtree.sh must run a planted channel")


if __name__ == "__main__":
    unittest.main()
